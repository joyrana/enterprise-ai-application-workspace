"""In-memory backend that follows a generated app's ``api/openapi.json`` (for end-to-end tests only).

Generated apps built with ``VITE_DATA_API_URL`` talk to a backend over the contract the
generator writes next to them (ADR-0014). CI starts this server with that contract and runs
the generated app's browser tests against it, so the HTTP store is exercised end to end.

It serves only the collections the contract lists, checks request bodies against each
schema's properties and required fields, and keeps records in memory. It has no
authentication and is not a product backend.

Usage: ``python scripts/e2e/fake_data_api.py --contract path/to/api/openapi.json --port 4310``
"""

from __future__ import annotations

import argparse
import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_BODY = 64 * 1024


class Contract:
    def __init__(self, document: dict[str, Any]) -> None:
        self.schemas: dict[str, dict[str, Any]] = {}
        for path, operations in document.get("paths", {}).items():
            parts = path.strip("/").split("/")
            if len(parts) != 1 or "post" not in operations:
                continue
            ref = operations["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            self.schemas[parts[0]] = document["components"]["schemas"][ref.rsplit("/", 1)[1]]

    def problems(self, collection: str, body: object) -> list[str]:
        if not isinstance(body, dict):
            return ["The body must be a JSON object."]
        schema = self.schemas[collection]
        known = set(schema.get("properties", {}))
        out = [f"Unknown field {name!r}." for name in sorted(set(body) - known)]
        out += [f"Missing field {name!r}." for name in schema.get("required", []) if name != "id" and name not in body]
        return out


class Handler(BaseHTTPRequestHandler):
    contract: Contract
    records: dict[str, dict[str, dict[str, Any]]]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.command} {self.path} -> {format % args}", flush=True)

    def _send(self, status: int, payload: object | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> tuple[str, str | None] | None:
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if parts[0] not in self.contract.schemas or len(parts) > 2:
            return None
        return parts[0], parts[1] if len(parts) == 2 else None

    def _body(self) -> object:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("The body is too large.")
        return json.loads(self.rfile.read(length) or b"null")

    def do_OPTIONS(self) -> None:
        self._send(204)

    def do_GET(self) -> None:
        route = self._route()
        if route is None:
            return self._send(404, {"detail": "Not found"})
        collection, record_id = route
        items = self.records.setdefault(collection, {})
        if record_id is None:
            return self._send(200, list(items.values()))
        if record_id not in items:
            return self._send(404, {"detail": "Not found"})
        return self._send(200, items[record_id])

    def _write(self, collection: str, record_id: str, created: bool) -> None:
        try:
            body = self._body()
        except ValueError as error:
            return self._send(400, {"detail": str(error)})
        problems = self.contract.problems(collection, body)
        if problems:
            return self._send(422, {"detail": problems})
        assert isinstance(body, dict)
        record = {**body, "id": record_id}
        self.records.setdefault(collection, {})[record_id] = record
        return self._send(201 if created else 200, record)

    def do_POST(self) -> None:
        route = self._route()
        if route is None or route[1] is not None:
            return self._send(404, {"detail": "Not found"})
        return self._write(route[0], str(uuid.uuid4()), created=True)

    def do_PUT(self) -> None:
        route = self._route()
        if route is None or route[1] is None or route[1] not in self.records.get(route[0], {}):
            return self._send(404, {"detail": "Not found"})
        return self._write(route[0], route[1], created=False)

    def do_DELETE(self) -> None:
        route = self._route()
        if route is None or route[1] is None or route[1] not in self.records.get(route[0], {}):
            return self._send(404, {"detail": "Not found"})
        del self.records[route[0]][route[1]]
        return self._send(204)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4310)
    args = parser.parse_args()
    Handler.contract = Contract(json.loads(args.contract.read_text(encoding="utf-8")))
    Handler.records = {}
    print(f"Serving {sorted(Handler.contract.schemas)} on http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
