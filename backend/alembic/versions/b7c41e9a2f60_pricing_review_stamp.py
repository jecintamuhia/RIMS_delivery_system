"""pricing review stamp

Adds the reviewer fields on ``pricing_versions`` that make the draft -> review -> active
lifecycle enforceable: a version records who validated it and when, and those stamps are cleared
when the version is retired so a stale approval can never be reused.

Also replaces the placeholder dispatch origin seeded by older deployments with RIMs' real
dispatch point, and pins it as the default. The placeholder was never a real depot - it existed
only so routing had somewhere to start - so it must not survive into a live deployment.

Revision ID: b7c41e9a2f60
Revises: 9d539f2b2ce6
Create Date: 2026-10-05 10:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c41e9a2f60"
down_revision: str | None = "9d539f2b2ce6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The pre-migration placeholder. Named exactly as it was seeded, matched literally below.
_PLACEHOLDER_NAME = "RIMs dispatch (set your real dispatch point)"

#: RIMs' dispatch point: Kenyatta Avenue, Naivasha, Nakuru County.
_DISPATCH_NAME = "RIMs Supplies and Hardware — Kenyatta Avenue, Naivasha"
_DISPATCH_LAT = -0.7256336
_DISPATCH_LNG = 36.4448417


def upgrade() -> None:
    with op.batch_alter_table("pricing_versions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "validated_by_id",
                sa.String(length=32),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("validation_note", sa.String(length=500), nullable=True))
        batch_op.create_index(batch_op.f("ix_pricing_versions_validated_by_id"), ["validated_by_id"])

    # Reuse the placeholder row where one exists so existing references stay valid, otherwise
    # insert the real dispatch point.
    connection = op.get_bind()
    updated = connection.execute(
        sa.text(
            "UPDATE delivery_origins SET name = :name, latitude = :lat, longitude = :lng, "
            "is_default = true, is_active = true WHERE name = :placeholder"
        ),
        {"name": _DISPATCH_NAME, "lat": _DISPATCH_LAT, "lng": _DISPATCH_LNG, "placeholder": _PLACEHOLDER_NAME},
    ).rowcount

    if not updated:
        exists = connection.execute(
            sa.text("SELECT 1 FROM delivery_origins WHERE name = :name"), {"name": _DISPATCH_NAME}
        ).first()
        if exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO delivery_origins "
                    "(id, name, latitude, longitude, is_default, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, :lat, :lng, true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": "orig_rims_dispatch_0000000000"[:32], "name": _DISPATCH_NAME, "lat": _DISPATCH_LAT, "lng": _DISPATCH_LNG},
            )

    # Exactly one default origin, always RIMs' real one.
    dispatch_id = connection.execute(
        sa.text("SELECT id FROM delivery_origins WHERE name = :name"), {"name": _DISPATCH_NAME}
    ).scalar()
    connection.execute(sa.text("UPDATE delivery_origins SET is_default = false WHERE id != :id"), {"id": dispatch_id})
    connection.execute(
        sa.text("UPDATE delivery_origins SET is_default = true WHERE id = :id"), {"id": dispatch_id}
    )

    # Keep the settings row that pins the dispatch origin pointing at the real point.
    if connection.execute(
        sa.text("SELECT 1 FROM system_settings WHERE key = 'default_origin_id'")
    ).first() is None:
        connection.execute(
            sa.text("INSERT INTO system_settings (key, value, updated_at) VALUES (:key, :value, CURRENT_TIMESTAMP)"),
            {"key": "default_origin_id", "value": json.dumps(dispatch_id)},
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE system_settings SET value = :value, updated_at = CURRENT_TIMESTAMP "
                "WHERE key = 'default_origin_id'"
            ),
            {"value": json.dumps(dispatch_id)},
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE delivery_origins SET is_default = false WHERE name = :name"), {"name": _DISPATCH_NAME}
    )
    connection.execute(
        sa.text(
            "UPDATE delivery_origins SET name = :placeholder, latitude = :lat, longitude = :lng, "
            "is_default = true WHERE name = :name"
        ),
        {
            "placeholder": _PLACEHOLDER_NAME,
            "name": _DISPATCH_NAME,
            "lat": -0.3031,
            "lng": 36.08,
        },
    )
    connection.execute(sa.text("DELETE FROM system_settings WHERE key = 'default_origin_id'"))

    with op.batch_alter_table("pricing_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pricing_versions_validated_by_id"))
        batch_op.drop_column("validation_note")
        batch_op.drop_column("validated_by_id")
        batch_op.drop_column("validated_at")
