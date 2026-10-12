"""Verify a migrated database matches the SQLAlchemy metadata.

Used as a deployment gate (``python -m app.cli.verify_schema``) and by the migration tests:
after ``alembic upgrade head`` on a clean database the schema must be complete - tables,
indexes, unique constraints, foreign keys and check constraints.

Exits non-zero and prints what is missing when it is not.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector

import app.models  # noqa: F401  - registers mappers
from app.db.base import Base
from app.db.session import dispose_engine, get_engine


def _expected_fk_keys() -> set[tuple[str, str, str, str]]:
    """(table, column, referred table, referred column) for every declared foreign key."""
    keys: set[tuple[str, str, str, str]] = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            referred = fk.column.table.name
            keys.add((table.name, fk.parent.name, referred, fk.column.name))
    return keys


def _actual_fk_keys(inspector: Inspector, tables: set[str]) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for table in sorted(tables):
        for fk in inspector.get_foreign_keys(table):
            referred = fk.get("referred_table")
            for local, remote in zip(
                fk.get("constrained_columns") or [], fk.get("referred_columns") or [], strict=False
            ):
                keys.add((table, local, str(referred), remote))
    return keys


def _expected_check_names() -> set[tuple[str, str]]:
    return {
        (table.name, str(constraint.name))
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint" and constraint.name
    }


def _inspect(connection: Connection) -> dict[str, list[str]]:
    """Everything the database is missing, per check, as printable strings.

    Every value is a sorted list of human-readable names so the caller can print them directly and
    a non-empty result is always a failure.
    """
    inspector = inspect(connection)
    expected_tables = set(Base.metadata.tables)
    tables = expected_tables & set(inspector.get_table_names())

    indexes: set[str] = set()
    uniques: set[str] = set()
    for table in tables:
        indexes.update(i["name"] or "" for i in inspector.get_indexes(table))
        uniques.update(u["name"] or "" for u in inspector.get_unique_constraints(table))
    # SQLite reports UNIQUE constraints created as indexes (including inline uniques) in get_indexes.
    for table in tables:
        for uq in inspector.get_unique_constraints(table):
            uniques.add(uq["name"] or "")

    checks: set[tuple[str, str]] = set()
    for table in tables:
        for ck in inspector.get_check_constraints(table):
            if ck.get("name"):
                checks.add((table, str(ck["name"])))

    return {
        "missing_tables": sorted(expected_tables - tables),
        "missing_indexes": sorted(
            {str(i.name) for t in Base.metadata.tables.values() for i in t.indexes if i.name} - indexes
        ),
        "missing_uniques": sorted(
            {
                str(c.name)
                for t in Base.metadata.tables.values()
                for c in t.constraints
                if c.__class__.__name__ == "UniqueConstraint" and c.name
            }
            - uniques
            - indexes
        ),
        "missing_foreign_keys": sorted(
            f"{t}.{c} -> {rt}.{rc}" for t, c, rt, rc in (_expected_fk_keys() - _actual_fk_keys(inspector, tables))
        ),
        "missing_checks": sorted(f"{t}:{n}" for t, n in (_expected_check_names() - checks)),
    }


async def _verify() -> dict[str, list[str]]:
    engine = get_engine()
    async with engine.connect() as connection:
        return await connection.run_sync(_inspect)


async def _verify_and_dispose() -> dict[str, list[str]]:
    """Keep connection-pool shutdown on the same asyncio loop as inspection."""
    try:
        return await _verify()
    finally:
        await dispose_engine()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    result = asyncio.run(_verify_and_dispose())
    problems = {key: value for key, value in result.items() if value}
    if problems:
        print("Schema verification FAILED")
        for key, value in problems.items():
            print(f"  - {key}: {', '.join(value)}")
        return 1
    print(f"Schema verification OK ({len(Base.metadata.tables)} tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
