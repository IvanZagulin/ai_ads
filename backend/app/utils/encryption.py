"""Fernet-based encryption for sensitive tokens."""

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet(key_str: str) -> Fernet:
    """Create Fernet instance from a base64-encoded key string."""
    if len(key_str) == 32 and not key_str.endswith('='):
        key = base64.urlsafe_b64encode(key_str.encode())
    else:
        key = key_str.encode()
    return Fernet(key)


def encrypt_token(plain_text: str, encryption_key: str) -> str:
    """Encrypt a token using Fernet symmetric encryption."""
    if not encryption_key:
        raise ValueError("ENCRYPTION_KEY is not configured")
    fernet = _get_fernet(encryption_key)
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_token(encrypted_text: str, encryption_key: str) -> str:
    """Decrypt a Fernet-encrypted token. Returns as-is if decryption fails."""
    if not encryption_key:
        return encrypted_text
    try:
        fernet = _get_fernet(encryption_key)
        return fernet.decrypt(encrypted_text.encode()).decode()
    except InvalidToken:
        logger.warning("Failed to decrypt token — may be stored in plaintext")
        return encrypted_text
    except Exception:
        logger.warning("Unexpected error during token decryption")
        return encrypted_text


def generate_encryption_key() -> str:
    """Generate a new Fernet key (base64-encoded)."""
    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# Convenience wrappers that read ENCRYPTION_KEY from settings
# ---------------------------------------------------------------------------
_key_cache: str | None = None


def _get_key() -> str:
    global _key_cache
    if _key_cache is None:
        from app.config import settings
        _key_cache = settings.ENCRYPTION_KEY or ""
    return _key_cache


def encrypt(plain_text: str) -> str:
    """Encrypt using the configured ENCRYPTION_KEY."""
    return encrypt_token(plain_text, _get_key())


def decrypt(encrypted_text: str) -> str:
    """Decrypt using the configured ENCRYPTION_KEY."""
    return decrypt_token(encrypted_text, _get_key())
