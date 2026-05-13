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
    Deploy an already-issued certificate to cPanel via its UAPI HTTP endpoint.
    acme.sh's cpanel_uapi deploy hook requires the uapi CLI on the cPanel server
    itself; this instead POSTs directly to https://{host}:2083/execute/SSL/install_ssl.
    Yields (log_line, returncode) — returncode == -1 until the final tuple.
    """
    import httpx

    # acme.sh stores ECC certs in {fqdn}_ecc, RSA certs in {fqdn}
    ecc_dir = os.path.join(ACME_HOME, f"{fqdn}_ecc")
    rsa_dir = os.path.join(ACME_HOME, fqdn)
    cert_dir = ecc_dir if os.path.isdir(ecc_dir) else rsa_dir

    cert_file = os.path.join(cert_dir, f"{fqdn}.cer")
    key_file  = os.path.join(cert_dir, f"{fqdn}.key")
    ca_file   = os.path.join(cert_dir, "ca.cer")

    try:
        cert      = open(cert_file).read()
        key       = open(key_file).read()
        cabundle  = open(ca_file).read() if os.path.exists(ca_file) else ""
    except FileNotFoundError as exc:
        yield (f"[{_ts()}] ERROR reading cert files: {exc}", -1)
        yield ("", 1)
        return

    url = f"https://{cpanel_hostname}:2083/execute/SSL/install_ssl"
    headers = {"Authorization": f"cpanel {cpanel_username}:{credential}"} if auth_method == "api_token" else {}
    auth    = None if auth_method == "api_token" else (cpanel_username, credential)

    yield (f"[{_ts()}] Installing certificate for {fqdn} via cPanel UAPI HTTP…", -1)

    try:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            resp = await client.post(
                url, headers=headers, auth=auth,
                data={"domain": fqdn, "cert": cert, "key": key, "cabundle": cabundle},
            )
        data = resp.json()
        if data.get("status") == 1:
            yield (f"[{_ts()}] Certificate installed successfully on cPanel.", -1)
            yield ("", 0)
        else:
            errors = data.get("errors") or [str(data)]
            yield (f"[{_ts()}] cPanel API error: {'; '.join(str(e) for e in errors)}", -1)
            yield ("", 1)
    except Exception as exc:
        yield (f"[{_ts()}] Deploy request failed: {exc}", -1)
        yield ("", 1)


def parse_expiry_from_acme_info(fqdn: str) -> datetime | None:
    """
    Read the cert file for *fqdn* and return the expiry datetime.
    Returns None if the cert file is not found.
    """
    import subprocess

    # Check ECC dir first, then RSA dir
    ecc_cert = os.path.join(ACME_HOME, f"{fqdn}_ecc", f"{fqdn}.cer")
    rsa_cert  = os.path.join(ACME_HOME, fqdn, f"{fqdn}.cer")
    if os.path.exists(ecc_cert):
        cert_file = ecc_cert
    elif os.path.exists(rsa_cert):
        cert_file = rsa_cert
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
