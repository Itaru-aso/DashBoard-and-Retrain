import { useMemo, useState } from "react";
import type { ReactElement } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FixedSizeList } from "react-window";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatTile } from "@/components/ui/StatTile";
import type { StatusVariant } from "@/components/ui/StatusChip";
import type { DashboardFilterParams } from "@/api/dashboardApi";
import {
  useMachines,
  useRecords,
  useSummary,
  useThresholdOverlay,
  useTrends,
} from "@/hooks/useDashboard";
import {
  CHART_AXIS_LINE_COLOR,
  CHART_BAR_RADIUS,
  CHART_DOT_RADIUS,
  CHART_DOT_STROKE_COLOR,
  CHART_DOT_STROKE_WIDTH,
  CHART_GRID_COLOR,
  CHART_LINE_WIDTH,
  CHART_SERIES_1_COLOR,
  CHART_SERIES_2_COLOR,
  CHART_THRESHOLD_COLOR,
  CHART_THRESHOLD_DASH,
  chartAxisTickStyle,
  chartTooltipContentStyle,
} from "@/styles/chartTheme";

import styles from "./Dashboard.module.css";
import { buildChartSeries, buildFaMissChartSeries } from "./dashboardChart";

const PERIOD_OPTIONS = [
  { value: "7", label: "7日" },
  { value: "30", label: "30日" },
  { value: "90", label: "90日" },
];

