import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import * as api from "@/api/taskApi";

import TaskList from "./TaskList";

vi.mock("@/api/taskApi");

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const TASK = {
  id: 7,
  color_no: "501",
  size: "05",
  chain: "CZT8",
  tape: "",
  task_type: "ng_rate",
  status: "OPEN",
  detected_value: 20,
  threshold_value: 5,
  evaluation_date: "2026-07-01",
  comments: [],
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

describe("TaskList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.listTasks as Mock).mockResolvedValue([TASK]);
    (api.transitionStatus as Mock).mockResolvedValue({ ...TASK, status: "IN_PROGRESS" });
    (api.addComment as Mock).mockResolvedValue(TASK);
  });

  it("一覧を表示する", async () => {
    renderWithClient(<TaskList />);
    expect(await screen.findByText("ng_rate")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "OPEN" })).toBeInTheDocument();
  });

  it("進めるで状態遷移 API を呼ぶ", async () => {
    renderWithClient(<TaskList />);
    fireEvent.click(await screen.findByRole("button", { name: "進める" }));
    await waitFor(() => expect(api.transitionStatus).toHaveBeenCalledWith(7, "IN_PROGRESS"));
  });

  it("コメント追加 API を呼ぶ", async () => {
    renderWithClient(<TaskList />);
    fireEvent.change(await screen.findByLabelText("comment-7"), {
      target: { value: "再発防止: 清掃" },
    });
    fireEvent.click(screen.getByRole("button", { name: "コメント追加" }));
    await waitFor(() => expect(api.addComment).toHaveBeenCalledWith(7, "再発防止: 清掃"));
  });
});
