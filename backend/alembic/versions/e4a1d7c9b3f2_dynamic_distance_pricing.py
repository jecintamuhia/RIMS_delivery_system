"""dynamic distance pricing

Adds model B of the pricing architecture: road distance multiplied by a configured,
versioned rate. It lives in its own table so a change to the distance rate can never rewrite
RIMs' official fixed destination price list, and so every quote records which of the two
models priced it.

Also records the *how* of each price on ``quote_calculations`` (``pricing_model`` and, for
distance-based amounts, the full audit record: distance, base rate, fuel adjustment,
effective rate and total), which is what lets the customer-facing quote state its own
arithmetic instead of implying a fixed official price it did not come from.

Existing rows are classified honestly: every already-priced quote and calculation was priced
from the fixed price list, because distance pricing did not exist when they were written.

Revision ID: e4a1d7c9b3f2
Revises: b7c41e9a2f60
Create Date: 2026-10-08 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4a1d7c9b3f2"
down_revision: str | None = "b7c41e9a2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dynamic_pricing_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("base_rate_per_km", sa.Numeric(12, 2), nullable=False),
        sa.Column("fuel_adjustment_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("min_charge", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(length=32), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "base_rate_per_km > 0",
            name=op.f("ck_dynamic_pricing_versions_dynamic_base_rate_positive"),
        ),
        sa.CheckConstraint(
            "min_charge IS NULL OR min_charge >= 0",
            name=op.f("ck_dynamic_pricing_versions_dynamic_min_charge_non_negative"),
        ),
        sa.CheckConstraint(
            "fuel_adjustment_percent >= -100 AND fuel_adjustment_percent <= 1000",
            name=op.f("ck_dynamic_pricing_versions_dynamic_fuel_adjustment_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_dynamic_pricing_versions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dynamic_pricing_versions")),
        sa.UniqueConstraint("label", name=op.f("uq_dynamic_pricing_versions_label")),
    )
    op.create_index(
        op.f("ix_dynamic_pricing_versions_created_by_id"),
        "dynamic_pricing_versions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_dynamic_pricing_versions_status", "dynamic_pricing_versions", ["status", "activated_at"]
    )

    # Which model priced this quote. NULL only for a quote that never reached a price.
    with op.batch_alter_table("quotes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pricing_model", sa.String(length=24), nullable=True))
    op.execute(
        "UPDATE quotes SET pricing_model = 'fixed_destination' WHERE fee_amount IS NOT NULL"
    )

    with op.batch_alter_table("quote_calculations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "pricing_model",
                sa.String(length=24),
                nullable=False,
                server_default=sa.text("'fixed_destination'"),
            )
        )
        batch_op.add_column(sa.Column("dynamic_pricing_version_id", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("pricing_details", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_quote_calculations_dynamic_pricing_version_id_dynamic_pricing_versions"),
            "dynamic_pricing_versions",
            ["dynamic_pricing_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("quote_calculations", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("fk_quote_calculations_dynamic_pricing_version_id_dynamic_pricing_versions"),
            type_="foreignkey",
        )
        batch_op.drop_column("pricing_details")
        batch_op.drop_column("dynamic_pricing_version_id")
        batch_op.drop_column("pricing_model")

    with op.batch_alter_table("quotes", schema=None) as batch_op:
        batch_op.drop_column("pricing_model")

    op.drop_index("ix_dynamic_pricing_versions_status", table_name="dynamic_pricing_versions")
    op.drop_index(
        op.f("ix_dynamic_pricing_versions_created_by_id"), table_name="dynamic_pricing_versions"
    )
    op.drop_table("dynamic_pricing_versions")
