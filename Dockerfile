FROM python:3.11-slim

# ── System dependencies required by acme.sh ────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      git \
      socat \
      openssl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Install acme.sh pinned to v3.0.7 ─────────────────────────────────────────
# Binary and support dirs go to /opt/acme.sh — never bind-mounted, always
# present at runtime. /root/.acme.sh is bind-mounted for cert data only.
ARG ACME_VERSION=3.0.7
RUN curl -sSL \
      "https://github.com/acmesh-official/acme.sh/archive/refs/tags/${ACME_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
    && mkdir -p /opt/acme.sh \
    && cp /tmp/acme.sh-${ACME_VERSION}/acme.sh /opt/acme.sh/acme.sh \
    && cp -r /tmp/acme.sh-${ACME_VERSION}/deploy /opt/acme.sh/deploy \
    && cp -r /tmp/acme.sh-${ACME_VERSION}/dnsapi /opt/acme.sh/dnsapi \
    && chmod +x /opt/acme.sh/acme.sh \
    && rm -rf /tmp/acme.sh-${ACME_VERSION}

# ── Python application ───────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Data directory (overridden at runtime by bind mount)
RUN mkdir -p /app/data

EXPOSE 8443

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8443"]
