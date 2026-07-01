// 配置先: frontend/src/hooks/useRetraining.ts
// 再学習ワークフローの TanStack Query フック群 ＋ 進捗 WebSocket フック。

import { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  cancelJob,
  createJob,
  deployJob,
  getJob,
  isTerminal,
  listDeployed,
  listJobs,
  progressWsUrl,
  type Job,
  type JobCreateRequest,
  type JobStatus,
} from "../api/retrainingApi";

const KEY = {
  jobs: (status?: JobStatus) => ["retraining", "jobs", status ?? "all"] as const,
  job: (id: number) => ["retraining", "job", id] as const,
  deployed: ["retraining", "deployed"] as const,
};

export function useJobs(status?: JobStatus) {
  return useQuery({
    queryKey: KEY.jobs(status),
    queryFn: () => listJobs({ status, limit: 50 }),
    // 実行中ジョブがあるうちは軽くポーリング（WS とは別に一覧の状態を追従）
    refetchInterval: (q) =>
      q.state.data?.items.some((j) => !isTerminal(j.status)) ? 4000 : false,
  });
}

export function useJob(id: number | null) {
  return useQuery({
    queryKey: id != null ? KEY.job(id) : ["retraining", "job", "none"],
    queryFn: () => getJob(id as number),
    enabled: id != null,
  });
}

export function useCreateJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: JobCreateRequest) => createJob(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retraining", "jobs"] });
    },
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => cancelJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retraining", "jobs"] });
    },
  });
}

export function useDeployed() {
  return useQuery({ queryKey: KEY.deployed, queryFn: listDeployed });
}

export function useDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deployJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY.deployed });
    },
  });
}

export type WsState = "connecting" | "open" | "closed";

/**
 * 進捗 WebSocket フック。標準出力の行を素通しで受け取り蓄積する（揮発）。
 * jobId が null / 終端ジョブのときは接続しない。
 */
export function useJobProgress(jobId: number | null, active: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [state, setState] = useState<WsState>("closed");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (jobId == null || !active) return;
    setLines([]);
    setState("connecting");
    const ws = new WebSocket(progressWsUrl(jobId));
    wsRef.current = ws;

    ws.onopen = () => setState("open");
    ws.onmessage = (ev) => setLines((prev) => [...prev, String(ev.data)]);
    ws.onerror = () => setState("closed");
    ws.onclose = () => setState("closed");

    return () => {
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    };
  }, [jobId, active]);

  return { lines, state };
}
