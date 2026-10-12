"""Exercise an already built hookscope:verify image using disposable resources.

No host ports are published; fixture accounts, events and backups live only in a
randomly named volume. Configuration files are mounted read-only. This verifies
internal HTTP and HTTPS configuration syntax, not public certificates/provider delivery.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which('docker')
if not DOCKER and os.name == 'nt':
    candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker/resources/bin/docker.exe'
    if candidate.is_file():
        DOCKER = str(candidate)
if not DOCKER:
    raise SystemExit('Docker CLI was not found. Install/start Docker before running this check.')


def run(*args, **kwargs):
    kwargs.setdefault('text', True)
    return subprocess.run([DOCKER, *args], check=True, **kwargs)


def inspect(name, template):
    return run('inspect', '--format', template, name, capture_output=True).stdout.strip()


def wait_healthy(name):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = inspect(name, '{{.State.Status}} {{.State.Health.Status}}')
        if status == 'running healthy':
            return
        if status.startswith(('exited ', 'dead ')):
            raise RuntimeError('Application container exited during startup.')
        time.sleep(1)
    raise RuntimeError('Application container did not become healthy within 90 seconds.')


# Resource flags mirror the production application container. All writable
# state is restricted to the disposable volume and /tmp tmpfs.
APP_LIMITS = [
    '--read-only', '--tmpfs', '/tmp:size=64m,mode=1777', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges:true', '--memory', '1g', '--cpus', '2',
    '--pids-limit', '128', '--stop-timeout', '35', '--log-driver', 'json-file',
    '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
]

READ_ONLY_PROBE = r'''
import errno
from pathlib import Path
probe = Path('/app/readonly-smoke-probe')
try:
    probe.write_text('fixture')
except OSError as error:
    assert error.errno == errno.EROFS, 'Root filesystem did not enforce read-only mode'
else:
    probe.unlink()
    raise AssertionError('Root filesystem was writable')
temporary = Path('/tmp/hookscope-smoke-probe')
temporary.write_text('fixture')
temporary.unlink()
'''

GATEWAY_PROBE = r'''
import base64
import json
import sys
import urllib.parse
import urllib.request

base = 'http://gateway:8080'
cookie = ''
kind = 'gateway+query /? keep&bytes'

def request(path, value=None):
    headers = {'Host': 'localhost', 'Origin': 'https://localhost', 'X-Real-IP': '192.0.2.10'}
    if cookie:
        headers['Cookie'] = cookie
    body = None
    if value is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(value, separators=(',', ':')).encode()
    response = urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers), timeout=10)
    return response, body

response, _ = request('/api/he%61lth?probe=literal%2Bquery%20value')
assert json.load(response)['status'] == 'ok', 'Encoded health route failed'

if sys.argv[1] == 'create':
    response, _ = request('/api/login', {'email': 'owner@localhost', 'password': 'container-fixture-password'})
    assert 'Secure' in response.headers['Set-Cookie']
    cookie = response.headers['Set-Cookie'].split(';', 1)[0]
    assert json.load(response)['ok']
    response, _ = request('/api/endpoints', {'name': 'container gateway fixture'})
    endpoint = json.load(response)
    # Encode a path character and include escaped query characters. Capture must
    # still reach the same endpoint and preserve the exact request body.
    token = endpoint['token']
    encoded_token = '%' + format(ord(token[0]), '02X') + token[1:]
    response, body = request('/hooks/' + encoded_token + '?fixture=keep%2Bquery%26value', {'type': kind, 'payload': 'exact bytes'})
    assert response.status == 202
    identity = json.load(response)['event_id']
    response, _ = request('/hooks/' + token, {'type': 'gateway-other'})
    assert response.status == 202
    fixture = {'cookie': cookie, 'event_id': identity, 'body': base64.b64encode(body).decode()}
else:
    fixture = json.loads(sys.argv[2])
    cookie = fixture['cookie']

# Losing or mis-decoding the search query would return both captured events.
query = urllib.parse.urlencode({'search': kind})
response, _ = request('/api/events?' + query)
events = json.load(response)
assert events['total'] == 1 and events['items'][0]['id'] == fixture['event_id'], 'Escaped query forwarding failed'
identity = fixture['event_id']
response, _ = request('/api/events/%' + format(ord(identity[0]), '02X') + identity[1:])
event = json.load(response)
assert event['body_base64'] == fixture['body'], 'Proxy changed the captured body'
print(json.dumps(fixture))
'''


def gateway_probe(name, mode, fixture=None):
    arguments = ['exec', name, 'python', '-c', GATEWAY_PROBE, mode]
    if fixture is not None:
        arguments.append(json.dumps(fixture))
    return json.loads(run(*arguments, capture_output=True).stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='hookscope:verify', help='Already built application image (default: hookscope:verify).')
    parser.add_argument('--platform', choices=('linux/amd64', 'linux/arm64'),
                        help='Request this platform for every container; emulation does not verify the actual deployment host.')
    args = parser.parse_args()
    image = args.image
    platform_flags = ['--platform', args.platform] if args.platform else []
    name = 'hookscope-verify-' + secrets.token_hex(12)
    volume = name + '-data'
    network = name + '-network'
    gateway = name + '-gateway'
    blocker = name + '-old-ip'
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    environment = [
        '-e', 'HOOKSCOPE_ENV=production', '-e', 'HOOKSCOPE_PUBLIC_URL=https://localhost',
        '-e', 'HOOKSCOPE_ALLOWED_HOSTS=localhost', '-e', 'HOOKSCOPE_SECURE_COOKIES=1',
        '-e', 'HOOKSCOPE_ENCRYPTION_KEY=' + key,
    ]
    created_volume = created_network = False

    def start_application():
        run('run', '-d', '--name', name, '--network', network, '--network-alias', 'hookscope',
            *APP_LIMITS, *environment, '-v', volume + ':/app/backend/data', *platform_flags, image,
            stdout=subprocess.DEVNULL)
        wait_healthy(name)

    try:
        run('volume', 'create', volume, stdout=subprocess.DEVNULL)
        created_volume = True
        run('network', 'create', network, stdout=subprocess.DEVNULL)
        created_network = True
        run('run', '--rm', '-i', *APP_LIMITS, *environment, '-v', volume + ':/app/backend/data',
            *platform_flags, image, 'python', '-m', 'app.configure',
            # Windows text pipes translate LF to CRLF; Linux getpass would keep
            # the CR as part of the password. Send exact LF-terminated bytes.
            input=b'container-fixture-password\ncontainer-fixture-password\n', text=False)
        start_application()
        run('exec', name, 'python', '-c', READ_ONLY_PROBE)
        run('exec', name, 'python', '-c',
            "import urllib.request,json; r=urllib.request.urlopen(urllib.request.Request('http://localhost:8787/api/login',data=json.dumps({'email':'owner@localhost','password':'container-fixture-password'}).encode(),headers={'Content-Type':'application/json'})); assert 'Secure' in r.headers['Set-Cookie']; assert json.load(r)['ok']")
        run('exec', name, 'python', '-m', 'app.maintenance', 'backup', '/app/backend/data/verified-backup.db')
        run('exec', name, 'python', '-m', 'app.maintenance', 'check', '/app/backend/data/verified-backup.db')
        run('restart', name, stdout=subprocess.DEVNULL)
        wait_healthy(name)

        nginx_mount = (ROOT / 'deploy/nginx.conf').as_posix() + ':/etc/nginx/nginx.conf:ro'
        run('run', '--rm', '--network', network, '-v', nginx_mount, *platform_flags, 'nginx:1.28-alpine', 'nginx', '-t')
        run('run', '-d', '--name', gateway, '--network', network, '--network-alias', 'gateway',
            '--read-only', '--tmpfs', '/var/cache/nginx', '--tmpfs', '/var/run', '--tmpfs', '/tmp',
            '--security-opt', 'no-new-privileges:true', '--memory', '128m', '--pids-limit', '64',
            '-v', nginx_mount, *platform_flags, 'nginx:1.28-alpine', stdout=subprocess.DEVNULL)
        # Nginx may still be entering its listener after Docker returns.
        deadline = time.monotonic() + 20
        while True:
            try:
                run('exec', name, 'python', '-c',
                    "import urllib.request,json; r=urllib.request.urlopen(urllib.request.Request('http://gateway:8080/api/health',headers={'Host':'localhost','X-Real-IP':'192.0.2.10'}),timeout=3); assert json.load(r)['status']=='ok'",
                    capture_output=True)
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Gateway did not serve the application health route.') from None
                time.sleep(1)
        fixture = gateway_probe(name, 'create')
        gateway_identity = inspect(gateway, '{{.Id}} {{.State.StartedAt}}')

        old_ip = inspect(name, '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
        if not old_ip:
            raise RuntimeError('Could not determine the original application IP.')
        run('rm', '-f', name, stdout=subprocess.DEVNULL)
        # Keep the old IP occupied without the application alias/listener, forcing
        # Docker to allocate a different address to the replacement application.
        run('run', '-d', '--name', blocker, '--network', network, '--ip', old_ip,
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '64m', '--pids-limit', '16', *platform_flags, image, 'python', '-c',
            'import time; time.sleep(300)', stdout=subprocess.DEVNULL)
        start_application()
        new_ip = inspect(name, '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
        if new_ip == old_ip or not new_ip:
            raise RuntimeError('Application recreation did not change its Docker IP.')
        deadline = time.monotonic() + 20
        while True:
            try:
                gateway_probe(name, 'check', fixture)
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Gateway did not recover after application IP changed.') from None
                time.sleep(1)
        if inspect(gateway, '{{.Id}} {{.State.StartedAt}}') != gateway_identity:
            raise RuntimeError('Gateway unexpectedly restarted during application recreation.')
        run('exec', name, 'python', '-m', 'app.maintenance', 'check', '/app/backend/data/verified-backup.db')

        caddy_mount = (ROOT / 'deploy/Caddyfile').as_posix() + ':/etc/caddy/Caddyfile:ro'
        run('run', '--rm', '-e', 'HOOKSCOPE_DOMAIN=localhost', '-v', caddy_mount,
            *platform_flags, 'caddy:2.10-alpine', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile')
        platform_label = args.platform or 'daemon default platform'
        print(f'{image} ({platform_label}): production constraints, startup, secure session, backup, restart, live gateway capture/query forwarding, IP-change recovery and HTTPS configuration syntax passed. Actual deployment-host and public TLS checks remain separate.')
    finally:
        # Only names allocated by this invocation are eligible for cleanup.
        for container in (gateway, name, blocker):
            subprocess.run([DOCKER, 'rm', '-f', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created_network:
            subprocess.run([DOCKER, 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created_volume:
            subprocess.run([DOCKER, 'volume', 'rm', volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
