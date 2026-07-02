import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/thresholdApi";

import ThresholdManagement from "./ThresholdManagement";

vi.mock("@/api/thresholdApi");

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const SAMPLE = {
  id: 1,
  metric: "ng_rate",
  scope: "global",
  color_no: null,
  size: null,
  chain: null,
  tape: null,
  value_pct: 5,
  valid_from: "2026-01-01T00:00:00Z",
  valid_to: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ThresholdManagement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("一覧に既存の閾値を表示する", async () => {
    (api.listThresholds as Mock).mockResolvedValue([SAMPLE]);
    renderWithClient(<ThresholdManagement />);
    expect(await screen.findByText("ng_rate")).toBeInTheDocument();
  });

  it("正しい入力で登録 API を呼ぶ", async () => {
    (api.listThresholds as Mock).mockResolvedValue([]);
    (api.createThreshold as Mock).mockResolvedValue(SAMPLE);
    renderWithClient(<ThresholdManagement />);

    fireEvent.change(screen.getByLabelText("閾値(%)"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("有効開始"), {
      target: { value: "2026-01-01T00:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登録" }));

    await waitFor(() => expect(api.createThreshold).toHaveBeenCalledTimes(1));
  });

  it("値域外はバリデーションエラーを表示し登録しない", async () => {
    (api.listThresholds as Mock).mockResolvedValue([]);
    renderWithClient(<ThresholdManagement />);

    fireEvent.change(screen.getByLabelText("閾値(%)"), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText("有効開始"), {
      target: { value: "2026-01-01T00:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登録" }));

    expect(await screen.findByText(/0〜100/)).toBeInTheDocument();
    expect(api.createThreshold).not.toHaveBeenCalled();
  });
});
