"""Phase 17 — Password Security and JWT Bearer Token Cryptography.

Provides:
1. Salted PBKDF2-HMAC-SHA256 password hashing with constant-time verification.
2. Standard RFC 7519 HMAC-SHA256 (HS256) JSON Web Token (JWT) encoding and validation.
3. Cryptographic signature and expiration checks with zero secrets leaked.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Any, Optional

from common.config import settings
from .models import ProjectMembership, TokenPayload, User

logger = logging.getLogger(__name__)

# Password hashing constants
PBKDF2_ITERATIONS = 100_000
SALT_BYTES = 32
HASH_NAME = "sha256"


class AuthSecurityError(Exception):
    """Base exception for authentication and token validation errors."""
    pass


class InvalidTokenError(AuthSecurityError):
    """Raised when token signature, format, or claims are malformed or invalid."""
    pass


class TokenExpiredError(AuthSecurityError):
    """Raised when token expiration timestamp has elapsed."""
    pass


# ==============================================================================
# Password Hashing & Verification
# ==============================================================================

def hash_password(password: str) -> str:
    """Computes a salted PBKDF2-HMAC-SHA256 hash using a cryptographically secure random salt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        HASH_NAME,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_hex = salt.hex()
    derived_hex = derived.hex()
    return f"$pbkdf2-{HASH_NAME}${PBKDF2_ITERATIONS}${salt_hex}${derived_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a stored modular crypt format hash in constant time."""
    if not plain_password or not hashed_password:
        return False
    try:
        parts = hashed_password.split("$")
        if len(parts) != 5:
            return False
        _, algo, iters_str, salt_hex, expected_hex = parts
        if algo != f"pbkdf2-{HASH_NAME}":
            return False
        iterations = int(iters_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        actual = hashlib.pbkdf2_hmac(
            HASH_NAME,
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    except Exception as exc:
        logger.warning(f"Password verification encountered error: {exc}")
        return False


# ==============================================================================
# Base64URL Encoding & Decoding (RFC 7515 / RFC 7519)
# ==============================================================================

def _base64url_encode(data: bytes) -> str:
    """Encodes bytes to base64url string without trailing padding '='."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    """Decodes a base64url string, adding required padding."""
    rem = len(data) % 4
    if rem > 0:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data.encode("utf-8"))


# ==============================================================================
# JWT Bearer Token Encoding & Decoding (HS256)
# ==============================================================================

import uuid


def get_signing_secret() -> str:
    """Retrieves the configured JWT secret key.
    Fails safely if missing or empty without fallback to hardcoded secrets.
    """
    secret = getattr(settings, "jwt_secret_key", "") or os.environ.get("JWT_SECRET_KEY", "") or os.environ.get("BEACON_JWT_SECRET", "")
    if not secret or len(secret.strip()) == 0:
        raise RuntimeError("JWT_SECRET_KEY is missing or invalid.")
    return secret


def create_access_token(
    user: User,
    memberships: Optional[list[ProjectMembership]] = None,
    expires_delta: Optional[timedelta] = None,
    secret_key: Optional[str] = None,
) -> str:
    """Generates a cryptographically signed HS256 JWT access token with unique jti."""
    key = secret_key or get_signing_secret()
    now = datetime.now(timezone.utc)
    expire_minutes = getattr(settings, "jwt_access_token_expire_minutes", 60)
    delta = expires_delta or timedelta(minutes=expire_minutes)
    exp = now + delta
    jti = uuid.uuid4().hex

    # Map memberships to dictionary {project_id: role_name}
    membership_dict = {}
    if memberships:
        for m in memberships:
            membership_dict[m.project_id] = m.role.value if hasattr(m.role, "value") else str(m.role)

    if isinstance(user, dict):
        user_id = user.get("user_id") or user.get("sub", "admin")
        username = user.get("username") or user.get("sub", "admin")
        is_sys_admin = bool(user.get("is_system_admin") or user.get("role") == "admin" or user.get("is_admin"))
    else:
        user_id = user.user_id
        username = user.username
        is_sys_admin = bool(user.is_system_admin)

    header = {
        "alg": "HS256",
        "typ": "JWT",
    }
    payload = {
        "sub": user_id,
        "username": username,
        "is_system_admin": is_sys_admin,
        "jti": jti,
        "memberships": membership_dict,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "token_type": "access",
    }

    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    encoded_header = _base64url_encode(header_bytes)
    encoded_payload = _base64url_encode(payload_bytes)

    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    encoded_signature = _base64url_encode(signature)

    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def decode_access_token(
    token: str,
    secret_key: Optional[str] = None,
    verify_exp: bool = True,
) -> TokenPayload:
    """Decodes, verifies signature, expiration, and revocation status of an HS256 JWT access token."""
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Token is empty or not a string")

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise InvalidTokenError("Malformed JWT token: expected 3 dot-separated segments")

    encoded_header, encoded_payload, encoded_signature = parts
    key = secret_key or get_signing_secret()

    # 1. Verify HMAC-SHA256 Signature
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    expected_signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    
    try:
        actual_signature = _base64url_decode(encoded_signature)
    except Exception as exc:
        raise InvalidTokenError(f"Invalid signature encoding: {exc}") from exc

    if not hmac.compare_digest(actual_signature, expected_signature):
        raise InvalidTokenError("Invalid token signature (tampered or wrong signing key)")

    # 2. Decode Header
    try:
        header = json.loads(_base64url_decode(encoded_header).decode("utf-8"))
        if header.get("alg") != "HS256":
            raise InvalidTokenError(f"Unsupported algorithm '{header.get('alg')}'; only HS256 supported")
    except Exception as exc:
        if isinstance(exc, InvalidTokenError):
            raise
        raise InvalidTokenError(f"Malformed token header: {exc}") from exc

    # 3. Decode Payload
    try:
        payload_data = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        raise InvalidTokenError(f"Malformed token payload JSON: {exc}") from exc

    # 4. Verify Token Type (must be 'access')
    token_type = payload_data.get("token_type")
    if token_type != "access":
        raise InvalidTokenError(f"Invalid token type '{token_type}'; expected 'access'")

    # 5. Verify Expiration
    if verify_exp:
        exp = payload_data.get("exp")
        if exp is None:
            raise InvalidTokenError("Token missing required 'exp' claim")
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if now_ts > int(exp):
            raise TokenExpiredError(f"Token has expired (exp: {exp}, now: {now_ts})")

    # 5. Verify Revocation Status
    jti = str(payload_data.get("jti", ""))
    if jti:
        from .repository import auth_repository
        if auth_repository.is_token_revoked(jti):
            raise InvalidTokenError("Authentication token has been revoked (logged out)")

    # 6. Build TokenPayload
    return TokenPayload(
        sub=str(payload_data.get("sub", "")),
        username=str(payload_data.get("username", "")),
        is_system_admin=bool(payload_data.get("is_system_admin", False)),
        jti=jti,
        memberships=payload_data.get("memberships", {}),
        iat=int(payload_data.get("iat", 0)),
        exp=int(payload_data.get("exp", 0)),
        token_type=str(payload_data.get("token_type", "access")),
    )
