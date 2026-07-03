import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  checkFtp,
  createEdgePc,
  deleteEdgePc,
  type EdgePcCreatePayload,
  type EdgePcUpdatePayload,
  listEdgePcs,
  updateEdgePc,
} from "@/api/edgePcApi";

export function useEdgePcs() {
  return useQuery({ queryKey: ["edge-pcs"], queryFn: () => listEdgePcs() });
}

export function useCreateEdgePc() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: EdgePcCreatePayload) => createEdgePc(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["edge-pcs"] }),
  });
}

export function useUpdateEdgePc() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; payload: EdgePcUpdatePayload }) =>
      updateEdgePc(args.id, args.payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["edge-pcs"] }),
  });
}

export function useDeleteEdgePc() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteEdgePc(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["edge-pcs"] }),
  });
}

export function useCheckFtp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => checkFtp(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["edge-pcs"] }),
  });
}
