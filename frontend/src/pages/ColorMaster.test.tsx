import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/colorApi";

import ColorMaster from "./ColorMaster";

vi.mock("@/api/colorApi");

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const COLOR = {
  id: 3,
  color_no: "001",
  size: "05",
  chain: "CZT8",
  tape: "",
  rgb_r: 10,
  rgb_g: 20,
  rgb_b: 30,
  lab_l: 50,
  lab_a: 1,
  lab_b: -2,
  status: "未実施",
  verification_at: null,
  production_at: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

const COLOR2 = { ...COLOR, id: 4, color_no: "002", status: "量産検証" };

describe("ColorMaster", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.listColors as Mock).mockResolvedValue([COLOR]);
    (api.importColors as Mock).mockResolvedValue({ created: 1, updated: 0, skipped: 0, errors: [] });
    (api.updateSample as Mock).mockResolvedValue(COLOR);
  });

  it("一覧を表示する", async () => {
    renderWithClient(<ColorMaster />);
    expect(await screen.findByText("001")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "未実施" })).toBeInTheDocument();
  });

  it("ファイル取り込み API を呼ぶ", async () => {
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");
    const file = new File(["x"], "colors.xlsx");
    fireEvent.change(screen.getByLabelText("ファイル"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "取り込み" }));
    await waitFor(() => expect(api.importColors).toHaveBeenCalledTimes(1));
  });

  it("取り込み成功時に結果件数を表示する", async () => {
    (api.importColors as Mock).mockResolvedValue({
      created: 3,
      updated: 2,
      skipped: 1,
      errors: [],
    });
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");
    const file = new File(["x"], "colors.xlsx");
    fireEvent.change(screen.getByLabelText("ファイル"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "取り込み" }));
    expect(await screen.findByText(/作成: 3件/)).toBeInTheDocument();
    expect(screen.getByText(/更新: 2件/)).toBeInTheDocument();
    expect(screen.getByText(/スキップ: 1件/)).toBeInTheDocument();
  });

  it("取り込み失敗時にエラーメッセージを表示する", async () => {
    (api.importColors as Mock).mockRejectedValue(new Error("ヘッダ行がありません"));
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");
    const file = new File(["x"], "colors.xlsx");
    fireEvent.change(screen.getByLabelText("ファイル"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "取り込み" }));
    expect(await screen.findByText("ヘッダ行がありません")).toBeInTheDocument();
  });

  it("色見本の保存 API を呼ぶ", async () => {
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");
    fireEvent.change(screen.getByLabelText("rgb-r-3"), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(api.updateSample).toHaveBeenCalledWith(3, { rgb_r: 99 }),
    );
  });

  it("ステータス別の件数をサマリーカードに表示する", async () => {
    (api.listColors as Mock).mockResolvedValue([COLOR, COLOR2]);
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");

    expect(screen.getByTestId("summary-total")).toHaveTextContent("2");
    expect(screen.getByTestId("summary-未実施")).toHaveTextContent("1");
    expect(screen.getByTestId("summary-量産検証")).toHaveTextContent("1");
  });

  it("色番検索で一覧を絞り込む", async () => {
    (api.listColors as Mock).mockResolvedValue([COLOR, COLOR2]);
    renderWithClient(<ColorMaster />);
    await screen.findByText("001");
    expect(screen.getByText("002")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("色番検索"), { target: { value: "002" } });

    expect(screen.queryByText("001")).not.toBeInTheDocument();
    expect(screen.getByText("002")).toBeInTheDocument();
  });
});
