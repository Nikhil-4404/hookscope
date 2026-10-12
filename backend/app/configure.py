"""Local terminal setup, also usable inside a Docker container."""
import getpass
import argparse
import time
import secrets
from .main import password_hash
from .store import initialize, query, engine
from sqlalchemy import text
from .tenancy import normalize_email

def main():
    parser = argparse.ArgumentParser(description='Configure or reset the workspace owner password locally.')
    parser.add_argument('--reset', action='store_true', help='Replace the password and revoke every session. Requires local filesystem access.')
    parser.add_argument('--email', help='Email for first operator setup, or existing account to reset.')
    args = parser.parse_args()
    initialize()
    account = query('SELECT id,email FROM tenants WHERE email=:email',{'email':args.email.strip().lower()}) if args.email else query("SELECT id,email FROM tenants WHERE id='legacy'")
    if account and not args.reset:
        print('Already configured. Sign in with your existing password.')
        return
    if args.reset and not account:
        raise SystemExit('Account not found. Use invitations for new accounts.')
    if not account and query("SELECT id FROM tenants WHERE id='legacy'"):
        raise SystemExit('Operator already exists. Use invitations for new accounts.')
    if args.email:
        try:
            email = normalize_email(args.email)
        except ValueError as exc:
            raise SystemExit(str(exc))
    else:
        email = account[0]['email'] if account else 'owner@localhost'
    identity = account[0]['id'] if account else 'legacy'
    password = getpass.getpass('Choose a workspace password (12–128 characters): ')
    if not 12 <= len(password) <= 128:
        raise SystemExit('Password must be 12–128 characters.')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords did not match.')
    salt = secrets.token_hex(16)
    with engine.begin() as conn:
        value=salt+':'+password_hash(password,salt)
        if identity == 'legacy':
            conn.execute(text("INSERT INTO settings(key,value) VALUES('password',:value) ON CONFLICT(key) DO UPDATE SET value=:value"), {'value':value})
        conn.execute(text('INSERT INTO tenants(id,email,password,created) VALUES(:id,:email,:value,:now) ON CONFLICT(id) DO UPDATE SET password=:value'),{'id':identity,'email':email,'value':value,'now':time.time()})
        conn.execute(text('DELETE FROM sessions WHERE owner_id=:id'),{'id':identity})
        conn.execute(text('DELETE FROM auth_limits'))
    print('Workspace configured. You can now sign in.')

if __name__ == '__main__':
    main()
