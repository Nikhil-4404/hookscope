import os
import tempfile

os.environ['HOOKSCOPE_DATA'] = tempfile.mkdtemp(prefix='hookscope-test-')
os.environ['HOOKSCOPE_DISABLE_WORKER'] = '1'

import pytest
from fastapi.testclient import TestClient
from app.main import app, login_attempts
from app.store import engine
from sqlalchemy import text

@pytest.fixture
def client():
    with TestClient(app) as client:
        with engine.begin() as conn:
            for table in ('attempts', 'events', 'endpoints', 'sessions', 'settings', 'auth_limits', 'worker_heartbeats', 'tenant_secrets', 'invitations', 'tenants'):
                conn.execute(text('DELETE FROM ' + table))
        login_attempts.clear()
        yield client

@pytest.fixture
def owner(client):
    assert client.post('/api/setup', json={'password':'a-strong-test-password'}).status_code == 200
    return client

@pytest.fixture
def endpoint(owner):
    result = owner.post('/api/endpoints', json={'name':'Test endpoint', 'destination':'demo://flaky'})
    assert result.status_code == 201
    return result.json()
