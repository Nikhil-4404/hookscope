"""Raw-body verification and durable authentication budget."""
import hashlib
import hmac
import time
from fastapi import HTTPException
from sqlalchemy import text
from .config import secret_value
from .store import engine


def login_budget(key: str) -> None:
    now = time.time()
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM auth_limits WHERE started<:before'), {'before':now-300})
        if conn.execute(text('SELECT count(*) FROM auth_limits')).scalar_one() >= 5000 and not conn.execute(text('SELECT key FROM auth_limits WHERE key=:key'),{'key':key}).first():
            raise HTTPException(429, 'Authentication traffic budget exhausted. Try again later.')
        row = conn.execute(text('''INSERT INTO auth_limits(key,started,count) VALUES(:key,:now,1)
            ON CONFLICT(key) DO UPDATE SET count=count+1 RETURNING count'''), {'key':key,'now':now}).scalar_one()
    if row > 10:
        raise HTTPException(429, 'Too many attempts. Try again in five minutes.')


def verify_body(endpoint: dict, body: bytes, headers: dict) -> None:
    mode = endpoint.get('verify_mode', 'none')
    if mode == 'none':
        return
    try:
        secret = secret_value(endpoint['incoming_secret_ref'],endpoint.get('owner_id','legacy')).encode()
    except ValueError:
        raise HTTPException(503, 'Endpoint verification secret is unavailable.')
    if mode == 'github':
        expected = 'sha256=' + hmac.new(secret, body, hashlib.sha256).hexdigest()
        supplied = headers.get('x-hub-signature-256', '')
    else:
        timestamp = headers.get('x-hookscope-timestamp', '')
        try:
            if abs(time.time() - int(timestamp)) > 300:
                raise ValueError()
        except ValueError:
            raise HTTPException(401, 'Invalid or expired webhook timestamp.')
        expected = 'v1=' + hmac.new(secret, timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
        supplied = headers.get('x-hookscope-signature', '')
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, 'Invalid webhook signature.')
