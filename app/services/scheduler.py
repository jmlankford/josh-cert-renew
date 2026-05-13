"""
APScheduler-based auto-renewal daemon.

Runs once daily at RENEWAL_CRON_TIME (HH:MM, UTC, default 02:00).
Queries all domains with an expiry within 30 days, force-renews each one
sequentially, deploys via cpanel_uapi, and writes a RenewalHistory record.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import SessionLocal
from app.models.domain import Domain
from app.models.credential import CloudflareZone, CPanelProfile
from app.models.history import RenewalHistory
from app.services import acme as acme_svc
from app.services.crypto import decrypt

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Tracks the last auto-renewal run result for the dashboard summary.
last_run_info: dict = {"timestamp": None, "result": "NEVER RUN"}


async def _run_renewal_job() -> None:
    global last_run_info
    db = SessionLocal()
    acme_email = os.environ.get("ACME_EMAIL", "")
    now = datetime.utcnow()
    threshold = now + timedelta(days=30)

    domains = (
        db.query(Domain)
        .filter(Domain.status == "ACTIVE", Domain.expiry_date <= threshold)
        .all()
    )
    # Also renew anything in ERROR state that has a cert (expiry_date set)
    error_domains = (
        db.query(Domain)
        .filter(Domain.status == "ERROR", Domain.expiry_date.isnot(None), Domain.expiry_date <= threshold)
        .all()
    )
    targets = domains + error_domains

    if not targets:
        logger.info("Auto-renewal: no domains due for renewal")
        last_run_info = {"timestamp": now.isoformat(), "result": "PASS"}
        db.close()
        return

    overall_result = "PASS"

    for domain in targets:
        log_lines: list[str] = []
        success = True

        try:
            cf_zone = db.query(CloudflareZone).filter(CloudflareZone.id == domain.cloudflare_zone_id).first()
            profile = db.query(CPanelProfile).filter(CPanelProfile.id == domain.cpanel_profile_id).first()

            if not cf_zone or not profile:
                raise RuntimeError(f"Missing credentials for domain {domain.fqdn}")

            cf_token = decrypt(cf_zone.cf_token_encrypted)
            credential = decrypt(profile.credential_encrypted)

            # Renew
            domain.status = "PENDING"
            db.commit()

            stream = await acme_svc.renew_cert(domain.fqdn, cf_token, cf_zone.cf_zone_id, acme_email)
            rc = -1
            async for line, returncode in stream:
                if line:
                    log_lines.append(line)
                    logger.info("[%s] %s", domain.fqdn, line)
                rc = returncode if returncode != -1 else rc

            if rc != 0:
                raise RuntimeError(f"acme.sh renew exited with code {rc}")

            # Deploy
            if domain.deploy_target == "cpanel":
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
                        log_lines.append(line)
                    rc2 = returncode if returncode != -1 else rc2

                if rc2 != 0:
                    raise RuntimeError(f"acme.sh deploy exited with code {rc2}")

            expiry = acme_svc.parse_expiry_from_acme_info(domain.fqdn)
            domain.status = "ACTIVE"
            domain.expiry_date = expiry
            domain.updated_at = datetime.utcnow()
            db.commit()

        except Exception as exc:
            success = False
            overall_result = "FAIL"
            logger.error("Auto-renewal failed for %s: %s", domain.fqdn, exc)
            log_lines.append(f"[ERROR] {exc}")
            domain.status = "ERROR"
            domain.updated_at = datetime.utcnow()
            db.commit()

        history = RenewalHistory(
            domain_fqdn=domain.fqdn,
            result="success" if success else "failure",
            log_output="\n".join(log_lines),
            triggered_by="scheduler",
        )
        db.add(history)
        db.commit()

    last_run_info = {"timestamp": now.isoformat(), "result": overall_result}
    db.close()


def start_scheduler() -> None:
    global _scheduler

    cron_time = os.environ.get("RENEWAL_CRON_TIME", "02:00")
    try:
        hour_str, minute_str = cron_time.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        logger.warning("Invalid RENEWAL_CRON_TIME '%s', defaulting to 02:00", cron_time)
        hour, minute = 2, 0

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_renewal_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="auto_renewal",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("Auto-renewal scheduler started — runs daily at %02d:%02d UTC", hour, minute)


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
