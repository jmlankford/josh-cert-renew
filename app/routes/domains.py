"""
Domain management routes.

Handles CRUD for managed domains and the SSE-streamed issue/renew operations.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db import get_db
from app.models.credential import CloudflareZone, CPanelProfile
from app.models.domain import Domain
from app.models.history import RenewalHistory
from app.services import acme as acme_svc
from app.services.crypto import decrypt

router = APIRouter(prefix="/api/domains", tags=["domains"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────────

class DomainCreate(BaseModel):
    root_domain: str
    subdomain: str | None = None        # None → APEX
    is_wildcard: bool = False
    cpanel_profile_id: int
    cloudflare_zone_id: int
    deploy_target: str = "cpanel"       # "cpanel" | "homelab"


class DomainOut(BaseModel):
    id: int
    root_domain: str
    subdomain: str | None
    fqdn: str
    is_wildcard: bool
    cpanel_profile_id: int | None
    cloudflare_zone_id: int | None
    deploy_target: str
    status: str
    expiry_date: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _serialise(d: Domain) -> dict:
    return {
        "id": d.id,
        "root_domain": d.root_domain,
        "subdomain": d.subdomain,
        "fqdn": d.fqdn,
        "is_wildcard": d.is_wildcard,
        "cpanel_profile_id": d.cpanel_profile_id,
        "cloudflare_zone_id": d.cloudflare_zone_id,
        "deploy_target": d.deploy_target,
        "status": d.status,
        "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


def _build_fqdn(root: str, subdomain: str | None) -> str:
    root = root.lower().strip().rstrip(".")
    if not subdomain:
        return root
    return f"{subdomain.lower().strip()}.{root}"


# ── CRUD ──────────────────────────────────────────────────────────────────

@router.get("")
def list_domains(db: Session = Depends(get_db)):
    domains = db.query(Domain).order_by(Domain.root_domain, Domain.subdomain).all()
    return [_serialise(d) for d in domains]


@router.post("", status_code=201)
def create_domain(payload: DomainCreate, db: Session = Depends(get_db)):
    fqdn = _build_fqdn(payload.root_domain, payload.subdomain)

    existing = db.query(Domain).filter(Domain.fqdn == fqdn).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Domain '{fqdn}' is already managed")

    # Wildcards only make sense on APEX records
    is_wildcard = payload.is_wildcard and payload.subdomain is None

    domain = Domain(
        root_domain=payload.root_domain.lower().strip().rstrip("."),
        subdomain=payload.subdomain.lower().strip() if payload.subdomain else None,
        fqdn=fqdn,
        is_wildcard=is_wildcard,
        cpanel_profile_id=payload.cpanel_profile_id,
        cloudflare_zone_id=payload.cloudflare_zone_id,
        deploy_target=payload.deploy_target if payload.deploy_target in ("cpanel", "homelab") else "cpanel",
        status="NEVER ISSUED",
    )
    db.add(domain)
    db.commit()
    db.refresh(domain)
    return _serialise(domain)


@router.delete("/{domain_id}", status_code=204)
def delete_domain(domain_id: int, db: Session = Depends(get_db)):
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    db.delete(domain)
    db.commit()


# ── SSE helpers ─────────────────────────────────────────────────────────────────

async def _collect_logs_and_rc(stream) -> tuple[list[str], int]:
    """Drain an acme async generator, return (log_lines, exit_code)."""
    lines: list[str] = []
    rc = -1
    async for line, returncode in stream:
        if line:
            lines.append(line)
        if returncode != -1:
            rc = returncode
    return lines, rc


def _make_sse_generator(
    domain_id: int,
    operation: str,   # "issue" | "renew"
    db_factory,
) -> AsyncGenerator:
    """
    Returns an async generator that:
    1. Streams acme.sh output as SSE data events.
    2. On completion writes a RenewalHistory record and updates the domain.
    """

    async def _gen():
        db: Session = db_factory()
        acme_email = os.environ.get("ACME_EMAIL", "")
        ts = lambda: datetime.utcnow().strftime("%H:%M:%S")  # noqa: E731

        try:
            domain = db.query(Domain).filter(Domain.id == domain_id).first()
            if not domain:
                yield {"data": json.dumps({"type": "error", "line": "Domain not found"})}
                return

            cf_zone = db.query(CloudflareZone).filter(CloudflareZone.id == domain.cloudflare_zone_id).first()
            profile = db.query(CPanelProfile).filter(CPanelProfile.id == domain.cpanel_profile_id).first()

            if not cf_zone:
                yield {"data": json.dumps({"type": "error", "line": "Cloudflare zone credentials not found"})}
                return
            if not profile:
                yield {"data": json.dumps({"type": "error", "line": "cPanel profile not found"})}
                return

            cf_token = decrypt(cf_zone.cf_token_encrypted)
            credential = decrypt(profile.credential_encrypted)

            domain.status = "PENDING"
            domain.updated_at = datetime.utcnow()
            db.commit()

            yield {"data": json.dumps({"type": "log", "line": f"[{ts()}] Starting {operation} for {domain.fqdn}…"})}

            # ── Issue / Renew ──────────────────────────────────────────────────
            all_logs: list[str] = []

            if operation == "issue":
                stream = await acme_svc.issue_cert(
                    domain.fqdn, domain.is_wildcard, cf_token, cf_zone.cf_zone_id, acme_email
                )
            else:
                stream = await acme_svc.renew_cert(
                    domain.fqdn, cf_token, cf_zone.cf_zone_id, acme_email
                )

            rc = -1
            async for line, returncode in stream:
                if line:
                    all_logs.append(line)
                    yield {"data": json.dumps({"type": "log", "line": line})}
                if returncode != -1:
                    rc = returncode

            if rc != 0:
                raise RuntimeError(f"acme.sh exited with code {rc}")

            # ── Deploy ──────────────────────────────────────────────────
            if domain.deploy_target == "cpanel":
                yield {"data": json.dumps({"type": "log", "line": f"[{ts()}] Deploying certificate to cPanel…"})}
                deploy_stream = await acme_svc.deploy_cert(
                    domain.fqdn,
                    profile.cpanel_hostname,
                    profile.cpanel_username,
                    profile.auth_method,
                    credential,
                )
                rc2 = -1
                async for line, returncode in deploy_stream:
                    if line:
                        all_logs.append(line)
                        yield {"data": json.dumps({"type": "log", "line": line})}
                    if returncode != -1:
                        rc2 = returncode

                if rc2 != 0:
                    raise RuntimeError(f"acme.sh deploy exited with code {rc2}")
            else:
                yield {"data": json.dumps({"type": "log", "line": f"[{ts()}] Deploy target is 'homelab' — skipping (Coming Soon)"})}

            # ── Success ──────────────────────────────────────────────────
            expiry = acme_svc.parse_expiry_from_acme_info(domain.fqdn)
            domain.status = "ACTIVE"
            domain.expiry_date = expiry
            domain.updated_at = datetime.utcnow()
            db.commit()

            history = RenewalHistory(
                domain_fqdn=domain.fqdn,
                result="success",
                log_output="\n".join(all_logs),
                triggered_by="manual",
            )
            db.add(history)
            db.commit()

            expiry_str = expiry.strftime("%Y-%m-%d") if expiry else "unknown"
            yield {"data": json.dumps({"type": "done", "status": "ACTIVE", "expiry": expiry_str})}

        except Exception as exc:
            err_msg = str(exc)
            try:
                domain = db.query(Domain).filter(Domain.id == domain_id).first()
                if domain:
                    domain.status = "ERROR"
                    domain.updated_at = datetime.utcnow()
                    db.commit()

                history = RenewalHistory(
                    domain_fqdn=domain.fqdn if domain else "unknown",
                    result="failure",
                    log_output=err_msg,
                    triggered_by="manual",
                )
                db.add(history)
                db.commit()
            except Exception:
                pass

            yield {"data": json.dumps({"type": "error", "line": f"[{ts()}] FAILED: {err_msg}"})}
            yield {"data": json.dumps({"type": "done", "status": "ERROR", "expiry": None})}
        finally:
            db.close()

    return _gen()


# ── SSE endpoints ───────────────────────────────────────────────────────────────

@router.get("/{domain_id}/issue")
async def issue_domain(domain_id: int, db: Session = Depends(get_db)):
    """Issue a new certificate. Streams acme.sh output via SSE."""
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    # db session must be closed before streaming begins (SQLite locking)
    db.close()
    from app.db import SessionLocal
    return EventSourceResponse(_make_sse_generator(domain_id, "issue", SessionLocal))


@router.get("/{domain_id}/renew")
async def renew_domain(domain_id: int, db: Session = Depends(get_db)):
    """Force-renew an existing certificate. Streams acme.sh output via SSE."""
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    db.close()
    from app.db import SessionLocal
    return EventSourceResponse(_make_sse_generator(domain_id, "renew", SessionLocal))
