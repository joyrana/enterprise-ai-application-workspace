"""Load demo data: one project in tenant ``demo`` with the finance-operations example spec.

Idempotent: re-running does not create duplicates.
Usage: ``DATABASE_URL=... uv run python -m workspace_api.seed``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from appspec import load_spec

from . import service
from .auth import Principal
from .config import get_settings
from .db import Database
from .schemas import ProjectCreate, SpecUpdate

EXAMPLE = Path(__file__).resolve().parents[4] / "packages" / "application-spec" / "examples" / "finance-operations.json"
DEMO = Principal(tenant_id="demo", user_id="demo-user")


def main() -> int:
    spec = load_spec(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    db = Database(get_settings().database_url)
    try:
        session = next(db.session())
        created = service.create_project(
            session,
            DEMO,
            ProjectCreate(name=spec.metadata.name, description=spec.metadata.description),
            idempotency_key="seed-finance-operations-v1",
        )
        project = created.project
        if project.current_revision == 1:
            service.update_spec(session, DEMO, project.id, '"r1"', SpecUpdate(spec=spec, change_summary="Seed data"))
        print(f"Demo project {project.id} ready (tenant 'demo', user 'demo-user').")
    finally:
        db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
