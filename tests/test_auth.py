"""Tests for issue-scout auth module."""
from __future__ import annotations

import json
import sys

import pytest
import requests

from issue_scout import auth as auth_mod
from issue_scout.client import AuthError


@pytest.fixture
def temp_auth_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    return tmp_path / "issue-scout" / "auth.json"


def test_save_and_load_round_trip(temp_auth_dir):
    auth_mod.save_token("ghp_abc123")
    assert temp_auth_dir.exists()
    assert auth_mod.load_token() == "ghp_abc123"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_save_token_is_0600(temp_auth_dir):
    auth_mod.save_token("ghp_abc")
    mode = temp_auth_dir.stat().st_mode & 0o777
    assert mode == 0o600


def test_load_returns_none_when_missing(temp_auth_dir):
    assert auth_mod.load_token() is None


def test_load_returns_none_when_corrupt(temp_auth_dir):
    temp_auth_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_auth_dir.write_text("{not json")
    assert auth_mod.load_token() is None


def test_delete_token_idempotent(temp_auth_dir):
    assert auth_mod.delete_token() is False
    auth_mod.save_token("x")
    assert auth_mod.delete_token() is True
    assert auth_mod.delete_token() is False


def test_resolve_credential_priority(temp_auth_dir):
    assert auth_mod.resolve_credential("flagtok", "envtok") == ("flagtok", "flag")
    assert auth_mod.resolve_credential(None, "envtok") == ("envtok", "env")
    assert auth_mod.resolve_credential(None, None) == (None, "anonymous")
    auth_mod.save_token("savedtok")
    assert auth_mod.resolve_credential(None, None) == ("savedtok", "saved")


def test_mask_token():
    assert auth_mod.mask_token("ghp_abcdef123456") == "ghp_…3456"
    assert auth_mod.mask_token("short") == "****"
    assert auth_mod.mask_token("") == ""


# ----- device_login -----

class _FakeResp:
    def __init__(self, status: int, body: dict | None = None, text: str = "", json_ct: bool = True):
        self.status_code = status
        self._body = body or {}
        self.text = text or json.dumps(self._body)
        self.headers = {"content-type": "application/json"} if json_ct else {}

    def json(self):
        return self._body


def test_device_login_success(monkeypatch):
    sleeps: list[float] = []
    responses = [
        _FakeResp(200, {"device_code": "DC", "user_code": "ABCD-1234",
                        "verification_uri": "https://example/login/device",
                        "interval": 5, "expires_in": 900}),
        _FakeResp(200, {"error": "authorization_pending"}),
        _FakeResp(200, {"error": "slow_down"}),
        _FakeResp(200, {"access_token": "gho_TEST"}),
    ]

    def fake_post(self, url, data=None, headers=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: False)

    token = auth_mod.device_login(open_browser=False, sleep=sleeps.append)
    assert token == "gho_TEST"
    # 3 polls (skipping the initial device_code call)
    assert len(sleeps) == 3
    # interval should have been bumped by slow_down: 5,5,10
    assert sleeps == [5, 5, 10]


def test_device_login_expired(monkeypatch):
    responses = [
        _FakeResp(200, {"device_code": "DC", "user_code": "X", "verification_uri": "u",
                        "interval": 5, "expires_in": 900}),
        _FakeResp(200, {"error": "expired_token"}),
    ]

    def fake_post(self, url, data=None, headers=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: False)

    with pytest.raises(AuthError, match="expired"):
        auth_mod.device_login(open_browser=False, sleep=lambda s: None)


def test_device_login_denied(monkeypatch):
    responses = [
        _FakeResp(200, {"device_code": "DC", "user_code": "X", "verification_uri": "u",
                        "interval": 5, "expires_in": 900}),
        _FakeResp(200, {"error": "access_denied"}),
    ]

    def fake_post(self, url, data=None, headers=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: False)

    with pytest.raises(AuthError, match="denied"):
        auth_mod.device_login(open_browser=False, sleep=lambda s: None)


def test_device_login_http_error(monkeypatch):
    responses = [_FakeResp(500, {}, text="boom")]

    def fake_post(self, url, data=None, headers=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    with pytest.raises(AuthError, match="500"):
        auth_mod.device_login(open_browser=False, sleep=lambda s: None)
