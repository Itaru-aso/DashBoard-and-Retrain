import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/dashboardApi";

import App from "./App";

vi.mock("@/api/dashboardApi");
vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    LineChart: Passthrough,
    BarChart: Passthrough,
    Line: () => null,
    Bar: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
  };
});
vi.mock("react-window", () => ({
  FixedSizeList: () => <div />,
}));

describe("App", () => {
  it("ルート / にアクセスすると /dashboard へリダイレクトされ、共通レイアウトとダッシュボードが描画される", async () => {
    (api.fetchMachines as Mock).mockResolvedValue([]);
    (api.fetchTrends as Mock).mockResolvedValue([]);
    (api.fetchSummary as Mock).mockResolvedValue(null);
    (api.fetchRecords as Mock).mockResolvedValue({ records: [], next_cursor: null });
    (api.fetchThresholdOverlay as Mock).mockResolvedValue([]);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Shisui")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "ダッシュボード" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("heading", { name: "検査結果ダッシュボード" })).toBeInTheDocument();
  });
});
