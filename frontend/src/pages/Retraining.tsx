import { useMemo, useState } from "react";

import { isTerminal, type Job, type JobStatus } from "@/api/retrainingApi";
import {
  useCancelJob,
  useCreateJob,
  useDeployed,
  useJobProgress,
  useJobs,
} from "@/hooks/useRetraining";

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
    <section>
      <h2>再学習を起票</h2>
      <div>
        <label htmlFor="rt-color">色番</label>
        <input id="rt-color" value={form.color_no} onChange={update("color_no")} />
        <label htmlFor="rt-size">サイズ</label>
        <input id="rt-size" value={form.size} onChange={update("size")} />
        <label htmlFor="rt-chain">チェーン</label>
        <input id="rt-chain" value={form.chain} onChange={update("chain")} />
        <label htmlFor="rt-tape">テープ</label>
        <input id="rt-tape" value={form.tape} onChange={update("tape")} />
        <label htmlFor="rt-by">起票者</label>
        <input id="rt-by" value={form.created_by} onChange={update("created_by")} />
      </div>
      <button type="button" onClick={submit} disabled={!canSubmit}>
        {create.isPending ? "起票中…" : "再学習を起票"}
      </button>
      {create.isError && (
        <p role="alert">起票できませんでした: {(create.error as Error).message}</p>
      )}
    </section>
  );
}

function ProgressPanel({ job }: { job: Job }) {
  const active = !isTerminal(job.status);
  const { lines, state } = useJobProgress(job.id, active);

  return (
    <section>
      <h2>
        進捗 — ジョブ #{job.id}（{job.color_no}/{job.size}/{job.chain}/{job.tape || "—"}）
      </h2>
      <p>
        {STATUS_LABEL[job.status]}
        {active ? (state === "open" ? " 配信中" : " 接続中…") : " 学習は終了しています"}
      </p>
      <pre aria-live="polite" aria-label="学習ログ">
        {lines.length
          ? lines.join("\n")
          : active
            ? "ログ待機中…"
            : "ライブログはありません（終了済み）。"}
      </pre>
      {job.status === "FAILED" && job.error_message && (
        <p role="alert">失敗理由: {job.error_message}</p>
      )}
    </section>
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
    return <p role="alert">履歴を取得できませんでした: {(error as Error).message}</p>;

  const jobs = data?.items ?? [];
  if (!jobs.length)
    return <p>まだ再学習はありません。上のフォームから起票してください。</p>;

  return (
    <table>
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
            <td>{j.id}</td>
            <td>
              {j.color_no}/{j.size}/{j.chain}/{j.tape || "—"}
            </td>
            <td>{STATUS_LABEL[j.status]}</td>
            <td>{new Date(j.queued_at).toLocaleString()}</td>
            <td>
              <button type="button" onClick={() => onSelect(j.id)}>
                進捗
              </button>
              {!isTerminal(j.status) && (
                <button
                  type="button"
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
  if (isLoading) return <p>現行モデルを読み込み中…</p>;
  const rows = data ?? [];
  if (!rows.length) return <p>配信済みの現行モデルはまだありません。</p>;

  return (
    <table>
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
            <td>
              {d.color_no}/{d.size}/{d.chain}/{d.tape || "—"}
            </td>
            <td>#{d.job_id}</td>
            <td>{d.deploy_status}</td>
            <td>{new Date(d.deployed_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
