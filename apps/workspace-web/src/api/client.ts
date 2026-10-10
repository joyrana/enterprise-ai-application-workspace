/**
 * Typed client for the workspace API.
 *
 * Types are derived from `schema.d.ts`, which is generated from the committed
 * OpenAPI document (`npm run gen:api`); CI fails if it drifts from the backend.
 * The backend stays authoritative for validation, permissions and revisions —
 * this module only transports requests and surfaces RFC 9457 problems.
 */
import type { paths } from "./schema";

type Json<T> = T extends { content: { "application/json": infer R } } ? R : never;

export type Project = Json<paths["/api/v1/projects/{project_id}"]["get"]["responses"][200]>;
export type ProjectPage = Json<paths["/api/v1/projects"]["get"]["responses"][200]>;
export type ProjectCreate = Json<NonNullable<paths["/api/v1/projects"]["post"]["requestBody"]>>;
export type SpecRevision = Json<paths["/api/v1/projects/{project_id}/spec"]["get"]["responses"][200]>;
export type SpecUpdate = Json<NonNullable<paths["/api/v1/projects/{project_id}/spec"]["put"]["requestBody"]>>;
export type ValidationResult = Json<paths["/api/v1/projects/{project_id}/spec/validate"]["post"]["responses"][200]>;
export type RevisionPage = Json<paths["/api/v1/projects/{project_id}/spec/revisions"]["get"]["responses"][200]>;
export type AuditPage = Json<paths["/api/v1/projects/{project_id}/audit"]["get"]["responses"][200]>;
export type ApplicationSpec = SpecRevision["spec"];
export type ApplicationSpecInput = SpecUpdate["spec"];

type RunPath = paths["/api/v1/projects/{project_id}/runs/{run_id}"];
type ApplyPath = paths["/api/v1/projects/{project_id}/runs/{run_id}/apply"];
export type AiStatus = Json<paths["/api/v1/ai/status"]["get"]["responses"][200]>;
export type Run = Json<RunPath["get"]["responses"][200]>;
export type RunPage = Json<paths["/api/v1/projects/{project_id}/runs"]["get"]["responses"][200]>;
export type SkillList = Json<paths["/api/v1/projects/{project_id}/skills"]["get"]["responses"][200]>;
export type SkillInfo = SkillList["items"][number];
export type Proposal = Run["proposals"][number];
export type ApplyRunRequest = Json<NonNullable<ApplyPath["post"]["requestBody"]>>;
export type ApplyRunResult = Json<ApplyPath["post"]["responses"][200]>;
export type DecisionValue = ApplyRunRequest["decisions"][number]["decision"];
export type SafetyScan = Json<paths["/api/v1/safety/scan"]["post"]["responses"][200]>;
export type RunSafety = NonNullable<Run["safety"]>;
type WorkflowPath = paths["/api/v1/projects/{project_id}/workflows/{workflow_id}"];
export type Workflow = Json<WorkflowPath["get"]["responses"][200]>;
export type WorkflowPage = Json<paths["/api/v1/projects/{project_id}/workflows"]["get"]["responses"][200]>;
export type WorkflowDefinitionList = Json<paths["/api/v1/workflow-definitions"]["get"]["responses"][200]>;
export type WorkflowDefinition = WorkflowDefinitionList["items"][number];
export type UiPreview = Json<paths["/api/v1/projects/{project_id}/ui"]["get"]["responses"][200]>;
export type RenderedScreen = UiPreview["rendered"][number];
export type RenderNode = RenderedScreen["root"][number];
export type UiIssue = UiPreview["issues"][number];
export type CodeManifest = Json<paths["/api/v1/projects/{project_id}/code"]["get"]["responses"][200]>;
export type CodeFile = Json<paths["/api/v1/projects/{project_id}/code/file"]["get"]["responses"][200]>;
export type CodeDiff = Json<paths["/api/v1/projects/{project_id}/code/diff"]["get"]["responses"][200]>;
export type Build = Json<paths["/api/v1/projects/{project_id}/builds/{build_id}"]["get"]["responses"][200]>;
export type BuildPage = Json<paths["/api/v1/projects/{project_id}/builds"]["get"]["responses"][200]>;
export type ImpactReport = Json<paths["/api/v1/projects/{project_id}/impact"]["post"]["responses"][200]>;
export type OrgPolicy = Json<paths["/api/v1/org/policies"]["get"]["responses"][200]>;
export type OrgPolicyUpdate = Json<NonNullable<paths["/api/v1/org/policies"]["put"]["requestBody"]>>;
export type OrgThemes = Json<paths["/api/v1/org/design-systems"]["get"]["responses"][200]>;
export type PolicyReport = Json<paths["/api/v1/projects/{project_id}/policy"]["get"]["responses"][200]>;
export type UpgradeResult = Json<paths["/api/v1/projects/{project_id}/code/upgrade"]["post"]["responses"][200]>;

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string | null;
  request_id?: string | null;
  errors?: { path: string; message: string; code?: string | null }[];
  extensions?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
  }

  get code(): string {
    return this.problem.type.replace(/^urn:workspace:error:/, "");
  }
}

