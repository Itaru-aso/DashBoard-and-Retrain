import { describe, expect, it } from "vitest";

import { classifyLine } from "./retrainingProgress";

describe("classifyLine", () => {
  it("tqdm進捗行（接頭辞なし・Current loss付き）を progress として分類する", () => {
    const raw =
      "Current loss: 0.3676  :  91%|████████ | 22001/24120 [1:05:02<5:39:04,  9.60s/it]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.phase).toBeUndefined();
    expect(result.percent).toBe(91);
    expect(result.current).toBe(22001);
    expect(result.total).toBe(24120);
    expect(result.loss).toBeCloseTo(0.3676);
    expect(result.eta).toBe("1:05:02<5:39:04, 9.60s/it");
  });

  it("[monochro]/[color] 接頭辞付きの進捗行から phase を取り出す", () => {
    const raw =
      "[color] Current loss: 0.10  :  10%|█ | 100/1000 [00:10<01:30, 10.0it/s]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.phase).toBe("color");
    expect(result.percent).toBe(10);
    expect(result.current).toBe(100);
    expect(result.total).toBe(1000);
  });

  it("descにlossが無い進捗行は loss が undefined になる", () => {
    const raw = "Computing threshold scores: 45%|███ | 10/20 [00:01<00:02, 5.00it/s]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.loss).toBeUndefined();
  });

  it("進捗パターンに一致しない行は other として分類する（phaseは保持）", () => {
    expect(classifyLine("🟢 モノクロAIの学習を開始します...")).toEqual({
      kind: "other",
      phase: undefined,
      raw: "🟢 モノクロAIの学習を開始します...",
    });
    expect(classifyLine("[monochro] Validation Loss: 1.4732")).toEqual({
      kind: "other",
      phase: "monochro",
      raw: "[monochro] Validation Loss: 1.4732",
    });
    expect(classifyLine("[STATUS] RUNNING color=001")).toEqual({
      kind: "other",
      phase: undefined,
      raw: "[STATUS] RUNNING color=001",
    });
  });

  it("進捗っぽいが不完全な行は例外を投げず other になる", () => {
    expect(() => classifyLine("50%|███ 完全ではない行")).not.toThrow();
    expect(classifyLine("50%|███ 完全ではない行").kind).toBe("other");
  });
});
