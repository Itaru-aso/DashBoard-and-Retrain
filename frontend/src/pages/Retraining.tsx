import { useMemo, useState } from "react";

import { isTerminal, type Job, type JobStatus } from "@/api/retrainingApi";
import {
  useCancelJob,
  useCreateJob,
  useDeployed,
  useJobProgress,
  useJobs,
} from "@/hooks/useRetraining";
import { STAGE_LABEL, type Phase, type ProgressState } from "@/pages/retrainingProgress";

import styles from "./Retraining.module.css";

const STATUS_LABEL: Record<JobStatus, string> = {
  QUEUED: "待機中",
  RUNNING: "学習中",
  COMPLETED: "完了",
  FAILED: "失敗",
  CANCELLED: "キャンセル",
};

function CreateJobForm() {
  const create = useCreateJob();
  const [form, setForm] = useState({
    color_no: "",
    size: "",
    chain: "",
    tape: "",
    created_by: "",
  });
  const canSubmit = Boolean(form.color_no && form.size && form.chain) && !create.isPending;

  const update =
    (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      { ...form, created_by: form.created_by || null },
      {
        onSuccess: () =>
          setForm({ color_no: "", size: "", chain: "", tape: "", created_by: "" }),
      },
    );
  };

  return (
    <div className={styles.panel}>
      <span className={styles.panelTitle}>再学習を起票</span>
      <div className={styles.formRow}>
        <div className={styles.field}>
          <label htmlFor="rt-color">色番</label>
          <input id="rt-color" value={form.color_no} onChange={update("color_no")} />
        </div>
        <div className={styles.field}>
          <label htmlFor="rt-size">サイズ</label>
          <input id="rt-size" value={form.size} onChange={update("size")} />
        </div>
        <div className={styles.field}>
          <label htmlFor="rt-chain">チェーン</label>
          <input id="rt-chain" value={form.chain} onChange={update("chain")} />
        </div>
        <div className={styles.field}>
          <label htmlFor="rt-tape">テープ</label>
          <input id="rt-tape" value={form.tape} onChange={update("tape")} />
        </div>
        <div className={styles.field}>
          <label htmlFor="rt-by">起票者</label>
          <input id="rt-by" value={form.created_by} onChange={update("created_by")} />
        </div>
        <button type="button" className={styles.submitButton} onClick={submit} disabled={!canSubmit}>
          {create.isPending ? "起票中…" : "再学習を起票"}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className={styles.error}>
          起票できませんでした: {(create.error as Error).message}
        </p>
      )}
    </div>
  );
}

const PHASE_LABEL: Record<Phase, string> = { monochro: "モノクロAI", color: "カラーAI" };

