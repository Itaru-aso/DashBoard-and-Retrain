import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createThreshold,
  disableThreshold,
  listThresholds,
  type ThresholdCreatePayload,
} from "@/api/thresholdApi";

const THRESHOLDS_KEY = ["thresholds"];

export function useThresholds() {
  return useQuery({ queryKey: THRESHOLDS_KEY, queryFn: listThresholds });
}

export function useCreateThreshold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ThresholdCreatePayload) => createThreshold(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: THRESHOLDS_KEY }),
  });
}

export function useDisableThreshold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; validTo: string }) =>
      disableThreshold(args.id, args.validTo),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: THRESHOLDS_KEY }),
  });
}
