import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  cancelJob,
  createJob,
  deployJob,
  getJob,
  isTerminal,
  type Job,
  type JobCreateRequest,
  type JobStatus,
  listDeployed,
  listJobs,
  progressWsUrl,
} from "@/api/retrainingApi";
import {
  classifyLine,
  detectStage,
  STAGE_ORDER,
  type Phase,
  type ProgressState,
  type Stage,
} from "@/pages/retrainingProgress";

const KEY = {
  jobs: (status?: JobStatus) => ["retraining", "jobs", status ?? "all"] as const,
  job: (id: number) => ["retraining", "job", id] as const,
  deployed: ["retraining", "deployed"] as const,
};

export function useJobs(status?: JobStatus) {
  return useQuery({
    queryKey: KEY.jobs(status),
    queryFn: () => listJobs({ status, limit: 50 }),
    // 実行中ジョブがあるうちは軽くポーリング（WS とは別に一覧の状態を追従）。
    refetchInterval: (q) =>
      q.state.data?.items.some((j: Job) => !isTerminal(j.status)) ? 4000 : false,
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["retraining", "jobs"] }),
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => cancelJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["retraining", "jobs"] }),
  });
}

export function useDeployed() {
  return useQuery({ queryKey: KEY.deployed, queryFn: listDeployed });
}

export function useDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deployJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY.deployed }),
  });
}

export type WsState = "connecting" | "open" | "closed";

/**
 * 進捗 WebSocket フック。標準出力の行を素通しで受け取り蓄積する（揮発）。
 * jobId が null / 非アクティブ（終端ジョブ）のときは接続しない。
 */
export function useJobProgress(jobId: number | null, active: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [importantLines, setImportantLines] = useState<string[]>([]);
  const [progress, setProgress] = useState<Partial<Record<Phase, ProgressState>>>({});
  const [stage, setStage] = useState<Stage | undefined>(undefined);
  const [state, setState] = useState<WsState>("closed");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (jobId == null || !active) return;
    setLines([]);
    setImportantLines([]);
    setProgress({});
    setStage(undefined);
    setState("connecting");
    const ws = new WebSocket(progressWsUrl(jobId));
    wsRef.current = ws;

    ws.onopen = () => setState("open");
    ws.onmessage = (ev) => {
      const raw = String(ev.data);
      setLines((prev) => [...prev, raw]);

      const detectedStage = detectStage(raw);
      if (detectedStage) {
        // 単調前進のみ（後退しない）。並列学習で monochro/color どちらの行が
        // 来ても同じ training ステージなので後退は起きない。
        setStage((prev) =>
          prev === undefined || STAGE_ORDER.indexOf(detectedStage) > STAGE_ORDER.indexOf(prev)
            ? detectedStage
            : prev,
        );
      }

      const classified = classifyLine(raw);
      if (classified.kind === "progress") {
        // phase不明、または学習ループ本体以外（閾値計算・中間処理など）の進捗行は
        // バーに反映しない。totalが小さくすぐ100%に達するため、学習ループ本体の
        // 進捗と混ぜると「学習が完了した」ように誤認させる（phase不明は並列学習では
        // 常に[monochro]/[color]接頭辞が付くため実運用では発生しない）。
        if (classified.phase && classified.isMainLoop) {
          const phase = classified.phase;
          setProgress((prev) => ({
            ...prev,
            [phase]: {
              percent: classified.percent,
              current: classified.current,
              total: classified.total,
              loss: classified.loss,
              eta: classified.eta,
            },
          }));
        }
      } else {
        setImportantLines((prev) => [...prev, raw]);
      }
    };
    ws.onerror = () => setState("closed");
    ws.onclose = () => setState("closed");

    return () => {
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    };
  }, [jobId, active]);

  return { lines, importantLines, progress, stage, state };
}
