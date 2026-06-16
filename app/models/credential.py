from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.db import Base


class CloudflareZone(Base):
    __tablename__ = "cloudflare_zones"

    id = Column(Integer, primary_key=True, index=True)
    zone_name = Column(String, nullable=False)
    cf_token_encrypted = Column(String, nullable=False)
    cf_zone_id = Column(String, nullable=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CPanelProfile(Base):
    __tablename__ = "cpanel_profiles"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, nullable=False)
    cpanel_hostname = Column(String, nullable=False)
    cpanel_username = Column(String, nullable=False)
    auth_method = Column(String, nullable=False)
    credential_encrypted = Column(String, nullable=False)
    addon_domain_suffix = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
