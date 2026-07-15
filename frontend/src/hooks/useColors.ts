import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ColorSampleUpdatePayload,
  getColorSummary,
  importColors,
  listColors,
  updateSample,
} from "@/api/colorApi";

export function useColors(filter: { status?: string; limit?: number; offset?: number }) {
  return useQuery({ queryKey: ["colors", filter], queryFn: () => listColors(filter) });
}

export function useColorSummary() {
  return useQuery({ queryKey: ["colors", "summary"], queryFn: getColorSummary });
}

export function useImportColors() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => importColors(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["colors"] }),
  });
}

export function useUpdateSample() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; payload: ColorSampleUpdatePayload }) =>
      updateSample(args.id, args.payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["colors"] }),
  });
}
