import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addComment,
  listTasks,
  type TaskFilterParams,
  transitionStatus,
} from "@/api/taskApi";

export function useTasks(filter: TaskFilterParams) {
  return useQuery({ queryKey: ["tasks", filter], queryFn: () => listTasks(filter) });
}

export function useTransitionStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; status: string }) =>
      transitionStatus(args.id, args.status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useAddComment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; body: string }) => addComment(args.id, args.body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
