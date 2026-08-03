import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("既定では primary variant のクラスを付与する", () => {
    render(<Button>保存</Button>);
    expect(screen.getByRole("button", { name: "保存" }).className).toContain("primary");
  });

  it.each(["secondary", "danger"] as const)("variant=%s のクラスを付与する", (variant) => {
    render(<Button variant={variant}>操作</Button>);
    expect(screen.getByRole("button", { name: "操作" }).className).toContain(variant);
  });

  it("クリックすると onClick を呼び出す", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>閾値を登録</Button>);
    fireEvent.click(screen.getByRole("button", { name: "閾値を登録" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disabled のとき操作できない", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        削除
      </Button>,
    );
    expect(screen.getByRole("button", { name: "削除" })).toBeDisabled();
  });

  it("既定の type は button であり、form内でも誤送信しない", () => {
    render(<Button>保存</Button>);
    expect(screen.getByRole("button", { name: "保存" })).toHaveAttribute("type", "button");
  });

  it("type を明示すれば submit にできる", () => {
    render(<Button type="submit">登録</Button>);
    expect(screen.getByRole("button", { name: "登録" })).toHaveAttribute("type", "submit");
  });
});
