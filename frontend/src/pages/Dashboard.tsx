import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FixedSizeList } from "react-window";

import type { DashboardFilterParams } from "@/api/dashboardApi";
import {
  useMachines,
  useRecords,
  useSummary,
  useThresholdOverlay,
  useTrends,
} from "@/hooks/useDashboard";

import styles from "./Dashboard.module.css";
import { buildChartSeries, buildFaMissChartSeries } from "./dashboardChart";

function fmtPct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(2)}%`;
}

/** 検査結果ダッシュボード（推移・集計・明細・閾値重ね描き）。 */
export default function Dashboard() {
  const machines = useMachines();

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [colorNo, setColorNo] = useState("");
  const [size, setSize] = useState("");
  const [chain, setChain] = useState("");
  const [tape, setTape] = useState("");
  const [selectedMachines, setSelectedMachines] = useState<string[]>([]);
  const [applied, setApplied] = useState<DashboardFilterParams | null>(null);

  const fullTuple = applied && colorNo && size && chain;
  const ngOverlayParams = fullTuple
    ? { metric: "ng_rate", color_no: colorNo, size, chain, tape, from: applied.from, to: applied.to }
    : null;
  const faOverlayParams = fullTuple
    ? {
        metric: "false_alarm_rate",
        color_no: colorNo,
        size,
        chain,
        tape,
        from: applied.from,
        to: applied.to,
      }
    : null;
  const missOverlayParams = fullTuple
    ? { metric: "miss_rate", color_no: colorNo, size, chain, tape, from: applied.from, to: applied.to }
    : null;

  const trends = useTrends(applied);
  const summary = useSummary(applied);
  const records = useRecords(applied);
  const ngOverlay = useThresholdOverlay(ngOverlayParams);
  const faOverlay = useThresholdOverlay(faOverlayParams);
  const missOverlay = useThresholdOverlay(missOverlayParams);

  const ngChartData = useMemo(
    () => buildChartSeries(trends.data ?? [], ngOverlay.data ?? []),
    [trends.data, ngOverlay.data],
  );
  const faMissChartData = useMemo(
    () => buildFaMissChartSeries(trends.data ?? [], faOverlay.data ?? [], missOverlay.data ?? []),
    [trends.data, faOverlay.data, missOverlay.data],
  );
  const throughputChartData = useMemo(
    () => (trends.data ?? []).map((t) => ({ date: t.jst_date, throughput: t.throughput })),
    [trends.data],
  );

  const handleApply = (event: React.FormEvent) => {
    event.preventDefault();
    const params: DashboardFilterParams = { from: dateFrom, to: dateTo };
    if (colorNo) params.color_no = colorNo;
    if (size) params.size = size;
    if (chain) params.chain = chain;
    if (tape) params.tape = tape;
    if (selectedMachines.length > 0) params.machine_ids = selectedMachines;
    setApplied(params);
  };

  const recordList = records.data?.records ?? [];

  return (
    <section>
      <h1>検査結果ダッシュボード</h1>

      <form onSubmit={handleApply} className={`${styles.panel} ${styles.filterBar}`}>
        <div className={styles.filterField}>
          <label htmlFor="date-from">開始日</label>
          <input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="date-to">終了日</label>
          <input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="color-no">色番号</label>
          <input id="color-no" value={colorNo} onChange={(e) => setColorNo(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="size">サイズ</label>
          <input id="size" value={size} onChange={(e) => setSize(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="chain">チェーン</label>
          <input id="chain" value={chain} onChange={(e) => setChain(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="tape">テープ</label>
          <input id="tape" value={tape} onChange={(e) => setTape(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label htmlFor="machines">号機</label>
          <select
            id="machines"
            multiple
            value={selectedMachines}
            onChange={(e) =>
              setSelectedMachines(Array.from(e.target.selectedOptions, (o) => o.value))
            }
          >
            {(machines.data ?? []).map((m) => (
              <option key={m.unit} value={m.unit}>
                {m.unit}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className={styles.applyButton}>
          適用
        </button>
      </form>

      <h2>集計</h2>
      {summary.data ? (
        <div className={styles.summaryGrid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>スループット</span>
            <span className={styles.cardValue}>{summary.data.throughput}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>NG率</span>
            <span className={styles.cardValue}>{fmtPct(summary.data.ng_rate)}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>虚報率</span>
            <span className={styles.cardValue}>{fmtPct(summary.data.false_alarm_rate)}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>見逃し率</span>
            <span className={styles.cardValue}>{fmtPct(summary.data.miss_rate)}</span>
          </div>
        </div>
      ) : (
        <p>集計データなし</p>
      )}

      <h2>推移</h2>
      <div className={styles.chartsGrid}>
        <div className={styles.panel}>
          <span className={styles.panelTitle}>検査数（スループット）</span>
          <span className={styles.panelSubtitle}>日別 検査数</span>
          <BarChart width={480} height={236} data={throughputChartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="throughput" fill="#22d3ee" />
          </BarChart>
        </div>

        <div className={styles.panel}>
          <span className={styles.panelTitle}>NG率推移</span>
          <span className={styles.panelSubtitle}>日別 NG率・閾値</span>
          <LineChart width={480} height={236} data={ngChartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            {/* KPI が NULL の点は欠損として扱い線をつながない */}
            <Line type="monotone" dataKey="ng_rate" stroke="#22d3ee" connectNulls={false} />
            <Line type="stepAfter" dataKey="threshold" stroke="#fb7185" connectNulls={false} />
          </LineChart>
        </div>
      </div>

      <div className={styles.panel}>
        <span className={styles.panelTitle}>虚報率・見逃し率</span>
        <span className={styles.panelSubtitle}>各系列に閾値ライン（破線）を重畳</span>
        <LineChart width={980} height={248} data={faMissChartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="false_alarm_rate" stroke="#22d3ee" connectNulls={false} />
          <Line type="monotone" dataKey="miss_rate" stroke="#a78bfa" connectNulls={false} />
          <Line type="stepAfter" dataKey="fa_threshold" stroke="#22d3ee" strokeDasharray="4 4" connectNulls={false} />
          <Line
            type="stepAfter"
            dataKey="miss_threshold"
            stroke="#a78bfa"
            strokeDasharray="4 4"
            connectNulls={false}
          />
        </LineChart>
      </div>

      <h2>明細</h2>
      <div className={styles.recordList}>
        <FixedSizeList height={200} width={980} itemCount={recordList.length} itemSize={30}>
          {({ index, style }: { index: number; style: React.CSSProperties }) => {
            const r = recordList[index];
            return (
              <div style={style} className={styles.recordRow} data-testid="record-row">
                {r.image_id} / {r.unit} / {r.color_no}
              </div>
            );
          }}
        </FixedSizeList>
      </div>
    </section>
  );
}
