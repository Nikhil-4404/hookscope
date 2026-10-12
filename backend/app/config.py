"""Fail closed for public deployments; development remains loopback-only."""
import os
import re
from urllib.parse import urlsplit

MAX_INSTANCE_BYTES = 4 * 1024 * 1024 * 1024
MAX_INSTANCE_EVENTS = 500_000
MAX_INSTANCE_ATTEMPTS = 1_000_000


def production() -> bool:
    return os.getenv('HOOKSCOPE_ENV', 'development') == 'production'


def validate_config() -> None:
    if os.getenv('HOOKSCOPE_ENV', 'development') not in {'development', 'production'}:
        raise RuntimeError('HOOKSCOPE_ENV must be development or production.')
    if not production():
        return
    origin = os.getenv('HOOKSCOPE_PUBLIC_URL', '')
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise RuntimeError('Production requires HOOKSCOPE_PUBLIC_URL=https://your-domain.')
    hosts = os.getenv('HOOKSCOPE_ALLOWED_HOSTS', '').split(',')
    if url.hostname not in hosts or '*' in hosts:
        raise RuntimeError('Production allowed hosts must explicitly include the public hostname; no wildcard.')
    if os.getenv('HOOKSCOPE_SECURE_COOKIES') != '1':
        raise RuntimeError('Production requires HOOKSCOPE_SECURE_COOKIES=1.')


def secret_value(reference: str, owner: str = 'legacy') -> str:
    if not reference:
        return ''
    if reference.startswith('sec_'):
        from .tenancy import read_secret
        return read_secret(reference, owner)
    if owner != 'legacy':
        raise ValueError('Use a secret created in your workspace.')
    if not re.fullmatch(r'HOOKSCOPE_SECRET_[A-Z0-9_]{1,80}', reference):
        raise ValueError('Secret references must be environment names beginning HOOKSCOPE_SECRET_.')
    value = os.getenv(reference, '')
    if len(value.encode()) < 32:
        raise ValueError('Configure the referenced secret with at least 32 bytes before using it.')
    return value
