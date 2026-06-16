from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.db import Base


class CloudflareZone(Base):
    __tablename__ = "cloudflare_zones"

    id = Column(Integer, primary_key=True, index=True)
    zone_name = Column(String, nullable=False)           # e.g. "bloomandrose.com"
    cf_token_encrypted = Column(String, nullable=False)  # Fernet-encrypted Cloudflare API token
    cf_zone_id = Column(String, nullable=False)          # Cloudflare Zone ID (plain — not secret)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CPanelProfile(Base):
    __tablename__ = "cpanel_profiles"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, nullable=False)            # e.g. "Namecheap Main"
    cpanel_hostname = Column(String, nullable=False)         # e.g. "server123.web-hosting.com"
    cpanel_username = Column(String, nullable=False)
    auth_method = Column(String, nullable=False)             # "api_token" | "password"
    credential_encrypted = Column(String, nullable=False)    # Fernet-encrypted API token or password
    addon_domain_suffix = Column(String, nullable=True)      # e.g. "lankamerica.com" — primary domain for addon-domain hosts

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
