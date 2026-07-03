import { useState } from "react";

import type { EdgePc as EdgePcModel } from "@/api/edgePcApi";
import {
  useCheckFtp,
  useCreateEdgePc,
  useDeleteEdgePc,
  useEdgePcs,
  useUpdateEdgePc,
} from "@/hooks/useEdgePcs";

function ftpLabel(edge: EdgePcModel): string {
  if (edge.last_ftp_ok === null) return "未確認";
  return edge.last_ftp_ok ? "OK" : "NG";
}

function EdgeRow({ edge }: { edge: EdgePcModel }) {
  const update = useUpdateEdgePc();
  const remove = useDeleteEdgePc();
  const check = useCheckFtp();

  return (
    <tr>
      <td>{edge.name}</td>
      <td>{edge.host}</td>
      <td>{edge.model_port ?? ""}</td>
      <td>{edge.enabled ? "有効" : "無効"}</td>
      <td>{ftpLabel(edge)}</td>
      <td>
        <button
          type="button"
          onClick={() => update.mutate({ id: edge.id, payload: { enabled: !edge.enabled } })}
        >
          {edge.enabled ? "無効化" : "有効化"}
        </button>
        <button type="button" onClick={() => check.mutate(edge.id)}>
          接続テスト
        </button>
        <button type="button" onClick={() => remove.mutate(edge.id)}>
          削除
        </button>
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

      <div>
        <label htmlFor="edge-name">名称</label>
        <input id="edge-name" value={name} onChange={(e) => setName(e.target.value)} />
        <label htmlFor="edge-host">ホスト</label>
        <input id="edge-host" value={host} onChange={(e) => setHost(e.target.value)} />
        <label htmlFor="edge-port">ポート</label>
        <input
          id="edge-port"
          type="number"
          value={port}
          onChange={(e) => setPort(e.target.value)}
        />
        <button type="button" onClick={submit}>
          登録
        </button>
      </div>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>ホスト</th>
              <th>ポート</th>
              <th>状態</th>
              <th>FTP</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {edges.map((e) => (
              <EdgeRow key={e.id} edge={e} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
