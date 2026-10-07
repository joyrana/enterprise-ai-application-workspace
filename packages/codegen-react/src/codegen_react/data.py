"""Data layer for generated apps: entity types, stores, and an OpenAPI contract for a real backend.

Generated apps keep records in the browser (localStorage, falling back to memory)
behind a ``Store`` interface, so they work immediately and can be pointed at a
backend later. ``api/openapi.json`` describes that backend's contract, derived
from the same entities. Entity and field names only ever appear as string
literals; TypeScript identifiers are derived from validated ids.
"""

from __future__ import annotations

import json
from typing import Literal

from appspec import ApplicationSpec
from appspec.model import DataEntity, FieldType

from .jsx import literal

ValueKind = Literal["string", "number", "boolean", "file"]

_KIND: dict[FieldType, ValueKind] = {
    FieldType.INTEGER: "number",
    FieldType.DECIMAL: "number",
    FieldType.MONEY: "number",
    FieldType.BOOLEAN: "boolean",
    FieldType.FILE: "file",
}

_TS = {"string": "string", "number": "number", "boolean": "boolean", "file": "string"}


def value_kind(field_type: FieldType) -> ValueKind:
    return _KIND.get(field_type, "string")


def type_name(entity_id: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in entity_id.split("-") if p)


STORE_TS = """import { useSyncExternalStore } from "react";

export interface Entity {
  id: string;
}

/** Where records live. Replace createLocalStore with a client for the API in api/openapi.json. */
export interface Store<T extends Entity> {
  list(): readonly T[];
  create(values: Omit<T, "id">): T;
  subscribe(listener: () => void): () => void;
}

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Keeps records in this browser (localStorage when available, otherwise in memory). */
export function createLocalStore<T extends Entity>(key: string): Store<T> {
  const storageKey = `generated-app:${key}`;
  let items: readonly T[] = [];
  try {
    const saved = window.localStorage.getItem(storageKey);
    if (saved) items = JSON.parse(saved) as T[];
  } catch {
    items = [];
  }
  const listeners = new Set<() => void>();
  return {
    list: () => items,
    create(values) {
      const record = { ...values, id: newId() } as T;
      items = [...items, record];
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(items));
      } catch {
        // Storage unavailable (private mode, quota): keep the record in memory.
      }
      listeners.forEach((listener) => listener());
      return record;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useEntityList<T extends Entity>(store: Store<T>): readonly T[] {
  return useSyncExternalStore(store.subscribe, store.list, store.list);
}
"""


def entities_ts(spec: ApplicationSpec, header: str) -> str:
    if not spec.entities:
        return header + "\n// No data entities are specified yet.\nexport const stores = {};\n"
    lines = [header.rstrip("\n"), "", 'import { createLocalStore, type Entity } from "./store";', ""]
    for entity in spec.entities:
        lines.append(f"/** {type_name(entity.id)}: generated from entity {literal(entity.id)}. */")
        lines.append(f"export interface {type_name(entity.id)} extends Entity {{")
        for field in entity.fields:
            ts = _TS[value_kind(field.type)]
            lines.append(f"  {literal(field.name)}: {ts}{'' if field.required else ' | null'};")
        lines.append("}")
        lines.append("")
    store_entries = [f"  {literal(e.id)}: createLocalStore<{type_name(e.id)}>({literal(e.id)})," for e in spec.entities]
    lines += ["export const stores = {", *store_entries, "};", ""]
    lines.append("export type EntityName = keyof typeof stores;")
    lines.append("")
    kinds = []
    for entity in spec.entities:
        entries = ", ".join(f"{literal(f.name)}: {literal(value_kind(f.type))}" for f in entity.fields)
        kinds.append(f"  {literal(entity.id)}: {{ {entries} }},")
    lines += [
        'const FIELD_KINDS: Record<EntityName, Record<string, "string" | "number" | "boolean" | "file">> = {',
        *kinds,
        "};",
        "",
    ]
    lines.append(_HELPERS)
    return "\n".join(lines)


