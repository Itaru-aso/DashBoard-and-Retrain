import { describe, expect, it } from "vitest";

import { classifyLine, detectStage, splitGluedLine, stripAnsi } from "./retrainingProgress";

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

  it("Current loss（学習ループ本体）の進捗行は isMainLoop=true になる", () => {
    const raw =
      "[color] Current loss: 0.3955  :  50%|████▉     | 12000/24120 [34:13<30:28,  6.63it/s]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.isMainLoop).toBe(true);
  });

  it("Computing threshold scores（学習ループ以外の進捗）は isMainLoop=false になる", () => {
    // 学習完了直後に1回だけ走る閾値計算。totalが小さくすぐ100%に達するため、
    // 学習ループ本体の進捗バーに混ぜてはならない（実ログで観測: 学習は27%/50%
    // しか進んでいないのにUIの進捗バーが100%と表示される不具合の原因）。
    const raw =
      "[color] Computing threshold scores:  100%|██████████| 50/50 [00:03<00:00, 14.2it/s]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.isMainLoop).toBe(false);
  });

  it("入れ子tqdmバー（末尾にANSIカーソル制御 \\x1b[A）も progress として分類し、isMainLoop=false になる", () => {
    // 学習中に定期的に挟まる中間処理（map正規化）。tqdmの入れ子バー描画に伴う
    // ANSIエスケープが末尾に付き、これを考慮しないと other 判定になって
    // 重要ログが埋め尽くされる（実ログで多数観測）。
    const raw =
      "[color] Intermediate map normalization:  17%|██▋       | 20/121 [00:01<00:09, 10.36it/s]\x1b[A";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.phase).toBe("color");
    expect(result.percent).toBe(17);
    expect(result.current).toBe(20);
    expect(result.total).toBe(121);
    expect(result.isMainLoop).toBe(false);
  });

  it("descが無いtqdm初期フレーム（%がスペースでパディングされる）も progress として分類する", () => {
    // tqdmは percentage を3桁幅で右詰めするため、desc無しの最初のフレームは
    // "  0%|...|" のように先頭に空白が入る。descありの場合は ":\s*" で吸収されるが
    // desc無しだとTQDM_PATTERNの先頭にマッチせず other に落ちていた（実ログで観測）。
    const raw = "  0%|          | 0/24120 [00:00<?, ?it/s]";
    const result = classifyLine(raw);
    expect(result.kind).toBe("progress");
    if (result.kind !== "progress") throw new Error("unreachable");
    expect(result.percent).toBe(0);
    expect(result.current).toBe(0);
    expect(result.total).toBe(24120);
  });
});

describe("splitGluedLine", () => {
  it("tqdm進捗フレームと直後のprint出力が分離子なしで連結された行を2行に分割する", () => {
    // tqdmの最終フレームは改行を出さないため、直後の print("Validation Loss: ...") が
    // \r/\n無しでそのまま連結される（実ログで観測: 学習ループの検証チェックポイント毎）。
    // 分割しないとTQDM_PATTERNの末尾アンカーにマッチせず other 判定になり、重要ログに
    // 読みにくい結合行が残る。
    const raw =
      "Current loss: 0.5505  :   8%|▊         | 2000/24120 [05:55<55:31,  6.64it/s]Validation Loss: 3.0476";
    const pieces = splitGluedLine(raw);
    expect(pieces).toEqual([
      "Current loss: 0.5505  :   8%|▊         | 2000/24120 [05:55<55:31,  6.64it/s]",
      "Validation Loss: 3.0476",
    ]);

    const progressPiece = classifyLine(pieces[0]);
    expect(progressPiece.kind).toBe("progress");
    if (progressPiece.kind !== "progress") throw new Error("unreachable");
    expect(progressPiece.percent).toBe(8);
    expect(progressPiece.isMainLoop).toBe(true);

    const otherPiece = classifyLine(pieces[1]);
    expect(otherPiece).toEqual({ kind: "other", phase: undefined, raw: "Validation Loss: 3.0476" });
  });

  it("連結されていない通常の行は1件のまま返す", () => {
    expect(splitGluedLine("パイプライン完了")).toEqual(["パイプライン完了"]);
    expect(
      splitGluedLine("Current loss: 0.37  :  91%|████ | 100/200 [00:01<00:01, 1.0it/s]"),
    ).toEqual(["Current loss: 0.37  :  91%|████ | 100/200 [00:01<00:01, 1.0it/s]"]);
  });

  it("[monochro]/[color] 接頭辞付きの連結行では、分割後の2件目にも同じ接頭辞を付与する", () => {
    // 並列学習では両モデルのログが混在するため、分割後の断片が接頭辞を失うと
    // どちらのモデルのValidation Lossか分からなくなる（実ログで観測）。
    const raw =
      "[color] Current loss: 0.5505  :   8%|▊         | 2000/24120 [05:55<55:31,  6.64it/s]Validation Loss: 3.0476";
    expect(splitGluedLine(raw)).toEqual([
      "[color] Current loss: 0.5505  :   8%|▊         | 2000/24120 [05:55<55:31,  6.64it/s]",
      "[color] Validation Loss: 3.0476",
    ]);
  });
});

