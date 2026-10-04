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
};

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
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
    ...options.headers,
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
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

  async listAudit(projectId: string, cursor?: string | null, signal?: AbortSignal): Promise<AuditPage> {
    return (
      await request<AuditPage>(`/api/v1/projects/${enc(projectId)}/audit${query({ limit: 50, cursor })}`, { signal })
    ).data;
  },
};
