from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.db import Base


class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)

    # DNS identity
    root_domain = Column(String, nullable=False)          # e.g. "bloomandrose.com"
    subdomain = Column(String, nullable=True)             # None → APEX record; "www" → subdomain
    fqdn = Column(String, nullable=False, unique=True)    # fully-qualified domain name stored for quick lookup

    # Certificate options
    is_wildcard = Column(Boolean, default=False)          # only valid when subdomain is None (APEX)

    # Credential links (FK-style integer references; no SQLAlchemy relationship
    # to avoid cascade complexity on a small single-user tool)
    cpanel_profile_id = Column(Integer, nullable=True)
    cloudflare_zone_id = Column(Integer, nullable=True)

    # Deploy target: "cpanel" | "homelab"
    deploy_target = Column(String, nullable=False, default="cpanel")

    # Certificate state
    status = Column(String, nullable=False, default="NEVER ISSUED")
    # status values: "NEVER ISSUED" | "PENDING" | "ACTIVE" | "ERROR"

    expiry_date = Column(DateTime, nullable=True)

    # Audit timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
