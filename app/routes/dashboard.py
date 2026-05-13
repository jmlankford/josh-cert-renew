"""
Dashboard summary route.

Returns aggregate counts and the last auto-renewal run status for the sticky
summary bar at the top of the domain table.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.domain import Domain

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_summary(db: Session = Depends(get_db)):
    from app.services.scheduler import last_run_info

    now = datetime.utcnow()
    soon_threshold = now + timedelta(days=30)

    total = db.query(Domain).count()
    never_issued = db.query(Domain).filter(Domain.status == "NEVER ISSUED").count()
    expired = (
        db.query(Domain)
        .filter(Domain.expiry_date < now, Domain.status != "NEVER ISSUED")
        .count()
    )
    expiring_soon = (
        db.query(Domain)
        .filter(
            Domain.expiry_date >= now,
            Domain.expiry_date <= soon_threshold,
            Domain.status == "ACTIVE",
        )
        .count()
    )

    return {
        "total": total,
        "never_issued": never_issued,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "last_run_timestamp": last_run_info.get("timestamp"),
        "last_run_result": last_run_info.get("result", "NEVER RUN"),
    }
