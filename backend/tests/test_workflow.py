import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.delivery import public_address, validate_destination, work_once, send
from app.store import query, mutate

def test_management_requires_authentication(client):
    assert client.get('/api/endpoints').status_code == 401
    assert client.post('/api/demo').status_code == 401
    assert client.get('/api/health').status_code == 200

def test_setup_login_and_logout(client):
    assert client.post('/api/setup',json={'password':'short'}).status_code == 422
    assert client.post('/api/setup',json={'password':'a-strong-test-password'}).status_code == 200
    assert client.post('/api/setup',json={'password':'other-strong-password'}).status_code == 409
    assert client.post('/api/logout').status_code == 200
    assert client.get('/api/events').status_code == 401
    assert client.post('/api/login',json={'password':'incorrect-password'}).status_code == 401
    assert client.post('/api/login',json={'password':'a-strong-test-password'}).status_code == 200
    assert client.get('/api/events').status_code == 200

def test_cross_origin_write_blocked(owner):
    assert owner.post('/api/endpoints',json={'name':'Bad'},headers={'origin':'https://evil.example'}).status_code == 403

def test_original_bytes_and_header_redaction(owner, endpoint):
    body = b'\x00\xff\xfe exact bytes\r\n'
    result = owner.post('/hooks/'+endpoint['token'], content=body, headers={'authorization':'Bearer SECRET','x-provider-signature':'SECRET','content-type':'application/octet-stream'})
    assert result.status_code == 202
    event_id = result.json()['event_id']
    stored = query('SELECT body FROM events WHERE id=:id',{'id':event_id})[0]
    assert stored['body'] == body
    value = owner.get('/api/events/'+event_id).json()
    assert value['headers']['authorization'] == '[redacted]'
    assert value['headers']['x-provider-signature'] == '[redacted]'
    assert value['size'] == len(body)

def test_flaky_delivery_and_manual_replay(owner, endpoint):
    event_id = owner.post('/hooks/'+endpoint['token'],json={'type':'order.created'}).json()['event_id']
    assert owner.post('/api/events/'+event_id+'/replay').status_code == 409
    assert work_once()
    first = owner.get('/api/events/'+event_id).json()['attempts'][0]
    assert first['code'] == 503 and first['status'] == 'failed'
    assert owner.post('/api/events/'+event_id+'/replay').status_code == 202
    assert work_once()
    attempts = owner.get('/api/events/'+event_id).json()['attempts']
    assert len(attempts) == 2
    assert attempts[0]['code'] == 200 and attempts[0]['replay'] == 1
    assert attempts[1]['code'] == 503
    assert owner.get('/api/events?status=delivered').json()['total'] == 1

def test_ingestion_idempotency(owner, endpoint):
    headers = {'x-hookscope-idempotency-key':'external-event-123'}
    first = owner.post('/hooks/'+endpoint['token'],json={'type':'same'},headers=headers).json()
    second = owner.post('/hooks/'+endpoint['token'],json={'type':'same'},headers=headers).json()
    assert first['event_id'] == second['event_id']
    assert second['duplicate']
    assert len(query('SELECT id FROM attempts')) == 1

def test_paused_oversized_and_unknown_endpoint(owner, endpoint):
    assert owner.post('/hooks/unknown',content=b'a').status_code == 404
    assert owner.post('/hooks/'+endpoint['token'],content=b'a'*(256*1024+1)).status_code == 413
    assert owner.patch('/api/endpoints/'+endpoint['id'],json={'name':'Test','destination':'','active':False}).status_code == 200
    assert owner.post('/hooks/'+endpoint['token'],content=b'a').status_code == 410

def test_capture_only_search_and_delete(owner):
    ep = owner.post('/api/endpoints',json={'name':'Capture only'}).json()
    event_id = owner.post('/hooks/'+ep['token'],json={'type':'invoice.sent'}).json()['event_id']
    assert not work_once()
    assert owner.get('/api/events?search=invoice').json()['total'] == 1
    assert owner.get('/api/events?search=missing').json()['total'] == 0
    assert owner.get('/api/events?status=received').json()['items'][0]['id'] == event_id
    assert owner.delete('/api/endpoints/'+ep['id']).status_code == 200
    assert owner.get('/api/events').json()['total'] == 0

