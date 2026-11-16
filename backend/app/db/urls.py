"""Database URL normalisation for managed providers.

Managed PostgreSQL providers (Render, Railway, Heroku, Neon, Supabase, ...) hand out
connection strings with a bare ``postgresql://`` or ``postgres://`` scheme. The application
talks to the database through SQLAlchemy's async engine, which needs the driver-qualified
``postgresql+asyncpg://`` form. Rather than requiring every deployment to hand-edit the value,
the scheme is upgraded here.

The query string is also adapted for asyncpg. Providers copy/paste URLs that contain libpq
options asyncpg does not accept as keyword arguments:

* ``sslmode=require`` is translated to asyncpg's ``ssl=require``.
* ``channel_binding`` (Neon) and ``pgbouncer`` (Supabase) are dropped; the driver does not
  understand either and would refuse to connect.

Only PostgreSQL URLs are rewritten. Any other URL (including ``sqlite+aiosqlite://``) is
returned unchanged.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_ASYNC_POSTGRES = frozenset({"postgres", "postgresql"})
_ASYNC_POSTGRES_SCHEME = "postgresql+asyncpg"
_UNSUPPORTED_QUERY_KEYS = frozenset({"channel_binding", "pgbouncer"})


def normalize_database_url(url: str) -> str:
    """Return *url* upgraded to the asyncpg driver with a driver-compatible query string."""
    scheme, separator, remainder = url.partition("://")
    if not separator:
        return url
    if scheme.lower() in _ASYNC_POSTGRES:
        url = f"{_ASYNC_POSTGRES_SCHEME}://{remainder}"
    elif scheme.lower() != _ASYNC_POSTGRES_SCHEME:
        return url
    return _normalise_asyncpg_query(url)


def _normalise_asyncpg_query(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    has_ssl = any(key.lower() == "ssl" for key, _ in pairs)
    normalised: list[tuple[str, str]] = []
    for key, value in pairs:
        lowered = key.lower()
        if lowered == "sslmode":
            if not has_ssl:
                normalised.append(("ssl", value))
        elif lowered not in _UNSUPPORTED_QUERY_KEYS:
            normalised.append((key, value))

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(normalised), parts.fragment))
