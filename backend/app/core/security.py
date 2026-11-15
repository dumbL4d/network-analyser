"""Password hashing (bcrypt) and JWT access-token helpers.

Token issuance/validation lives here; the auth dependencies the routes use
are in ``app.core.deps``.
"""

import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from passlib.exc import PasswordValueError

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# The signing secrets this repository ships as examples: the default in
# config.py (also in backend/.env.example) and the one in infra/.env.example.
# Anyone can read them, so anyone could sign a token with them.
PLACEHOLDER_JWT_SECRETS = frozenset(
    {"CHANGE_ME_DEV_ONLY_INSECURE_DEFAULT", "generate_me_with_openssl_rand_hex_32"}
)
# HS256 wants a key of at least 256 bits; `openssl rand -hex 32` gives 64
# characters.
MIN_JWT_SECRET_LENGTH = 32


def jwt_secret_problem(secret: str) -> str | None:
    """Why ``secret`` must not sign tokens, or None when it may. Pure."""
    if secret in PLACEHOLDER_JWT_SECRETS:
        return "JWT_SECRET_KEY is still a placeholder from the example files, which anyone can read"
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        return (
            f"JWT_SECRET_KEY is {len(secret)} characters long, and it has to be "
            f"at least {MIN_JWT_SECRET_LENGTH}"
        )
    return None


def require_private_jwt_secret() -> None:
    """Refuse to start on a signing secret that others can know or guess.

    Whoever has the secret can sign a token for any account, admin included,
    without a password. DEMO_MODE is the one exception: its passwords are
    public anyway, so it starts with a warning.

    Called first thing at startup rather than when the settings are loaded, so
    tools that only need the database path (alembic, the scripts) still run.
    """
    problem = jwt_secret_problem(settings.JWT_SECRET_KEY)
    if problem is None:
        return
    if not settings.DEMO_MODE:
        raise RuntimeError(
            f"Refusing to start: {problem}. Generate one with `openssl rand -hex 32` "
            "and set it as JWT_SECRET_KEY."
        )
    logger.warning(
        "%s. Starting anyway because DEMO_MODE is on: whoever knows the secret "
        "can sign in as any user without a password.",
        problem,
    )


def hash_password(plain: str) -> str:
    """Hash a plaintext password into a bcrypt hash (``$2b$...``)."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the stored bcrypt ``hashed`` value.

    A password bcrypt cannot take (one with a NUL byte, or thousands of
    characters long) is nobody's password: False, not an error.
    """
    try:
        return pwd_context.verify(plain, hashed)
    except PasswordValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    """Build a signed HS256 JWT for ``subject`` (the username).

    Claims: ``sub``, ``role``, ``iat`` (when it was issued) and ``exp``
    (``settings.JWT_EXPIRE_MINUTES`` later).
    """
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a token, raising ``jose.JWTError`` on any failure.

    Callers translate the exception into an HTTP 401; it is deliberately not
    caught here.
    """
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )