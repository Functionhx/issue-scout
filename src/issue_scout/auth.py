"""Credential storage + GitHub OAuth Device Flow for issue-scout."""
from __future__ import annotations

import json
import os
import platform
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests

from .client import AuthError, NetworkError

OAUTH_CLIENT_ID = "Ov23liplxjhVEwR0TlMs"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
OAUTH_SCOPE = "public_repo"


def _config_dir() -> Path:
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "issue-scout"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "issue-scout"


def auth_file() -> Path:
    return _config_dir() / "auth.json"


def load_token() -> str | None:
    path = auth_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = data.get("github_token")
    return token if isinstance(token, str) and token else None


def save_token(token: str) -> Path:
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    payload = {
        "github_token": token,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def delete_token() -> bool:
    path = auth_file()
    if path.exists():
        path.unlink()
        return True
    return False


def resolve_credential(
    explicit_token: str | None, env_token: str | None
) -> tuple[str | None, str]:
    """Return (token, source). source ∈ {flag, env, saved, anonymous}."""
    if explicit_token:
        return explicit_token, "flag"
    if env_token:
        return env_token, "env"
    saved = load_token()
    if saved:
        return saved, "saved"
    return None, "anonymous"


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-4:]}"


def device_login(
    *,
    client_id: str | None = None,
    open_browser: bool = True,
    console=None,
    sleep=time.sleep,
    session: requests.Session | None = None,
) -> str:
    """Run the GitHub OAuth Device Flow; return the access_token on success."""
    cid = client_id or os.environ.get("ISSUE_SCOUT_CLIENT_ID") or OAUTH_CLIENT_ID
    sess = session or requests.Session()
    headers = {"Accept": "application/json", "User-Agent": "issue-scout"}

    try:
        resp = sess.post(
            DEVICE_CODE_URL,
            data={"client_id": cid, "scope": OAUTH_SCOPE},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as e:
        raise NetworkError(f"Could not reach GitHub: {e}") from e
    if resp.status_code >= 400:
        raise AuthError(f"GitHub device code endpoint returned {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if "device_code" not in data:
        raise AuthError(f"Unexpected device-code response: {data}")

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri") or "https://github.com/login/device"
    interval = max(int(data.get("interval", 5)), 5)
    expires_in = int(data.get("expires_in", 900))

    if console is not None:
        console.print(
            f"\n[bold]To authorize issue-scout, open[/] [cyan]{verification_uri}[/]\n"
            f"and enter the code: [bold yellow]{user_code}[/]\n"
        )
    else:
        print(f"Open {verification_uri} and enter code: {user_code}")
    sys.stdout.flush()
    sys.stderr.flush()

    if open_browser:
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        sleep(interval)
        try:
            poll = sess.post(
                ACCESS_TOKEN_URL,
                data={
                    "client_id": cid,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            raise NetworkError(f"Polling GitHub failed: {e}") from e
        body = poll.json() if poll.headers.get("content-type", "").startswith("application/json") else {}
        if "access_token" in body:
            return body["access_token"]
        err = body.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err == "expired_token":
            raise AuthError("Device code expired. Run 'issue-scout login' again.")
        if err == "access_denied":
            raise AuthError("Authorization was denied.")
        if err:
            raise AuthError(f"OAuth error: {err} — {body.get('error_description', '')}")
        raise AuthError(f"Unexpected response while polling: {poll.text[:200]}")

    raise AuthError("Device flow timed out waiting for authorization.")
