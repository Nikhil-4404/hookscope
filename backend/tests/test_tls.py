"""Real loopback TLS fixture; private routing exceptions exist only in this test."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import ssl
import threading
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from app.delivery import send, PinnedHTTPSConnection


def test_real_tls_body_signature_and_certificate_verification(tmp_path,monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'receiver.example.test')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('receiver.example.test')]),critical=False)
          .sign(key,hashes.SHA256()))
    certfile=tmp_path/'cert.pem';keyfile=tmp_path/'key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    seen={}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(body=self.rfile.read(int(self.headers['Content-Length'])),headers=dict(self.headers),path=self.path)
            self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'OK')
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(certfile,keyfile)
    server.socket=server_context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original_create=__import__('socket').create_connection
    monkeypatch.setattr('app.delivery.public_address',lambda hostname:'127.0.0.1')
    monkeypatch.setattr('socket.create_connection',lambda address,timeout:original_create((address[0],server.server_port),timeout))
    original_context=ssl.create_default_context
    monkeypatch.setattr('ssl.create_default_context',lambda:original_context(cafile=str(certfile)))
    monkeypatch.setenv('HOOKSCOPE_SECRET_TLS','signing-secret-at-least-thirty-two-bytes')
    body=b'\xff\x00 { "unchanged": true }\r\n'
    try:
        code,response,latency=send({'id':'att_tls','destination':'https://receiver.example.test/path?q=1','replay':0,'signing_secret_ref':'HOOKSCOPE_SECRET_TLS'},
            {'id':'evt_tls','body':body,'headers':json.dumps({'content-type':'application/octet-stream','authorization':'DO NOT FORWARD'})})
        assert code==200 and response=='OK' and latency>=0
        assert seen['body']==body and seen['path']=='/path?q=1'
        assert 'authorization' not in {k.lower() for k in seen['headers']}
        timestamp=seen['headers']['X-Hookscope-Timestamp']
        expected='v1='+hmac.new(b'signing-secret-at-least-thirty-two-bytes',timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        assert hmac.compare_digest(seen['headers']['X-Hookscope-Signature'],expected)
        connection=PinnedHTTPSConnection('wrong.example.test','127.0.0.1')
        try:
            import pytest
            with pytest.raises(ssl.SSLCertVerificationError):connection.connect()
        finally:connection.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
