import base64
import hashlib
import hmac
import json
import multiprocessing
from pathlib import Path
import secrets
import sqlite3
import time
import subprocess
import os
import sys
import shutil
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.config import validate_config
from app.delivery import work_once, bounded_send
from app.store import query, mutate, backup_to, engine, initialize, data, service_lock
from app.tenancy import read_secret, validate_secret_key


def invitation(email):
    token = secrets.token_urlsafe(32)
    mutate('INSERT INTO invitations(token,email,expires,created) VALUES(:token,:email,:expires,:now)',
           {'token':hashlib.sha256(token.encode()).hexdigest(),'email':email,'expires':time.time()+60,'now':time.time()})
    return token


def register(client,email='tenant@example.test'):
    response = client.post('/api/register',json={'email':email,'password':'tenant-strong-test-password','invitation':invitation(email)})
    assert response.status_code == 201,response.text
    return client


def test_tenant_isolation_every_management_surface(owner,endpoint):
    event = owner.post('/hooks/'+endpoint['token'],content=b'private data').json()['event_id']
    secret = owner.post('/api/secrets',json={'name':'Private secret','value':'x'*32}).json()['id']
    cookie = owner.cookies.get('hookscope_session')
    register(owner)
    assert owner.get('/api/endpoints').json() == []
    assert owner.get('/api/events?endpoint='+endpoint['id']).json()['total'] == 0
    assert owner.get('/api/stats').json()['events'] == 0
    assert owner.get('/api/operations').json()['storage']['n'] == 0
    assert owner.get('/api/secrets').json() == []
    assert owner.get('/api/events/'+event).status_code == 404
    assert owner.post('/api/events/'+event+'/replay').status_code == 404
    assert owner.delete('/api/events/'+event).status_code == 404
    assert owner.patch('/api/endpoints/'+endpoint['id'],json={'name':'Stolen'}).status_code == 404
    assert owner.delete('/api/endpoints/'+endpoint['id']).status_code == 404
    assert owner.post('/api/endpoints/'+endpoint['id']+'/rotate').status_code == 404
    assert owner.post('/api/endpoints/'+endpoint['id']+'/test',json={'body':'x'}).status_code == 404
    assert owner.delete('/api/secrets/'+secret).status_code == 404
    assert owner.post('/api/endpoints',json={'name':'Bad','signing_secret_ref':secret}).status_code == 422
    assert owner.post('/api/endpoints',json={'name':'Bad','incoming_secret_ref':'HOOKSCOPE_SECRET_OTHER'}).status_code == 422
    owner.cookies.set('hookscope_session',cookie)
    assert owner.get('/api/events/'+event).status_code == 200


def test_invitation_single_use_expiration_and_binding(client):
    token=invitation('new@example.test')
    payload={'email':'wrong@example.test','password':'tenant-strong-test-password','invitation':token}
    assert client.post('/api/register',json=payload).status_code == 403
    payload['email']='new@example.test'
    assert client.post('/api/register',json=payload).status_code == 201
    assert client.post('/api/register',json=payload).status_code == 403
    token=invitation('expired@example.test')
    mutate('UPDATE invitations SET expires=0')
    payload.update(email='expired@example.test',invitation=token)
    assert client.post('/api/register',json=payload).status_code == 403


def test_secret_encryption_and_tenant_aad(owner):
    value='super-secret-value-not-in-plaintext'*2
    result=owner.post('/api/secrets',json={'name':'Receiver','value':value})
    assert result.status_code == 201
    identity=result.json()['id']
    assert value not in json.dumps(query('SELECT * FROM tenant_secrets'))
    assert read_secret(identity,'legacy') == value
    with pytest.raises(ValueError):read_secret(identity,'someone-else')
    assert 'value' not in owner.get('/api/secrets').json()[0]


