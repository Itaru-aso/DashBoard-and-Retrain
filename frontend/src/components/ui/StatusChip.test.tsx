import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusChip } from "./StatusChip";

describe("StatusChip", () => {
  it("children のラベルを表示する", () => {
    render(<StatusChip variant="ok">正常</StatusChip>);
    expect(screen.getByText("正常")).toBeInTheDocument();
  });

  it.each([
    ["ok", "chipOk"],
    ["warn", "chipWarn"],
    ["bad", "chipBad"],
    ["neutral", "chipNeutral"],
  ] as const)("variant=%s のとき対応するクラスを付与する", (variant, className) => {
    render(<StatusChip variant={variant}>ラベル</StatusChip>);
    expect(screen.getByText("ラベル").className).toContain(className);
  });
});
