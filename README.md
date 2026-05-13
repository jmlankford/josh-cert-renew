# SSL Manager

Self-hosted web application for managing free Let's Encrypt SSL certificates
across multiple domains and subdomains. DNS challenges run via Cloudflare,
certificates deploy to Namecheap cPanel hosting via acme.sh's `cpanel_uapi`
hook. Designed for deployment on Unraid via Portainer.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| Database | SQLite (bind-mounted volume) |
| Cert tooling | acme.sh v3.0.7 (pinned) |
| DNS challenge | Cloudflare API (dns_cf plugin) |
| Deployment hook | cPanel UAPI |
| Frontend | Vanilla JS, no framework |
| Container | Docker, managed via Portainer |

---

## Prerequisites

### 1. Cloudflare API Token

Each managed zone needs a dedicated API token:

1. Go to **Cloudflare Dashboard → My Profile → API Tokens → Create Token**
2. Use the **Edit zone DNS** template
3. Under **Zone Resources** select **Specific zone → your domain**
4. Click **Continue to summary → Create Token**
5. Copy the token — you will enter it in the app's Credentials page

Required permission: `Zone → DNS → Edit` on the target zone.

### 2. Namecheap cPanel API Token

1. Log in to **Namecheap → cPanel** for your hosting account
2. Go to **Security → Manage API Tokens → Create**
3. Name the token (e.g. "acme-ssl-manager"), set no expiry
4. Copy the token — you will enter it in the app's Credentials page

The app uses port `2083` (HTTPS) to reach cPanel UAPI.

---

## First Deploy via Portainer (Git Repo Stack Method)

1. In Portainer, navigate to **Stacks → Add stack → Repository**
2. Set **Repository URL** to this GitHub repo URL
3. Set **Compose path** to `docker-compose.yml`
4. Under **Environment variables**, add:

   | Variable | Value |
   |---|---|
   | `ADMIN_PASSWORD` | A strong password for the web UI |
   | `MASTER_SECRET` | A random 32+ character string |
   | `ACME_EMAIL` | Your email for Let's Encrypt registration |
   | `RENEWAL_CRON_TIME` | `02:00` (or your preferred UTC time) |

5. Click **Deploy the stack**

The app will be available at `http://YOUR-UNRAID-IP:11518`

> **Note:** `MASTER_SECRET` and `ADMIN_PASSWORD` are required. The container
> will exit immediately with a clear error message if either is missing.

---

## Volume Structure

```
/mnt/user/appdata/JOSH-OS/certrenew/
├── db/
│   └── certmanager.db    ← SQLite database (domains, credentials, history)
└── acme/                 ← acme.sh home (/root/.acme.sh in container)
    ├── account.conf      ← CA and account settings
    ├── bloomandrose.com/ ← issued cert files per domain
    └── ...
```

Both directories are created automatically on first run if they do not exist.
Both survive container rebuilds, image pulls, and Portainer stack updates
because they are bind-mounted from the Unraid host filesystem.

---

## Adding a New Domain

1. Open the app at `http://YOUR-UNRAID-IP:11518`
2. Ensure you have added a **Cloudflare Zone** and a **cPanel Profile** on the
   Credentials page first
3. Click **Add Domain** on the Domains page
4. Choose APEX or Subdomain; for APEX you can optionally tick **Wildcard cert**
   to issue `*.yourdomain.com + yourdomain.com` in one cert
5. Select the matching Cloudflare zone and cPanel profile
6. Click **Save Domain** — the row appears with status `NEVER ISSUED`
7. Click **Issue** in the Actions column
8. A live terminal log streams acme.sh output in real time
9. On success the cert is deployed to cPanel automatically; status becomes
   `ACTIVE` and expiry date is populated

---

## Manually Triggering a Renewal

Click the **Renew** button on any domain row in the Domains table. This runs
`acme.sh --renew --force` regardless of expiry state and redeploys the cert
via `cpanel_uapi`.

Alternatively, exec into the container and run acme.sh directly:

```bash
docker exec -it josh-certrenew \
  /root/.acme.sh/acme.sh --renew --force -d yourdomain.com
```

---

## Auto-Renewal Schedule

The scheduler runs daily at the time configured in `RENEWAL_CRON_TIME` (UTC).
Any domain with an expiry within **30 days** is automatically force-renewed and
redeployed. Results are logged to the **Renewal History** page.

The **Last Auto-Renewal** indicator in the summary bar shows the most recent
run timestamp and a PASS / FAIL status.

---

## Backup

The only file that needs backing up is the SQLite database:

```bash
# On the Unraid host
cp /mnt/user/appdata/JOSH-OS/certrenew/db/certmanager.db \
   /mnt/user/appdata/JOSH-OS/certrenew/db/certmanager.db.$(date +%Y%m%d)
```

The `/mnt/user/appdata/JOSH-OS/certrenew/acme/` directory contains issued
cert files and the acme.sh account key. Back it up along with the database if
you want to avoid re-registering with Let's Encrypt after a full restore.

Consider scheduling this with Unraid's User Scripts plugin or a cron job.

---

## Troubleshooting

### acme.sh exits non-zero / DNS challenge fails

- Verify the Cloudflare token has **DNS:Edit** permission on the exact zone
- Use the **Test** button on the Credentials page to validate the token
- Check that `CF_Zone_ID` matches the zone shown in Cloudflare Dashboard →
  your domain → Overview (bottom-right "Zone ID")
- acme.sh requires the DNS TXT record to propagate before it can verify;
  if your zone's TTL is high this may time out — lower the TTL on the zone's
  SOA or wait and retry

### cPanel UAPI auth failures

- Confirm the cPanel hostname is the server hostname (e.g.
  `server123.web-hosting.com`), not your domain
- Use the **Test** button on the Credentials page
- If using a cPanel API Token, ensure it was created under **Security →
  Manage API Tokens** inside cPanel (not Namecheap account-level API)
- Port `2083` must be reachable from the Docker host; some networks block it

### Container exits at startup

Check logs with `docker logs josh-certrenew`. The most common cause is a
missing `MASTER_SECRET` or `ADMIN_PASSWORD` environment variable. Both must be
set in `.env` or the Portainer environment variables panel.

### Certificate shows ACTIVE but is expired in browser

The expiry date in the app is read from the cert file after issuance. If the
cert was issued outside the app (e.g. manually via acme.sh), the DB row won't
update automatically — click **Renew** to force a fresh issue and sync the date.

### Wildcard cert not covering subdomains in browser

Wildcard certs (`*.domain.com`) do not cover the root apex (`domain.com`).
The app issues both when the wildcard option is selected, so both should be
deployed to cPanel. If the root is not covered, verify the cPanel SSL
installation shows both the wildcard and the root in the "Domains" field.
