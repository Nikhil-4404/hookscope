"""Local operator account administration. Invitations are capabilities: share privately."""
import argparse
import hashlib
import secrets
import time
from .store import initialize, query, mutate
from .store import engine
from sqlalchemy import text
from .tenancy import normalize_email


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['invite','revoke-sessions','list'])
    parser.add_argument('--email')
    parser.add_argument('--origin',default='http://127.0.0.1:8787')
    args = parser.parse_args()
    initialize()
    if args.command == 'list':
        for row in query('SELECT id,email FROM tenants ORDER BY created'):
            print(row['id'],row['email'])
        return
    try:
        email = normalize_email(args.email or '')
    except ValueError as exc:
        raise SystemExit(str(exc))
    if args.command == 'revoke-sessions':
        mutate('DELETE FROM sessions WHERE owner_id IN (SELECT id FROM tenants WHERE email=:email)',{'email':email})
        print('Sessions revoked.')
        return
    if query('SELECT id FROM tenants WHERE email=:email',{'email':email}):
        raise SystemExit('Account already exists.')
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM invitations WHERE expires<:now OR email=:email'),{'now':time.time(),'email':email})
        if conn.execute(text('SELECT count(*) FROM invitations')).scalar_one() >= 1000:
            raise SystemExit('Invitation capacity reached.')
        conn.execute(text('INSERT INTO invitations(token,email,expires,created) VALUES(:token,:email,:expires,:now)'),
                     {'token':hashlib.sha256(token.encode()).hexdigest(),'email':email,'expires':time.time()+86400,'now':time.time()})
    print('Private invitation, valid once for 24 hours:')
    print(args.origin.rstrip('/')+'/#invite='+token)


if __name__ == '__main__':
    main()
