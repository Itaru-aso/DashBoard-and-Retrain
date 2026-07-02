import { apiClient } from "./client";

export interface TrendPoint {
  jst_date: string;
  throughput: number;
  ng_rate: number;
  false_alarm_rate: number | null;
  miss_rate: number | null;
}

export interface Summary {
  throughput: number;
  ng_rate: number;
  false_alarm_rate: number | null;
  miss_rate: number | null;
}

export interface DetailRecord {
  image_id: number;
  inspect_timestamp: string;
  unit: string | null;
  camera_model: string | null;
  judgment_result: number | null;
  color_no: string | null;
  size: string | null;
  chain: string | null;
  tape: string | null;
}

export interface RecordsPage {
  records: DetailRecord[];
  next_cursor: { inspect_timestamp: string; image_id: number } | null;
}

export interface OverlayPoint {
  jst_date: string;
  value_pct: number;
}

export interface Machine {
  unit: string;
}

export interface DashboardFilterParams {
  from: string;
  to: string;
  color_no?: string;
  size?: string;
  chain?: string;
  tape?: string;
  machine_ids?: string[];
}

export async function fetchTrends(params: DashboardFilterParams): Promise<TrendPoint[]> {
  const { data } = await apiClient.get<TrendPoint[]>("/dashboard/trends", { params });
  return data;
}

export async function fetchSummary(params: DashboardFilterParams): Promise<Summary | null> {
  const { data } = await apiClient.get<Summary | null>("/dashboard/summary", { params });
  return data;
}

export async function fetchRecords(params: DashboardFilterParams): Promise<RecordsPage> {
  const { data } = await apiClient.get<RecordsPage>("/dashboard/records", { params });
  return data;
}

export async function fetchThresholdOverlay(params: {
  metric: string;
  color_no: string;
  size: string;
  chain: string;
  tape: string;
  from: string;
  to: string;
}): Promise<OverlayPoint[]> {
  const { data } = await apiClient.get<OverlayPoint[]>("/dashboard/threshold-overlay", {
    params,
  });
  return data;
}

export async function fetchMachines(): Promise<Machine[]> {
  const { data } = await apiClient.get<Machine[]>("/dashboard/machines");
  return data;
}
