"""Database URL normalisation for managed providers.

Managed PostgreSQL providers (Render, Railway, Heroku, Neon, ...) hand out connection
strings with a bare ``postgresql://`` or ``postgres://`` scheme. The application talks to the
database through SQLAlchemy's async engine, which needs the driver-qualified
``postgresql+asyncpg://`` form. Rather than requiring every deployment to hand-edit the value,
the scheme is upgraded here.

Only the generically-named PostgreSQL schemes are rewritten. Any URL that already names a
driver (including ``sqlite+aiosqlite://``) is returned unchanged.
"""

from __future__ import annotations

_ASYNC_POSTGRES = frozenset({"postgres", "postgresql"})


def normalize_database_url(url: str) -> str:
    """Return *url* with a driver-less PostgreSQL scheme upgraded to asyncpg."""
    scheme, separator, remainder = url.partition("://")
    if separator and scheme.lower() in _ASYNC_POSTGRES:
        return f"postgresql+asyncpg://{remainder}"
    return url
