from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.db import Base


class RenewalHistory(Base):
    __tablename__ = "renewal_history"

    id = Column(Integer, primary_key=True, index=True)
    domain_fqdn = Column(String, nullable=False, index=True)
    result = Column(String, nullable=False)          # "success" | "failure"
    log_output = Column(Text, nullable=True)         # full captured acme.sh stdout+stderr
    triggered_by = Column(String, nullable=False, default="scheduler")  # "scheduler" | "manual"

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
