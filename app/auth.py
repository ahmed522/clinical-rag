"""
Password hashing and JWT issuing/verification.
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# bcrypt is used directly rather than through passlib: passlib 1.7.4's
# bcrypt backend probes `bcrypt.__about__`, which bcrypt 5.x removed, and
# its fallback path then raises on perfectly valid short passwords. One
# less compatibility layer between a password and its hash.

ROLE_CLINIC_ADMIN = "clinic_admin"
ROLE_PATIENT = "patient"

# bcrypt truncates silently at 72 bytes. Rejecting longer passwords is
# safer than accepting one whose tail is never actually checked.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Malformed stored hash, or an over-length candidate password.
        return False


def create_access_token(user_id: str, role: str, clinic_id: str) -> str:
    """
    Issue a token carrying the tenant.

    clinic_id lives in the token, not in request bodies, so a caller
    cannot reach another clinic's data by editing a payload.
    """
    expire = datetime.utcnow() + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "role": role,
        "clinic_id": clinic_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Return the claims, or None if the token is invalid or expired."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None
