"""
Credential profile routes.

Manages Cloudflare zone entries and cPanel hosting profiles.
All sensitive values are encrypted at rest via Fernet before being stored.
Secrets are never returned in API responses — only masked placeholders.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.credential import CloudflareZone, CPanelProfile
from app.services.cloudflare import validate_token
from app.services.cpanel import validate_profile
from app.services.crypto import encrypt, decrypt

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

_MASKED = "••••••••"


# ── Cloudflare Zones ────────────────────────────────────────────

class CFZoneCreate(BaseModel):
    zone_name: str
    cf_token: str
    cf_zone_id: str


class CFZoneUpdate(BaseModel):
    zone_name: str | None = None
    cf_token: str | None = None     # omit to keep existing secret
    cf_zone_id: str | None = None


def _serialise_cf(z: CloudflareZone) -> dict:
    return {
        "id": z.id,
        "zone_name": z.zone_name,
        "cf_token": _MASKED,
        "cf_zone_id": z.cf_zone_id,
        "created_at": z.created_at.isoformat(),
        "updated_at": z.updated_at.isoformat(),
    }


@router.get("/cloudflare")
def list_cf_zones(db: Session = Depends(get_db)):
    zones = db.query(CloudflareZone).order_by(CloudflareZone.zone_name).all()
    return [_serialise_cf(z) for z in zones]


@router.post("/cloudflare", status_code=201)
def create_cf_zone(payload: CFZoneCreate, db: Session = Depends(get_db)):
    zone = CloudflareZone(
        zone_name=payload.zone_name.strip().lower(),
        cf_token_encrypted=encrypt(payload.cf_token),
        cf_zone_id=payload.cf_zone_id.strip(),
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return _serialise_cf(zone)


@router.put("/cloudflare/{zone_id}")
def update_cf_zone(zone_id: int, payload: CFZoneUpdate, db: Session = Depends(get_db)):
    zone = db.query(CloudflareZone).filter(CloudflareZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Cloudflare zone not found")

    if payload.zone_name is not None:
        zone.zone_name = payload.zone_name.strip().lower()
    if payload.cf_zone_id is not None:
        zone.cf_zone_id = payload.cf_zone_id.strip()
    if payload.cf_token is not None and payload.cf_token not in (_MASKED, ""):
        zone.cf_token_encrypted = encrypt(payload.cf_token)

    from datetime import datetime
    zone.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(zone)
    return _serialise_cf(zone)


@router.delete("/cloudflare/{zone_id}", status_code=204)
def delete_cf_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(CloudflareZone).filter(CloudflareZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Cloudflare zone not found")
    db.delete(zone)
    db.commit()


@router.post("/cloudflare/{zone_id}/test")
async def test_cf_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(CloudflareZone).filter(CloudflareZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Cloudflare zone not found")
    token = decrypt(zone.cf_token_encrypted)
    result = await validate_token(token, zone.cf_zone_id)
    return result


# ── cPanel Profiles ────────────────────────────────────────────

class CPanelCreate(BaseModel):
    profile_name: str
    cpanel_hostname: str
    cpanel_username: str
    auth_method: str        # "api_token" | "password"
    credential: str


class CPanelUpdate(BaseModel):
    profile_name: str | None = None
    cpanel_hostname: str | None = None
    cpanel_username: str | None = None
    auth_method: str | None = None
    credential: str | None = None   # omit to keep existing secret


def _serialise_cp(p: CPanelProfile) -> dict:
    return {
        "id": p.id,
        "profile_name": p.profile_name,
        "cpanel_hostname": p.cpanel_hostname,
        "cpanel_username": p.cpanel_username,
        "auth_method": p.auth_method,
        "credential": _MASKED,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.get("/cpanel")
def list_cpanel_profiles(db: Session = Depends(get_db)):
    profiles = db.query(CPanelProfile).order_by(CPanelProfile.profile_name).all()
    return [_serialise_cp(p) for p in profiles]


@router.post("/cpanel", status_code=201)
def create_cpanel_profile(payload: CPanelCreate, db: Session = Depends(get_db)):
    if payload.auth_method not in ("api_token", "password"):
        raise HTTPException(status_code=422, detail="auth_method must be 'api_token' or 'password'")

    profile = CPanelProfile(
        profile_name=payload.profile_name.strip(),
        cpanel_hostname=payload.cpanel_hostname.strip(),
        cpanel_username=payload.cpanel_username.strip(),
        auth_method=payload.auth_method,
        credential_encrypted=encrypt(payload.credential),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _serialise_cp(profile)


@router.put("/cpanel/{profile_id}")
def update_cpanel_profile(profile_id: int, payload: CPanelUpdate, db: Session = Depends(get_db)):
    profile = db.query(CPanelProfile).filter(CPanelProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="cPanel profile not found")

    if payload.profile_name is not None:
        profile.profile_name = payload.profile_name.strip()
    if payload.cpanel_hostname is not None:
        profile.cpanel_hostname = payload.cpanel_hostname.strip()
    if payload.cpanel_username is not None:
        profile.cpanel_username = payload.cpanel_username.strip()
    if payload.auth_method is not None:
        if payload.auth_method not in ("api_token", "password"):
            raise HTTPException(status_code=422, detail="auth_method must be 'api_token' or 'password'")
        profile.auth_method = payload.auth_method
    if payload.credential is not None and payload.credential not in (_MASKED, ""):
        profile.credential_encrypted = encrypt(payload.credential)

    from datetime import datetime
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return _serialise_cp(profile)


@router.delete("/cpanel/{profile_id}", status_code=204)
def delete_cpanel_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(CPanelProfile).filter(CPanelProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="cPanel profile not found")
    db.delete(profile)
    db.commit()


@router.post("/cpanel/{profile_id}/test")
async def test_cpanel_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(CPanelProfile).filter(CPanelProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="cPanel profile not found")
    credential = decrypt(profile.credential_encrypted)
    result = await validate_profile(
        profile.cpanel_hostname,
        profile.cpanel_username,
        profile.auth_method,
        credential,
    )
    return result
