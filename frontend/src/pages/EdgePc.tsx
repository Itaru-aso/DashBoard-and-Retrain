import { useState } from "react";

import type { EdgePc as EdgePcModel } from "@/api/edgePcApi";
import {
  useCheckFtp,
  useCreateEdgePc,
  useDeleteEdgePc,
  useEdgePcs,
  useUpdateEdgePc,
} from "@/hooks/useEdgePcs";

import styles from "./EdgePc.module.css";

function ftpLabel(edge: EdgePcModel): string {
  if (edge.last_ftp_ok === null) return "未確認";
  return edge.last_ftp_ok ? "OK" : "NG";
}

function EdgeCard({ edge }: { edge: EdgePcModel }) {
  const update = useUpdateEdgePc();
  const remove = useDeleteEdgePc();
  const check = useCheckFtp();

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardName}>{edge.name}</span>
        <span className={edge.enabled ? styles.badgeEnabled : styles.badgeDisabled}>
          {edge.enabled ? "有効" : "無効"}
        </span>
      </div>
      <span className={styles.ipLabel}>IPアドレス</span>
      <span className={styles.ipValue}>{edge.host}</span>
      <span className={styles.meta}>
        ポート {edge.model_port ?? "—"} ／ FTP {ftpLabel(edge)}
      </span>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.actionButton}
          onClick={() => update.mutate({ id: edge.id, payload: { enabled: !edge.enabled } })}
        >
          {edge.enabled ? "無効化" : "有効化"}
        </button>
        <button type="button" className={styles.actionButton} onClick={() => check.mutate(edge.id)}>
          接続テスト
        </button>
        <button type="button" className={styles.actionButton} onClick={() => remove.mutate(edge.id)}>
          削除
        </button>
      </div>
    </div>
  );
}

/** エッジPC管理画面（一覧・登録・有効フラグ切替・削除・接続テスト）。 */
export default function EdgePc() {
  const { data: edges = [], isLoading } = useEdgePcs();
  const create = useCreateEdgePc();
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");

  const submit = () => {
    if (!name || !host) return;
    const payload: { name: string; host: string; model_port?: number } = { name, host };
    if (port) payload.model_port = Number(port);
    create.mutate(payload);
    setName("");
    setHost("");
    setPort("");
  };

  return (
    <section>
      <h1>エッジPC管理</h1>

      <div className={styles.panel}>
        <div className={styles.field}>
          <label htmlFor="edge-name">名称</label>
          <input id="edge-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label htmlFor="edge-host">ホスト</label>
          <input id="edge-host" value={host} onChange={(e) => setHost(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label htmlFor="edge-port">ポート</label>
          <input
            id="edge-port"
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          />
        </div>
        <button type="button" className={styles.submitButton} onClick={submit}>
          登録
        </button>
      </div>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <div className={styles.grid}>
          {edges.map((e) => (
            <EdgeCard key={e.id} edge={e} />
          ))}
        </div>
      )}
    </section>
  );
}
