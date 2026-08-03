import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./SegmentedControl";

const options = [
  { value: "7d", label: "7日" },
  { value: "30d", label: "30日" },
  { value: "90d", label: "90日" },
];

describe("SegmentedControl", () => {
  it("全選択肢のラベルを表示し、現在値を選択中として表す", () => {
    render(<SegmentedControl options={options} value="30d" onChange={vi.fn()} />);
    expect(screen.getByRole("tab", { name: "7日" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "30日" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "90日" })).toHaveAttribute("aria-selected", "false");
  });

  it("選択肢をクリックすると onChange にその value を渡す", () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={options} value="7d" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "90日" }));
    expect(onChange).toHaveBeenCalledWith("90d");
  });
});
