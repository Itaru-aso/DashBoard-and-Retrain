import { useState } from "react";

import type { Task } from "@/api/taskApi";
import { useAddComment, useTasks, useTransitionStatus } from "@/hooks/useTasks";

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
      <td>{task.task_type}</td>
      <td>{`${task.color_no}/${task.size}/${task.chain}/${task.tape}`}</td>
      <td>{task.status}</td>
      <td>
        {next && (
          <button
            type="button"
            onClick={() => transition.mutate({ id: task.id, status: next })}
          >
            進める
          </button>
        )}
      </td>
      <td>
        <input
          aria-label={`comment-${task.id}`}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <button
          type="button"
          onClick={() => {
            if (comment) {
              addComment.mutate({ id: task.id, body: comment });
              setComment("");
            }
          }}
        >
          コメント追加
        </button>
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

      <label htmlFor="status-filter">状態フィルタ</label>
      <select
        id="status-filter"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
      >
        <option value="">すべて</option>
        <option value="OPEN">OPEN</option>
        <option value="IN_PROGRESS">IN_PROGRESS</option>
        <option value="DONE">DONE</option>
      </select>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>種別</th>
              <th>対象</th>
              <th>状態</th>
              <th>遷移</th>
              <th>コメント</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <TaskRow key={t.id} task={t} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
