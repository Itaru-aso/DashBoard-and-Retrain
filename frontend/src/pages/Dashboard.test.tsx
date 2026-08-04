import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/dashboardApi";
import {
  CHART_SERIES_1_COLOR,
  CHART_SERIES_2_COLOR,
  CHART_THRESHOLD_COLOR,
  CHART_THRESHOLD_DASH,
} from "@/styles/chartTheme";

import Dashboard from "./Dashboard";

vi.mock("@/api/dashboardApi");

// recharts / react-window は jsdom で扱いにくいため軽量スタブに置換する。
// Line/Bar は stroke/fill/strokeDasharray を data-* 属性に写し、配色の検証に使う。
vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    LineChart: Passthrough,
    BarChart: Passthrough,
    Line: (props: { dataKey: string; stroke?: string; strokeDasharray?: string }) => (
      <div
        data-testid={`line-${props.dataKey}`}
        data-stroke={props.stroke}
        data-dash={props.strokeDasharray}
      />
    ),
    Bar: (props: { dataKey: string; fill?: string }) => (
      <div data-testid={`bar-${props.dataKey}`} data-fill={props.fill} />
    ),
    Legend: () => <div data-testid="legend" />,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
  };
});
vi.mock("react-window", () => ({
  FixedSizeList: ({
    itemCount,
    children,
  }: {
    itemCount: number;
    children: (p: { index: number; style: object }) => ReactElement;
  }) => (
    <div>
      {Array.from({ length: itemCount }, (_, i) => (
        <div key={i}>{children({ index: i, style: {} })}</div>
      ))}
    </div>
  ),
}));

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.fetchMachines as Mock).mockResolvedValue([{ unit: "1" }, { unit: "2" }]);
    (api.fetchTrends as Mock).mockResolvedValue([]);
    (api.fetchSummary as Mock).mockResolvedValue({
      throughput: 14,
      ng_rate: 0.1,
      false_alarm_rate: null,
      miss_rate: null,
    });
    (api.fetchRecords as Mock).mockResolvedValue({
      records: [
        {
          image_id: 1,
          inspect_timestamp: "2026-07-01T10:00:00Z",
          unit: "1",
          camera_model: "camera1_image",
          judgment_result: 0,
          color_no: "501",
          size: "05",
          chain: "CZT8",
          tape: "",
        },
      ],
      next_cursor: null,
    });
    (api.fetchThresholdOverlay as Mock).mockResolvedValue([]);
  });

  it("適用でフィルタ（号機含む）を送信し、集計・明細を表示する", async () => {
    renderWithClient(<Dashboard />);

    // 号機一覧の読み込みを待つ
    await screen.findByRole("option", { name: "1" });

    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-07-03" } });
    fireEvent.click(screen.getByRole("button", { name: "適用" }));

    // 集計が表示される
    expect(await screen.findByText("14")).toBeInTheDocument();
    // 虚報率 NULL は "—"
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // 明細（react-window スタブ経由）
    await waitFor(() =>
      expect(screen.getAllByTestId("record-row").length).toBe(1),
    );

    // trends/summary が期間付きで呼ばれた
    await waitFor(() => expect(api.fetchSummary).toHaveBeenCalled());
    const call = (api.fetchSummary as Mock).mock.calls[0][0];
    expect(call.from).toBe("2026-07-01");
    expect(call.to).toBe("2026-07-03");
  });

  it("チャート配色はdesign.md §7のchartTheme定数に従う（単系列の閾値は赤・2系列は系列色）", () => {
    renderWithClient(<Dashboard />);

    expect(screen.getByTestId("bar-throughput")).toHaveAttribute("data-fill", CHART_SERIES_1_COLOR);

    expect(screen.getByTestId("line-ng_rate")).toHaveAttribute("data-stroke", CHART_SERIES_1_COLOR);
    expect(screen.getByTestId("line-threshold")).toHaveAttribute(
      "data-stroke",
      CHART_THRESHOLD_COLOR,
    );
    expect(screen.getByTestId("line-threshold")).toHaveAttribute(
      "data-dash",
      CHART_THRESHOLD_DASH,
    );

    expect(screen.getByTestId("line-false_alarm_rate")).toHaveAttribute(
      "data-stroke",
      CHART_SERIES_1_COLOR,
    );
    expect(screen.getByTestId("line-miss_rate")).toHaveAttribute(
      "data-stroke",
      CHART_SERIES_2_COLOR,
    );
    expect(screen.getByTestId("line-fa_threshold")).toHaveAttribute(
      "data-stroke",
      CHART_SERIES_1_COLOR,
    );
    expect(screen.getByTestId("line-miss_threshold")).toHaveAttribute(
      "data-stroke",
      CHART_SERIES_2_COLOR,
    );

    // 凡例は2系列以上のチャート（虚報率・見逃し率）にのみ表示する
    expect(screen.getAllByTestId("legend")).toHaveLength(1);
  });

  it("色・サイズ・チェーンが一意に定まる場合、NG率/虚報率/見逃し率それぞれの閾値を取得する", async () => {
    renderWithClient(<Dashboard />);

    await screen.findByRole("option", { name: "1" });

    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-07-03" } });
    fireEvent.change(screen.getByLabelText("色番号"), { target: { value: "501" } });
    fireEvent.change(screen.getByLabelText("サイズ"), { target: { value: "05" } });
    fireEvent.change(screen.getByLabelText("チェーン"), { target: { value: "CZT8" } });
    fireEvent.click(screen.getByRole("button", { name: "適用" }));

    await waitFor(() => {
      const metrics = (api.fetchThresholdOverlay as Mock).mock.calls.map((c) => c[0].metric);
      expect(metrics).toContain("ng_rate");
      expect(metrics).toContain("false_alarm_rate");
      expect(metrics).toContain("miss_rate");
    });
  });
});
