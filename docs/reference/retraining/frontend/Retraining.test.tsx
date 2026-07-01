// 配置先: frontend/src/pages/Retraining.test.tsx
// Vitest + Testing Library。API は ../api/retrainingApi をモック、WebSocket はフェイクに差し替える。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import Retraining from "./Retraining";
import * as api from "../api/retrainingApi";

vi.mock("../api/retrainingApi", async () => {
  const actual = await vi.importActual<typeof import("../api/retrainingApi")>("../api/retrainingApi");
  return {
    ...actual, // isTerminal / TERMINAL など純関数は実物を使う
    listJobs: vi.fn(),
    getJob: vi.fn(),
    createJob: vi.fn(),
    cancelJob: vi.fn(),
    listDeployed: vi.fn(),
    deployJob: vi.fn(),
    progressWsUrl: vi.fn((id: number) => `ws://test/api/retraining/jobs/${id}/progress`),
  };
});

const mocked = api as unknown as {
  listJobs: ReturnType<typeof vi.fn>;
  createJob: ReturnType<typeof vi.fn>;
  cancelJob: ReturnType<typeof vi.fn>;
  listDeployed: ReturnType<typeof vi.fn>;
};

// ---- WebSocket フェイク ----
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onclose: ((e: unknown) => void) | null = null;
  readyState = 0;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.({});
    });
  }
  emit(line: string) {
    this.onmessage?.({ data: line });
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const job = (over: Partial<api.Job> = {}): api.Job => ({
  id: 1, color_no: "501", size: "05", chain: "CZT8", tape: "",
  status: "RUNNING", queued_at: new Date().toISOString(),
  started_at: null, finished_at: null, error_message: null,
  onnx_monochro_path: null, onnx_color_path: null, created_by: null, ...over,
});

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  FakeWebSocket.instances = [];
  mocked.listJobs.mockResolvedValue({ items: [], limit: 50, offset: 0 });
  mocked.listDeployed.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("Retraining 画面", () => {
  it("空のときは起票を促す", async () => {
    render(<Retraining />, { wrapper });
    expect(await screen.findByText(/まだ再学習はありません/)).toBeInTheDocument();
    expect(screen.getByText(/配信済みの現行モデルはまだありません/)).toBeInTheDocument();
  });

  it("起票フォームを送信すると createJob が呼ばれる（フルタプル＋起票者）", async () => {
    const user = userEvent.setup();
    mocked.createJob.mockResolvedValue(job({ status: "QUEUED" }));
    render(<Retraining />, { wrapper });

    await user.type(screen.getByLabelText("色番"), "501");
    await user.type(screen.getByLabelText("サイズ"), "05");
    await user.type(screen.getByLabelText("チェーン"), "CZT8");
    await user.type(screen.getByLabelText("起票者"), "op1");
    await user.click(screen.getByRole("button", { name: "再学習を起票" }));

    await waitFor(() =>
      expect(mocked.createJob).toHaveBeenCalledWith({
        color_no: "501", size: "05", chain: "CZT8", tape: "", created_by: "op1",
      }),
    );
  });

  it("必須未入力では起票ボタンが無効", async () => {
    render(<Retraining />, { wrapper });
    expect(await screen.findByRole("button", { name: "再学習を起票" })).toBeDisabled();
  });

  it("履歴を一覧表示し、進捗を開くと WS の行が素通し表示される", async () => {
    const user = userEvent.setup();
    mocked.listJobs.mockResolvedValue({ items: [job({ id: 7, status: "RUNNING" })], limit: 50, offset: 0 });
    render(<Retraining />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "進捗" }));

    // WS 接続が張られ、サーバ行が表示に反映される
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));
    ws.emit("学習開始");
    ws.emit("Validation Loss: 0.12");
    ws.emit("パイプライン完了");

    const log = await screen.findByLabelText("学習ログ");
    await waitFor(() => {
      expect(within(log).getByText(/学習開始/)).toBeInTheDocument();
      expect(within(log).getByText(/パイプライン完了/)).toBeInTheDocument();
    });
  });

  it("非終端ジョブはキャンセルでき cancelJob が呼ばれる", async () => {
    const user = userEvent.setup();
    mocked.listJobs.mockResolvedValue({ items: [job({ id: 9, status: "QUEUED" })], limit: 50, offset: 0 });
    mocked.cancelJob.mockResolvedValue({ job_id: 9, accepted: true });
    render(<Retraining />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "キャンセル" }));
    await waitFor(() => expect(mocked.cancelJob).toHaveBeenCalledWith(9));
  });

  it("終端ジョブにはキャンセルボタンを出さない", async () => {
    mocked.listJobs.mockResolvedValue({ items: [job({ id: 3, status: "COMPLETED" })], limit: 50, offset: 0 });
    render(<Retraining />, { wrapper });
    expect(await screen.findByRole("button", { name: "進捗" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "キャンセル" })).not.toBeInTheDocument();
  });

  it("現行配信モデルを一覧表示する", async () => {
    mocked.listDeployed.mockResolvedValue([{
      id: 1, color_no: "501", size: "05", chain: "CZT8", tape: "",
      job_id: 7, onnx_monochro_path: "m", onnx_color_path: "c",
      deploy_status: "SUCCESS", deployed_at: new Date().toISOString(),
    }]);
    render(<Retraining />, { wrapper });
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(screen.getByText("SUCCESS")).toBeInTheDocument();
  });

  it("起票失敗時はエラーを表示する", async () => {
    const user = userEvent.setup();
    mocked.createJob.mockRejectedValue(new api.ApiError(404, "color_master に存在しない色です"));
    render(<Retraining />, { wrapper });
    await user.type(screen.getByLabelText("色番"), "999");
    await user.type(screen.getByLabelText("サイズ"), "05");
    await user.type(screen.getByLabelText("チェーン"), "CZT8");
    await user.click(screen.getByRole("button", { name: "再学習を起票" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/存在しない色/);
  });
});
