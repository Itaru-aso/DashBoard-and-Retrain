import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/retrainingApi";

import Retraining from "./Retraining";

vi.mock("@/api/retrainingApi", async () => {
  const actual = await vi.importActual<typeof import("@/api/retrainingApi")>(
    "@/api/retrainingApi",
  );
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
  id: 1,
  color_no: "501",
  size: "05",
  chain: "CZT8",
  tape: "",
  status: "RUNNING",
  queued_at: new Date("2026-07-01T00:00:00Z").toISOString(),
  started_at: null,
  finished_at: null,
  error_message: null,
  onnx_monochro_path: null,
  onnx_color_path: null,
  created_by: null,
  ...over,
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
    mocked.createJob.mockResolvedValue(job({ status: "QUEUED" }));
    render(<Retraining />, { wrapper });

    fireEvent.change(screen.getByLabelText("色番"), { target: { value: "501" } });
    fireEvent.change(screen.getByLabelText("サイズ"), { target: { value: "05" } });
    fireEvent.change(screen.getByLabelText("チェーン"), { target: { value: "CZT8" } });
    fireEvent.change(screen.getByLabelText("起票者"), { target: { value: "op1" } });
    fireEvent.click(screen.getByRole("button", { name: "再学習を起票" }));

    await waitFor(() =>
      expect(mocked.createJob).toHaveBeenCalledWith({
        color_no: "501",
        size: "05",
        chain: "CZT8",
        tape: "",
        created_by: "op1",
      }),
    );
  });

  it("必須未入力では起票ボタンが無効", async () => {
    render(<Retraining />, { wrapper });
    expect(await screen.findByRole("button", { name: "再学習を起票" })).toBeDisabled();
  });

  it("履歴を一覧表示し、進捗を開くと WS の行が素通し表示される", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 7, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));
    ws.emit("学習開始");
    ws.emit("パイプライン完了");

    const log = await screen.findByLabelText("学習ログ");
    await waitFor(() => {
      expect(within(log).getByText(/学習開始/)).toBeInTheDocument();
      expect(within(log).getByText(/パイプライン完了/)).toBeInTheDocument();
    });
  });

  it("非終端ジョブはキャンセルでき cancelJob が呼ばれる", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 9, status: "QUEUED" })],
      limit: 50,
      offset: 0,
    });
    mocked.cancelJob.mockResolvedValue({ job_id: 9, accepted: true });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "キャンセル" }));
    await waitFor(() => expect(mocked.cancelJob).toHaveBeenCalledWith(9));
  });

  it("終端ジョブにはキャンセルボタンを出さない", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 3, status: "COMPLETED" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });
    expect(await screen.findByRole("button", { name: "進捗" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "キャンセル" })).not.toBeInTheDocument();
  });

  it("現行配信モデルを一覧表示する", async () => {
    mocked.listDeployed.mockResolvedValue([
      {
        id: 1,
        color_no: "501",
        size: "05",
        chain: "CZT8",
        tape: "",
        job_id: 7,
        onnx_monochro_path: "m",
        onnx_color_path: "c",
        deploy_status: "SUCCESS",
        deployed_at: new Date("2026-07-01T00:00:00Z").toISOString(),
      },
    ]);
    render(<Retraining />, { wrapper });
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(screen.getByText("SUCCESS")).toBeInTheDocument();
  });

  it("tqdm進捗行は進捗バーに反映され、学習ログには重要行のみ表示される", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 11, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit("[monochro] 🟢 モノクロAIの学習を開始します...");
    ws.emit(
      "[monochro] Current loss: 0.37  :  91%|████████ | 22001/24120 [1:05:02<5:39:04,  9.60s/it]",
    );

    const bar = await screen.findByRole("progressbar", { name: "モノクロAI進捗" });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "91"));

    const log = screen.getByLabelText("学習ログ");
    expect(within(log).getByText(/モノクロAIの学習を開始します/)).toBeInTheDocument();
    expect(within(log).queryByText(/Current loss/)).not.toBeInTheDocument();
  });

  it("元ログは既定で折りたたまれ、開くと全行（進捗行含む）が見える", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 12, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit(
      "[color] Current loss: 0.10  :  10%|█ | 100/1000 [00:10<01:30, 10.0it/s]",
    );

    expect(screen.queryByLabelText("元ログ")).not.toBeVisible();
    fireEvent.click(screen.getByText("元ログを表示"));
    await waitFor(() => expect(screen.getByLabelText("元ログ")).toBeVisible());
    expect(within(screen.getByLabelText("元ログ")).getByText(/Current loss/)).toBeInTheDocument();
  });

  it("学習ループ以外の進捗（閾値計算等）で進捗バーが100%に誤表示されない", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 13, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit(
      "[color] Current loss: 0.3955  :  50%|████▉     | 12000/24120 [34:13<30:28,  6.63it/s]",
    );
    const bar = await screen.findByRole("progressbar", { name: "カラーAI進捗" });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "50"));

    // 学習完了直後に1回だけ走る閾値計算（totalが小さくすぐ100%に達する）。
    // これに引っ張られて進捗バーが100%へ飛んではならない。
    ws.emit(
      "[color] Computing threshold scores:  100%|██████████| 50/50 [00:03<00:00, 14.2it/s]",
    );
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "50"));
  });

  it("ステージ表示: マーカー行に応じて「現在の処理」ラベルが更新される", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 14, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    expect(screen.getByText("現在の処理: 起動中…")).toBeInTheDocument();

    ws.emit("バックアップ作成中...");
    await waitFor(() => expect(screen.getByText("現在の処理: バックアップ中")).toBeInTheDocument());

    ws.emit("並列学習 GPU 割当: monochro=GPU0, color=GPU1 (検出: 2枚)");
    await waitFor(() => expect(screen.getByText("現在の処理: 学習中")).toBeInTheDocument());
  });

  it("ステージ表示: 単調前進のみで、前段のマーカーが遅延到着しても後退しない", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 15, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit("Exported ONNX: /model_dir/501/monochro/501_monochro_model.onnx");
    await waitFor(() =>
      expect(screen.getByText("現在の処理: モデル出力・評価中")).toBeInTheDocument(),
    );

    // 並列学習中のcolor側の開始行が遅れて届いても、export_evalより前段のtrainingへは戻らない。
    ws.emit("🔵 カラーAIの学習を開始します... (物理 GPU: 1, 論理 cuda:0, color: 501)");
    await waitFor(() =>
      expect(screen.getByText("現在の処理: モデル出力・評価中")).toBeInTheDocument(),
    );
    expect(screen.queryByText("現在の処理: 学習中")).not.toBeInTheDocument();
  });

  it("tqdmフレームとValidation Loss出力が連結された行でもバー更新とログ表示が正しく行われる", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 16, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    // tqdmの最終フレームが改行を出さず、直後のprint("Validation Loss: ...")が
    // \r/\n無しでそのまま連結された行（実ログで観測）。
    ws.emit(
      "[color] Current loss: 0.5505  :   8%|▊         | 2000/24120 [05:55<55:31,  6.64it/s]Validation Loss: 3.0476",
    );

    const bar = await screen.findByRole("progressbar", { name: "カラーAI進捗" });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "8"));

    const log = screen.getByLabelText("学習ログ");
    await waitFor(() => expect(within(log).getByText("Validation Loss: 3.0476")).toBeInTheDocument());
    expect(within(log).queryByText(/Current loss/)).not.toBeInTheDocument();
  });

  it("ANSIカーソル制御（\\x1b[A）の残骸が学習ログ・元ログに表示されない", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 17, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    // 実UIで観測: "Validation Loss: 2.046[A" のように連結された行と、
    // "[A" だけの行が続けて届く（入れ子tqdmバーが閉じる際の残骸）。
    ws.emit("[color] Validation Loss: 2.046\x1b[A");
    ws.emit("[color] \x1b[A");
    ws.emit("[color] \x1b[A");

    const log = await screen.findByLabelText("学習ログ");
    await waitFor(() => expect(within(log).getByText(/Validation Loss: 2.046/)).toBeInTheDocument());
    expect(log.textContent).not.toContain("[A");

    fireEvent.click(screen.getByText("元ログを表示"));
    const raw = screen.getByLabelText("元ログ");
    expect(raw.textContent).not.toContain("[A");
  });
});
