FROM python:3.11-slim

# ── System dependencies required by acme.sh ────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      git \
      socat \
      openssl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Install acme.sh pinned to v3.0.7 ──────────────────────────────────────────
# --install-online is intentionally NOT used so the tag is honoured exactly.
# We clone the specific tag and run the installer so acme.sh writes its config
# and default CA setting into /root/.acme.sh (which is bind-mounted at runtime).
ARG ACME_VERSION=3.0.7
RUN curl -sSL \
      "https://github.com/acmesh-official/acme.sh/archive/refs/tags/${ACME_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
    && /tmp/acme.sh-${ACME_VERSION}/acme.sh \
         --install \
         --home /root/.acme.sh \
         --nocron \
    && rm -rf /tmp/acme.sh-${ACME_VERSION}

# ── Set Let's Encrypt as default CA ───────────────────────────────────────────
# This writes to /root/.acme.sh/account.conf. The bind-mounted volume at
# /root/.acme.sh will persist this setting across container rebuilds.
RUN /root/.acme.sh/acme.sh \
      --set-default-ca \
      --server letsencrypt

# ── Python application ─────────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Data directory (overridden at runtime by bind mount)
RUN mkdir -p /app/data

EXPOSE 8443

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8443"]
