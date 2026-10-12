"""Bounded HTTPS delivery. Resolve once, reject non-public answers, pin the connection.

Redirects are never followed. Incoming credentials and signatures are not forwarded.
"""
import http.client
import hashlib
import hmac
import ipaddress
import json
import logging
import multiprocessing
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit
from sqlalchemy import text
from .store import engine, query, mutate
from .config import secret_value, production, MAX_INSTANCE_BYTES, MAX_INSTANCE_ATTEMPTS

DEMOS = {'demo://success', 'demo://failure', 'demo://flaky'}
MAX_RESPONSE = 32_768
MAX_STORED_BYTES = 512 * 1024 * 1024
ALLOWED_HEADERS = {'content-type', 'accept', 'user-agent', 'x-github-event', 'x-github-delivery', 'x-event-type', 'x-request-id'}

def validate_destination(value):
    if value == '' or value in DEMOS:
        return
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValueError('Destination must not contain whitespace or control characters.')
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError('Use an HTTPS URL without credentials or a fragment.')
    try:
        if url.port not in (None, 443):
            raise ValueError('Only HTTPS port 443 is supported.')
    except ValueError:
        raise ValueError('Only HTTPS port 443 is supported.')
    hostname = url.hostname.lower().rstrip('.')
    if hostname == 'localhost' or hostname.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Private and local destinations are blocked.')
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (not address.is_global or address.is_multicast):
        raise ValueError('Private and local destinations are blocked.')

def public_address(hostname):
    answers = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in addresses):
        raise ValueError('Destination resolves to a non-public address; delivery blocked.')
    return addresses[0]

