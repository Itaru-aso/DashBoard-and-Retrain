import { apiClient } from "./client";

export interface Color {
  id: number;
  color_no: string;
  size: string;
  chain: string;
  tape: string;
  rgb_r: number | null;
  rgb_g: number | null;
  rgb_b: number | null;
  lab_l: number | null;
  lab_a: number | null;
  lab_b: number | null;
  status: string;
  verification_at: string | null;
  production_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface ColorSampleUpdatePayload {
  rgb_r?: number;
  rgb_g?: number;
  rgb_b?: number;
  lab_l?: number;
  lab_a?: number;
  lab_b?: number;
}

export async function listColors(params: { status?: string } = {}): Promise<Color[]> {
  const { data } = await apiClient.get<Color[]>("/colors", { params });
  return data;
}

export async function importColors(file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<ImportResult>("/colors/import", form);
  return data;
}

export async function updateSample(
  id: number,
  payload: ColorSampleUpdatePayload,
): Promise<Color> {
  const { data } = await apiClient.patch<Color>(`/colors/${id}`, payload);
  return data;
}
