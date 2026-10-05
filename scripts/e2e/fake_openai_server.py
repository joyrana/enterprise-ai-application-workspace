"""Scripted OpenAI-compatible chat-completions server for end-to-end tests.

It lets the E2E suite exercise the real path — browser → API → background run →
``OpenAICompatibleProvider`` over HTTP → JSON extraction and validation — with
deterministic answers. It recognises which skill is calling from the system
prompt and answers that skill's schema. It is never used to report model quality.

Usage: ``python scripts/e2e/fake_openai_server.py --port 9100``
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_REQ_ID = re.compile(r"- id: ([a-z][a-z0-9-]*) \|")
_REQ = re.compile(r'- id: ([a-z][a-z0-9-]*) \| title: "([^"]+)"')
_ENTITY = re.compile(r'- id: ([a-z][a-z0-9-]*) \| name: "([^"]+)" \| fields:')


def _user_message(text: str) -> str:
    match = re.search(r"<user_(?:message|description)>\n(.*?)\n</user_(?:message|description)>", text, re.DOTALL)
    return match.group(1).lower() if match else ""


def answer(system: str, user: str) -> dict[str, Any]:
    if "You route a person's request" in system:
        message = _user_message(user)
        if any(w in message for w in ("acceptance", "test", "verify")):
            skill = "acceptance-criteria"
        elif any(w in message for w in ("conflict", "contradict", "duplicate")):
            skill = "requirements-conflict-detection"
        elif any(w in message for w in ("screen", "page", "layout", "interface")):
            skill = "screen-design"
        elif any(w in message for w in ("weather", "poem")):
            skill = "none"
        else:
            skill = "business-discovery"
        return {"skill_id": skill, "confidence": 0.9, "rationale": f"Scripted E2E routing to {skill}."}
    if "business-discovery step" in system and "root administrator" in _user_message(user):
        # Plays a model that followed injected text (as qwen3:4b-instruct did in run 37209762015),
        # so the E2E suite can check that echoing proposals are marked and start as Reject.
        return {
            "is_application_request": True,
            "objective": "Track which laptops each employee has.",
            "personas": [{"name": "Root Administrator", "goals": []}, {"name": "IT technician", "goals": []}],
            "requirements": [{"title": "Record laptop assignments", "priority": "must", "persona_names": []}],
            "open_questions": [],
            "assumptions": [],
        }
    if "business-discovery step" in system:
        return {
            "is_application_request": True,
            "application_type": "Internal operations tool",
            "domain": "Finance operations",
            "objective": "Reduce manual effort for adjustments and approvals.",
            "personas": [
                {"name": "Operations analyst", "goals": ["Configure adjustments"]},
                {"name": "Finance approver", "goals": ["Approve risky transactions"]},
            ],
            "requirements": [
                {"title": "Configure adjustment rules", "priority": "must", "persona_names": ["Operations analyst"]},
                {"title": "Approve risky transactions", "priority": "must", "persona_names": ["Finance approver"]},
            ],
            "open_questions": [{"question": "What risk score requires approval?", "blocking": True}],
            "assumptions": ["Source files arrive daily"],
        }
    if "You write acceptance criteria" in system:
        ids = _REQ_ID.findall(user)
        return {
            "criteria": [
                {
                    "requirement_id": rid,
                    "given": "an authorised user",
                    "when": f"they complete {rid.replace('-', ' ')}",
                    "then": "the result is saved and visible",
                }
                for rid in ids
            ]
        }
    if "You design the screens" in system:
        requirements = _REQ.findall(user.split("<requirements>")[1].split("</requirements>")[0])
        entities = _ENTITY.findall(user.split("<entities>")[1].split("</entities>")[0])
        screens = []
        for rid, title in requirements:
            components: list[dict[str, Any]] = (
                [{"kind": "table", "label": f"{entities[0][1]} list", "entity_id": entities[0][0]}]
                if entities
                else [{"kind": "text", "label": f"Work area for: {title}"}]
            )
            screens.append(
                {
                    "name": f"{title} screen",
                    "purpose": f"Lets people {title.lower()}.",
                    "requirement_ids": [rid],
                    "components": components,
                    "states": ["loading", "empty"],
                }
            )
        return {"screens": screens}
    if "for conflicts" in system:
        return {"conflicts": []}
    return {"error": "unrecognised prompt"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = json.dumps(answer(system, user))
        payload = {
            "id": "chatcmpl-e2e",
            "object": "chat.completion",
            "model": body.get("model", "fake-e2e"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
