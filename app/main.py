"""
SSL Certificate Manager — FastAPI application entry point.

Startup checks:
  - MASTER_SECRET must be set (required for Fernet encryption)
  - ADMIN_PASSWORD must be set (gates all routes via HTTP Basic Auth)

All API routes are protected by HTTP Basic Auth.
The SPA (index.html) is served from /app/static/ and is also auth-gated
via a separate dependency on the static-file mount.
"""

import os
import secrets
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routes import domains, credentials, history, dashboard
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Startup validation ────────────────────────────────────────────

def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "The application cannot start without it."
        )
    return value


# Fail immediately at import time so the container exits with a clear message
# rather than accepting traffic with a broken configuration.
_ADMIN_PASSWORD = _require_env("ADMIN_PASSWORD")
_MASTER_SECRET = _require_env("MASTER_SECRET")  # also initialises crypto module


# ── HTTP Basic Auth ──────────────────────────────────────────────

_security = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    correct_password = secrets.compare_digest(
        credentials.password.encode(), _ADMIN_PASSWORD.encode()
    )
    if not correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="SSL Manager"'},
        )
    return credentials.username


# ── Application lifespan ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised")
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Scheduler stopped")


# ── FastAPI app ────────────────────────────────────────────────

app = FastAPI(
    title="SSL Certificate Manager",
    version="1.0.0",
    docs_url=None,   # disable Swagger UI in production
    redoc_url=None,
    lifespan=lifespan,
)


# ── API routes (auth-gated) ───────────────────────────────────────────

_auth_dep = [Depends(require_auth)]

app.include_router(domains.router, dependencies=_auth_dep)
app.include_router(credentials.router, dependencies=_auth_dep)
app.include_router(history.router, dependencies=_auth_dep)
app.include_router(dashboard.router, dependencies=_auth_dep)


# ── Static SPA ────────────────────────────────────────────────
# Served last so /api/* routes take priority.
# The browser's Basic Auth prompt covers the SPA automatically because the
# first API call the page makes will trigger the 401 challenge.

_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
