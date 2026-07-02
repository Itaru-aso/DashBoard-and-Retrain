import { apiClient } from "./client";

// 閾値（バックエンド ThresholdOut に対応）
export interface Threshold {
  id: number;
  metric: string;
  scope: string;
  color_no: string | null;
  size: string | null;
  chain: string | null;
  tape: string | null;
  value_pct: number;
  valid_from: string;
  valid_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThresholdCreatePayload {
  metric: string;
  scope: string;
  color_no?: string | null;
  size?: string | null;
  chain?: string | null;
  tape?: string | null;
  value_pct: number;
  valid_from: string;
  valid_to?: string | null;
}

export async function listThresholds(): Promise<Threshold[]> {
  const { data } = await apiClient.get<Threshold[]>("/thresholds");
  return data;
}

export async function createThreshold(
  payload: ThresholdCreatePayload,
): Promise<Threshold> {
  const { data } = await apiClient.post<Threshold>("/thresholds", payload);
  return data;
}

export async function disableThreshold(
  id: number,
  validTo: string,
): Promise<Threshold> {
  const { data } = await apiClient.patch<Threshold>(`/thresholds/${id}`, {
    valid_to: validTo,
  });
  return data;
}
