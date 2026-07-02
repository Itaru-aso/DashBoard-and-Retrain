import { useQuery } from "@tanstack/react-query";

import {
  type DashboardFilterParams,
  fetchMachines,
  fetchRecords,
  fetchSummary,
  fetchThresholdOverlay,
  fetchTrends,
} from "@/api/dashboardApi";

export function useMachines() {
  return useQuery({ queryKey: ["machines"], queryFn: fetchMachines });
}

export function useTrends(params: DashboardFilterParams | null) {
  return useQuery({
    queryKey: ["trends", params],
    queryFn: () => fetchTrends(params as DashboardFilterParams),
    enabled: params !== null,
  });
}

export function useSummary(params: DashboardFilterParams | null) {
  return useQuery({
    queryKey: ["summary", params],
    queryFn: () => fetchSummary(params as DashboardFilterParams),
    enabled: params !== null,
  });
}

export function useRecords(params: DashboardFilterParams | null) {
  return useQuery({
    queryKey: ["records", params],
    queryFn: () => fetchRecords(params as DashboardFilterParams),
    enabled: params !== null,
  });
}

export function useThresholdOverlay(
  params:
    | { metric: string; color_no: string; size: string; chain: string; tape: string; from: string; to: string }
    | null,
) {
  return useQuery({
    queryKey: ["overlay", params],
    queryFn: () => fetchThresholdOverlay(params!),
    enabled: params !== null,
  });
}
