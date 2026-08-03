import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("title・description・actions を表示する", () => {
    render(
      <PageHeader
        title="ダッシュボード"
        description="検査KPIの日次推移と閾値の逸脱状況"
        actions={<button>設定</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "ダッシュボード" })).toBeInTheDocument();
    expect(screen.getByText("検査KPIの日次推移と閾値の逸脱状況")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "設定" })).toBeInTheDocument();
  });

  it("description・actions が無ければ描画しない", () => {
    render(<PageHeader title="タスク" />);
    expect(screen.getByRole("heading", { name: "タスク" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
