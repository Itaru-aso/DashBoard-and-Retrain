import { useState } from "react";

import type { EdgePc as EdgePcModel } from "@/api/edgePcApi";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { StatusChip } from "@/components/ui/StatusChip";
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

function ftpDotClass(edge: EdgePcModel): string {
  if (edge.last_ftp_ok === null) return styles.dotNeutral;
  return edge.last_ftp_ok ? styles.dotOk : styles.dotBad;
}

function EdgeRow({ edge }: { edge: EdgePcModel }) {
  const update = useUpdateEdgePc();
  const remove = useDeleteEdgePc();
  const check = useCheckFtp();

  return (
    <tr>
      <td>{edge.name}</td>
      <td className={styles.mono}>{edge.host}</td>
      <td className={styles.mono}>{edge.model_port ?? "—"}</td>
      <td>
        <span className={styles.connectionCell}>
          <span className={`${styles.dot} ${ftpDotClass(edge)}`} />
          {ftpLabel(edge)}
        </span>
      </td>
      <td>
        <StatusChip variant={edge.enabled ? "ok" : "neutral"}>
          {edge.enabled ? "有効" : "無効"}
        </StatusChip>
      </td>
      <td>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={() => check.mutate(edge.id)}>
            接続テスト
          </Button>
          <Button
            variant="secondary"
            onClick={() => update.mutate({ id: edge.id, payload: { enabled: !edge.enabled } })}
          >
            {edge.enabled ? "無効化" : "有効化"}
          </Button>
          <Button variant="danger" onClick={() => remove.mutate(edge.id)}>
            削除
          </Button>
        </div>
      </td>
    </tr>
  );
}

/** エッジPC管理画面（一覧・登録・有効フラグ切替・削除・接続テスト）。 */
export default function EdgePc() {
  const { data: edges = [], isLoading } = useEdgePcs();
  const create = useCreateEdgePc();
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const submit = () => {
    if (!name || !host) return;
    const payload: {
      name: string;
      host: string;
      model_port?: number;
      username?: string;
      password?: string;
    } = { name, host };
    if (port) payload.model_port = Number(port);
    if (username) payload.username = username;
    if (password) payload.password = password;
    create.mutate(payload);
    setName("");
    setHost("");
    setPort("");
    setUsername("");
    setPassword("");
  };

  return (
    <section>
      <PageHeader title="エッジPC管理" />

      <Panel title="エッジPCを登録">
        <div className={styles.form}>
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
          <div className={styles.field}>
            <label htmlFor="edge-username">ユーザー名</label>
            <input
              id="edge-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="edge-password">パスワード</label>
            <input
              id="edge-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button onClick={submit}>登録</Button>
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
                  <th>名称</th>
                  <th>ホスト</th>
                  <th>ポート</th>
                  <th>接続状態</th>
                  <th>状態</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {edges.map((e) => (
                  <EdgeRow key={e.id} edge={e} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </section>
  );
}