class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address):
        super().__init__(hostname, 443, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise

def send(attempt, event):
    destination = attempt['destination']
    validate_destination(destination)
    if destination in DEMOS:
        if production():
            raise ValueError('Simulators are disabled in production.')
        if destination == 'demo://success':
            code = 200
        elif destination == 'demo://failure':
            code = 503
        else:
            previous = query("SELECT count(*) AS n FROM attempts WHERE event_id=:id AND finished IS NOT NULL", {'id': event['id']})[0]['n']
            code = 200 if previous else 503
        return code, json.dumps({'received': code == 200, 'simulator': True, 'event_id': event['id']}), 34
    url = urlsplit(destination)
    address = public_address(url.hostname)
    headers = {k: v for k, v in json.loads(event['headers']).items() if k.lower() in ALLOWED_HEADERS}
    headers.update({'X-Hookscope-Event-Id': event['id'], 'X-Hookscope-Attempt-Id': attempt['id'],
                    'X-Hookscope-Replay': 'true' if attempt['replay'] else 'false',
                    'Idempotency-Key': event['id']})
    reference = attempt.get('signing_secret_ref', '')
    if reference:
        timestamp = str(int(time.time()))
        signature = hmac.new(secret_value(reference,event.get('owner_id','legacy')).encode(), timestamp.encode()+b'.'+event['body'], hashlib.sha256).hexdigest()
        headers.update({'X-Hookscope-Timestamp':timestamp,'X-Hookscope-Signature':'v1='+signature})
    path = url.path or '/'
    if url.query:
        path += '?' + url.query
    conn = PinnedHTTPSConnection(url.hostname, address)
    start = time.monotonic()
    try:
        conn.request('POST', path, body=event['body'], headers=headers)
        response = conn.getresponse()
        deadline = start + 20
        body = bytearray()
        while len(body) <= MAX_RESPONSE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Delivery exceeded the 20-second response deadline.')
            if conn.sock:
                conn.sock.settimeout(min(10, remaining))
            chunk = response.read1(min(4096, MAX_RESPONSE + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        truncated = len(body) > MAX_RESPONSE
        result = bytes(body[:MAX_RESPONSE]).decode('utf-8', errors='replace')
        if truncated:
            result += '\n[Response truncated at 32 KiB]'
        return response.status, result, round((time.monotonic() - start) * 1000)
    finally:
        conn.close()


def _send_child(pipe, attempt: dict, event: dict) -> None:
    try:
        pipe.send(('ok', send(attempt, event)))
    except Exception as exc:
        # Network exception text can contain destination credentials/query parameters.
        pipe.send(('error', type(exc).__name__))
    finally:
        pipe.close()


def bounded_send(attempt: dict, event: dict, timeout: float = 20) -> tuple:
    """Hard wall-clock bound including DNS, TLS, request, headers and slow bodies.

    A child process is used because OS DNS and blocking TLS cannot be reliably
    cancelled by a Python thread. No thread survives a timed-out delivery.
    """
    if attempt['destination'] in DEMOS:
        return send(attempt, event)
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_send_child, args=(sender,attempt,event), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            raise TimeoutError('Delivery exceeded the 20-second total deadline.')
        kind, result = receiver.recv()
        if kind != 'ok':
            raise RuntimeError('Delivery failed: '+result)
        return result
    finally:
        sender.close()
        receiver.close()
        if process.pid:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()

def work_once():
    now = time.time()
    # Atomic claim prevents two workers taking the same live attempt.
    with engine.begin() as conn:
        conn.execute(text("UPDATE attempts SET status='failed',error='Crash recovery execution limit exceeded.',finished=:now,lease=NULL WHERE status='sending' AND lease<:now AND execution_count>=10"), {'now':now})
        row = conn.execute(text('''UPDATE attempts SET status='sending', lease=:lease,
            execution_count=execution_count+1 WHERE id=(SELECT a.id FROM attempts a
            JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id
            JOIN workspace_usage u ON u.owner_id=p.owner_id
            WHERE (a.status='queued' AND a.next_run<=:now OR a.status='sending' AND a.lease<:now) AND p.active=1
            ORDER BY u.last_claim,a.created LIMIT 1) RETURNING *'''), {'now': now, 'lease': now + 120}).mappings().first()
        if row is None:
            return False
        attempt = dict(row)
        conn.execute(text('UPDATE workspace_usage SET last_claim=:now WHERE owner_id=(SELECT p.owner_id FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=:event)'),{'now':now,'event':attempt['event_id']})
    event_rows = query('SELECT e.*,p.owner_id FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=:id', {'id': attempt['event_id']})
    if not event_rows:
        return True
    code = None
    latency = None
    response = None
    error = None
    start = time.monotonic()
    try:
        code, response, latency = bounded_send(attempt, event_rows[0])
        status = 'delivered' if 200 <= code < 300 else 'failed'
    except Exception as exc:
        status = 'failed'
        error = str(exc)[:1000]
        latency = round((time.monotonic() - start) * 1000)
    # An expired execution may not overwrite a newer claim.
    with engine.begin() as conn:
        conn.execute(text('UPDATE attempts SET execution_count=execution_count WHERE id=:id'), {'id':attempt['id']})
        owner = event_rows[0]['owner_id']
        stored = conn.execute(text('SELECT body_bytes+response_bytes FROM workspace_usage WHERE owner_id=:owner'),{'owner':owner}).scalar_one()
        instance_bytes = conn.execute(text('SELECT body_bytes+response_bytes FROM instance_usage WHERE id=1')).scalar_one()
        if stored + len((response or '').encode()) > MAX_STORED_BYTES or instance_bytes+len((response or '').encode())>MAX_INSTANCE_BYTES:
            response = None
            error = 'Response preview omitted: workspace storage quota exhausted.'
        updated = conn.execute(text('''UPDATE attempts SET status=:status, code=:code, latency=:latency,
            response=:response, error=:error, finished=:finished, lease=NULL
            WHERE id=:id AND lease=:lease'''), {'id': attempt['id'], 'lease': attempt['lease'],
            'status': status, 'code': code, 'latency': latency, 'response': response,
            'error': error, 'finished': time.time()}).rowcount
        retryable = code is None or code in (408,425,429) or code >= 500
        if updated and status == 'failed' and retryable and attempt['retry_count'] < attempt['retries']:
            count = attempt['retry_count']+1
            inserted = conn.execute(text('''INSERT INTO attempts(id,event_id,created,status,destination,replay,signing_secret_ref,retries,retry_count,next_run)
                SELECT :id,:event,:now,'queued',:destination,:replay,:secret,:retries,:count,:due
                WHERE NOT EXISTS (SELECT 1 FROM attempts WHERE event_id=:event AND status IN ('queued','sending'))
                AND (SELECT count(*) FROM attempts WHERE event_id=:event)<100 AND
                (SELECT attempt_count FROM workspace_usage WHERE owner_id=:owner)<150000
                AND (SELECT attempt_count FROM instance_usage WHERE id=1)<:instance_limit'''),
                {'id':'att_'+secrets.token_hex(8), 'event':attempt['event_id'], 'now':time.time(),
                 'destination':attempt['destination'], 'replay':attempt['replay'], 'secret':attempt['signing_secret_ref'],
                 'retries':attempt['retries'],'count':count,'due':time.time()+min(300,5*2**(count-1))+secrets.randbelow(5),'owner':owner,'instance_limit':MAX_INSTANCE_ATTEMPTS}).rowcount
            if not inserted:
                logging.warning('Automatic retry suppressed by attempt quota or pending attempt')
    logging.info('delivery_complete attempt=%s status=%s code=%s execution=%s', attempt['id'],status,code,attempt['execution_count'])
    return True
