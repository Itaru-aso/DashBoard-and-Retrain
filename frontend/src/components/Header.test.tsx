import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Header from "./Header";

describe("Header", () => {
  it("ロゴ・アプリ名・サブタイトルを表示する", () => {
    render(<Header />);
    expect(screen.getByText("SHISUI")).toBeInTheDocument();
    expect(screen.getByText("紫翠 ─ AIモデル管理")).toBeInTheDocument();
  });

  it("エッジPC稼働の静的プレースホルダーと「オンプレ LAN」バッジを表示する", () => {
    render(<Header />);
    expect(screen.getByText(/エッジPC/)).toBeInTheDocument();
    expect(screen.getByText("オンプレ LAN")).toBeInTheDocument();
  });
});