_HELPERS = """/** Converts submitted form data to a typed record and stores it. */
export function saveRecord(entity: EntityName, data: FormData): void {
  const record: Record<string, string | number | boolean | null> = {};
  for (const [name, kind] of Object.entries(FIELD_KINDS[entity])) {
    const raw = data.get(name);
    if (kind === "boolean") record[name] = raw !== null;
    else if (raw instanceof File) record[name] = raw.name || null;
    else if (raw === null || raw === "") record[name] = null;
    else if (kind === "number") record[name] = Number(raw);
    else record[name] = raw;
  }
  (stores[entity] as unknown as { create(values: object): unknown }).create(record);
}

/** A short human label for a record: its first non-empty field, or a shortened id. */
export function displayName(entity: EntityName, record: Entity): string {
  const values = record as unknown as Record<string, unknown>;
  for (const name of Object.keys(FIELD_KINDS[entity])) {
    const value = values[name];
    if (value !== null && value !== undefined && value !== "") return formatValue(value);
  }
  return record.id.slice(0, 8);
}

export function displayRef(entity: EntityName, id: unknown): string {
  if (typeof id !== "string" || !id) return "—";
  const match = (stores[entity].list() as readonly Entity[]).find((r) => r.id === id);
  return match ? displayName(entity, match) : id.slice(0, 8);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}
"""


_OPENAPI_TYPE = {
    FieldType.INTEGER: {"type": "integer"},
    FieldType.DECIMAL: {"type": "number"},
    FieldType.MONEY: {"type": "number"},
    FieldType.BOOLEAN: {"type": "boolean"},
    FieldType.DATE: {"type": "string", "format": "date"},
    FieldType.DATETIME: {"type": "string", "format": "date-time"},
    FieldType.FILE: {"type": "string", "description": "File name or storage reference."},
}


def _schema(entity: DataEntity) -> dict[str, object]:
    properties: dict[str, object] = {"id": {"type": "string", "readOnly": True}}
    for field in entity.fields:
        prop: dict[str, object] = dict(_OPENAPI_TYPE.get(field.type, {"type": "string"}))
        if field.type is FieldType.ENUM and field.enum_values:
            prop["enum"] = list(field.enum_values)
        if field.type is FieldType.REFERENCE and field.reference_entity_id:
            prop["description"] = f"Id of a {field.reference_entity_id} record."
        if field.description:
            prop["description"] = field.description
        if not field.required:
            prop = {"anyOf": [prop, {"type": "null"}]}
        properties[field.name] = prop
    return {
        "type": "object",
        "title": entity.name,
        "properties": properties,
        "required": ["id", *[f.name for f in entity.fields if f.required]],
        "additionalProperties": False,
    }


def openapi_json(spec: ApplicationSpec, generator: str, spec_revision: int | None) -> str:
    paths: dict[str, object] = {}
    schemas: dict[str, object] = {}
    for entity in spec.entities:
        name = type_name(entity.id)
        ref = {"$ref": f"#/components/schemas/{name}"}
        schemas[name] = _schema(entity)
        paths[f"/{entity.id}"] = {
            "get": {
                "operationId": f"list{name}",
                "summary": f"List {entity.name} records",
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {"application/json": {"schema": {"type": "array", "items": ref}}},
                    }
                },
            },
            "post": {
                "operationId": f"create{name}",
                "summary": f"Create a {entity.name} record",
                "requestBody": {"required": True, "content": {"application/json": {"schema": ref}}},
                "responses": {"201": {"description": "Created", "content": {"application/json": {"schema": ref}}}},
            },
        }
        paths[f"/{entity.id}/{{id}}"] = {
            "get": {
                "operationId": f"get{name}",
                "summary": f"Get one {entity.name} record",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "OK", "content": {"application/json": {"schema": ref}}},
                    "404": {"description": "Not found"},
                },
            }
        }
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{spec.metadata.name} data API",
            "version": f"r{spec_revision}" if spec_revision is not None else "unsaved",
            "description": f"Contract for the backend of the generated app ({generator}). Derived from the spec's "
            "data entities; the generated app uses an in-browser store until a backend implements this.",
        },
        "paths": paths,
        "components": {"schemas": schemas},
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
