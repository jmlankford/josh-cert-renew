"""
Cloudflare API helpers.

Currently used only for test-connection validation of stored zone credentials.
acme.sh handles all DNS challenge operations natively via CF_Token / CF_Zone_ID.
"""

import httpx

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 10.0


async def validate_token(cf_token: str, cf_zone_id: str) -> dict:
    """
    Verify that cf_token can read the specified zone.

    Returns {"ok": True, "zone_name": "..."} on success.
    Returns {"ok": False, "error": "..."} on any failure.
    """
    headers = {
        "Authorization": f"Bearer {cf_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Verify token validity
            token_resp = await client.get(f"{CLOUDFLARE_API}/user/tokens/verify", headers=headers)
            if token_resp.status_code != 200:
                return {"ok": False, "error": f"Token verification failed: HTTP {token_resp.status_code}"}

            token_data = token_resp.json()
            if not token_data.get("success"):
                messages = "; ".join(m.get("message", "") for m in token_data.get("errors", []))
                return {"ok": False, "error": f"Cloudflare rejected token: {messages}"}

            # Verify the zone is accessible
            zone_resp = await client.get(f"{CLOUDFLARE_API}/zones/{cf_zone_id}", headers=headers)
            if zone_resp.status_code == 404:
                return {"ok": False, "error": "Zone ID not found or token lacks access to this zone"}
            if zone_resp.status_code != 200:
                return {"ok": False, "error": f"Zone lookup failed: HTTP {zone_resp.status_code}"}

            zone_data = zone_resp.json()
            if not zone_data.get("success"):
                messages = "; ".join(m.get("message", "") for m in zone_data.get("errors", []))
                return {"ok": False, "error": f"Zone lookup error: {messages}"}

            zone_name = zone_data["result"]["name"]
            return {"ok": True, "zone_name": zone_name}

    except httpx.TimeoutException:
        return {"ok": False, "error": "Request timed out reaching Cloudflare API"}
    except Exception as exc:
        return {"ok": False, "error": f"Unexpected error: {exc}"}
