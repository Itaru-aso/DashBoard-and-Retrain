import type { OverlayPoint, TrendPoint } from "@/api/dashboardApi";

// recharts に渡す1日ぶんの行。NULL の KPI は null のまま保持し、線をつながない
// （recharts の connectNulls=false と組み合わせて欠損描画）。
export interface ChartRow {
  date: string;
  ng_rate: number | null;
  false_alarm_rate: number | null;
  miss_rate: number | null;
  threshold: number | null;
}

/** 推移系列と閾値系列を日付で突き合わせ、欠損を保持したチャート行に変換する。 */
export function buildChartSeries(
  trends: TrendPoint[],
  overlay: OverlayPoint[],
): ChartRow[] {
  const byDate = new Map<string, ChartRow>();

  for (const t of trends) {
    byDate.set(t.jst_date, {
      date: t.jst_date,
      ng_rate: t.ng_rate,
      false_alarm_rate: t.false_alarm_rate,
      miss_rate: t.miss_rate,
      threshold: null,
    });
  }

  for (const o of overlay) {
    const existing = byDate.get(o.jst_date) ?? {
      date: o.jst_date,
      ng_rate: null,
      false_alarm_rate: null,
      miss_rate: null,
      threshold: null,
    };
    existing.threshold = o.value_pct;
    byDate.set(o.jst_date, existing);
  }

  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
}

// 虚報率・見逃し率チャート用の1日ぶんの行（それぞれ別の閾値系列を持つ）。
export interface FaMissChartRow {
  date: string;
  false_alarm_rate: number | null;
  miss_rate: number | null;
  fa_threshold: number | null;
  miss_threshold: number | null;
}

/** 推移・虚報率閾値・見逃し率閾値の3系列を日付で突き合わせる。 */
export function buildFaMissChartSeries(
  trends: TrendPoint[],
  faOverlay: OverlayPoint[],
  missOverlay: OverlayPoint[],
): FaMissChartRow[] {
  const byDate = new Map<string, FaMissChartRow>();

  const getRow = (date: string): FaMissChartRow => {
    let row = byDate.get(date);
    if (!row) {
      row = { date, false_alarm_rate: null, miss_rate: null, fa_threshold: null, miss_threshold: null };
      byDate.set(date, row);
    }
    return row;
  };

  for (const t of trends) {
    const row = getRow(t.jst_date);
    row.false_alarm_rate = t.false_alarm_rate;
    row.miss_rate = t.miss_rate;
  }
  for (const o of faOverlay) {
    getRow(o.jst_date).fa_threshold = o.value_pct;
  }
  for (const o of missOverlay) {
    getRow(o.jst_date).miss_threshold = o.value_pct;
  }

  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
}
