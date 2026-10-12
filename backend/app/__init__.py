"""RIMs delivery pricing API.

Layering, outermost first:

* ``app.api`` - HTTP surface (public endpoints, session auth, admin area).
* ``app.services`` - business logic; the only layer allowed to orchestrate the others.
* ``app.models`` - ORM models and enums.
* ``app.providers`` - external geocoding/routing adapters behind a protocol.
* ``app.cli`` - operational entry points.
"""
