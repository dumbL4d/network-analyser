"""Password hashing utilities (bcrypt).

JWT issuance/validation is intentionally NOT here yet; that arrives with the
auth ticket. This module only knows how to hash and verify bcrypt hashes.
"""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password into a bcrypt hash (``$2b$...``)."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the stored bcrypt ``hashed`` value."""
    return pwd_context.verify(plain, hashed)