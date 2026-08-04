/**
 * design.md §7「チャート共通仕様」の定数（recharts の各チャートから参照する）。
 *
 * 色は tokens.css の同名変数の値をリテラル(hex)で複製している。recharts は
 * stroke/fill を SVG のプレゼンテーション属性として設定するため、Chromium系
 * ブラウザでは `var(--x)` がプレゼンテーション属性上で解決されない
 * （style属性経由でのみ解決される）。tokens.css の値を変更した場合は
 * ここも合わせて更新すること。
 */

export const CHART_GRID_COLOR = "#ece7d8"; // tokens.css --chart-grid
export const CHART_AXIS_LINE_COLOR = "#ddd6c4"; // tokens.css --chart-axis
export const CHART_AXIS_TEXT_COLOR = "#6f6a5c"; // tokens.css --color-text-secondary
export const CHART_AXIS_FONT_SIZE = 11;

export const CHART_SERIES_1_COLOR = "#3568ad"; // tokens.css --chart-series-1（藍）
export const CHART_SERIES_2_COLOR = "#a87400"; // tokens.css --chart-series-2（辛子）
export const CHART_THRESHOLD_COLOR = "#b3402e"; // tokens.css --chart-threshold（赤）

export const CHART_LINE_WIDTH = 2;
export const CHART_THRESHOLD_DASH = "6 4";

// 最終点マーカー（design.md §7: 白縁3.5px）。実際の <circle> 描画は各ページで組む。
export const CHART_DOT_RADIUS = 3.5;
export const CHART_DOT_STROKE_COLOR = "#fdfcf8"; // tokens.css --color-surface
export const CHART_DOT_STROKE_WIDTH = 2;

// 棒グラフ: 藍単色＋上角丸2px（[topLeft, topRight, bottomRight, bottomLeft]）。
export const CHART_BAR_RADIUS: [number, number, number, number] = [2, 2, 0, 0];

export const chartAxisTickStyle = {
  fontSize: CHART_AXIS_FONT_SIZE,
  fill: CHART_AXIS_TEXT_COLOR,
};

// ツールチップ: 生成りカード様式（surface + border + radius）。
export const chartTooltipContentStyle = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius)",
  fontSize: "var(--font-size-caption)",
  color: "var(--color-text-primary)",
};
