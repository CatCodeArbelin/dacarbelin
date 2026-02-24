"""Определяет управление сессией администратора для веб-интерфейса."""

import base64
import hashlib
import hmac
import json
import time
import uuid

from app.core.config import settings

ADMIN_SESSION_COOKIE = "admin_session"
_USED_JUDGE_LOGIN_NONCES: set[str] = set()


def _b64_encode(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8")
    return encoded.rstrip("=")


def _b64_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")


def _sign(payload: str) -> str:
    digest = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def create_admin_session_cookie() -> str:
    payload = _b64_encode(json.dumps({"is_admin": True}, separators=(",", ":")))
    signature = _sign(payload)
    return f"{payload}.{signature}"


def create_judge_login_token(ttl_seconds: int = 60 * 10) -> str:
    now = int(time.time())
    payload_raw = json.dumps(
        {
            "purpose": "judge_login",
            "issued_at": now,
            "expires_at": now + ttl_seconds,
            "nonce": uuid.uuid4().hex,
        },
        separators=(",", ":"),
    )
    payload = _b64_encode(payload_raw)
    return f"{payload}.{_sign(payload)}"


def consume_judge_login_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False

    payload, signature = token.rsplit(".", 1)
    expected_signature = _sign(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        data = json.loads(_b64_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return False

    if data.get("purpose") != "judge_login":
        return False

    expires_at = data.get("expires_at")
    nonce = data.get("nonce")
    if not isinstance(expires_at, int) or not isinstance(nonce, str):
        return False
    if int(time.time()) > expires_at:
        return False
    if nonce in _USED_JUDGE_LOGIN_NONCES:
        return False

    _USED_JUDGE_LOGIN_NONCES.add(nonce)
    return True


def is_admin_session(cookie_value: str | None) -> bool:
    if not cookie_value or "." not in cookie_value:
        return False

    payload, signature = cookie_value.rsplit(".", 1)
    expected_signature = _sign(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        data = json.loads(_b64_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return False
    return bool(data.get("is_admin"))
