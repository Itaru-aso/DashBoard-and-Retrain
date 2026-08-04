import { describe, expect, it } from "vitest";

import {
  CHART_AXIS_FONT_SIZE,
  CHART_BAR_RADIUS,
  CHART_GRID_COLOR,
  CHART_LINE_WIDTH,
  CHART_SERIES_1_COLOR,
  CHART_SERIES_2_COLOR,
  CHART_THRESHOLD_COLOR,
  CHART_THRESHOLD_DASH,
  chartAxisTickStyle,
  chartTooltipContentStyle,
} from "./chartTheme";

describe("chartTheme", () => {
  it("グリッド線・軸色はtokens.cssのdesign.md §7対応色をリテラルhexで複製する（Chromiumのプレゼンテーション属性var()制約のため）", () => {
    expect(CHART_GRID_COLOR).toBe("#ece7d8");
    expect(CHART_AXIS_FONT_SIZE).toBe(11);
  });

  it("系列1(藍)・系列2(辛子)・閾値(赤)の色は互いに異なるhex値である", () => {
    expect(CHART_SERIES_1_COLOR).toBe("#3568ad");
    expect(CHART_SERIES_2_COLOR).toBe("#a87400");
    expect(CHART_THRESHOLD_COLOR).toBe("#b3402e");
    const colors = new Set([CHART_SERIES_1_COLOR, CHART_SERIES_2_COLOR, CHART_THRESHOLD_COLOR]);
    expect(colors.size).toBe(3);
  });

  it("線幅は2px、閾値線の破線パターンは6 4である", () => {
    expect(CHART_LINE_WIDTH).toBe(2);
    expect(CHART_THRESHOLD_DASH).toBe("6 4");
  });

  it("棒グラフは上角丸2pxである", () => {
    expect(CHART_BAR_RADIUS).toEqual([2, 2, 0, 0]);
  });

  it("軸目盛は11px・--color-text-secondary相当のhexを使う", () => {
    expect(chartAxisTickStyle.fontSize).toBe(11);
    expect(chartAxisTickStyle.fill).toBe("#6f6a5c");
  });

  it("ツールチップは生成りカード様式（surface/border/radius）を使う", () => {
    expect(chartTooltipContentStyle.background).toBe("var(--color-surface)");
    expect(chartTooltipContentStyle.border).toContain("var(--color-border)");
    expect(chartTooltipContentStyle.borderRadius).toBe("var(--radius)");
  });
});
