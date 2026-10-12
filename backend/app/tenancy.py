"""Tenant identity, invitation onboarding and encrypted workspace secrets."""
import base64
from contextvars import ContextVar
import os
import re
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .config import production
from .store import data, query

current_owner: ContextVar[str] = ContextVar('current_owner', default='legacy')


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
        raise ValueError('Enter a valid email address.')
    return value


def encryption_key() -> bytes:
    value = os.getenv('HOOKSCOPE_ENCRYPTION_KEY', '')
    if value:
        try:
            key = base64.urlsafe_b64decode(value)
            if len(key) == 32:
                return key
        except ValueError:
            pass
        raise RuntimeError('HOOKSCOPE_ENCRYPTION_KEY must be a Base64 encoded 32-byte key.')
    if production():
        raise RuntimeError('Production requires HOOKSCOPE_ENCRYPTION_KEY. Back it up separately from the database.')
    path = data / 'development.key'
    try:
        with path.open('xb') as file:
            path.chmod(0o600)
            file.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError('Invalid development encryption key.')
    return key


def encrypt_secret(value: str, owner: str, identity: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(encryption_key()).encrypt(nonce,value.encode(),(owner+':'+identity).encode())
    return base64.urlsafe_b64encode(nonce+ciphertext).decode()


def read_secret(identity: str, owner: str) -> str:
    rows = query('SELECT value FROM tenant_secrets WHERE id=:id AND owner_id=:owner', {'id':identity,'owner':owner})
    if not rows:
        raise ValueError('Workspace secret does not exist.')
    raw = base64.urlsafe_b64decode(rows[0]['value'])
    return AESGCM(encryption_key()).decrypt(raw[:12],raw[12:],(owner+':'+identity).encode()).decode()


def validate_secret_key() -> None:
    for secret in query('SELECT id,owner_id FROM tenant_secrets'):
        try:
            read_secret(secret['id'],secret['owner_id'])
        except Exception:
            raise RuntimeError('Stored secrets cannot be decrypted. Restore the matching encryption key and database.') from None
