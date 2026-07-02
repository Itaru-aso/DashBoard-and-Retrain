import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/dashboardApi";

import Dashboard from "./Dashboard";

vi.mock("@/api/dashboardApi");

// recharts / react-window は jsdom で扱いにくいため軽量スタブに置換する。
vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    LineChart: Passthrough,
    Line: () => null,
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
});
