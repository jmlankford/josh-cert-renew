"""
Renewal history routes.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.history import RenewalHistory

router = APIRouter(prefix="/api/history", tags=["history"])


def _serialise(h: RenewalHistory) -> dict:
    return {
        "id": h.id,
        "domain_fqdn": h.domain_fqdn,
        "result": h.result,
        "log_output": h.log_output,
        "triggered_by": h.triggered_by,
        "created_at": h.created_at.isoformat(),
    }


@router.get("")
def list_history(
    domain: str | None = Query(default=None),
    result: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(RenewalHistory)
    if domain:
        q = q.filter(RenewalHistory.domain_fqdn.ilike(f"%{domain}%"))
    if result:
        q = q.filter(RenewalHistory.result == result)
    records = q.order_by(RenewalHistory.created_at.desc()).all()
    return [_serialise(r) for r in records]


@router.delete("", status_code=204)
def clear_history(db: Session = Depends(get_db)):
    db.query(RenewalHistory).delete()
    db.commit()
