import { useState } from "react";

import type { Color } from "@/api/colorApi";
import { useColors, useImportColors, useUpdateSample } from "@/hooks/useColors";

function ColorRow({ color }: { color: Color }) {
  const update = useUpdateSample();
  const [rgbR, setRgbR] = useState(color.rgb_r ?? 0);

  return (
    <tr>
      <td>{color.color_no}</td>
      <td>{`${color.size}/${color.chain}/${color.tape}`}</td>
      <td>{color.status}</td>
      <td>
        <input
          aria-label={`rgb-r-${color.id}`}
          type="number"
          value={rgbR}
          onChange={(e) => setRgbR(Number(e.target.value))}
        />
        <button
          type="button"
          onClick={() => update.mutate({ id: color.id, payload: { rgb_r: rgbR } })}
        >
          保存
        </button>
      </td>
    </tr>
  );
}

/** 色マスター画面（一覧・ステータス絞り込み・取り込み・色見本編集）。 */
export default function ColorMaster() {
  const [status, setStatus] = useState("");
  const filter = status ? { status } : {};
  const { data: colors = [], isLoading } = useColors(filter);
  const importColors = useImportColors();
  const [file, setFile] = useState<File | null>(null);

  return (
    <section>
      <h1>色マスター</h1>

      <label htmlFor="status-filter">ステータス</label>
      <select
        id="status-filter"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
      >
        <option value="">すべて</option>
        <option value="未実施">未実施</option>
        <option value="量産検証">量産検証</option>
        <option value="実生産">実生産</option>
      </select>

      <div>
        <label htmlFor="import-file">ファイル</label>
        <input
          id="import-file"
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          onClick={() => {
            if (file) importColors.mutate(file);
          }}
        >
          取り込み
        </button>
      </div>

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>色番号</th>
              <th>タプル</th>
              <th>状態</th>
              <th>色見本(R)</th>
            </tr>
          </thead>
          <tbody>
            {colors.map((c) => (
              <ColorRow key={c.id} color={c} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