@pytest.mark.parametrize('mode',['github','hmac'])
def test_provider_verification_exact_bytes_and_replay_window(owner,mode):
    secret='verification-secret-with-32-bytes-or-more'
    identity=owner.post('/api/secrets',json={'name':'Provider','value':secret}).json()['id']
    ep=owner.post('/api/endpoints',json={'name':'Verified','verify_mode':mode,'incoming_secret_ref':identity}).json()
    body=b'{ "value": "original spacing" }\r\n'
    timestamp=str(int(time.time()))
    headers={'x-hub-signature-256':'sha256='+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()} if mode=='github' else {
        'x-hookscope-timestamp':timestamp,'x-hookscope-signature':'v1='+hmac.new(secret.encode(),timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()}
    assert owner.post('/hooks/'+ep['token'],content=body).status_code == 401
    assert owner.post('/hooks/'+ep['token'],content=body,headers=headers).status_code == 202
    assert owner.post('/hooks/'+ep['token'],content=body+b' ',headers=headers).status_code == 401
    if mode=='hmac':
        headers['x-hookscope-timestamp']=str(int(time.time())-400)
        assert owner.post('/hooks/'+ep['token'],content=body,headers=headers).status_code == 401
    else:
        headers['x-github-delivery']='github-event-id'
        first=owner.post('/hooks/'+ep['token'],content=body,headers=headers).json()
        second=owner.post('/hooks/'+ep['token'],content=body,headers=headers).json()
        assert first['event_id']==second['event_id'] and second['duplicate']
    assert owner.delete('/api/secrets/'+identity).status_code == 409


def test_token_rotation_and_empty_dedupe_key(owner,endpoint):
    new=owner.post('/api/endpoints/'+endpoint['id']+'/rotate').json()['token']
    assert owner.post('/hooks/'+endpoint['token'],content=b'x').status_code == 404
    one=owner.post('/hooks/'+new,content=b'x',headers={'x-hookscope-idempotency-key':''}).json()
    two=owner.post('/hooks/'+new,content=b'x',headers={'x-hookscope-idempotency-key':''}).json()
    assert one['event_id']!=two['event_id']


def test_password_revokes_all_own_sessions_but_not_other_tenants(owner):
    first=owner.cookies.get('hookscope_session')
    owner.post('/api/login',json={'password':'a-strong-test-password'})
    second=owner.cookies.get('hookscope_session')
    register(owner)
    other=owner.cookies.get('hookscope_session')
    owner.cookies.clear();owner.cookies.set('hookscope_session',first)
    assert owner.post('/api/password',json={'current_password':'wrong-current-password','password':'replacement-strong-password'}).status_code == 401
    assert owner.post('/api/password',json={'current_password':'a-strong-test-password','password':'replacement-strong-password'}).status_code == 200
    owner.cookies.clear();owner.cookies.set('hookscope_session',second)
    assert owner.get('/api/events').status_code == 401
    owner.cookies.clear();owner.cookies.set('hookscope_session',other)
    assert owner.get('/api/events').status_code == 200


def test_retry_schedule_history_budget_and_paused_queue(owner):
    ep=owner.post('/api/endpoints',json={'name':'Retry','destination':'demo://failure','retries':2}).json()
    event=owner.post('/hooks/'+ep['token'],content=b'x').json()['event_id']
    assert work_once()
    attempts=owner.get('/api/events/'+event).json()['attempts']
    assert len(attempts)==2 and attempts[0]['retry_count']==1 and attempts[0]['next_run']>time.time()
    assert not work_once()
    mutate('UPDATE attempts SET next_run=0')
    owner.patch('/api/endpoints/'+ep['id'],json={'name':'Retry','destination':'demo://failure','active':False,'retries':2})
    assert not work_once()
    owner.patch('/api/endpoints/'+ep['id'],json={'name':'Retry','destination':'demo://failure','active':True,'retries':2})
    assert work_once()
    mutate('UPDATE attempts SET next_run=0')
    assert work_once()
    attempts=owner.get('/api/events/'+event).json()['attempts']
    assert len(attempts)==3 and all(a['status']=='failed' for a in attempts)
    assert not work_once()


def test_no_retry_for_permanent_4xx(owner,monkeypatch):
    ep=owner.post('/api/endpoints',json={'name':'No retry','destination':'demo://failure','retries':5}).json()
    owner.post('/hooks/'+ep['token'],content=b'x')
    monkeypatch.setattr('app.delivery.bounded_send',lambda *a:(400,'Bad request',1))
    work_once()
    assert len(query('SELECT id FROM attempts'))==1


def test_backup_restore_integrity_and_idempotent_migrations(owner,endpoint,tmp_path):
    event=owner.post('/hooks/'+endpoint['token'],content=b'\xfforiginal').json()['event_id']
    target=tmp_path/'backup.db'
    backup_to(target)
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT body FROM events WHERE id=?',(event,)).fetchone()[0]==b'\xfforiginal'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]==3
    initialize();initialize()
    assert query('SELECT count(*) n FROM schema_migrations')[0]['n']==3
    with pytest.raises(ValueError):backup_to(target)


def test_production_config_fails_closed(monkeypatch):
    monkeypatch.setenv('HOOKSCOPE_ENV','production')
    with pytest.raises(RuntimeError):validate_config()
    monkeypatch.setenv('HOOKSCOPE_PUBLIC_URL','https://hooks.example.test')
    monkeypatch.setenv('HOOKSCOPE_ALLOWED_HOSTS','hooks.example.test,localhost')
    monkeypatch.setenv('HOOKSCOPE_SECURE_COOKIES','1')
    validate_config()
    monkeypatch.setenv('HOOKSCOPE_ALLOWED_HOSTS','*')
    with pytest.raises(RuntimeError):validate_config()


def test_production_disables_setup_demo_and_insecure_origins(owner,monkeypatch):
    monkeypatch.setenv('HOOKSCOPE_ENV','production')
    monkeypatch.setenv('HOOKSCOPE_PUBLIC_URL','https://hooks.example.test')
    assert owner.post('/api/setup',json={'password':'some-strong-password'}).status_code == 403
    assert owner.post('/api/demo').status_code == 403
    assert owner.post('/api/endpoints',json={'name':'Demo','destination':'demo://success'}).status_code == 422
    assert owner.post('/api/endpoints',json={'name':'Origin'},headers={'origin':'http://localhost:5173'}).status_code == 403
    assert owner.get('/api/health').headers['strict-transport-security']=='max-age=31536000'


def test_readiness_checks_worker_heartbeat(owner):
    assert owner.get('/api/ready').status_code == 503
    mutate('INSERT INTO worker_heartbeats(id,updated) VALUES(:id,:now)',{'id':'test','now':time.time()})
    assert owner.get('/api/ready').status_code == 200


def slow_child(pipe,attempt,event):
    time.sleep(10)


def test_entire_delivery_deadline_kills_child(monkeypatch):
    monkeypatch.setattr('app.delivery._send_child',slow_child)
    before={process.pid for process in multiprocessing.active_children()}
    start=time.monotonic()
    with pytest.raises(TimeoutError):bounded_send({'destination':'https://example.test'}, {},timeout=0.3)
    assert time.monotonic()-start<3
    assert {process.pid for process in multiprocessing.active_children()}==before


def test_atomic_endpoint_capacity_under_concurrency(owner):
    for n in range(29):assert owner.post('/api/endpoints',json={'name':str(n)}).status_code==201
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda n:owner.post('/api/endpoints',json={'name':str(n)}).status_code,range(4)))
    assert sorted(results)==[201,409,409,409]
    assert len(owner.get('/api/endpoints').json())==30


