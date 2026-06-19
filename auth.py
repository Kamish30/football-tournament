"""Authentication: JWT tokens and password hashing."""

import os
import hashlib
import hmac
import json
import base64
import time
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-tournament-2024")
TOKEN_EXPIRE_HOURS = 72

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, h = password_hash.split("$")
    return hmac.compare_digest(
        h, hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    )


def create_token(user_id: int, username: str, role: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
    payload_data = {
        "sub": user_id, "username": username, "role": role,
        "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
    }
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{header}.{payload}.{signature}"


def decode_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError()
        header, payload, signature = parts
        expected_sig = hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("Bad signature")
        padding = 4 - len(payload) % 4
        payload_data = json.loads(base64.urlsafe_b64decode(payload + "=" * padding))
        if payload_data.get("exp", 0) < time.time():
            raise ValueError("Token expired")
        return payload_data
    except Exception:
        raise HTTPException(status_code=401, detail="Невалидный или истёкший токен")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Dependency: require auth."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return decode_token(credentials.credentials)


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency: auth optional (for public pages)."""
    if not credentials:
        return None
    try:
        return decode_token(credentials.credentials)
    except Exception:
        return None
