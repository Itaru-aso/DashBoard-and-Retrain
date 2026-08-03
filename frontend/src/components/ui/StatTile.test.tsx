import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatTile } from "./StatTile";

describe("StatTile", () => {
  it("label と value を表示する", () => {
    render(<StatTile label="検査数" value="1,234" />);
    expect(screen.getByText("検査数")).toBeInTheDocument();
    expect(screen.getByText("1,234")).toBeInTheDocument();
  });

  it("status と statusLabel を指定すると状態チップを表示する", () => {
    render(<StatTile label="NG率" value="1.2%" status="warn" statusLabel="注意" />);
    expect(screen.getByText("注意")).toBeInTheDocument();
  });

  it("status を指定しないと状態チップを描画しない", () => {
    render(<StatTile label="検査数" value="1,234" />);
    expect(screen.queryByText("注意")).not.toBeInTheDocument();
  });

  it("caption と sparkline を表示する", () => {
    render(
      <StatTile
        label="虚報率"
        value="0.8%"
        caption="閾値まで残り 0.2pt"
        sparkline={<span>spark</span>}
      />,
    );
    expect(screen.getByText("閾値まで残り 0.2pt")).toBeInTheDocument();
    expect(screen.getByText("spark")).toBeInTheDocument();
  });
});
