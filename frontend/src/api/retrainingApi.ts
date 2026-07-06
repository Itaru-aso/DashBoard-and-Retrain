import { apiClient } from "./client";

// 型（backend の schemas/retraining.py と対応）。

export type JobStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

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
  detail: string;
  edge_pc_count: number;
}

export async function listJobs(params?: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}): Promise<JobList> {
  const { data } = await apiClient.get<JobList>("/retraining/jobs", { params });
  return data;
}

export async function getJob(id: number): Promise<Job> {
  const { data } = await apiClient.get<Job>(`/retraining/jobs/${id}`);
  return data;
}

export async function createJob(body: JobCreateRequest): Promise<Job> {
  const { data } = await apiClient.post<Job>("/retraining/jobs", body);
  return data;
}

export async function cancelJob(id: number): Promise<CancelResult> {
  const { data } = await apiClient.post<CancelResult>(`/retraining/jobs/${id}/cancel`);
  return data;
}

export async function listDeployed(): Promise<DeployedModel[]> {
  const { data } = await apiClient.get<DeployedModel[]>("/retraining/deployed");
  return data;
}

export async function deployJob(id: number): Promise<DeployResult> {
  const { data } = await apiClient.post<DeployResult>(`/retraining/jobs/${id}/deploy`);
  return data;
}

/** 進捗 WebSocket の URL を組み立てる（素通しの行テキストを受信）。 */
export function progressWsUrl(id: number): string {
  const wsBase = window.location.origin.replace(/^http/, "ws");
  return `${wsBase}/api/retraining/jobs/${id}/progress`;
}

export const TERMINAL: JobStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];
export const isTerminal = (s: JobStatus): boolean => TERMINAL.includes(s);
