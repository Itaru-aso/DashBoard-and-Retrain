let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let prompt = "";
  try {
    prompt = JSON.parse(raw).prompt ?? "";
  } catch {
    process.exit(0);
  }

  const m = prompt.match(/\/kiro:spec-impl\s+([A-Za-z0-9._-]+)\s+(\d+)/);
  if (!m) process.exit(0);

  const feature = m[1];
  const n = m[2];

  process.stdout.write(`
${feature}/tasks.md のタスク${n} を TDD で1つだけ実装してください。

前提（厳守）:
- design.md と docs/reference/schema-spec-mapping.md（実列・不変）に従う。
- 参照実装: docs/reference/${feature}/{該当ファイル}（コピーせず、本プロジェクトの
  import 規約・DI・config に合わせて実装し直す）。
- 越境結合しない（app_db と ver2 を1 SQL で結合しない。2エンジンで読み Service で突合）。

手順:
1) 失敗するテストを先に書く（RED）。tasks のテスト方針・トレーサビリティに沿う。
2) 実装して通す（GREEN）。
3) 整える（REFACTOR・テストは緑のまま）。
4) 検証ゲートを通す: pytest(cov≥80) / black / flake8 / mypy
   （フロントは tsc / eslint / vitest）。
5) Conventional Commits でコミット（例: feat(${feature}): ...）。

このタスクだけ進めて、完了したら結果（テスト名・コミット）を報告して、次の指示を待ってください。
`);
  process.exit(0);
});
