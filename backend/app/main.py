import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .store import initialize, query, mutate, engine, service_lock
from .delivery import validate_destination, work_once
from .config import production, validate_config, secret_value, MAX_INSTANCE_BYTES, MAX_INSTANCE_EVENTS, MAX_INSTANCE_ATTEMPTS
from .security import login_budget, verify_body
from .tenancy import current_owner, normalize_email, encrypt_secret, encryption_key, validate_secret_key

MAX_BODY = 256 * 1024
MAX_STORED_EVENTS = 50_000
MAX_STORED_BYTES = 512 * 1024 * 1024
COOKIE = 'hookscope_session'
RETENTION_DAYS = 7
login_attempts = defaultdict(deque)
WORKER_ID = secrets.token_hex(16)
MAX_ATTEMPTS = 150_000
MAX_EVENT_ATTEMPTS = 100

def uid(prefix):
    return prefix + '_' + secrets.token_hex(8)

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()

def redact_headers(headers):
    return {k: ('[redacted]' if any(s in k.lower() for s in ('authorization', 'cookie', 'token', 'secret', 'signature', 'api-key')) else v)
            for k, v in headers.items() if k.lower() not in {'host', 'content-length'}}

async def worker():
    last_cleanup = 0
    while True:
        try:
            if time.time() - last_cleanup > 3600:
                cutoff = time.time() - RETENTION_DAYS * 86400
                while await asyncio.to_thread(mutate,'DELETE FROM events WHERE id IN (SELECT id FROM events WHERE created<:before ORDER BY created LIMIT 500)', {'before':cutoff}):
                    await asyncio.sleep(0.01)
                mutate('DELETE FROM sessions WHERE expires<:now', {'now': time.time()})
                mutate('DELETE FROM auth_limits WHERE started<:before', {'before':time.time()-300})
                mutate('DELETE FROM invitations WHERE expires<:now', {'now':time.time()})
                mutate('DELETE FROM worker_heartbeats WHERE updated<:before', {'before':time.time()-3600})
                last_cleanup = time.time()
            mutate('INSERT INTO worker_heartbeats(id,updated) VALUES(:id,:now) ON CONFLICT(id) DO UPDATE SET updated=:now', {'id':WORKER_ID,'now':time.time()})
            worked = await asyncio.to_thread(work_once)
            await asyncio.sleep(0.05 if worked else 0.4)
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.exception('Delivery worker failed; retrying shortly')
            await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app):
    validate_config()
    with service_lock():
        async with runtime(app):
            yield

