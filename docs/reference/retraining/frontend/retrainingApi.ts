// 配置先: frontend/src/api/retrainingApi.ts
// 再学習ワークフローの API クライアント（型 + fetch ラッパ）。
// バックエンド: api/retraining_endpoint.py（/api/retraining/...）。Basic 認証はブラウザ資格情報で通す前提。

// ---- 型（schemas/retraining.py と対応） ----

export type JobStatus =
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface FullTuple {
  color_no: string;
  size: string;
  chain: string;
  tape: string; // 基本空白だがキーの一部
}

export interface JobCreateRequest extends FullTuple {
  created_by?: string | null;
}

export interface Job extends FullTuple {
  id: number;
  status: JobStatus;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  onnx_monochro_path: string | null;
  onnx_color_path: string | null;
  created_by: string | null;
}

export interface JobList {
  items: Job[];
  limit: number;
  offset: number;
}

export type DeployStatus = "SUCCESS" | "PARTIAL" | "FAILED";

export interface DeployedModel extends FullTuple {
  id: number;
  job_id: number;
  onnx_monochro_path: string | null;
  onnx_color_path: string | null;
  deploy_status: DeployStatus;
  deployed_at: string;
}

export interface CancelResult {
  job_id: number;
  accepted: boolean;
}

export interface DeployResult {
  job_id: number;
  status: DeployStatus;
  detail: Record<string, { ok: boolean; errors: string[] }>;
  edge_pc_count: number;
}

// ---- 基盤 ----

const BASE = (import.meta as any).env?.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include", // Basic 認証セッション
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* noop */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// ---- エンドポイント ----

export function listJobs(params?: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}): Promise<JobList> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request<JobList>(`/api/retraining/jobs${qs ? `?${qs}` : ""}`);
}

export function getJob(id: number): Promise<Job> {
  return request<Job>(`/api/retraining/jobs/${id}`);
}

export function createJob(body: JobCreateRequest): Promise<Job> {
  return request<Job>(`/api/retraining/jobs`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cancelJob(id: number): Promise<CancelResult> {
  return request<CancelResult>(`/api/retraining/jobs/${id}/cancel`, {
    method: "POST",
  });
}

export function listDeployed(): Promise<DeployedModel[]> {
  return request<DeployedModel[]>(`/api/retraining/deployed`);
}

export function deployJob(id: number): Promise<DeployResult> {
  return request<DeployResult>(`/api/retraining/jobs/${id}/deploy`, {
    method: "POST",
  });
}

// 進捗 WebSocket の URL を組み立てる（素通しの行テキストを受信）。
export function progressWsUrl(id: number): string {
  const httpBase = BASE || window.location.origin;
  const wsBase = httpBase.replace(/^http/, "ws");
  return `${wsBase}/api/retraining/jobs/${id}/progress`;
}

export const TERMINAL: JobStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];
export const isTerminal = (s: JobStatus): boolean => TERMINAL.includes(s);