function ProgressBar({ phase, state }: { phase: Phase; state?: ProgressState }) {
  const label = PHASE_LABEL[phase];
  if (!state) {
    return (
      <div className={styles.progressBarRow}>
        <span className={styles.progressBarLabel}>{label}</span>
        <span className={styles.progressBarWaiting}>待機中…</span>
      </div>
    );
  }
  const detail = [
    `${state.percent}% (${state.current}/${state.total})`,
    state.loss != null ? `loss=${state.loss}` : null,
    state.eta ?? null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={styles.progressBarRow}>
      <span className={styles.progressBarLabel}>{label}</span>
      <div
        className={styles.progressBarTrack}
        role="progressbar"
        aria-label={`${label}進捗`}
        aria-valuenow={state.percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={styles.progressBarFill} style={{ width: `${state.percent}%` }} />
      </div>
      <span className={styles.progressBarText}>{detail}</span>
    </div>
  );
}

function ProgressPanel({ job }: { job: Job }) {
  const active = !isTerminal(job.status);
  const { lines, importantLines, progress, stage, state } = useJobProgress(job.id, active);

  return (
    <div className={styles.progressCard}>
      <span className={styles.panelTitle}>
        進捗 — ジョブ #{job.id}（{job.color_no}/{job.size}/{job.chain}/{job.tape || "—"}）
      </span>
      <div className={styles.statusRow}>
        <span className={styles.pulseDot} />
        <span>
          {STATUS_LABEL[job.status]}
          {active ? (state === "open" ? " 配信中" : " 接続中…") : " 学習は終了しています"}
        </span>
        {active && (
          <span className={styles.stageLabel}>
            現在の処理: {stage ? STAGE_LABEL[stage] : "起動中…"}
          </span>
        )}
      </div>
      <div className={styles.progressBars}>
        <ProgressBar phase="monochro" state={progress.monochro} />
        <ProgressBar phase="color" state={progress.color} />
      </div>
      <pre aria-live="polite" aria-label="学習ログ" className={styles.logBox}>
        {importantLines.length
          ? importantLines.join("\n")
          : active
            ? "ログ待機中…"
            : "ライブログはありません（終了済み）。"}
      </pre>
      <details className={styles.rawLogDetails}>
        <summary>元ログを表示</summary>
        <pre aria-label="元ログ" className={styles.logBox}>
          {lines.length ? lines.join("\n") : "ログはありません。"}
        </pre>
      </details>
      {job.status === "FAILED" && job.error_message && (
        <p role="alert" className={styles.error}>
          失敗理由: {job.error_message}
        </p>
      )}
    </div>
  );
}

function JobsTable({
  onSelect,
}: {
  onSelect: (id: number) => void;
}) {
  const { data, isLoading, isError, error } = useJobs();
  const cancel = useCancelJob();

  if (isLoading) return <p>履歴を読み込み中…</p>;
  if (isError)
    return (
      <p role="alert" className={styles.error}>
        履歴を取得できませんでした: {(error as Error).message}
      </p>
    );

  const jobs = data?.items ?? [];
  if (!jobs.length)
    return <p>まだ再学習はありません。上のフォームから起票してください。</p>;

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>#</th>
            <th>色（フルタプル）</th>
            <th>状態</th>
            <th>起票</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td className={styles.mono}>{j.id}</td>
              <td className={styles.mono}>
                {j.color_no}/{j.size}/{j.chain}/{j.tape || "—"}
              </td>
              <td>{STATUS_LABEL[j.status]}</td>
              <td className={styles.mono}>{new Date(j.queued_at).toLocaleString()}</td>
              <td>
                <button type="button" className={styles.actionButton} onClick={() => onSelect(j.id)}>
                  進捗
                </button>
                {!isTerminal(j.status) && (
                  <button
                    type="button"
                    className={styles.actionButton}
                    onClick={() => cancel.mutate(j.id)}
                    disabled={cancel.isPending}
                  >
                    キャンセル
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeployedTable() {
  const { data, isLoading } = useDeployed();
  if (isLoading) return <p>現行モデルを読み込み中…</p>;
  const rows = data ?? [];
  if (!rows.length) return <p>配信済みの現行モデルはまだありません。</p>;

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>色（フルタプル）</th>
            <th>由来ジョブ</th>
            <th>配信状態</th>
            <th>配信日時</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id}>
              <td className={styles.mono}>
                {d.color_no}/{d.size}/{d.chain}/{d.tape || "—"}
              </td>
              <td className={styles.mono}>#{d.job_id}</td>
              <td>{d.deploy_status}</td>
              <td className={styles.mono}>{new Date(d.deployed_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** モデル再学習画面（起票・履歴一覧・ライブ進捗・キャンセル・現行配信モデル）。 */
export default function Retraining() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data } = useJobs();
  const selected = useMemo(
    () => data?.items.find((j) => j.id === selectedId) ?? null,
    [data, selectedId],
  );

  return (
    <section>
      <h1>モデル再学習</h1>

      <CreateJobForm />

      <section>
        <h2>履歴</h2>
        <JobsTable onSelect={setSelectedId} />
      </section>

      {selected && <ProgressPanel job={selected} />}

      <section>
        <h2>現行配信モデル</h2>
        <DeployedTable />
      </section>
    </section>
  );
}
