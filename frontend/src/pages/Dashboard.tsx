import { useMemo, useState } from "react";
import {
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

import { buildChartSeries } from "./dashboardChart";

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

  const overlayParams =
    applied && colorNo && size && chain
      ? {
          metric: "ng_rate",
          color_no: colorNo,
          size,
          chain,
          tape,
          from: applied.from,
          to: applied.to,
        }
      : null;

  const trends = useTrends(applied);
  const summary = useSummary(applied);
  const records = useRecords(applied);
  const overlay = useThresholdOverlay(overlayParams);

  const chartData = useMemo(
    () => buildChartSeries(trends.data ?? [], overlay.data ?? []),
    [trends.data, overlay.data],
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

      <form onSubmit={handleApply}>
        <label htmlFor="date-from">開始日</label>
        <input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <label htmlFor="date-to">終了日</label>
        <input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <label htmlFor="color-no">色番号</label>
        <input id="color-no" value={colorNo} onChange={(e) => setColorNo(e.target.value)} />
        <label htmlFor="size">サイズ</label>
        <input id="size" value={size} onChange={(e) => setSize(e.target.value)} />
        <label htmlFor="chain">チェーン</label>
        <input id="chain" value={chain} onChange={(e) => setChain(e.target.value)} />
        <label htmlFor="tape">テープ</label>
        <input id="tape" value={tape} onChange={(e) => setTape(e.target.value)} />
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
        <button type="submit">適用</button>
      </form>

      <h2>集計</h2>
      {summary.data ? (
        <table>
          <tbody>
            <tr>
              <th>スループット</th>
              <td>{summary.data.throughput}</td>
            </tr>
            <tr>
              <th>NG率</th>
              <td>{fmtPct(summary.data.ng_rate)}</td>
            </tr>
            <tr>
              <th>虚報率</th>
              <td>{fmtPct(summary.data.false_alarm_rate)}</td>
            </tr>
            <tr>
              <th>見逃し率</th>
              <td>{fmtPct(summary.data.miss_rate)}</td>
            </tr>
          </tbody>
        </table>
      ) : (
        <p>集計データなし</p>
      )}

      <h2>推移</h2>
      <LineChart width={600} height={300} data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" />
        <YAxis />
        <Tooltip />
        {/* KPI が NULL の点は欠損として扱い線をつながない */}
        <Line type="monotone" dataKey="ng_rate" stroke="#c00" connectNulls={false} />
        {/* 閾値ライン（階段・欠損） */}
        <Line type="stepAfter" dataKey="threshold" stroke="#08c" connectNulls={false} />
      </LineChart>

      <h2>明細</h2>
      <FixedSizeList
        height={200}
        width={600}
        itemCount={recordList.length}
        itemSize={30}
      >
        {({ index, style }: { index: number; style: React.CSSProperties }) => {
          const r = recordList[index];
          return (
            <div style={style} data-testid="record-row">
              {r.image_id} / {r.unit} / {r.color_no}
            </div>
          );
        }}
      </FixedSizeList>
    </section>
  );
}
