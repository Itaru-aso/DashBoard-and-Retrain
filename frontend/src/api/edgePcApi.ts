import { apiClient } from "./client";

export interface EdgePc {
  id: number;
  name: string;
  host: string;
  username: string | null;
  password: string | null;
  model_port: number | null;
  enabled: boolean;
  last_ftp_ok: boolean | null;
  last_ftp_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface EdgePcCreatePayload {
  name: string;
  host: string;
  username?: string;
  password?: string;
  model_port?: number;
  enabled?: boolean;
}

export interface EdgePcUpdatePayload {
  name?: string;
  host?: string;
  username?: string;
  password?: string;
  model_port?: number;
  enabled?: boolean;
}

export async function listEdgePcs(): Promise<EdgePc[]> {
  const { data } = await apiClient.get<EdgePc[]>("/edge-pcs");
  return data;
}

export async function createEdgePc(payload: EdgePcCreatePayload): Promise<EdgePc> {
  const { data } = await apiClient.post<EdgePc>("/edge-pcs", payload);
  return data;
}

export async function updateEdgePc(
  id: number,
  payload: EdgePcUpdatePayload,
): Promise<EdgePc> {
  const { data } = await apiClient.patch<EdgePc>(`/edge-pcs/${id}`, payload);
  return data;
}

export async function deleteEdgePc(id: number): Promise<void> {
  await apiClient.delete(`/edge-pcs/${id}`);
}

export async function checkFtp(id: number): Promise<EdgePc> {
  const { data } = await apiClient.post<EdgePc>(`/edge-pcs/${id}/check-ftp`);
  return data;
}
