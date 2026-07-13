import { useState } from "react";

import type { ThresholdCreatePayload } from "@/api/thresholdApi";
import {
  useCreateThreshold,
  useDisableThreshold,
  useThresholds,
} from "@/hooks/useThresholds";

import styles from "./ThresholdManagement.module.css";

const METRICS = ["ng_rate", "false_alarm_rate", "miss_rate"] as const;
const SCOPES = ["global", "per_color"] as const;

/** 閾値管理画面（一覧・登録・無効化）。 */
export default function ThresholdManagement() {
  const { data: thresholds = [], isLoading } = useThresholds();
  const createMutation = useCreateThreshold();
  const disableMutation = useDisableThreshold();

  const [metric, setMetric] = useState<string>("ng_rate");
  const [scope, setScope] = useState<string>("global");
  const [colorNo, setColorNo] = useState("");
  const [size, setSize] = useState("");
  const [chain, setChain] = useState("");
  const [tape, setTape] = useState("");
  const [valuePct, setValuePct] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isPerColor = scope === "per_color";

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    const value = Number(valuePct);
    if (valuePct === "" || Number.isNaN(value) || value < 0 || value > 100) {
      setError("閾値は 0〜100 の範囲で入力してください");
      return;
    }
    if (!validFrom) {
      setError("有効開始を入力してください");
      return;
    }
    if (isPerColor && (!colorNo || !size || !chain)) {
      setError("色別では色番号・サイズ・チェーンを入力してください");
      return;
    }

    const payload: ThresholdCreatePayload = {
      metric,
      scope,
      value_pct: value,
      valid_from: new Date(validFrom).toISOString(),
      ...(isPerColor
        ? { color_no: colorNo, size, chain, tape }
        : {}),
    };
    createMutation.mutate(payload);
  };

  return (
    <section>
      <h1>閾値管理</h1>

      <div className={styles.infoBanner}>
        <span className={styles.infoDot} />
        <span>
          閾値を超過した色×サイズ×チェーンには、保守タスクが自動生成されます。登録・無効化は即時反映されます。
        </span>
      </div>

      <form onSubmit={handleSubmit} className={styles.panel}>
        <div className={styles.field}>
          <label>
            メトリクス
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className={styles.field}>
          <label>
            スコープ
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              {SCOPES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
        {isPerColor && (
          <>
            <div className={styles.field}>
              <label>
                色番号
                <input value={colorNo} onChange={(e) => setColorNo(e.target.value)} />
              </label>
            </div>
            <div className={styles.field}>
              <label>
                サイズ
                <input value={size} onChange={(e) => setSize(e.target.value)} />
              </label>
            </div>
            <div className={styles.field}>
              <label>
                チェーン
                <input value={chain} onChange={(e) => setChain(e.target.value)} />
              </label>
            </div>
            <div className={styles.field}>
              <label>
                テープ
                <input value={tape} onChange={(e) => setTape(e.target.value)} />
              </label>
            </div>
          </>
        )}
        <div className={styles.field}>
          <label htmlFor="threshold-value">閾値(%)</label>
          <input
            id="threshold-value"
            type="number"
            className={styles.valueInput}
            value={valuePct}
            onChange={(e) => setValuePct(e.target.value)}
          />
        </div>
        <div className={styles.field}>
          <label htmlFor="threshold-valid-from">有効開始</label>
          <input
            id="threshold-valid-from"
            type="datetime-local"
            value={validFrom}
            onChange={(e) => setValidFrom(e.target.value)}
          />
        </div>
        <button type="submit" className={styles.submitButton}>
          登録
        </button>
      </form>

      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {isLoading ? (
        <p>読み込み中...</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>対象</th>
                <th>範囲</th>
                <th>現在値(%)</th>
                <th>開始日時</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {thresholds.map((t) => (
                <tr key={t.id}>
                  <td>{t.metric}</td>
                  <td>{t.scope}</td>
                  <td className={styles.mono}>{t.value_pct}</td>
                  <td className={styles.mono}>{t.valid_from}</td>
                  <td>
                    <button
                      type="button"
                      className={styles.disableButton}
                      onClick={() =>
                        disableMutation.mutate({
                          id: t.id,
                          validTo: new Date().toISOString(),
                        })
                      }
                    >
                      無効化
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
