import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Panel } from "./Panel";

describe("Panel", () => {
  it("title と children を表示する", () => {
    render(
      <Panel title="タイトル">
        <p>本文</p>
      </Panel>,
    );
    expect(screen.getByText("タイトル")).toBeInTheDocument();
    expect(screen.getByText("本文")).toBeInTheDocument();
  });

  it("actions（右端補助表示）を表示する", () => {
    render(
      <Panel title="タイトル" actions={<button>更新</button>}>
        本文
      </Panel>,
    );
    expect(screen.getByRole("button", { name: "更新" })).toBeInTheDocument();
  });

  it("title も actions も無いときはヘッダー行を描画しない", () => {
    render(<Panel>本文のみ</Panel>);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});
