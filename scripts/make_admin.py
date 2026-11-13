r"""Grant admin access to an account, or list accounts.

There is deliberately no API that creates an admin (signup always produces a
non-admin user), so this is the supported way to promote yourself.

Usage
-----
    # Bash / Git Bash — URL through the environment (recommended):
    DATABASE_URL="postgresql://..." python scripts/make_admin.py you@example.com

    # PowerShell (note the $env: form and the semicolon):
    $env:DATABASE_URL = "postgresql://..."; .\venv\Scripts\python.exe scripts\make_admin.py you@example.com

    # Otherwise it prompts for the URL (input hidden). Pasting into a hidden
    # prompt is unreliable on Windows - prefer the environment variable.
    python scripts/make_admin.py you@example.com

    # Just look at what exists:
    python scripts/make_admin.py --list

On Render: Postgres instance -> Connect -> External Database URL (the internal
one only resolves inside Render's network). Paste it at the prompt.

Passwords are never touched, so the person keeps the password they signed up
with. The change is visible immediately to the API (it reads is_admin from the
database per request); the browser also caches your role at login, so log out
and back in to see the admin UI.
"""
import getpass
import os
import sys

from sqlalchemy import create_engine, text


def _clean(raw: str) -> str:
    """Strip whitespace/quotes picked up by a paste; modernise the scheme."""
    url = (raw or '').strip().strip('"').strip("'").strip()
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def _resolve_url() -> str:
    url = _clean(os.environ.get('DATABASE_URL', ''))
    from_prompt = False
    if not url:
        url = _clean(getpass.getpass('Database URL (input hidden): '))
        from_prompt = True
    if not url:
        sys.exit('No database URL given.')
    if '://' not in url:
        # Almost always a bad paste: on Windows the hidden prompt can capture
        # stale clipboard text (e.g. a venv activation line) instead of a URL.
        sys.exit(
            'That does not look like a database URL - it has no "://".\n'
            + ('The hidden prompt cannot reliably take a paste on Windows.\n'
               if from_prompt else '')
            + 'Copy the External Database URL from Render, then run one of these:\n\n'
            '  PowerShell:\n'
            '    $env:DATABASE_URL = "postgresql://..."\n'
            '    .\\venv\\Scripts\\python.exe scripts\\make_admin.py you@example.com\n\n'
            '  Git Bash:\n'
            '    DATABASE_URL="postgresql://..." ./venv/Scripts/python.exe '
            'scripts/make_admin.py you@example.com\n'
        )
    return url


def _list_accounts(conn) -> None:
    rows = conn.execute(text(
        'SELECT id, email, role, is_admin, is_verified FROM users ORDER BY id'
    )).fetchall()
    if not rows:
        print('No accounts yet - sign up on the site first.')
        return
    print(f'{len(rows)} account(s):')
    for r in rows:
        print(f'  id={r[0]:<4} {r[1]:<42} role={r[2]:<10} '
              f'admin={bool(r[3])!s:<5} verified={bool(r[4])}')


def main() -> None:
    args = [a for a in sys.argv[1:] if a.strip()]
    if not args:
        sys.exit(__doc__.split('Usage')[1].split('On Render')[0].strip())

    engine = create_engine(_resolve_url())
    with engine.begin() as conn:
        if args[0] in ('--list', '-l'):
            _list_accounts(conn)
            return

        email = args[0].strip().lower()
        updated = conn.execute(
            text('UPDATE users SET is_admin = TRUE WHERE lower(email) = :e'),
            {'e': email},
        ).rowcount

        if updated:
            row = conn.execute(
                text('SELECT id, email, role, is_admin FROM users WHERE lower(email) = :e'),
                {'e': email},
            ).fetchone()
            print(f'Done: {updated} row updated -> id={row[0]} {row[1]} '
                  f'role={row[2]} admin={bool(row[3])}')
            print('Now log out and log back in on the site, then open /admin.')
        else:
            print(f'No account with email {email!r}.')
            _list_accounts(conn)


if __name__ == '__main__':
    main()
