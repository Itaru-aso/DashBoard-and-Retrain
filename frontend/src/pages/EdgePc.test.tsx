import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/edgePcApi";

import EdgePc from "./EdgePc";

vi.mock("@/api/edgePcApi");

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const EDGE = {
  id: 5,
  name: "検査PC_1",
  host: "169.254.93.171",
  username: null,
  password: null,
  model_port: 2123,
  enabled: true,
  last_ftp_ok: null,
  last_ftp_checked_at: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

describe("EdgePc", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.listEdgePcs as Mock).mockResolvedValue([EDGE]);
    (api.createEdgePc as Mock).mockResolvedValue(EDGE);
    (api.updateEdgePc as Mock).mockResolvedValue({ ...EDGE, enabled: false });
    (api.deleteEdgePc as Mock).mockResolvedValue(undefined);
    (api.checkFtp as Mock).mockResolvedValue({ ...EDGE, last_ftp_ok: true });
  });

  it("一覧を表示する", async () => {
    renderWithClient(<EdgePc />);
    expect(await screen.findByText("検査PC_1")).toBeInTheDocument();
    expect(screen.getByText("169.254.93.171")).toBeInTheDocument();
  });

  it("登録 API を呼ぶ", async () => {
    renderWithClient(<EdgePc />);
    await screen.findByText("検査PC_1");
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "検査PC_2" } });
    fireEvent.change(screen.getByLabelText("ホスト"), { target: { value: "10.0.0.2" } });
    fireEvent.change(screen.getByLabelText("ポート"), { target: { value: "21" } });
    fireEvent.click(screen.getByRole("button", { name: "登録" }));
    await waitFor(() =>
      expect(api.createEdgePc).toHaveBeenCalledWith({
        name: "検査PC_2",
        host: "10.0.0.2",
        model_port: 21,
      }),
    );
  });

  it("username/password を含めて登録 API を呼ぶ", async () => {
    renderWithClient(<EdgePc />);
    await screen.findByText("検査PC_1");
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "検査PC_2" } });
    fireEvent.change(screen.getByLabelText("ホスト"), { target: { value: "10.0.0.2" } });
    fireEvent.change(screen.getByLabelText("ユーザー名"), { target: { value: "ykk\\shisui_PJ" } });
    fireEvent.change(screen.getByLabelText("パスワード"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "登録" }));
    await waitFor(() =>
      expect(api.createEdgePc).toHaveBeenCalledWith({
        name: "検査PC_2",
        host: "10.0.0.2",
        username: "ykk\\shisui_PJ",
        password: "secret123",
      }),
    );
  });

  it("有効フラグ切替の更新 API を呼ぶ", async () => {
    renderWithClient(<EdgePc />);
    await screen.findByText("検査PC_1");
    fireEvent.click(screen.getByRole("button", { name: "無効化" }));
    await waitFor(() =>
      expect(api.updateEdgePc).toHaveBeenCalledWith(5, { enabled: false }),
    );
  });

  it("削除 API を呼ぶ", async () => {
    renderWithClient(<EdgePc />);
    await screen.findByText("検査PC_1");
    fireEvent.click(screen.getByRole("button", { name: "削除" }));
    await waitFor(() => expect(api.deleteEdgePc).toHaveBeenCalledWith(5));
  });

  it("接続テスト API を呼ぶ", async () => {
    renderWithClient(<EdgePc />);
    await screen.findByText("検査PC_1");
    fireEvent.click(screen.getByRole("button", { name: "接続テスト" }));
    await waitFor(() => expect(api.checkFtp).toHaveBeenCalledWith(5));
  });
});
