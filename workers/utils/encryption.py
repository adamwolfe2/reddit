"""
Password encryption utilities using Fernet symmetric encryption
"""
from cryptography.fernet import Fernet, InvalidToken
from typing import Optional

from workers.config import config


def get_fernet() -> Fernet:
    """Get Fernet instance with the encryption key"""
    if not config.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY environment variable is not set")

    key = config.ENCRYPTION_KEY
    # If the key is a string, encode it
    if isinstance(key, str):
        key = key.encode()

    return Fernet(key)


def encrypt_password(password: str) -> str:
    """
    Encrypt a password for secure storage

    Args:
        password: Plain text password

    Returns:
        Encrypted password as a string
    """
    fernet = get_fernet()
    encrypted = fernet.encrypt(password.encode())
    return encrypted.decode()


def decrypt_password(encrypted_password: str) -> str:
    """
    Decrypt a stored password

    Args:
        encrypted_password: Encrypted password string

    Returns:
        Plain text password

    Raises:
        InvalidToken: If the encrypted password is invalid or corrupted
    """
    fernet = get_fernet()
    decrypted = fernet.decrypt(encrypted_password.encode())
    return decrypted.decode()


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key

    Returns:
        Base64-encoded encryption key as a string
    """
    return Fernet.generate_key().decode()


def is_encrypted(value: str) -> bool:
    """
    Check if a value appears to be Fernet-encrypted

    Args:
        value: String to check

    Returns:
        True if the value looks like a Fernet token
    """
    # Fernet tokens start with 'gAAAAA' and are base64-encoded
    if not value or len(value) < 10:
        return False

    try:
        # Try to decode as base64 - Fernet tokens are valid base64
        import base64

        base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        return value.startswith("gAAAAA")
    except Exception:
        return False


def safe_decrypt(encrypted_password: str) -> Optional[str]:
    """
    Safely decrypt a password, returning None on failure

    Args:
        encrypted_password: Encrypted password string

    Returns:
        Plain text password or None if decryption fails
    """
    try:
        return decrypt_password(encrypted_password)
    except (InvalidToken, ValueError, Exception):
        return None