def test_expired_worker_lease_recovers(owner, endpoint):
    event_id = owner.post('/hooks/'+endpoint['token'],json={'type':'lease'}).json()['event_id']
    mutate("UPDATE attempts SET status='sending',lease=:expired,execution_count=1 WHERE event_id=:id",{'expired':time.time()-1,'id':event_id})
    assert work_once()
    attempt = owner.get('/api/events/'+event_id).json()['attempts'][0]
    assert attempt['execution_count'] == 2
    assert attempt['finished'] is not None

def test_concurrent_workers_claim_only_once(owner, endpoint):
    owner.post('/hooks/'+endpoint['token'],json={'type':'concurrency'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:work_once(), range(2)))
    assert sum(results) == 1
    assert query('SELECT execution_count FROM attempts')[0]['execution_count'] == 1

@pytest.mark.parametrize('destination', ['http://example.com','https://127.0.0.1','https://[::1]','https://169.254.169.254','https://localhost','https://foo.local','https://example.com:8443','https://user:password@example.com','https://example.com/#fragment'])
def test_unsafe_destinations_rejected(destination):
    with pytest.raises(ValueError):
        validate_destination(destination)

def test_dns_rebinding_and_mixed_answers_rejected(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):
        public_address('example.com')

def test_forwarding_preserves_bytes_and_does_not_forward_secrets(monkeypatch):
    observed = {}
    class Connection:
        sock = None
        def __init__(self,host,address): observed.update(host=host,address=address)
        def request(self,method,path,body,headers): observed.update(method=method,path=path,body=body,headers=headers)
        def getresponse(self):
            class Response:
                status = 302
                done = False
                def read1(self,limit):
                    if self.done: return b''
                    self.done = True
                    return b'redirect response'
            return Response()
        def close(self): observed['closed']=True
    monkeypatch.setattr('app.delivery.public_address',lambda host:'93.184.216.34')
    monkeypatch.setattr('app.delivery.PinnedHTTPSConnection',Connection)
    body = b'\xff\x00 unchanged'
    attempt = {'id':'attempt','destination':'https://example.com/receive?q=1','replay':1}
    event = {'id':'event','body':body,'headers':json.dumps({'content-type':'application/json','authorization':'secret','cookie':'secret','x-provider-signature':'secret','connection':'keep-alive'})}
    code,_,_ = send(attempt,event)
    assert code == 302  # Redirect is a failed delivery; no second request.
    assert observed['address'] == '93.184.216.34'
    assert observed['body'] == body and observed['path'] == '/receive?q=1'
    assert 'authorization' not in observed['headers']
    assert 'cookie' not in observed['headers']
    assert observed['headers']['Idempotency-Key'] == 'event'
    assert observed['closed']

def test_concurrent_replay_is_enqueued_once(owner, endpoint):
    event_id = owner.post('/hooks/'+endpoint['token'],json={'type':'concurrent.replay'}).json()['event_id']
    work_once()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _:owner.post('/api/events/'+event_id+'/replay').status_code, range(2)))
    assert sorted(responses) == [202,409]
    assert len(query('SELECT id FROM attempts WHERE replay=1')) == 1

def test_storage_limit_and_duplicate_exception(owner, endpoint, monkeypatch):
    key = {'x-hookscope-idempotency-key':'quota-test'}
    assert owner.post('/hooks/'+endpoint['token'],json={'type':'quota'},headers=key).status_code == 202
    monkeypatch.setattr('app.main.MAX_STORED_EVENTS',1)
    assert owner.post('/hooks/'+endpoint['token'],content=b'new').status_code == 507
    assert owner.post('/hooks/'+endpoint['token'],json={'type':'quota'},headers=key).json()['duplicate']

def test_failed_login_rate_limit(client):
    client.post('/api/setup',json={'password':'a-strong-test-password'})
    client.post('/api/logout')
    for _ in range(10):
        assert client.post('/api/login',json={'password':'incorrect-password'}).status_code == 401
    assert client.post('/api/login',json={'password':'incorrect-password'}).status_code == 429