function fmtPct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(2)}%`;
}

// ローカル日付部分から yyyy-mm-dd を組み立てる（toISOString はUTCへ変換するため使わない。
// 既存の <input type="date"> もローカル日付を扱うため、ここも合わせる）。
function toDateInputValue(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 折れ線の最終点にのみ白縁マーカーを描く recharts の dot 関数（design.md §7）。 */
function createLastPointDot(color: string, dataLength: number) {
  return (props: { cx?: number; cy?: number; index?: number }): ReactElement => {
    const { cx, cy, index } = props;
    if (index !== dataLength - 1 || cx === undefined || cy === undefined) {
      return <circle cx={cx} cy={cy} r={0} />;
    }
    return (
      <circle
        cx={cx}
        cy={cy}
        r={CHART_DOT_RADIUS}
        fill={color}
        stroke={CHART_DOT_STROKE_COLOR}
        strokeWidth={CHART_DOT_STROKE_WIDTH}
      />
    );
  };
}

/** KPIタイル用の小型スパークライン（軸・目盛なし、全タイル藍単色。design.md §6.1.3）。 */
function Sparkline({ data, dataKey }: { data: readonly unknown[]; dataKey: string }) {
  return (
    <LineChart width={72} height={24} data={data}>
      <Line
        type="monotone"
        dataKey={dataKey}
        stroke={CHART_SERIES_1_COLOR}
        strokeWidth={CHART_LINE_WIDTH}
        dot={false}
        connectNulls={false}
      />
    </LineChart>
  );
}

/** overlay配列（未整列）から日付降順で最新の閾値(%)を取り出す。無ければ null。 */
function latestThresholdPct(overlay: { jst_date: string; value_pct: number }[] | undefined): number | null {
  if (!overlay || overlay.length === 0) return null;
  return [...overlay].sort((a, b) => (a.jst_date < b.jst_date ? 1 : -1))[0].value_pct;
}

/** rate(0-1)と最新閾値(0-100)を同じ%スケールに揃えた上で「閾値まで残りpt」を計算する。 */
function remainingPt(rate: number | null, thresholdPct: number | null): number | null {
  if (rate === null || thresholdPct === null) return null;
  return thresholdPct - rate * 100;
}

function remainingStatus(remaining: number | null): { status: StatusVariant; label: string } | null {
  if (remaining === null) return null;
  return remaining < 0 ? { status: "bad", label: "逸脱" } : { status: "ok", label: "正常" };
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
  const [periodDays, setPeriodDays] = useState<string | null>(null);

  const handlePeriodChange = (value: string) => {
    setPeriodDays(value);
    const days = Number(value);
    const to = new Date();
    const from = new Date(to);
    from.setDate(from.getDate() - (days - 1));
    setDateFrom(toDateInputValue(from));
    setDateTo(toDateInputValue(to));
  };

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

  // KPIタイルの「閾値まで残りpt」。rate(0-1)と最新閾値(0-100)を揃えて計算する。
  const ngRemaining = remainingPt(summary.data?.ng_rate ?? null, latestThresholdPct(ngOverlay.data));
  const faRemaining = remainingPt(summary.data?.false_alarm_rate ?? null, latestThresholdPct(faOverlay.data));
  const missRemaining = remainingPt(summary.data?.miss_rate ?? null, latestThresholdPct(missOverlay.data));
  const ngStatus = remainingStatus(ngRemaining);
  const faStatus = remainingStatus(faRemaining);
  const missStatus = remainingStatus(missRemaining);

  return (
    <section>
      <PageHeader title="検査結果ダッシュボード" description="検査KPIの日次推移と閾値の逸脱状況" />

      <Panel>
        <form onSubmit={handleApply} className={styles.filterBar}>
          <div className={styles.filterField}>
            <span className={styles.filterFieldLabel}>期間</span>
            <SegmentedControl options={PERIOD_OPTIONS} value={periodDays ?? ""} onChange={handlePeriodChange} />
          </div>
          <div className={styles.filterField}>
            <label htmlFor="date-from">開始日</label>
            <input
              id="date-from"
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setPeriodDays(null);
                setDateFrom(e.target.value);
              }}
            />
          </div>
          <div className={styles.filterField}>
            <label htmlFor="date-to">終了日</label>
            <input
              id="date-to"
              type="date"
              value={dateTo}
              onChange={(e) => {
                setPeriodDays(null);
                setDateTo(e.target.value);
              }}
            />
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
          <Button type="submit">適用</Button>
        </form>
      </Panel>

      {summary.data ? (
        <div className={styles.statTileGrid}>
          <StatTile
            label="検査数"
            value={String(summary.data.throughput)}
            sparkline={<Sparkline data={throughputChartData} dataKey="throughput" />}
          />
          <StatTile
            label="NG率"
            value={fmtPct(summary.data.ng_rate)}
            status={ngStatus?.status}
            statusLabel={ngStatus?.label}
            caption={ngRemaining !== null ? `閾値まで残り${ngRemaining.toFixed(1)}pt` : undefined}
            sparkline={<Sparkline data={ngChartData} dataKey="ng_rate" />}
          />
          <StatTile
            label="虚報率"
            value={fmtPct(summary.data.false_alarm_rate)}
            status={faStatus?.status}
            statusLabel={faStatus?.label}
            caption={faRemaining !== null ? `閾値まで残り${faRemaining.toFixed(1)}pt` : undefined}
            sparkline={<Sparkline data={faMissChartData} dataKey="false_alarm_rate" />}
          />
          <StatTile
            label="見逃し率"
            value={fmtPct(summary.data.miss_rate)}
            status={missStatus?.status}
            statusLabel={missStatus?.label}
            caption={missRemaining !== null ? `閾値まで残り${missRemaining.toFixed(1)}pt` : undefined}
            sparkline={<Sparkline data={faMissChartData} dataKey="miss_rate" />}
          />
        </div>
      ) : (
        <p>集計データなし</p>
      )}

      <div className={styles.chartsGrid}>
        <Panel title="検査数（スループット）">
          <span className={styles.panelSubtitle}>日別 検査数</span>
          <BarChart width={480} height={260} data={throughputChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_COLOR} />
            <XAxis dataKey="date" tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
            <YAxis tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
            <Tooltip contentStyle={chartTooltipContentStyle} />
            <Bar dataKey="throughput" fill={CHART_SERIES_1_COLOR} radius={CHART_BAR_RADIUS} />
          </BarChart>
        </Panel>

        <Panel title="NG率推移">
          <span className={styles.panelSubtitle}>日別 NG率・閾値</span>
          <LineChart width={480} height={260} data={ngChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_COLOR} />
            <XAxis dataKey="date" tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
            <YAxis tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
            <Tooltip contentStyle={chartTooltipContentStyle} />
            {/* KPI が NULL の点は欠損として扱い線をつながない */}
            <Line
              type="monotone"
              dataKey="ng_rate"
              stroke={CHART_SERIES_1_COLOR}
              strokeWidth={CHART_LINE_WIDTH}
              dot={createLastPointDot(CHART_SERIES_1_COLOR, ngChartData.length)}
              connectNulls={false}
            />
            {/* 系列が1本のチャートなので閾値は赤固定（design.md §7） */}
            <Line
              type="stepAfter"
              dataKey="threshold"
              stroke={CHART_THRESHOLD_COLOR}
              strokeWidth={CHART_LINE_WIDTH}
              strokeDasharray={CHART_THRESHOLD_DASH}
              dot={false}
              connectNulls={false}
            />
          </LineChart>
        </Panel>
      </div>

      <Panel title="虚報率・見逃し率">
        <span className={styles.panelSubtitle}>各系列に閾値ライン（破線）を重畳</span>
        <LineChart width={980} height={270} data={faMissChartData}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_COLOR} />
          <XAxis dataKey="date" tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
          <YAxis tick={chartAxisTickStyle} axisLine={{ stroke: CHART_AXIS_LINE_COLOR }} />
          <Tooltip contentStyle={chartTooltipContentStyle} />
          <Legend />
          <Line
            type="monotone"
            dataKey="false_alarm_rate"
            name="虚報率"
            stroke={CHART_SERIES_1_COLOR}
            strokeWidth={CHART_LINE_WIDTH}
            dot={createLastPointDot(CHART_SERIES_1_COLOR, faMissChartData.length)}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="miss_rate"
            name="見逃し率"
            stroke={CHART_SERIES_2_COLOR}
            strokeWidth={CHART_LINE_WIDTH}
            dot={createLastPointDot(CHART_SERIES_2_COLOR, faMissChartData.length)}
            connectNulls={false}
          />
          {/* 閾値は対応する系列と同色（design.md §7） */}
          <Line
            type="stepAfter"
            dataKey="fa_threshold"
            name="虚報率 閾値"
            stroke={CHART_SERIES_1_COLOR}
            strokeWidth={CHART_LINE_WIDTH}
            strokeDasharray={CHART_THRESHOLD_DASH}
            dot={false}
            connectNulls={false}
          />
          <Line
            type="stepAfter"
            dataKey="miss_threshold"
            name="見逃し率 閾値"
            stroke={CHART_SERIES_2_COLOR}
            strokeWidth={CHART_LINE_WIDTH}
            strokeDasharray={CHART_THRESHOLD_DASH}
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      </Panel>

      <Panel title="明細">
        <div className={styles.recordHeader}>
          <span className={styles.recordHeaderCell}>状態</span>
          <span className={styles.recordHeaderCell}>画像ID</span>
          <span className={styles.recordHeaderCell}>号機</span>
          <span className={styles.recordHeaderCell}>色番号</span>
        </div>
        <FixedSizeList height={240} width={980} itemCount={recordList.length} itemSize={40}>
          {({ index, style }: { index: number; style: React.CSSProperties }) => {
            const r = recordList[index];
            const dotClass =
              r.judgment_result === 0
                ? styles.recordDotOk
                : r.judgment_result === 1
                  ? styles.recordDotBad
                  : styles.recordDotNeutral;
            return (
              <div style={style} className={styles.recordRow} data-testid="record-row">
                <span className={`${styles.recordDot} ${dotClass}`} />
                <span className={styles.recordCellNumeric}>{r.image_id}</span>
                <span>{r.unit}</span>
                <span>{r.color_no}</span>
              </div>
            );
          }}
        </FixedSizeList>
      </Panel>
    </section>
  );
}
