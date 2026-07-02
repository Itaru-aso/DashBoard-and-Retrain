import { describe, expect, it } from "vitest";

import type { OverlayPoint, TrendPoint } from "@/api/dashboardApi";

import { buildChartSeries } from "./dashboardChart";

const trend = (jst_date: string, ng_rate: number | null): TrendPoint => ({
  jst_date,
  throughput: 10,
  ng_rate: ng_rate ?? 0,
  false_alarm_rate: ng_rate,
  miss_rate: ng_rate,
});

describe("buildChartSeries", () => {
  it("推移と閾値を日付で突き合わせ、日付昇順で返す", () => {
    const trends: TrendPoint[] = [trend("2026-07-02", 0.2), trend("2026-07-01", 0.1)];
    const overlay: OverlayPoint[] = [{ jst_date: "2026-07-01", value_pct: 5 }];

    const rows = buildChartSeries(trends, overlay);
    expect(rows.map((r) => r.date)).toEqual(["2026-07-01", "2026-07-02"]);
    expect(rows[0].threshold).toBe(5);
    expect(rows[1].threshold).toBeNull(); // 閾値なしの日は欠損
  });

  it("KPI が null の点は null のまま保持する（欠損描画）", () => {
    const trends: TrendPoint[] = [
      { jst_date: "2026-07-01", throughput: 8, ng_rate: 0.25, false_alarm_rate: null, miss_rate: null },
    ];
    const rows = buildChartSeries(trends, []);
    expect(rows[0].false_alarm_rate).toBeNull();
    expect(rows[0].miss_rate).toBeNull();
    expect(rows[0].ng_rate).toBe(0.25);
  });
});
