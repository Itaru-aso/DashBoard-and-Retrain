# 共通レイアウト（UIシェル） — Tasks

> spec: `共通レイアウト（UIシェル） (ui-shell)`
> 配置想定: `.kiro/specs/ui-shell/tasks.md`
> 上流: `requirements.md`（UI-R1〜UI-R5・確定事項）・`design.md` ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト（該当する場合）+ 1実装 + 1コミット**。
> UI の見た目（CSS）そのものは自動テスト対象外のため、代替検証として `npm run dev` での目視確認を用いる
> （`design.md` テスト設計を参照）。完了条件は `tech.md` の検証ゲート（front: `tsc`・`eslint`・`vitest`）。
> コミットは Conventional Commits（例: `feat(ui-shell): ...`）。

## 前提 (Preconditions)

- backend 側の変更なし。既存の各ページコンポーネント・hooks・API クライアントは無変更。
- 新規 npm 依存なし。

---

## タスク (Tasks)

- [x] **1. デザイントークン・フォント基盤**
  - `frontend/src/styles/tokens.css`（CSS変数・body既定スタイル）、`frontend/src/styles/fonts.css`
    （JetBrains Mono 400/500/600 の `@font-face`）を追加。`frontend/public/fonts/` に woff2 を配置。
    `main.tsx` で読み込む。
  - 検証: `npm run dev` で背景色・フォントが適用されることを目視確認（自動テスト対象外）。
  - Refs: UI-R4 ／ commit: `feat(ui-shell): add design tokens and self-hosted mono font`

- [x] **2. `Header` コンポーネント**
  - `frontend/src/components/Header.tsx` + `Header.module.css`。ロゴ・アプリ名・サブタイトル・
    エッジPC稼働の静的プレースホルダー・「オンプレ LAN」バッジ。アバターは持たない。
  - テスト（Vitest + Testing Library）: ロゴ・アプリ名・プレースホルダーテキストが描画されること。
  - Refs: UI-R3 ／ commit: `feat(ui-shell): add Header component`

- [x] **3. `Sidebar` コンポーネント**
  - `frontend/src/components/Sidebar.tsx` + `Sidebar.module.css`。3項目＋「設定」展開で3項目、
    アクティブ判定、設定配下ルートでの自動展開。
  - テスト（Vitest + Testing Library）: 各ルートでの active 表示、設定の開閉、自動展開。
  - Refs: UI-R1 ／ commit: `feat(ui-shell): add Sidebar component with settings submenu`

- [x] **4. `AppLayout` とルーティング変更**
  - `frontend/src/layouts/AppLayout.tsx` + `AppLayout.module.css`。`App.tsx` を変更し、`Home` を削除、
    `/` → `/dashboard` リダイレクトを追加、既存ルートを `AppLayout` にネスト。
  - テスト: `AppLayout.test.tsx`（ヘッダー・6ナビ項目の描画）、`App.test.tsx` 更新
    （`/` アクセスで `/dashboard` にリダイレクトされ `Dashboard` が描画される）。
  - Refs: UI-R2, UI-R5 ／ commit: `feat(ui-shell): add AppLayout and wire routing`

- [x] **5. 既存ページとの結合確認**
  - 既存の各ページ `*.test.tsx`（`Dashboard.test.tsx` 等）が無変更で通ることを確認。
  - `npm run dev` で6画面すべて（`/dashboard`, `/tasks`, `/colors`, `/thresholds`, `/edge-pcs`,
    `/retraining`）を開き、サイドバーのアクティブ表示・設定展開が正しいことを目視確認（代替検証）。
  - Refs: UI-R1, UI-R5 ／ commit 不要（確認のみ。問題があればタスク2-4に戻って修正）

- [x] **6. 仕上げ: 検証ゲート確認**
  - `tsc --noEmit`・`eslint .`・`vitest run` をグリーンに。
  - commit: `chore(ui-shell): satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- UI-R1（共通ナビゲーション）→ 3, 5
- UI-R2（トップページのリダイレクト）→ 4
- UI-R3（共通ヘッダー）→ 2
- UI-R4（デザイントークン）→ 1
- UI-R5（既存画面との非干渉）→ 4, 5

> 後追い: なし。
