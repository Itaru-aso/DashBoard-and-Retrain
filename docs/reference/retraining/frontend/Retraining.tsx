// 配置先: frontend/src/pages/Retraining.tsx
// 再学習画面: 起票フォーム（フルタプル）・履歴一覧・ライブ進捗（WS 素通し）・キャンセル・現行配信モデル。
// スタイルは既存 shisui app_ver2 のデザインシステム（クラス/トークン）に合わせて調整すること。

import { useMemo, useState } from "react";
import {
  isTerminal,
  type Job,
  type JobStatus,
} from "../api/retrainingApi";
import {
  useCancelJob,
  useCreateJob,
  useDeployed,
  useJobProgress,
  useJobs,
} from "../hooks/useRetraining";

const STATUS_LABEL: Record<JobStatus, string> = {
  QUEUED: "待機中",
  RUNNING: "学習中",
  COMPLETED: "完了",
  FAILED: "失敗",
  CANCELLED: "キャンセル",
};

function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`status-badge status-${status.toLowerCase()}`}>{STATUS_LABEL[status]}</span>;
}

function CreateJobForm() {
  const create = useCreateJob();
  const [form, setForm] = useState({ color_no: "", size: "", chain: "", tape: "", created_by: "" });
  const canSubmit = form.color_no && form.size && form.chain && !create.isPending;

  const update = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      { ...form, created_by: form.created_by || null },
      { onSuccess: () => setForm({ color_no: "", size: "", chain: "", tape: "", created_by: "" }) },
    );
  };

  return (
    <section aria-labelledby="create-heading" className="card">
      <h2 id="create-heading">再学習を起票</h2>
      <p className="hint">色を選んで再学習をキューに追加します。1 件の学習で monochro / color の両モデルを更新します。</p>
      <div className="form-grid">
        <label>色番<input value={form.color_no} onChange={update("color_no")} placeholder="例: 501" /></label>
        <label>サイズ<input value={form.size} onChange={update("size")} placeholder="例: 05" /></label>
        <label>チェーン<input value={form.chain} onChange={update("chain")} placeholder="例: CZT8" /></label>
        <label>テープ<input value={form.tape} onChange={update("tape")} placeholder="（基本空白）" /></label>
        <label>起票者<input value={form.created_by} onChange={update("created_by")} placeholder="任意" /></label>
      </div>
      <div className="form-actions">
        <button type="button" onClick={submit} disabled={!canSubmit}>
          {create.isPending ? "起票中…" : "再学習を起票"}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="error">
          起票できませんでした: {(create.error as Error).message}
        </p>
      )}
    </section>
  );
}

function ProgressPanel({ job }: { job: Job }) {
  const active = !isTerminal(job.status);
  const { lines, state } = useJobProgress(job.id, active);

  return (
    <section aria-labelledby="progress-heading" className="card">
      <h2 id="progress-heading">
        進捗 — ジョブ #{job.id}（{job.color_no}/{job.size}/{job.chain}/{job.tape || "—"}）
      </h2>
      <p className="hint">
        <StatusBadge status={job.status} />
        {active ? (state === "open" ? " 配信中" : " 接続中…") : " 学習は終了しています"}
      </p>
      <pre className="log" aria-live="polite" aria-label="学習ログ">
        {lines.length ? lines.join("\n") : active ? "ログ待機中…" : "ライブログはありません（終了済み）。"}
      </pre>
      {job.status === "FAILED" && job.error_message && (
        <p role="alert" className="error">失敗理由: {job.error_message}</p>
      )}
    </section>
  );
}

function JobsTable({ onSelect, selectedId }: { onSelect: (id: number) => void; selectedId: number | null }) {
  const { data, isLoading, isError, error } = useJobs();
  const cancel = useCancelJob();

  if (isLoading) return <p className="hint">履歴を読み込み中…</p>;
  if (isError) return <p role="alert" className="error">履歴を取得できませんでした: {(error as Error).message}</p>;

  const jobs = data?.items ?? [];
  if (!jobs.length) return <p className="empty">まだ再学習はありません。上のフォームから起票してください。</p>;

  return (
    <table className="jobs-table">
      <caption className="sr-only">再学習ジョブの履歴</caption>
      <thead>
        <tr><th>#</th><th>色（フルタプル）</th><th>状態</th><th>起票</th><th>操作</th></tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id} aria-selected={j.id === selectedId}>
            <td>{j.id}</td>
            <td>{j.color_no}/{j.size}/{j.chain}/{j.tape || "—"}</td>
            <td><StatusBadge status={j.status} /></td>
            <td>{new Date(j.queued_at).toLocaleString()}</td>
            <td className="row-actions">
              <button type="button" onClick={() => onSelect(j.id)}>進捗</button>
              {!isTerminal(j.status) && (
                <button
                  type="button"
                  className="danger"
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
  );
}

function DeployedTable() {
  const { data, isLoading } = useDeployed();
  if (isLoading) return <p className="hint">現行モデルを読み込み中…</p>;
  const rows = data ?? [];
  if (!rows.length) return <p className="empty">配信済みの現行モデルはまだありません。</p>;

  return (
    <table className="deployed-table">
      <caption className="sr-only">色ごとの現行配信モデル</caption>
      <thead>
        <tr><th>色（フルタプル）</th><th>由来ジョブ</th><th>配信状態</th><th>配信日時</th></tr>
      </thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.id}>
            <td>{d.color_no}/{d.size}/{d.chain}/{d.tape || "—"}</td>
            <td>#{d.job_id}</td>
            <td>{d.deploy_status}</td>
            <td>{new Date(d.deployed_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Retraining() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data } = useJobs();
  const selected = useMemo(
    () => data?.items.find((j) => j.id === selectedId) ?? null,
    [data, selectedId],
  );

  return (
    <main className="retraining-page">
      <header className="page-header">
        <h1>モデル再学習</h1>
        <p className="hint">色ごとの AI モデルを再学習し、検査PCへ配信します。</p>
      </header>

      <CreateJobForm />

      <section aria-labelledby="history-heading" className="card">
        <h2 id="history-heading">履歴</h2>
        <JobsTable onSelect={setSelectedId} selectedId={selectedId} />
      </section>

      {selected && <ProgressPanel job={selected} />}

      <section aria-labelledby="deployed-heading" className="card">
        <h2 id="deployed-heading">現行配信モデル</h2>
        <DeployedTable />
      </section>
    </main>
  );
}
