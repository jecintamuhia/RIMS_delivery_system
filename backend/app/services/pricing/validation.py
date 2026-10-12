"""Pricing version validation.

The gate between *imported* and *customer-facing*. RIMs sends a spreadsheet; this decides whether
what arrived is safe to show to a customer as a delivery fee.

Two severities, because they mean different things to the business:

* ``error``   - activating would put a wrong or unpriceable price in front of customers, so
                activation is blocked.
* ``warning`` - activation is safe, but an administrator should look before the next price
                change. A destination with no coordinates still prices correctly when the
                geocoder names it exactly, so it must not stop RIMs trading; it does mean that
                destination cannot be resolved from a map pin.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Destination, PricingVersion

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

#: Name characters that do not appear in Kenyan place names. RIMs' own price list contains one
#: such name; it is reported here, never rewritten.
_NAME_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -/'&.()")

#: Names too generic to identify a single place. Reported for confirmation; a matching failure at
#: quote time is what proves it wrong.
_VAGUE_NAMES = frozenset({"TOWN AREA", "JUNCTION", "FLYOVER", "VI", "DCK", "MAIN", "OTHER"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem, warning, or review item found in a pricing version."""

    code: str
    severity: str
    message: str
    destination_name: str | None = None
    rule_id: str | None = None

    @property
    def blocks_activation(self) -> bool:
        return self.severity == SEVERITY_ERROR


@dataclass(slots=True)
class ValidationReport:
    """Verdict for one version. ``valid`` means "nothing blocks activation"."""

    version_id: str
    label: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    rule_count: int = 0
    destination_count: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == SEVERITY_WARNING]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def summary(self) -> str:
        if self.errors:
            return f"{len(self.errors)} problem(s) must be fixed before this version can be activated."
        if self.warnings:
            return (
                f"{self.rule_count} rule(s) across {self.destination_count} destination(s) can be "
                f"activated. {len(self.warnings)} item(s) need review."
            )
        return f"{self.rule_count} rule(s) across {self.destination_count} destination(s) can be activated."


def _has_geography(destination: Destination) -> bool:
    return (
        (destination.latitude is not None and destination.longitude is not None)
        or bool(destination.boundary)
        or destination.catchment_radius_km is not None
    )


async def _load_destinations(
    session: AsyncSession, destination_ids: Sequence[str]
) -> dict[str, Destination]:
    unique = set(destination_ids)
    if not unique:
        return {}
    rows = (await session.scalars(select(Destination).where(Destination.id.in_(unique)))).all()
    return {row.id: row for row in rows}


async def validate_version(session: AsyncSession, version: PricingVersion) -> ValidationReport:
    """Check that ``version`` is safe to activate. Read-only: nothing is written."""
    rules = list(version.rules)
    findings: list[Finding] = []

    if not rules:
        findings.append(
            Finding(
                code="no_rules",
                severity=SEVERITY_ERROR,
                message=(
                    f"Pricing version “{version.label}” has no rules, so every quote would be "
                    "unpriced. Import a price list first."
                ),
            )
        )

    destinations = await _load_destinations(session, [rule.destination_id for rule in rules])
    priced: set[str] = set()

    for rule in rules:
        destination = destinations.get(rule.destination_id)
        name = destination.name if destination is not None else None

        if destination is None:
            findings.append(
                Finding(
                    code="destination_missing",
                    severity=SEVERITY_ERROR,
                    message="A rule points at a destination that no longer exists.",
                    rule_id=rule.id,
                )
            )
        elif destination.id in priced:
            findings.append(
                Finding(
                    code="duplicate_destination_price",
                    severity=SEVERITY_ERROR,
                    message=(
                        f"{destination.name} has more than one rule in this version, so which "
                        "price applies is ambiguous. RIMs quotes one fixed price per destination."
                    ),
                    destination_name=destination.name,
                    rule_id=rule.id,
                )
            )
        else:
            priced.add(destination.id)

        if rule.base_price < 0:
            findings.append(
                Finding(
                    code="negative_price",
                    severity=SEVERITY_ERROR,
                    message="A rule has a negative price.",
                    destination_name=name,
                    rule_id=rule.id,
                )
            )

        # Flag only rules that can *never* apply. A future-dated price inside the version's window
        # is deliberate and valid.
        version_end = version.effective_to
        rule_ends = rule.effective_to or rule.effective_from
        can_never_apply = rule_ends < version.effective_from or (
            version_end is not None and rule.effective_from > version_end
        )
        if can_never_apply:
            findings.append(
                Finding(
                    code="rule_outside_version_window",
                    severity=SEVERITY_ERROR,
                    message="A rule's effective dates fall outside the version's window.",
                    destination_name=name,
                    rule_id=rule.id,
                )
            )

    for destination in sorted(destinations.values(), key=lambda row: row.name):
        if not _has_geography(destination):
            findings.append(
                Finding(
                    code="no_geography",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"{destination.name} has no coordinates, boundary or catchment, so it can "
                        "only be matched when the address search returns this exact name."
                    ),
                    destination_name=destination.name,
                )
            )

        unusual = "".join(sorted({char for char in destination.name if char not in _NAME_ALLOWED}))
        if unusual:
            findings.append(
                Finding(
                    code="unusual_destination_name",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"{destination.name} contains {unusual!r}. RIMs' price list uses this "
                        "spelling; confirm it before it goes live."
                    ),
                    destination_name=destination.name,
                )
            )

        if destination.name.strip().upper() in _VAGUE_NAMES:
            findings.append(
                Finding(
                    code="vague_destination_name",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"“{destination.name}” does not identify one place on its own. Confirm "
                        "which place it means and add coordinates so map pins resolve to it."
                    ),
                    destination_name=destination.name,
                )
            )

    if len(version.currency or "") != 3:
        findings.append(
            Finding(
                code="invalid_currency",
                severity=SEVERITY_ERROR,
                message="The version currency must be a three-letter code.",
            )
        )

    return ValidationReport(
        version_id=version.id,
        label=version.label,
        status=version.status.value,
        findings=findings,
        rule_count=len(rules),
        destination_count=len(priced),
    )
