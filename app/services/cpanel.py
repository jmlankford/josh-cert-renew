"""
cPanel UAPI helpers.

Used for test-connection validation of stored cPanel credential profiles.
Actual certificate deployment is handled by acme.sh's cpanel_uapi deploy hook
which reads CPANEL_* environment variables set per-invocation.
"""

import httpx

TIMEOUT = 10.0


def _build_headers(auth_method: str, credential: str, cpanel_username: str) -> dict:
    if auth_method == "api_token":
        return {
            "Authorization": f"cpanel {cpanel_username}:{credential}",
        }
    # Password auth uses HTTP Basic
    import base64
    token = base64.b64encode(f"{cpanel_username}:{credential}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def validate_profile(
    cpanel_hostname: str,
    cpanel_username: str,
    auth_method: str,
    credential: str,
) -> dict:
    """
    Verify credentials against cPanel UAPI by calling a lightweight endpoint
    (list email accounts — read-only, always available).

    Returns {"ok": True} on success.
    Returns {"ok": False, "error": "..."} on any failure.
    """
    headers = _build_headers(auth_method, credential, cpanel_username)
    url = f"https://{cpanel_hostname}:2083/execute/Email/list_pops?domain={cpanel_hostname}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:  # noqa: S501 – cPanel may use self-signed cert
            resp = await client.get(url, headers=headers)

        if resp.status_code == 401:
            return {"ok": False, "error": "Authentication failed — check username and credential"}
        if resp.status_code == 403:
            return {"ok": False, "error": "Access forbidden — API token may lack required permissions"}
        if resp.status_code not in (200, 204):
            return {"ok": False, "error": f"Unexpected HTTP {resp.status_code} from cPanel UAPI"}

        data = resp.json()
        if data.get("status") == 0:
            messages = "; ".join(data.get("errors") or ["Unknown error"])
            return {"ok": False, "error": f"cPanel returned error: {messages}"}

        return {"ok": True}

    except httpx.ConnectError:
        return {"ok": False, "error": f"Could not connect to {cpanel_hostname}:2083 — check hostname"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Request timed out reaching cPanel"}
    except Exception as exc:
        return {"ok": False, "error": f"Unexpected error: {exc}"}
