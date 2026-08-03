import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("message を表示する", () => {
    render(<EmptyState message="タスクはありません" />);
    expect(screen.getByText("タスクはありません")).toBeInTheDocument();
  });

  it("action を指定すると次の行動を表示する", () => {
    render(<EmptyState message="色マスターがありません" action={<button>登録する</button>} />);
    expect(screen.getByRole("button", { name: "登録する" })).toBeInTheDocument();
  });
});