/** Development identity. Replaced by a real identity provider before production use. */
export const devIdentity = {
  tenant: import.meta.env.VITE_DEV_TENANT ?? "demo",
  user: import.meta.env.VITE_DEV_USER ?? "demo-user",
  /** Development only: the demo user administers its organization (set VITE_DEV_ROLES="" to drop it). */
  roles: import.meta.env.VITE_DEV_ROLES ?? "org-admin",
};

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Raw request body (for example a zip upload) sent with `contentType` instead of JSON. */
  raw?: { body: Blob; contentType: string };
}

interface ApiResponse<T> {
  data: T;
  headers: Headers;
  status: number;
}

function isProblem(value: unknown): value is ProblemDetails {
  return typeof value === "object" && value !== null && "status" in value && "title" in value;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    Accept: "application/json, application/problem+json",
    "X-Dev-Tenant": devIdentity.tenant,
    "X-Dev-User": devIdentity.user,
    ...(devIdentity.roles ? { "X-Dev-Roles": devIdentity.roles } : {}),
    ...options.headers,
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.raw !== undefined) headers["Content-Type"] = options.raw.contentType;

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body:
        options.raw !== undefined
          ? options.raw.body
          : options.body === undefined
            ? undefined
            : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError({
      type: "urn:workspace:error:network",
      title: "Cannot reach the workspace API",
      status: 0,
      detail: "Check your connection and that the API is running, then try again.",
    });
  }

  const text = await response.text();
  let payload: unknown = undefined;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = undefined;
    }
  }
  if (!response.ok) {
    throw new ApiError(
      isProblem(payload)
        ? payload
        : {
            type: `urn:workspace:error:http-${response.status}`,
            title: response.statusText || "Request failed",
            status: response.status,
          },
    );
  }
  return { data: payload as T, headers: response.headers, status: response.status };
}

