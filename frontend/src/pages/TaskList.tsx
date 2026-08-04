import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusChip, type StatusVariant } from "@/components/ui/StatusChip";
import type { Task } from "@/api/taskApi";
import { useAddComment, useTasks, useTransitionStatus } from "@/hooks/useTasks";

import styles from "./TaskList.module.css";

const NEXT_STATUS: Record<string, string | null> = {
  OPEN: "IN_PROGRESS",
  IN_PROGRESS: "DONE",
  DONE: null,
};

const STATUS_META: Record<string, { label: string; variant: StatusVariant }> = {
  OPEN: { label: "未着手", variant: "neutral" },
  IN_PROGRESS: { label: "対応中", variant: "warn" },
  DONE: { label: "完了", variant: "ok" },
};

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "すべて" },
  { value: "OPEN", label: "未着手" },
  { value: "IN_PROGRESS", label: "対応中" },
  { value: "DONE", label: "完了" },
];

function TaskRow({ task }: { task: Task }) {
  const transition = useTransitionStatus();
  const addComment = useAddComment();
  const [comment, setComment] = useState("");
  const next = NEXT_STATUS[task.status];
  const statusMeta = STATUS_META[task.status];

  return (
    <tr>
      <td className={styles.mono}>{task.evaluation_date ?? "—"}</td>
      <td>{task.task_type}</td>
      <td className={styles.mono}>{task.size}</td>
      <td className={styles.mono}>{task.chain}</td>
      <td className={styles.mono}>{task.tape}</td>
      <td>{task.color_no}</td>
      <td className={styles.mono}>
        <span className={styles.detected}>{task.detected_value ?? "—"}</span>{" "}
        <span className={styles.threshold}>/ {task.threshold_value ?? "—"}</span>
      </td>
      <td>
        {statusMeta ? (
          <StatusChip variant={statusMeta.variant}>{statusMeta.label}</StatusChip>
        ) : (
          task.status
        )}
      </td>
      <td>
        {next && (
          <Button
            variant="secondary"
            onClick={() => transition.mutate({ id: task.id, status: next })}
          >
            進める
          </Button>
        )}
      </td>
      <td>
        <div className={styles.commentCell}>
          <input
            aria-label={`comment-${task.id}`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <Button
            variant="secondary"
            onClick={() => {
              if (comment) {
                addComment.mutate({ id: task.id, body: comment });
                setComment("");
              }
            }}
          >
            コメント追加
          </Button>
        </div>
      </td>
    </tr>
  );
}

/** 保守タスク管理画面（一覧・フィルタ・状態遷移・コメント追記）。 */
export default function TaskList() {
  const [status, setStatus] = useState("");
  const filter = status ? { status } : {};
  const { data: tasks = [], isLoading } = useTasks(filter);

  return (
    <section>
      <PageHeader title="保守タスク" />

      <Panel>
        <div className={styles.filterBar}>
          <span className={styles.filterBarLabel}>状態フィルタ</span>
          <SegmentedControl options={STATUS_FILTER_OPTIONS} value={status} onChange={setStatus} />
        </div>
      </Panel>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <Panel>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>検査日 (JST)</th>
                  <th>種別</th>
                  <th>サイズ</th>
                  <th>チェーン</th>
                  <th>テープ</th>
                  <th>色番</th>
                  <th>検知値 / 閾値</th>
                  <th>ステータス</th>
                  <th>操作</th>
                  <th>コメント</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <TaskRow key={t.id} task={t} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </section>
  );
}