def test_offline_restore_boots_with_encrypted_secrets(owner,endpoint,tmp_path):
    secret=owner.post('/api/secrets',json={'name':'Restorable','value':'a'*32}).json()['id']
    event=owner.post('/hooks/'+endpoint['token'],content=b'restore-exact-body').json()['event_id']
    restore=tmp_path/'restored';restore.mkdir()
    backup_to(restore/'hookscope.db')
    shutil.copy2(data/'development.key',restore/'development.key')
    script="from app.store import initialize,query; from app.tenancy import read_secret; initialize(); assert query('SELECT body FROM events WHERE id=:id',{'id':"+repr(event)+"})[0]['body']==b'restore-exact-body'; assert read_secret("+repr(secret)+",'legacy')=='a'*32"
    result=subprocess.run([sys.executable,'-c',script],env={**os.environ,'HOOKSCOPE_DATA':str(restore)},capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_legacy_database_migration_preserves_records(tmp_path):
    legacy=tmp_path/'legacy';legacy.mkdir()
    with sqlite3.connect(legacy/'hookscope.db') as conn:
        conn.executescript('''
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE sessions(token TEXT PRIMARY KEY,expires REAL NOT NULL);
            CREATE TABLE endpoints(id TEXT PRIMARY KEY,name TEXT NOT NULL,token TEXT UNIQUE NOT NULL,destination TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL);
            CREATE TABLE events(id TEXT PRIMARY KEY,endpoint_id TEXT NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,created REAL NOT NULL,method TEXT NOT NULL,headers TEXT NOT NULL,body BLOB NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,external_id TEXT,UNIQUE(endpoint_id,external_id));
            CREATE TABLE attempts(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,created REAL NOT NULL,finished REAL,status TEXT NOT NULL,code INTEGER,latency INTEGER,response TEXT,error TEXT,destination TEXT NOT NULL,replay INTEGER NOT NULL DEFAULT 0,lease REAL,execution_count INTEGER NOT NULL DEFAULT 0);
            INSERT INTO settings VALUES('password','salt:historical-hash');
            INSERT INTO endpoints VALUES('ep_old','Existing endpoint','test-only-token','',1,1);
            INSERT INTO events VALUES('evt_old','ep_old',1,'POST','{}',X'00FF','legacy','webhook',NULL);
            INSERT INTO attempts(id,event_id,created,status,destination) VALUES('att_old','evt_old',1,'failed','https://example.test');
        ''')
    script="from app.store import initialize,query; initialize(); initialize(); assert query('SELECT body FROM events')[0]['body']==b'\\x00\\xff'; assert query('SELECT owner_id FROM endpoints')[0]['owner_id']=='legacy'; assert query('SELECT password FROM tenants')[0]['password']=='salt:historical-hash'; assert len(query('SELECT id FROM attempts'))==1"
    result=subprocess.run([sys.executable,'-c',script],env={**os.environ,'HOOKSCOPE_DATA':str(legacy)},capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert len(list(legacy.glob('pre-migration-*.db')))==3


def test_response_preview_quota_does_not_change_delivery_outcome(owner,endpoint,monkeypatch):
    event=owner.post('/hooks/'+endpoint['token'],content=b'x').json()['event_id']
    monkeypatch.setattr('app.delivery.bounded_send',lambda *a:(200,'x'*40000,1))
    monkeypatch.setattr('app.delivery.MAX_STORED_BYTES',1)
    work_once()
    detail=owner.get('/api/events/'+event).json()
    assert detail['attempts'][0]['status']=='delivered'
    assert detail['attempts'][0]['response'] is None
    assert 'quota' in detail['attempts'][0]['error']


def test_byte_quota_rate_limit_and_management_request_bound(owner,monkeypatch):
    ep=owner.post('/api/endpoints',json={'name':'Quota'}).json()
    monkeypatch.setattr('app.main.MAX_STORED_BYTES',2)
    assert owner.post('/hooks/'+ep['token'],content=b'abc').status_code==507
    monkeypatch.setattr('app.main.MAX_STORED_BYTES',512*1024*1024)
    for _ in range(120):assert owner.post('/hooks/'+ep['token'],content=b'x').status_code==202
    assert owner.post('/hooks/'+ep['token'],content=b'x').status_code==429
    assert owner.post('/api/endpoints',content=b'x'*(256*1024*6+1)).status_code==413


def test_usage_counters_survive_replay_response_update_and_cascade(owner,endpoint):
    event=owner.post('/hooks/'+endpoint['token'],content=b'bytes').json()['event_id']
    usage=query("SELECT * FROM workspace_usage WHERE owner_id='legacy'")[0]
    assert usage['events']==1 and usage['body_bytes']==5 and usage['attempt_count']==1
    work_once()
    assert owner.get('/api/events?status=failed').json()['total']==1
    usage=query("SELECT * FROM workspace_usage WHERE owner_id='legacy'")[0]
    actual=query('SELECT sum(length(CAST(response AS BLOB))) n FROM attempts')[0]['n']
    assert usage['response_bytes']==actual and actual>0
    owner.post('/api/events/'+event+'/replay');work_once()
    assert owner.get('/api/events?status=delivered').json()['total']==1
    assert query("SELECT attempt_count FROM workspace_usage WHERE owner_id='legacy'")[0]['attempt_count']==2
    owner.delete('/api/endpoints/'+endpoint['id'])
    usage=query("SELECT * FROM workspace_usage WHERE owner_id='legacy'")[0]
    assert usage['events']==usage['body_bytes']==usage['response_bytes']==usage['attempt_count']==0


def test_capture_rollback_keeps_usage_counters_consistent(owner,endpoint,monkeypatch):
    monkeypatch.setattr('app.main.MAX_ATTEMPTS',0)
    assert owner.post('/hooks/'+endpoint['token'],content=b'rollback').status_code==507
    usage=query("SELECT * FROM workspace_usage WHERE owner_id='legacy'")[0]
    assert usage['events']==usage['body_bytes']==usage['attempt_count']==0


def test_worker_scheduling_interleaves_workspaces(owner,endpoint):
    for _ in range(3):owner.post('/hooks/'+endpoint['token'],content=b'owner backlog')
    register(owner)
    other=owner.post('/api/endpoints',json={'name':'Second workspace','destination':'demo://success'}).json()
    own_event=owner.post('/hooks/'+other['token'],content=b'other workspace').json()['event_id']
    work_once();work_once()
    assert owner.get('/api/events/'+own_event).json()['attempts'][0]['status']=='delivered'
    assert query("SELECT count(*) n FROM attempts WHERE status='queued'")[0]['n']==2


def test_global_capacity_preserves_dedupe_and_rolls_back(owner,endpoint,monkeypatch):
    headers={'x-hookscope-idempotency-key':'global-quota'}
    first=owner.post('/hooks/'+endpoint['token'],content=b'x',headers=headers).json()
    monkeypatch.setattr('app.main.MAX_INSTANCE_EVENTS',1)
    assert owner.post('/hooks/'+endpoint['token'],content=b'x').status_code==507
    assert owner.post('/hooks/'+endpoint['token'],content=b'x',headers=headers).json()['event_id']==first['event_id']
    assert query('SELECT events,body_bytes FROM instance_usage')[0]=={'events':1,'body_bytes':1}


def test_restore_refuses_live_service(owner,tmp_path):
    snapshot=tmp_path/'snapshot.db';backup_to(snapshot)
    result=subprocess.run([sys.executable,'-m','app.maintenance','restore',str(snapshot),'--offline'],capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'already in use' in result.stderr


def test_offline_restore_command_preserves_data_and_revokes_sessions(owner,endpoint,tmp_path):
    event=owner.post('/hooks/'+endpoint['token'],content=b'command-restore').json()['event_id']
    snapshot=tmp_path/'snapshot.db';backup_to(snapshot)
    target=tmp_path/'offline';target.mkdir()
    environment={**os.environ,'HOOKSCOPE_DATA':str(target)}
    result=subprocess.run([sys.executable,'-m','app.maintenance','restore',str(snapshot),'--offline'],env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    with sqlite3.connect(target/'hookscope.db') as conn:
        assert conn.execute('SELECT body FROM events WHERE id=?',(event,)).fetchone()[0]==b'command-restore'
        assert conn.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
    assert list(target.glob('pre-restore-*.db'))


def test_wrong_master_key_fails_secret_validation(owner,monkeypatch):
    owner.post('/api/secrets',json={'name':'Key match','value':'a'*32})
    validate_secret_key()
    monkeypatch.setenv('HOOKSCOPE_ENCRYPTION_KEY',base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    with pytest.raises(RuntimeError,match='matching encryption key'):validate_secret_key()


def test_authenticated_responses_identify_the_workspace(owner):
    assert owner.get('/api/endpoints').headers['x-hookscope-workspace']=='legacy'
    register(owner)
    account=owner.get('/api/auth').json()['account']['id']
    assert owner.get('/api/endpoints').headers['x-hookscope-workspace']==account
