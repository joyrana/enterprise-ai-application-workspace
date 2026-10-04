import type { Project, SpecRevision } from "../api/client";

export const project: Project = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Finance ops",
  description: "Adjustments and approvals",
  current_revision: 1,
  created_by: "demo-user",
  created_at: "2026-10-04T10:00:00Z",
  updated_at: "2026-10-04T10:00:00Z",
};

const unknownFact = {
  value: null,
  status: "unknown",
  provenance: null,
  confirmed_by: null,
  revision: { created_in: 1, updated_in: 1 },
};

export function specRevision(revision = 1): SpecRevision {
  return {
    project_id: project.id,
    revision,
    schema_version: "1.0.0",
    content_hash: "sha256:abcdef0123456789",
    change_summary: null,
    created_by: "demo-user",
    created_at: "2026-10-04T10:00:00Z",
    issues: [],
    summary: {
      facts: [{ path: "/objective", label: "Business objective", status: "unknown" }],
      collections: [{ name: "personas", label: "Personas", proposed: 0, confirmed: 0 }],
      open_questions: 0,
      blocking_questions: 0,
      confirmed_facts: 0,
      total_facts: 1,
    },
    spec: {
      metadata: { name: "Finance ops", description: null, tags: [] },
      objective: unknownFact,
      open_questions: [],
    },
  } as unknown as SpecRevision;
}
