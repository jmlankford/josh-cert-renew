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
    yield ("", rc)


async def issue_cert(
    fqdn: str,
    is_wildcard: bool,
    cf_token: str,
    cf_zone_id: str,
    acme_email: str,
) -> AsyncGenerator[tuple[str, int], None]:
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
    addon_domain_suffix: str | None = None,
) -> AsyncGenerator[tuple[str, int], None]:
    """
    Deploy an already-issued certificate to cPanel via its UAPI HTTP endpoint.
    If addon_domain_suffix is set, also installs on the internal addon vhost
    (e.g. darkrosedeli.lankamerica.com) so HTTPS activates for addon domains.
    """
    import httpx

    ecc_dir = os.path.join(ACME_HOME, f"{fqdn}_ecc")
    rsa_dir = os.path.join(ACME_HOME, fqdn)
    cert_dir = ecc_dir if os.path.isdir(ecc_dir) else rsa_dir

    cert_file = os.path.join(cert_dir, f"{fqdn}.cer")
    key_file  = os.path.join(cert_dir, f"{fqdn}.key")
    ca_file   = os.path.join(cert_dir, "ca.cer")

    try:
        cert     = open(cert_file).read()
        key      = open(key_file).read()
        cabundle = open(ca_file).read() if os.path.exists(ca_file) else ""
    except FileNotFoundError as exc:
        yield (f"[{_ts()}] ERROR reading cert files: {exc}", -1)
        yield ("", 1)
        return

    url     = f"https://{cpanel_hostname}:2083/execute/SSL/install_ssl"
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
                yield (f"[{_ts()}] Certificate installed for {fqdn}.", -1)
            else:
                errors = data.get("errors") or [str(data)]
                yield (f"[{_ts()}] cPanel API error: {'; '.join(str(e) for e in errors)}", -1)
                yield ("", 1)
                return

            if addon_domain_suffix:
                root_label  = fqdn.split(".")[0]
                addon_vhost = f"{root_label}.{addon_domain_suffix}"
                yield (f"[{_ts()}] Installing on addon vhost {addon_vhost}…", -1)
                try:
                    resp2 = await client.post(
                        url, headers=headers, auth=auth,
                        data={"domain": addon_vhost, "cert": cert, "key": key, "cabundle": cabundle},
                    )
                    data2 = resp2.json()
                    if data2.get("status") == 1:
                        yield (f"[{_ts()}] Addon vhost install successful.", -1)
                    else:
                        errors2 = data2.get("errors") or [str(data2)]
                        yield (f"[{_ts()}] Addon vhost warning: {'; '.join(str(e) for e in errors2)}", -1)
                except Exception as exc2:
                    yield (f"[{_ts()}] Addon vhost install warning: {exc2}", -1)

        yield ("", 0)
    except Exception as exc:
        yield (f"[{_ts()}] Deploy request failed: {exc}", -1)
        yield ("", 1)


def parse_expiry_from_acme_info(fqdn: str) -> datetime | None:
    import subprocess

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
    for line in result.stdout.splitlines():
        if line.startswith("notAfter="):
            date_str = line.split("=", 1)[1].strip()
            try:
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
            except ValueError:
                return None
    return None