describe("stripAnsi", () => {
  it("末尾のANSIカーソル制御を除去する", () => {
    // 入れ子tqdmバーが閉じる際に付与される \x1b[A（実UIで「Validation Loss: 2.046[A」
    // のような表示になっていた不具合の原因）。
    expect(stripAnsi("Validation Loss: 2.046\x1b[A")).toBe("Validation Loss: 2.046");
  });

  it("ANSIエスケープのみの行は空文字になる", () => {
    // \x1b[A 単独の行（実UIで「[A」だけの行が並んでいた不具合の原因）。
    expect(stripAnsi("\x1b[A")).toBe("");
  });

  it("ANSIエスケープを含まない行はそのまま返す", () => {
    expect(stripAnsi("パイプライン完了")).toBe("パイプライン完了");
  });
});

describe("classifyLine（ANSI除去）", () => {
  it("classifyLineが返すrawからもANSIカーソル制御が除去されている", () => {
    // 分類判定用の内部処理だけでなく、表示に使うraw自体からも除去しないと、
    // 重要ログ・元ログに制御文字の残骸（"[A"）がそのまま出てしまう。
    const result = classifyLine("Validation Loss: 2.046\x1b[A");
    expect(result).toEqual({ kind: "other", phase: undefined, raw: "Validation Loss: 2.046" });
  });

  it("接頭辞だけでANSI除去後に本文が無い行は raw が空文字になる", () => {
    // "[color] \x1b[A" のような、ANSIエスケープのみの行に[monochro]/[color]接頭辞が
    // 付いた形（実UIで観測: "[A" だけの行が並んでいた不具合の原因）。
    expect(classifyLine("[color] \x1b[A")).toEqual({ kind: "other", phase: "color", raw: "" });
  });
});

describe("detectStage", () => {
  it("バックアップ開始のマーカーを検出する", () => {
    expect(detectStage("バックアップ作成中...")).toBe("backup");
  });

  it("学習開始のマーカー（モノクロ/カラー/並列学習割当のいずれ）を検出する", () => {
    expect(
      detectStage("🟢 モノクロAIの学習を開始します... (物理 GPU: 0, 論理 cuda:0, color: 501)"),
    ).toBe("training");
    expect(
      detectStage("🔵 カラーAIの学習を開始します... (物理 GPU: 1, 論理 cuda:0, color: 501)"),
    ).toBe("training");
    expect(
      detectStage("並列学習 GPU 割当: monochro=GPU0, color=GPU1 (検出: 2枚)"),
    ).toBe("training");
  });

  it("ONNXエクスポート完了のマーカーを検出する", () => {
    expect(detectStage("Exported ONNX: /model_dir/501/color/501_color_model.onnx")).toBe(
      "export_eval",
    );
  });

  it("パイプライン完了のマーカーを検出する", () => {
    expect(detectStage("パイプライン完了")).toBe("completed");
  });

  it("マーカーに一致しない行は undefined を返す", () => {
    expect(
      detectStage("Current loss: 0.37  :  50%|████ | 100/200 [00:01<00:01, 1.0it/s]"),
    ).toBeUndefined();
    expect(detectStage("[monochro] Validation Loss: 1.4732")).toBeUndefined();
    expect(detectStage("[STATUS] RUNNING color=501")).toBeUndefined();
  });
});
