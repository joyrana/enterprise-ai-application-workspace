"""Print status, routing and errors of recent AI runs (E2E failure diagnostics; no secrets involved)."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
HEADERS = {"X-Dev-Tenant": "demo", "X-Dev-User": "demo-user"}


def get(path: str) -> dict:  # type: ignore[type-arg]
    request = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed local URL
        return json.loads(response.read())  # type: ignore[no-any-return]


for project in get("/projects?limit=5")["items"]:
    for run in get(f"/projects/{project['id']}/runs")["items"][:3]:
        print(
            json.dumps(
                {
                    "project": project["name"],
                    "status": run["status"],
                    "skill": run["skill_id"],
                    "routing": run["routing"],
                    "error": run["error"],
                    "summary": run["summary"],
                    "not_applicable": run["not_applicable_reason"],
                    "proposals": len(run["proposals"]),
                }
            )
        )
