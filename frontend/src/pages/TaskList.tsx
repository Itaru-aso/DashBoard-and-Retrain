import { useState } from "react";

import type { Task } from "@/api/taskApi";
import { useAddComment, useTasks, useTransitionStatus } from "@/hooks/useTasks";

import styles from "./TaskList.module.css";

const NEXT_STATUS: Record<string, string | null> = {
  OPEN: "IN_PROGRESS",
  IN_PROGRESS: "DONE",
  DONE: null,
};

function TaskRow({ task }: { task: Task }) {
  const transition = useTransitionStatus();
  const addComment = useAddComment();
  const [comment, setComment] = useState("");
  const next = NEXT_STATUS[task.status];

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
      <td>{task.status}</td>
      <td>
        {next && (
          <button type="button" className={styles.actionButton} onClick={() => transition.mutate({ id: task.id, status: next })}>
            進める
          </button>
        )}
      </td>
      <td>
        <div className={styles.commentCell}>
          <input
            aria-label={`comment-${task.id}`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button
            type="button"
            className={styles.actionButton}
            onClick={() => {
              if (comment) {
                addComment.mutate({ id: task.id, body: comment });
                setComment("");
              }
            }}
          >
            コメント追加
          </button>
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
      <h1>保守タスク</h1>

      <div className={styles.filterBar}>
        <label htmlFor="status-filter">状態フィルタ</label>
        <select id="status-filter" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">すべて</option>
          <option value="OPEN">OPEN</option>
          <option value="IN_PROGRESS">IN_PROGRESS</option>
          <option value="DONE">DONE</option>
        </select>
      </div>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
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
      )}
    </section>
  );
}
