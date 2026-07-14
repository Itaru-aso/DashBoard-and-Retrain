import { useMemo, useState } from "react";

import type { Color } from "@/api/colorApi";
import { useColors, useImportColors, useUpdateSample } from "@/hooks/useColors";

import styles from "./ColorMaster.module.css";

function swatchColor(color: Color): string {
  if (color.rgb_r === null || color.rgb_g === null || color.rgb_b === null) {
    return "rgba(255,255,255,0.1)";
  }
  return `rgb(${color.rgb_r}, ${color.rgb_g}, ${color.rgb_b})`;
}

function ColorRow({ color }: { color: Color }) {
  const update = useUpdateSample();
  const [rgbR, setRgbR] = useState(color.rgb_r ?? 0);

  return (
    <tr>
      <td className={styles.mono}>{color.color_no}</td>
      <td className={styles.mono}>{`${color.size}/${color.chain}/${color.tape}`}</td>
      <td>{color.status}</td>
      <td>
        <div className={styles.swatchRow}>
          <span className={styles.swatch} style={{ background: swatchColor(color) }} />
          <input
            aria-label={`rgb-r-${color.id}`}
            type="number"
            className={styles.rgbInput}
            value={rgbR}
            onChange={(e) => setRgbR(Number(e.target.value))}
          />
          <button
            type="button"
            className={styles.actionButton}
            onClick={() => update.mutate({ id: color.id, payload: { rgb_r: rgbR } })}
          >
            保存
          </button>
        </div>
      </td>
    </tr>
  );
}

/** 色マスター画面（一覧・ステータス絞り込み・検索・取り込み・色見本編集）。 */
export default function ColorMaster() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const filter = status ? { status } : {};
  const { data: colors = [], isLoading } = useColors(filter);
  const { data: allColors = [] } = useColors({});
  const importColors = useImportColors();
  const [file, setFile] = useState<File | null>(null);

  const summary = useMemo(
    () => ({
      total: allColors.length,
      未実施: allColors.filter((c) => c.status === "未実施").length,
      量産検証: allColors.filter((c) => c.status === "量産検証").length,
      実生産: allColors.filter((c) => c.status === "実生産").length,
    }),
    [allColors],
  );

  const visibleColors = useMemo(
    () => (search ? colors.filter((c) => c.color_no.includes(search)) : colors),
    [colors, search],
  );

  return (
    <section>
      <h1>色マスター</h1>

      <div className={styles.summaryGrid}>
        <div className={styles.card}>
          <span className={styles.cardLabel}>登録色数</span>
          <span className={styles.cardValue} data-testid="summary-total">
            {summary.total}
          </span>
        </div>
        <div className={styles.card}>
          <span className={styles.cardLabel}>未実施</span>
          <span className={styles.cardValue} data-testid="summary-未実施">
            {summary.未実施}
          </span>
        </div>
        <div className={styles.card}>
          <span className={styles.cardLabel}>量産検証</span>
          <span className={styles.cardValue} data-testid="summary-量産検証">
            {summary.量産検証}
          </span>
        </div>
        <div className={styles.card}>
          <span className={styles.cardLabel}>実生産</span>
          <span className={styles.cardValue} data-testid="summary-実生産">
            {summary.実生産}
          </span>
        </div>
      </div>

      <div className={styles.toolbar}>
        <label htmlFor="status-filter">ステータス</label>
        <select id="status-filter" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">すべて</option>
          <option value="未実施">未実施</option>
          <option value="量産検証">量産検証</option>
          <option value="実生産">実生産</option>
        </select>

        <label htmlFor="color-search">色番検索</label>
        <input
          id="color-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="色番で検索"
        />

        <label htmlFor="import-file">ファイル</label>
        <input id="import-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button
          type="button"
          className={styles.actionButton}
          onClick={() => {
            if (file) importColors.mutate(file);
          }}
        >
          取り込み
        </button>
      </div>

      {importColors.isError && (
        <p className={styles.importError}>{(importColors.error as Error).message}</p>
      )}
      {importColors.isSuccess && (
        <p className={styles.importResult}>
          作成: {importColors.data.created}件 / 更新: {importColors.data.updated}件 / スキップ:{" "}
          {importColors.data.skipped}件
          {importColors.data.errors.length > 0 && ` / エラー: ${importColors.data.errors.join(", ")}`}
        </p>
      )}

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>色番号</th>
                <th>タプル</th>
                <th>状態</th>
                <th>色見本(R)</th>
              </tr>
            </thead>
            <tbody>
              {visibleColors.map((c) => (
                <ColorRow key={c.id} color={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
