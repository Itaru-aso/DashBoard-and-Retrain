import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Sidebar from "./Sidebar";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  it("上位3項目を表示する", () => {
    renderAt("/dashboard");
    expect(screen.getByRole("link", { name: "ダッシュボード" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI学習" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "タスク" })).toBeInTheDocument();
  });

  it("現在のルートに対応する項目がアクティブになる", () => {
    renderAt("/dashboard");
    expect(screen.getByRole("link", { name: "ダッシュボード" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "AI学習" })).not.toHaveAttribute("aria-current");
  });

  it("設定配下のルートでは初期状態でサブメニューが展開されている", () => {
    renderAt("/colors");
    expect(screen.getByRole("link", { name: "色マスター" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "閾値" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "エッジPC" })).toBeInTheDocument();
  });

  it("設定配下でないルートでは初期状態でサブメニューが閉じており、クリックで開閉する", async () => {
    renderAt("/dashboard");
    expect(screen.queryByRole("link", { name: "色マスター" })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "設定" });
    fireEvent.click(toggle);
    expect(screen.getByRole("link", { name: "色マスター" })).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByRole("link", { name: "色マスター" })).not.toBeInTheDocument();
  });
});
