import { apiClient } from "./client";

export interface TaskComment {
  body: string;
  created_at: string;
}

export interface Task {
  id: number;
  color_no: string;
  size: string;
  chain: string;
  tape: string;
  task_type: string;
  status: string;
  detected_value: number | null;
  threshold_value: number | null;
  evaluation_date: string | null;
  comments: TaskComment[];
  created_at: string;
  updated_at: string;
}

export interface TaskFilterParams {
  status?: string;
  task_type?: string;
  color_no?: string;
}

export async function listTasks(params: TaskFilterParams = {}): Promise<Task[]> {
  const { data } = await apiClient.get<Task[]>("/tasks", { params });
  return data;
}

export async function transitionStatus(id: number, status: string): Promise<Task> {
  const { data } = await apiClient.patch<Task>(`/tasks/${id}/status`, { status });
  return data;
}

export async function addComment(id: number, body: string): Promise<Task> {
  const { data } = await apiClient.post<Task>(`/tasks/${id}/comments`, { body });
  return data;
}
