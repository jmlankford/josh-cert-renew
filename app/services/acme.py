"""
acme.sh subprocess wrapper.

All certificate operations run acme.sh as a subprocess. stdout and stderr are
merged and streamed line-by-line so the caller can forward them to the frontend
via Server-Sent Events.

acme.sh binary lives at /opt/acme.sh/acme.sh (never bind-mounted).
Cert data and account config are stored in /root/.acme.sh (bind-mounted volume).
"""

import asyncio
import os
from datetime import datetime
from typing import AsyncGenerator

ACME_SH = "/opt/acme.sh/acme.sh"
ACME_HOME = "/root/.acme.sh"


def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


async def _stream(cmd: list[str], env: dict) -> AsyncGenerator[tuple[str, int], None]:
    """
    Run *cmd* with the merged environment and yield (line, returncode) pairs.
    returncode is -1 for every line except the final sentinel where it holds
    the real exit code of the subprocess.
    """
    full_env = {**os.environ, **env}
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=full_env,
    )
    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        line = raw.decode(errors="replace").rstrip()
        yield (f"[{_ts()}] {line}", -1)

    rc = await process.wait()
    yield ("", rc)  # sentinel


async def issue_cert(
    fqdn: str,
    is_wildcard: bool,
    cf_token: str,
    cf_zone_id: str,
    acme_email: str,
) -> AsyncGenerator[tuple[str, int], None]:
    """
    Issue a new certificate via Cloudflare DNS challenge.
    For wildcard domains the command adds both *.root and root itself.
    Yields (log_line, returncode) — returncode == -1 until the final tuple.
    """
    cmd = [
        ACME_SH,
        "--home", ACME_HOME,
        "--issue",
        "--dns", "dns_cf",
        "--server", "letsencrypt",
        "-d", fqdn,
    ]
    if is_wildcard:
        cmd += ["-d", f"*.{fqdn}"]

    env = {
        "CF_Token": cf_token,
        "CF_Zone_ID": cf_zone_id,
        "ACME_EMAIL": acme_email,
    }
    return _stream(cmd, env)


async def renew_cert(
    fqdn: str,
    cf_token: str,
    cf_zone_id: str,
    acme_email: str,
) -> AsyncGenerator[tuple[str, int], None]:
    """
    Force-renew an existing certificate.
    Yields (log_line, returncode) — returncode == -1 until the final tuple.
    """
    cmd = [
        ACME_SH,
        "--home", ACME_HOME,
        "--renew",
        "--force",
        "--dns", "dns_cf",
        "--server", "letsencrypt",
        "-d", fqdn,
    ]
    env = {
        "CF_Token": cf_token,
        "CF_Zone_ID": cf_zone_id,
        "ACME_EMAIL": acme_email,
    }
    return _stream(cmd, env)


async def deploy_cert(
    fqdn: str,
    cpanel_hostname: str,
    cpanel_username: str,
    auth_method: str,
    credential: str,
) -> AsyncGenerator[tuple[str, int], None]:
    """
    Deploy an already-issued certificate to cPanel via cpanel_uapi deploy hook.
    Yields (log_line, returncode) — returncode == -1 until the final tuple.
    """
    cmd = [
        ACME_SH,
        "--home", ACME_HOME,
        "--deploy",
        "--deploy-hook", "cpanel_uapi",
        "-d", fqdn,
    ]
    env: dict = {
        "CPANEL_HOST": cpanel_hostname,
        "CPANEL_PORT": "2083",
        "CPANEL_USERNAME": cpanel_username,
    }
    if auth_method == "api_token":
        env["CPANEL_APITOKEN"] = credential
    else:
        env["CPANEL_PASSWORD"] = credential

    return _stream(cmd, env)


def parse_expiry_from_acme_info(fqdn: str) -> datetime | None:
    """
    Read the acme.sh cert info for *fqdn* and return the expiry datetime.
    Returns None if the cert directory or notAfter field is not found.
    """
    import subprocess

    result = subprocess.run(
        [ACME_SH, "--home", ACME_HOME, "--info", "-d", fqdn],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Le_NextRenewTime=") or line.startswith("Le_CertCreateTimeStr="):
            pass
        if "Le_CertCreateTimeStr" in line:
            # acme.sh stores human-readable date in this field after issuance
            pass

    # acme.sh --info outputs fields like:
    #   Le_CertCreateTimeStr='Thu 01 Jan 2026 00:00:00 UTC'
    # The most reliable approach is to read the cert directly.
    cert_file = os.path.join(ACME_HOME, fqdn, f"{fqdn}.cer")
    if not os.path.exists(cert_file):
        # Try without tld path variants
        for entry in os.listdir(ACME_HOME) if os.path.isdir(ACME_HOME) else []:
            if entry.startswith(fqdn):
                candidate = os.path.join(ACME_HOME, entry, f"{fqdn}.cer")
                if os.path.exists(candidate):
                    cert_file = candidate
                    break
        else:
            return None

    result = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", cert_file],
        capture_output=True,
        text=True,
    )
    # output: notAfter=Jan  1 00:00:00 2026 GMT
    for line in result.stdout.splitlines():
        if line.startswith("notAfter="):
            date_str = line.split("=", 1)[1].strip()
            try:
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
            except ValueError:
                return None
    return None