@asynccontextmanager
async def runtime(app):
    initialize()
    encryption_key()
    if production() and not query("SELECT value FROM settings WHERE key='password'"):
        raise RuntimeError('Configure the owner password with python -m app.configure before production startup.')
    if production() and not (dist / 'index.html').is_file():
        raise RuntimeError('Production requires the compiled frontend assets.')
    if production():
        validate_secret_key()
        mutate("UPDATE endpoints SET active=0 WHERE destination LIKE 'demo://%'")
    task = asyncio.create_task(worker()) if os.environ.get('HOOKSCOPE_DISABLE_WORKER') != '1' else None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(title='Hookscope', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.environ.get('HOOKSCOPE_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(','))

def authorized(request):
    token = request.cookies.get(COOKIE, '')
    rows = query('SELECT owner_id FROM sessions WHERE token=:token AND expires>:now',
                 {'token': hashlib.sha256(token.encode()).hexdigest(), 'now': time.time()}) if token else []
    if not rows:
        raise HTTPException(401, 'Sign in to continue.')
    return rows[0]['owner_id']

@app.middleware('http')
async def protections(request: Request, call_next):
    identity = None
    owner = None
    try:
        if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            allowed = {os.environ.get('HOOKSCOPE_PUBLIC_URL', '').rstrip('/')} if production() else {f'{request.url.scheme}://{request.headers.get("host")}', 'http://127.0.0.1:5173', 'http://localhost:5173'}
            if not production():
                allowed.update(filter(None, os.environ.get('HOOKSCOPE_ORIGINS', '').split(',')))
            if origin and origin not in allowed:
                raise HTTPException(403, 'Cross-origin request blocked.')
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/auth', '/api/login', '/api/setup', '/api/health', '/api/ready', '/api/register'):
            owner = authorized(request)
            identity = current_owner.set(owner)
        if request.url.path.startswith('/api/') and request.method in ('POST','PATCH','PUT'):
            # Bound all management bodies, including chunked requests.
            body = bytearray()
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY * 6:
                        raise HTTPException(413, 'Management request is too large.')
            request._body = bytes(body)
        response = await call_next(request)
    except TimeoutError:
        response = JSONResponse({'detail':'Request body deadline exceeded.'}, status_code=408)
    except HTTPException as exc:
        response = JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
    finally:
        if identity is not None:
            current_owner.reset(identity)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if owner:
        response.headers['X-Hookscope-Workspace'] = owner
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    if production():
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response

class Credentials(BaseModel):
    password: str = Field(min_length=12, max_length=128)

class Login(Credentials):
    email: str = Field(default='owner@localhost', max_length=254)

def create_session(response, owner='legacy'):
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM sessions WHERE expires<:now'), {'now':time.time()})
        conn.execute(text('INSERT INTO sessions(token,expires,owner_id) VALUES(:token,:expires,:owner)'),
                     {'token': hashlib.sha256(token.encode()).hexdigest(), 'expires': time.time()+43200,'owner':owner})
        conn.execute(text('DELETE FROM sessions WHERE token IN (SELECT token FROM sessions WHERE owner_id=:owner ORDER BY expires DESC LIMIT -1 OFFSET 20)'), {'owner':owner})
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=os.environ.get('HOOKSCOPE_SECURE_COOKIES') == '1', max_age=43200)

@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.0.0'}

@app.get('/api/ready')
def ready():
    try:
        query('SELECT 1')
        recent = query('SELECT count(*) n FROM worker_heartbeats WHERE updated>:after', {'after':time.time()-60})[0]['n']
        if not recent:
            raise HTTPException(503, 'Delivery worker has no recent heartbeat.')
        return {'status':'ready','schema':query('SELECT max(version) version FROM schema_migrations')[0]['version']}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Database is unavailable.')

@app.get('/api/operations')
def operations():
    scope = {'owner':current_owner.get()}
    counts = query('SELECT a.status,count(*) n FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=:owner GROUP BY a.status',scope)
    pending = query("SELECT min(a.created) oldest FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE a.status IN ('queued','sending') AND p.owner_id=:owner",scope)[0]['oldest']
    usage = query('SELECT events n,body_bytes size,response_bytes FROM workspace_usage WHERE owner_id=:owner',scope)[0]
    return {'queue':{r['status']:r['n'] for r in counts}, 'oldest_pending_seconds':round(time.time()-pending) if pending else 0,
            'storage':usage, 'schema':query('SELECT max(version) version FROM schema_migrations')[0]['version'],
            'worker_healthy':bool(query('SELECT id FROM worker_heartbeats WHERE updated>:after', {'after':time.time()-60})),
            'production':production()}

@app.get('/api/auth')
def auth(request: Request):
    initialized = bool(query("SELECT value FROM settings WHERE key='password'"))
    signed_in = False
    account = None
    try:
        owner = authorized(request)
        rows = query('SELECT id,email FROM tenants WHERE id=:id', {'id':owner})
        account = rows[0] if rows else None
        signed_in = True
    except HTTPException:
        pass
    return {'initialized': initialized, 'authenticated': signed_in, 'production':production(), 'account':account}

@app.post('/api/setup')
def setup(credentials: Credentials, request: Request, response: Response):
    if production():
        raise HTTPException(403, 'Use terminal configuration for production setup.')
    if request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
        raise HTTPException(403, 'Initial setup is allowed only from this computer.')
    salt = secrets.token_hex(16)
    value = salt + ':' + password_hash(credentials.password, salt)
    try:
        mutate("INSERT INTO settings(key,value) VALUES('password',:value)", {'value': value})
    except IntegrityError:
        raise HTTPException(409, 'Already configured. Sign in instead.')
    mutate("INSERT INTO tenants(id,email,password,created) VALUES('legacy','owner@localhost',:value,:now)",{'value':value,'now':time.time()})
    create_session(response)
    return {'ok': True}

@app.post('/api/login')
def login(credentials: Login, request: Request, response: Response):
    # One owner: a global durable budget also prevents forwarded-IP rotation attacks.
    email = credentials.email.strip().lower()
    login_budget('login:'+hashlib.sha256(email.encode()).hexdigest())
    rows = query('SELECT id,password FROM tenants WHERE email=:email',{'email':email})
    if not rows:
        password_hash(credentials.password, '0'*32)
        raise HTTPException(401, 'Incorrect email or password.')
    salt, expected = rows[0]['password'].split(':')
    if not hmac.compare_digest(expected, password_hash(credentials.password, salt)):
        raise HTTPException(401, 'Incorrect email or password.')
    create_session(response,rows[0]['id'])
    return {'ok': True}

@app.post('/api/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, '')
    mutate('DELETE FROM sessions WHERE token=:token', {'token': hashlib.sha256(token.encode()).hexdigest()})
    response.delete_cookie(COOKIE)
    return {'ok': True}

class Registration(Credentials):
    email: str = Field(max_length=254)
    invitation: str = Field(min_length=20, max_length=200)

@app.post('/api/register', status_code=201)
def register(value: Registration, response: Response):
    try:
        email = normalize_email(value.email)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    login_budget('register:'+hashlib.sha256(email.encode()).hexdigest())
    token = hashlib.sha256(value.invitation.encode()).hexdigest()
    if not query('SELECT token FROM invitations WHERE token=:token AND email=:email AND expires>:now', {'token':token,'email':email,'now':time.time()}):
        raise HTTPException(403,'Invalid, expired or already used invitation.')
    owner = uid('ws')
    salt = secrets.token_hex(16)
    password = salt+':'+password_hash(value.password,salt)
    with engine.begin() as conn:
        invite = conn.execute(text('DELETE FROM invitations WHERE token=:token AND email=:email AND expires>:now RETURNING email'),
                              {'token':token,'email':email,'now':time.time()}).first()
        if not invite:
            raise HTTPException(403,'Invalid, expired or already used invitation.')
        if conn.execute(text('SELECT count(*) FROM tenants')).scalar_one() >= 100:
            raise HTTPException(409,'Account capacity reached. Contact the operator.')
        try:
            conn.execute(text('INSERT INTO tenants(id,email,password,created) VALUES(:id,:email,:password,:now)'),
                         {'id':owner,'email':email,'password':password,'now':time.time()})
        except IntegrityError:
            raise HTTPException(409,'An account already exists for this email.')
    create_session(response,owner)
    return {'ok':True}

class SecretInput(BaseModel):
    name: str = Field(min_length=1,max_length=60)
    value: str = Field(min_length=32,max_length=4096)

@app.get('/api/secrets')
def list_secrets():
    return query('SELECT id,name FROM tenant_secrets WHERE owner_id=:owner ORDER BY name',{'owner':current_owner.get()})

@app.post('/api/secrets', status_code=201)
def create_secret(value: SecretInput):
    if not value.name.strip():
        raise HTTPException(422,'Enter a secret name.')
    owner = current_owner.get()
    identity = uid('sec')
    ciphertext = encrypt_secret(value.value,owner,identity)
    try:
        inserted = mutate('''INSERT INTO tenant_secrets(id,owner_id,name,value)
            SELECT :id,:owner,:name,:value WHERE (SELECT count(*) FROM tenant_secrets WHERE owner_id=:owner)<60''',
            {'id':identity,'owner':owner,'name':value.name.strip(),'value':ciphertext})
    except IntegrityError:
        raise HTTPException(409,'A secret with this name already exists.')
    if not inserted:
        raise HTTPException(409,'Secret capacity reached.')
    return {'id':identity,'name':value.name.strip()}

@app.delete('/api/secrets/{secret_id}')
def delete_secret(secret_id: str):
    owner = current_owner.get()
    with engine.begin() as conn:
        conn.execute(text('UPDATE tenant_secrets SET name=name WHERE id=:id AND owner_id=:owner'),{'id':secret_id,'owner':owner})
        used = conn.execute(text('''SELECT id FROM endpoints WHERE owner_id=:owner AND (incoming_secret_ref=:id OR signing_secret_ref=:id)
            UNION ALL SELECT a.id FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id
            WHERE p.owner_id=:owner AND a.signing_secret_ref=:id AND a.status IN ('queued','sending')'''),{'id':secret_id,'owner':owner}).first()
        if used:
            raise HTTPException(409,'Update endpoints and finish pending deliveries before deleting this secret.')
        if not conn.execute(text('DELETE FROM tenant_secrets WHERE id=:id AND owner_id=:owner'),{'id':secret_id,'owner':owner}).rowcount:
            raise HTTPException(404,'Secret not found.')
    return {'ok':True}

class EndpointInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    destination: str = Field(default='', max_length=2000)
    active: bool = True
    verify_mode: Literal['none','github','hmac'] = 'none'
    incoming_secret_ref: str = Field(default='', max_length=100)
    signing_secret_ref: str = Field(default='', max_length=100)
    retries: int = Field(default=0, ge=0, le=5)

def check_policy(value: EndpointInput):
    if value.verify_mode != 'none' and not value.incoming_secret_ref:
        raise HTTPException(422, 'Signature verification requires an incoming secret reference.')
    try:
        if value.incoming_secret_ref:
            secret_value(value.incoming_secret_ref,current_owner.get())
        if value.signing_secret_ref:
            secret_value(value.signing_secret_ref,current_owner.get())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if production() and value.destination.startswith('demo://'):
        raise HTTPException(422, 'Simulators are disabled in production.')

def check_destination(destination):
    try:
        validate_destination(destination)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

@app.get('/api/endpoints')
def endpoints():
    return query('''SELECT e.*, (SELECT count(*) FROM events v WHERE v.endpoint_id=e.id) AS event_count
        FROM endpoints e WHERE e.owner_id=:owner ORDER BY created''',{'owner':current_owner.get()})

@app.post('/api/endpoints', status_code=201)
def create_endpoint(value: EndpointInput):
    check_destination(value.destination)
    check_policy(value)
    endpoint = {'id': uid('ep'), 'name': value.name.strip(), 'token': secrets.token_urlsafe(32),
                'destination': value.destination, 'active': int(value.active), 'created': time.time(),
                'verify_mode':value.verify_mode,'incoming_secret_ref':value.incoming_secret_ref,
                'signing_secret_ref':value.signing_secret_ref,'retries':value.retries,'owner':current_owner.get()}
    if not endpoint['name']:
        raise HTTPException(422, 'Enter an endpoint name.')
    inserted = mutate('''INSERT INTO endpoints(id,name,token,destination,active,created,verify_mode,incoming_secret_ref,signing_secret_ref,retries,owner_id)
        SELECT :id,:name,:token,:destination,:active,:created,:verify_mode,:incoming_secret_ref,:signing_secret_ref,:retries,:owner
        WHERE (SELECT count(*) FROM endpoints WHERE owner_id=:owner)<30''', endpoint)
    if not inserted:
        raise HTTPException(409, 'This workspace supports up to 30 endpoints.')
    return endpoint

@app.patch('/api/endpoints/{endpoint_id}')
def update_endpoint(endpoint_id: str, value: EndpointInput):
    check_destination(value.destination)
    check_policy(value)
    if not value.name.strip():
        raise HTTPException(422, 'Enter an endpoint name.')
    if not mutate('UPDATE endpoints SET name=:name,destination=:destination,active=:active,verify_mode=:verify_mode,incoming_secret_ref=:incoming_secret_ref,signing_secret_ref=:signing_secret_ref,retries=:retries WHERE id=:id AND owner_id=:owner',
                  {'id': endpoint_id, **value.model_dump(), 'name': value.name.strip(), 'active': int(value.active), 'owner':current_owner.get()}):
        raise HTTPException(404, 'Endpoint not found.')
    return {'ok': True}

@app.post('/api/endpoints/{endpoint_id}/rotate')
def rotate_endpoint(endpoint_id: str):
    token = secrets.token_urlsafe(32)
    if not mutate('UPDATE endpoints SET token=:token WHERE id=:id AND owner_id=:owner', {'token':token,'id':endpoint_id,'owner':current_owner.get()}):
        raise HTTPException(404, 'Endpoint not found.')
    return {'token':token}

class PasswordChange(Credentials):
    current_password: str = Field(min_length=12, max_length=128)

@app.post('/api/password')
def change_password(value: PasswordChange, response: Response):
    owner = current_owner.get()
    login_budget('password:'+owner)
    with engine.begin() as conn:
        conn.execute(text('UPDATE tenants SET password=password WHERE id=:owner'),{'owner':owner})
        current = conn.execute(text('SELECT password FROM tenants WHERE id=:owner'),{'owner':owner}).scalar_one()
        salt, expected = current.split(':')
        if not hmac.compare_digest(expected, password_hash(value.current_password, salt)):
            raise HTTPException(401, 'Incorrect current password.')
        salt = secrets.token_hex(16)
        new_value = salt+':'+password_hash(value.password,salt)
        conn.execute(text('UPDATE tenants SET password=:value WHERE id=:owner'),{'value':new_value,'owner':owner})
        if owner == 'legacy':
            conn.execute(text("UPDATE settings SET value=:value WHERE key='password'"), {'value':new_value})
        conn.execute(text('DELETE FROM sessions WHERE owner_id=:owner'),{'owner':owner})
    response.delete_cookie(COOKIE)
    return {'ok':True}

@app.delete('/api/endpoints/{endpoint_id}')
def delete_endpoint(endpoint_id: str):
    if not mutate('DELETE FROM endpoints WHERE id=:id AND owner_id=:owner', {'id': endpoint_id,'owner':current_owner.get()}):
        raise HTTPException(404, 'Endpoint not found.')
    return {'ok': True}

def record_event(endpoint, body, headers, source='webhook'):
    external_id = headers.get('x-hookscope-idempotency-key') or (headers.get('x-github-delivery') if endpoint.get('verify_mode') == 'github' else None)
    if external_id and len(external_id) > 200:
        raise HTTPException(422, 'Idempotency key must be at most 200 characters.')
    kind = 'http.request'
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict):
            kind = str(decoded.get('type') or decoded.get('event') or kind)[:120]
    except (ValueError, UnicodeError):
        pass
    event = {'id': uid('evt'), 'endpoint_id': endpoint['id'], 'created': time.time(), 'method': 'POST',
             'headers': json.dumps(redact_headers(headers)), 'body': body, 'kind': kind, 'source': source, 'external_id': external_id}
    attempt_id = None
    try:
        with engine.begin() as conn:
            # Serialize capture before checking quotas and duplicate identities.
            conn.execute(text('UPDATE endpoints SET active=active WHERE id=:id'), {'id':endpoint['id']})
            current = conn.execute(text('SELECT * FROM endpoints WHERE id=:id'), {'id':endpoint['id']}).mappings().first()
            if not current or not current['active']:
                raise HTTPException(410, 'Endpoint is paused or removed.')
            if source == 'webhook':
                if current['token'] != endpoint['token']:
                    raise HTTPException(410, 'Receiving token has been rotated.')
                verify_body(dict(current), body, headers)
            if external_id:
                existing = conn.execute(text('SELECT id FROM events WHERE endpoint_id=:endpoint AND external_id=:key'), {'endpoint':endpoint['id'], 'key':external_id}).mappings().first()
                if existing:
                    return {'event_id':existing['id'], 'duplicate':True}
            recent = conn.execute(text('SELECT count(*) n FROM events WHERE endpoint_id=:id AND created>:after'), {'id':endpoint['id'], 'after':time.time()-60}).scalar_one()
            if recent >= 120:
                raise HTTPException(429, 'Endpoint limit reached: 120 events per minute.')
            scope = {'owner':current['owner_id']}
            usage = conn.execute(text('SELECT events n,body_bytes+response_bytes size,attempt_count FROM workspace_usage WHERE owner_id=:owner'),scope).mappings().one()
            instance = conn.execute(text('SELECT * FROM instance_usage WHERE id=1')).mappings().one()
            if instance['events'] >= MAX_INSTANCE_EVENTS or instance['body_bytes']+instance['response_bytes']+len(body)>MAX_INSTANCE_BYTES:
                raise HTTPException(507, 'Server storage capacity reached. Contact the operator.')
            if usage['n'] >= MAX_STORED_EVENTS or usage['size'] + len(body) > MAX_STORED_BYTES:
                raise HTTPException(507, 'Workspace storage limit reached. Delete old events to continue.')
            conn.execute(text('INSERT INTO events(id,endpoint_id,created,method,headers,body,kind,source,external_id) VALUES(:id,:endpoint_id,:created,:method,:headers,:body,:kind,:source,:external_id)'), event)
            if current['destination']:
                backlog = conn.execute(text("SELECT count(*) FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE a.status IN ('queued','sending') AND p.owner_id=:owner"),scope).scalar_one()
                if backlog >= 1000:
                    raise HTTPException(429,'Workspace delivery backlog reached 1,000. Wait for deliveries or pause forwarding.')
                if usage['attempt_count'] >= MAX_ATTEMPTS or instance['attempt_count'] >= MAX_INSTANCE_ATTEMPTS:
                    raise HTTPException(507, 'Attempt storage limit reached.')
                attempt_id = uid('att')
                conn.execute(text("INSERT INTO attempts(id,event_id,created,status,destination,signing_secret_ref,retries) VALUES(:id,:event,:created,'queued',:destination,:signing_secret_ref,:retries)"),
                             {'id': attempt_id, 'event': event['id'], 'created': time.time(), 'destination': current['destination'],
                              'signing_secret_ref':current['signing_secret_ref'],'retries':current['retries']})
    except IntegrityError:
        existing = query('SELECT id FROM events WHERE endpoint_id=:endpoint AND external_id=:key', {'endpoint': endpoint['id'], 'key': external_id})
        if existing:
            return {'event_id': existing[0]['id'], 'duplicate': True}
        raise
    return {'event_id': event['id'], 'attempt_id': attempt_id, 'duplicate': False}

@app.post('/hooks/{token}', status_code=202)
async def receive(token: str, request: Request):
    rows = query('SELECT * FROM endpoints WHERE token=:token', {'token': token})
    if not rows:
        raise HTTPException(404, 'Endpoint not found.')
    endpoint = rows[0]
    if not endpoint['active']:
        raise HTTPException(410, 'Endpoint is paused.')
    body = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise HTTPException(413, 'Payload limit is 256 KiB.')
    except TimeoutError:
        raise HTTPException(408, 'Webhook upload exceeded 15 seconds.')
    return await asyncio.to_thread(record_event, endpoint, bytes(body), dict(request.headers))

@app.get('/api/events')
def list_events(endpoint: str = '', status: str = '', search: str = '', page: int = 1):
    page = max(1, page)
    filters = 'WHERE p.owner_id=:owner AND (:endpoint=\'\' OR e.endpoint_id=:endpoint) AND (:search=\'\' OR e.kind LIKE :pattern OR e.id LIKE :pattern OR p.name LIKE :pattern)'
    params = {'owner':current_owner.get(),'endpoint': endpoint, 'search': search, 'pattern': '%' + search[:120] + '%', 'status': status, 'offset': (page-1)*50}
    base = f'''SELECT e.id,e.endpoint_id,e.created,e.kind,e.source,e.method,length(e.body) size,p.name endpoint_name,
        e.latest_status status,
        (SELECT code FROM attempts WHERE event_id=e.id ORDER BY created DESC LIMIT 1) code,
        (SELECT latency FROM attempts WHERE event_id=e.id ORDER BY created DESC LIMIT 1) latency,
        (SELECT count(*) FROM attempts WHERE event_id=e.id) attempt_count
        FROM events e JOIN endpoints p ON p.id=e.endpoint_id {filters}'''
    wrapped = f'SELECT * FROM ({base}) WHERE (:status=\'\' OR status=:status)'
    total = query(f'SELECT count(*) n FROM ({wrapped})', params)[0]['n']
    return {'items': query(wrapped + ' ORDER BY created DESC LIMIT 50 OFFSET :offset', params), 'total': total, 'page': page}

@app.get('/api/events/{event_id}')
def event_detail(event_id: str):
    rows = query('SELECT e.*,p.name endpoint_name,p.destination FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=:id AND p.owner_id=:owner', {'id': event_id,'owner':current_owner.get()})
    if not rows:
        raise HTTPException(404, 'Event not found.')
    value = rows[0]
    body = value.pop('body')
    value['body'] = body.decode('utf-8', errors='replace')
    value['body_base64'] = base64.b64encode(body).decode()
    value['size'] = len(body)
    value['headers'] = json.loads(value['headers'])
    value['attempts'] = query('SELECT * FROM attempts WHERE event_id=:id ORDER BY created DESC', {'id': event_id})
    return value

@app.post('/api/events/{event_id}/replay', status_code=202)
def replay(event_id: str):
    rows = query('SELECT e.id,p.destination,p.active,p.signing_secret_ref,p.retries FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=:id AND p.owner_id=:owner', {'id': event_id,'owner':current_owner.get()})
    if not rows:
        raise HTTPException(404, 'Event not found.')
    row = rows[0]
    if not row['destination'] or not row['active']:
        raise HTTPException(409, 'Set a destination and activate the endpoint before replaying.')
    attempt = uid('att')
    inserted = mutate("""INSERT INTO attempts(id,event_id,created,status,destination,replay,signing_secret_ref,retries)
        SELECT :id,:event,:created,'queued',:destination,1,:signing_secret_ref,:retries WHERE NOT EXISTS
        (SELECT 1 FROM attempts WHERE event_id=:event AND status IN ('queued','sending'))
        AND (SELECT count(*) FROM attempts WHERE event_id=:event)<:event_limit
        AND (SELECT attempt_count FROM workspace_usage WHERE owner_id=:owner)<:total_limit
        AND (SELECT attempt_count FROM instance_usage WHERE id=1)<:instance_limit""",
        {'id':attempt, 'event':event_id, 'created':time.time(), 'destination':row['destination'],
         'signing_secret_ref':row['signing_secret_ref'],'retries':row['retries'], 'event_limit':MAX_EVENT_ATTEMPTS,'total_limit':MAX_ATTEMPTS,'owner':current_owner.get(),'instance_limit':MAX_INSTANCE_ATTEMPTS})
    if not inserted:
        raise HTTPException(409, 'An attempt is pending or the attempt quota is exhausted.')
    return {'attempt_id': attempt}

@app.delete('/api/events/{event_id}')
def remove_event(event_id: str):
    if not mutate('DELETE FROM events WHERE id=:id AND endpoint_id IN (SELECT id FROM endpoints WHERE owner_id=:owner)', {'id': event_id,'owner':current_owner.get()}):
        raise HTTPException(404, 'Event not found.')
    return {'ok': True}

@app.get('/api/stats')
def stats():
    events = list_events()['total']
    scope = {'owner':current_owner.get(),'after':time.time()-86400}
    statuses = query('SELECT e.latest_status status,count(*) n FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=:owner GROUP BY e.latest_status',scope)
    attempts = query("SELECT count(*) n, round(avg(a.latency)) latency FROM attempts a INDEXED BY attempts_completed JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE a.finished IS NOT NULL AND a.destination NOT LIKE 'demo://%' AND p.owner_id=:owner",scope)[0]
    timeline = query("SELECT strftime('%Y-%m-%dT%H:00:00Z',created,'unixepoch') hour,count(*) n FROM events WHERE created>:after AND endpoint_id IN (SELECT id FROM endpoints WHERE owner_id=:owner) GROUP BY hour ORDER BY hour",scope)
    return {'events': events, 'statuses': {r['status']:r['n'] for r in statuses}, 'attempts': attempts['n'], 'latency': attempts['latency'] or 0, 'timeline': timeline, 'retention_days': RETENTION_DAYS}

@app.post('/api/demo', status_code=201)
def demo():
    if production():
        raise HTTPException(403, 'Demo generation is disabled in production.')
    existing = query("SELECT id FROM endpoints WHERE destination LIKE 'demo://%' AND owner_id=:owner",{'owner':current_owner.get()})
    if existing:
        raise HTTPException(409, 'Demo endpoints already exist. Use Send test event to add more.')
    specs = [('Payments sandbox', 'demo://success'), ('Deployment listener', 'demo://flaky'), ('Support sync', 'demo://failure')]
    for name, destination in specs:
        ep = create_endpoint(EndpointInput(name=name, destination=destination))
        for i, kind in enumerate(['payment.completed', 'customer.updated', 'subscription.created'] if 'Payments' in name else ['deployment.finished', 'issue.created']):
            payload = {'id': uid('sample'), 'type': kind, 'created': int(time.time()), 'data': {'environment': 'sandbox', 'sequence': i+1, 'description': 'Generated example event'}}
            record_event(ep, json.dumps(payload, indent=2).encode(), {'content-type':'application/json','user-agent':'Hookscope demo'}, 'demo')
    return {'ok': True}

class TestInput(BaseModel):
    body: str = Field(max_length=MAX_BODY)

@app.post('/api/endpoints/{endpoint_id}/test', status_code=202)
def test_event(endpoint_id: str, value: TestInput):
    rows = query('SELECT * FROM endpoints WHERE id=:id AND owner_id=:owner', {'id':endpoint_id,'owner':current_owner.get()})
    if not rows:
        raise HTTPException(404, 'Endpoint not found.')
    if not rows[0]['active']:
        raise HTTPException(409, 'Activate this endpoint before sending a test event.')
    body = value.body.encode()
    if len(body) > MAX_BODY:
        raise HTTPException(413, 'Payload limit is 256 KiB.')
    return record_event(rows[0], body, {'content-type':'application/json','user-agent':'Hookscope test'}, 'test')

dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if dist.exists():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

@app.get('/')
def index():
    if dist.exists():
        return FileResponse(dist / 'index.html')
    return JSONResponse({'message': 'Build the frontend or open the development server on http://127.0.0.1:5173.'})