const enc = encodeURIComponent;

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  async listProjects(cursor?: string | null, signal?: AbortSignal): Promise<ProjectPage> {
    return (await request<ProjectPage>(`/api/v1/projects${query({ limit: 20, cursor })}`, { signal })).data;
  },

  async createProject(body: ProjectCreate, idempotencyKey: string): Promise<Project> {
    return (
      await request<Project>("/api/v1/projects", {
        method: "POST",
        body,
        headers: { "Idempotency-Key": idempotencyKey },
      })
    ).data;
  },

  async getProject(projectId: string, signal?: AbortSignal): Promise<Project> {
    return (await request<Project>(`/api/v1/projects/${enc(projectId)}`, { signal })).data;
  },

  async getSpec(projectId: string, signal?: AbortSignal): Promise<{ revision: SpecRevision; etag: string }> {
    const res = await request<SpecRevision>(`/api/v1/projects/${enc(projectId)}/spec`, { signal });
    return { revision: res.data, etag: res.headers.get("ETag") ?? `"r${res.data.revision}"` };
  },

  async saveSpec(
    projectId: string,
    body: SpecUpdate,
    etag: string,
  ): Promise<{ revision: SpecRevision; etag: string; created: boolean }> {
    const res = await request<SpecRevision>(`/api/v1/projects/${enc(projectId)}/spec`, {
      method: "PUT",
      body,
      headers: { "If-Match": etag },
    });
    return {
      revision: res.data,
      etag: res.headers.get("ETag") ?? `"r${res.data.revision}"`,
      created: res.headers.get("X-Revision-Created") !== "false",
    };
  },

  async getOrgPolicies(signal?: AbortSignal): Promise<OrgPolicy> {
    return (await request<OrgPolicy>("/api/v1/org/policies", { signal })).data;
  },

  async saveOrgPolicies(policy: unknown, version: number): Promise<OrgPolicy> {
    return (
      await request<OrgPolicy>("/api/v1/org/policies", {
        method: "PUT",
        body: { policy },
        headers: { "If-Match": `"v${version}"` },
      })
    ).data;
  },

  async getOrgThemes(signal?: AbortSignal): Promise<OrgThemes> {
    return (await request<OrgThemes>("/api/v1/org/design-systems", { signal })).data;
  },

  async saveOrgThemes(themes: unknown, version: number): Promise<OrgThemes> {
    return (
      await request<OrgThemes>("/api/v1/org/design-systems", {
        method: "PUT",
        body: { themes },
        headers: { "If-Match": `"v${version}"` },
      })
    ).data;
  },

  async getPolicyReport(projectId: string, signal?: AbortSignal): Promise<PolicyReport> {
    return (await request<PolicyReport>(`/api/v1/projects/${enc(projectId)}/policy`, { signal })).data;
  },

  async previewImpact(projectId: string, spec: unknown): Promise<ImpactReport> {
    return (await request<ImpactReport>(`/api/v1/projects/${enc(projectId)}/impact`, { method: "POST", body: spec }))
      .data;
  },

  async validateSpec(projectId: string, spec: unknown): Promise<ValidationResult> {
    return (
      await request<ValidationResult>(`/api/v1/projects/${enc(projectId)}/spec/validate`, {
        method: "POST",
        body: spec,
      })
    ).data;
  },

  async listRevisions(projectId: string, cursor?: string | null, signal?: AbortSignal): Promise<RevisionPage> {
    return (
      await request<RevisionPage>(`/api/v1/projects/${enc(projectId)}/spec/revisions${query({ limit: 20, cursor })}`, {
        signal,
      })
    ).data;
  },

  async getRevision(projectId: string, revision: number, signal?: AbortSignal): Promise<SpecRevision> {
    return (await request<SpecRevision>(`/api/v1/projects/${enc(projectId)}/spec/revisions/${revision}`, { signal }))
      .data;
  },

  async aiStatus(signal?: AbortSignal): Promise<AiStatus> {
    return (await request<AiStatus>("/api/v1/ai/status", { signal })).data;
  },

  async listRuns(projectId: string, signal?: AbortSignal): Promise<RunPage> {
    return (await request<RunPage>(`/api/v1/projects/${enc(projectId)}/runs`, { signal })).data;
  },

  async getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<Run> {
    return (await request<Run>(`/api/v1/projects/${enc(projectId)}/runs/${enc(runId)}`, { signal })).data;
  },

  async listWorkflowDefinitions(signal?: AbortSignal): Promise<WorkflowDefinitionList> {
    return (await request<WorkflowDefinitionList>("/api/v1/workflow-definitions", { signal })).data;
  },

  async listWorkflows(projectId: string, signal?: AbortSignal): Promise<WorkflowPage> {
    return (await request<WorkflowPage>(`/api/v1/projects/${enc(projectId)}/workflows`, { signal })).data;
  },

  async getWorkflow(projectId: string, workflowId: string, signal?: AbortSignal): Promise<Workflow> {
    return (await request<Workflow>(`/api/v1/projects/${enc(projectId)}/workflows/${enc(workflowId)}`, { signal }))
      .data;
  },

  async startWorkflow(
    projectId: string,
    definitionId: string,
    message: string,
    idempotencyKey: string,
  ): Promise<Workflow> {
    return (
      await request<Workflow>(`/api/v1/projects/${enc(projectId)}/workflows`, {
        method: "POST",
        body: { definition_id: definitionId, message },
        headers: { "Idempotency-Key": idempotencyKey },
      })
    ).data;
  },

  async resumeWorkflow(projectId: string, workflowId: string): Promise<Workflow> {
    return (
      await request<Workflow>(`/api/v1/projects/${enc(projectId)}/workflows/${enc(workflowId)}/resume`, {
        method: "POST",
      })
    ).data;
  },

  async cancelWorkflow(projectId: string, workflowId: string): Promise<Workflow> {
    return (
      await request<Workflow>(`/api/v1/projects/${enc(projectId)}/workflows/${enc(workflowId)}/cancel`, {
        method: "POST",
      })
    ).data;
  },

  async getUiPreview(projectId: string, signal?: AbortSignal): Promise<UiPreview> {
    return (await request<UiPreview>(`/api/v1/projects/${enc(projectId)}/ui`, { signal })).data;
  },

  async getCode(projectId: string, signal?: AbortSignal): Promise<CodeManifest> {
    return (await request<CodeManifest>(`/api/v1/projects/${enc(projectId)}/code`, { signal })).data;
  },

  async getCodeFile(projectId: string, path: string, revision: number, signal?: AbortSignal): Promise<CodeFile> {
    return (
      await request<CodeFile>(`/api/v1/projects/${enc(projectId)}/code/file${query({ path, revision })}`, { signal })
    ).data;
  },

  async getCodeDiff(projectId: string, from: number, to: number, signal?: AbortSignal): Promise<CodeDiff> {
    return (await request<CodeDiff>(`/api/v1/projects/${enc(projectId)}/code/diff${query({ from, to })}`, { signal }))
      .data;
  },

  /** Upload a hand-edited project zip; returns the per-file outcome and the upgraded zip (Milestone 5). */
  async upgradeCode(projectId: string, archive: Blob): Promise<UpgradeResult> {
    return (
      await request<UpgradeResult>(`/api/v1/projects/${enc(projectId)}/code/upgrade`, {
        method: "POST",
        raw: { body: archive, contentType: "application/zip" },
      })
    ).data;
  },

  async listBuilds(projectId: string, signal?: AbortSignal): Promise<BuildPage> {
    return (await request<BuildPage>(`/api/v1/projects/${enc(projectId)}/builds`, { signal })).data;
  },

  async requestBuild(projectId: string, revision: number): Promise<Build> {
    return (await request<Build>(`/api/v1/projects/${enc(projectId)}/builds${query({ revision })}`, { method: "POST" }))
      .data;
  },

  /** The zip needs the dev identity headers, so it is fetched rather than linked. */
  async downloadCode(projectId: string, revision: number): Promise<{ blob: Blob; filename: string }> {
    const response = await fetch(`${BASE}/api/v1/projects/${enc(projectId)}/code.zip${query({ revision })}`, {
      headers: { "X-Dev-Tenant": devIdentity.tenant, "X-Dev-User": devIdentity.user },
    });
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => undefined);
      throw new ApiError(
        isProblem(payload)
          ? payload
          : { type: `urn:workspace:error:http-${response.status}`, title: "Download failed", status: response.status },
      );
    }
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "generated-app.zip";
    return { blob: await response.blob(), filename };
  },

  async scanText(text: string, signal?: AbortSignal): Promise<SafetyScan> {
    return (await request<SafetyScan>("/api/v1/safety/scan", { method: "POST", body: { text }, signal })).data;
  },

  async listSkills(projectId: string, signal?: AbortSignal): Promise<SkillList> {
    return (await request<SkillList>(`/api/v1/projects/${enc(projectId)}/skills`, { signal })).data;
  },

  async startRun(projectId: string, message: string, skillId: string | null, idempotencyKey: string): Promise<Run> {
    return (
      await request<Run>(`/api/v1/projects/${enc(projectId)}/runs`, {
        method: "POST",
        body: skillId ? { message, skill_id: skillId } : { message },
        headers: { "Idempotency-Key": idempotencyKey },
      })
    ).data;
  },

  async applyRun(
    projectId: string,
    runId: string,
    body: ApplyRunRequest,
    etag: string,
  ): Promise<{ result: ApplyRunResult; etag: string }> {
    const res = await request<ApplyRunResult>(`/api/v1/projects/${enc(projectId)}/runs/${enc(runId)}/apply`, {
      method: "POST",
      body,
      headers: { "If-Match": etag },
    });
    return { result: res.data, etag: res.headers.get("ETag") ?? `"r${res.data.revision.revision}"` };
  },

  async listAudit(projectId: string, cursor?: string | null, signal?: AbortSignal): Promise<AuditPage> {
    return (
      await request<AuditPage>(`/api/v1/projects/${enc(projectId)}/audit${query({ limit: 50, cursor })}`, { signal })
    ).data;
  },
};
