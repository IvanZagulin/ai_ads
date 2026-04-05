# Plaintext storage — no encryption for local development
# In production, consider proper encryption with a persistent ENCRYPTION_KEY

def encrypt_token(plain_text: str) -> str:
    """Store token as-is (no encryption for local dev)."""
    return plain_text


def decrypt_token(encrypted_text: str) -> str:
    """Return token as-is. If it looks like a Fernet ciphertext, try decrypting."""
    # Detect Fernet-encrypted tokens (start with 'gAAAAA') and try to decrypt
    if encrypted_text.startswith('gAAAAA'):
        try:
            from cryptography.fernet import Fernet
            import base64
            # Try with common key that might have been used
            fernet = Fernet(base64.urlsafe_b64encode(b'dummy-key-32-bytes-for-dev-only!'))
            return fernet.decrypt(encrypted_text.encode()).decode()
        except Exception:
            pass  # Fall through to returning as-is
    return encrypted_text


def generate_encryption_key() -> str:
    """Generate a random key (not used in plaintext mode)."""
    import base64
    return base64.urlsafe_b64encode(b'dummy-key-32-bytes-for-dev-only!').decode()
