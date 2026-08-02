# UIリデザイン — 藍染テキスタイル — Tasks

> spec: `UIリデザイン (ui-redesign)`
> 配置: `.kiro/specs/ui-redesign/tasks.md`
> 上流: `requirements.md`（R1–R8）・`design.md`（ADR・承認済み） ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト（該当する場合）+ 1実装 + 1コミット**。
> 視覚デザイン（CSS・配色）そのものは自動テスト対象外のため、代替検証として `npm run dev` での
> 目視確認・スクリーンショット提示を用いる（design.md §9 検証ゲート）。
> 完了条件は `tech.md` の検証ゲート（front: `tsc --noEmit`・`eslint .`・`vitest run`）。
> コミットは Conventional Commits（例: `feat(ui-redesign): ...`）。
> **コミット順序（design.md §8）: 共通基盤（tokens/ui部品/シェル）→ ページ単位。**

## 前提 (Preconditions)

- `ui-shell` spec（Header/Sidebar/AppLayout/既存トークン）が実装済み。本specはその視覚を
  刷新する（ナビ構造・ルーティング・コンポーネント責務は変更しない）。
- 新規 npm 依存を追加しない（Tailwind・UIライブラリは design.md §2.2 で不採用）。
- Zen Kaku Gothic New（400/500/700・SIL OFL）の woff2 サブセットを用意し、
  `frontend/public/fonts/` に配置する（自前ホスト・CDN非依存）。
- チャート配色（`--chart-series-1/2`・`--chart-threshold`）は dataviz バリデータで
  PASS 済み（design.md §2.3・2026-07-31）。実装時に色値を変更しない限り再検証不要。
- `frontend/src/api/`・`hooks/`・ルーティング・バックエンドは変更しない（R7）。

---

## タスク (Tasks)

- [ ] **1. デザイントークン全面差し替え + フォント基盤**
  - `frontend/src/styles/tokens.css` の `:root` を design.md §3 の定義で全面差し替え
    （面・藍・文字・署名モチーフ・状態3点セット・チャート・タイポグラフィ・形状/間隔）。
    現行トークン名（`--color-bg` 等）は可能な限り維持し値のみ更新する（design.md §3 方針）。
  - `--color-accent-cyan` / `--color-accent-purple` / `--color-panel-header` / `--color-panel-sidebar`
    等の廃止対象トークンは、**本タスクでは定義を残したまま**（未移行ページ (タスク3・6〜10) の
    参照が壊れるのを防ぐ）。廃止トークンの**削除**と参照ゼロ確認はタスク11で行う。
  - `frontend/src/styles/fonts.css`（既存・JetBrains Mono の `@font-face` 定義済み）に
    Zen Kaku Gothic New（400/500/700）の `@font-face` を追加。`frontend/public/fonts/` に woff2 配置。
  - `body` 既定スタイル（`main.tsx` 読み込み対象）を新トークンに追随。
  - 検証: `npm run dev` で背景色・フォントが適用されることを目視確認（自動テスト対象外）。
  - Refs: R1, R6 ／ commit: `feat(ui-redesign): replace design tokens and self-host Zen Kaku Gothic New`

- [ ] **2. 共通UI部品の新設**
  - `frontend/src/components/ui/` に `Panel` / `PageHeader` / `StatTile` / `StatusChip` /
    `Button`（primary/secondary/danger） / `SegmentedControl` / `DataTable` 用スタイル /
    `EmptyState` を新設（CSS Modules・TypeScript strict・named export）。
  - テスト（Vitest + Testing Library）: 各部品の基本レンダリング（タイトル・状態別クラス付与・
    クリックハンドラ呼び出し等）。
  - Refs: R2 ／ commit: `feat(ui-redesign): add shared ui components`

- [ ] **3. 共通シェルの視覚刷新（`Header`/`Sidebar`）**
  - 既存 `Header.tsx`/`Sidebar.tsx` の CSS を design.md §5 に合わせて更新
    （ヘッダ46px・`--color-indigo-deep`、サイドバー148px・`--color-indigo`、選択中ナビの
    縫い目装飾 `3px dashed var(--color-stitch)`）。コンポーネントの props・構造は変更しない。
  - 既存テスト（`Header.test.tsx`/`Sidebar.test.tsx`/`AppLayout.test.tsx`）が無変更で通ることを確認。
    class名変更で落ちる場合のみ表示仕様の追随修正とする（R7.3）。
  - Refs: R3 ／ commit: `feat(ui-redesign): restyle shared header and sidebar`

- [ ] **4. チャート共通仕様（`chartTheme.ts`）**
  - `frontend/src/styles/chartTheme.ts` を新設し、グリッド線・軸/目盛文字・線幅・マーカー・
    閾値線（`ReferenceLine` 破線 `6 4`・対応系列と同色）・ツールチップ様式の定数をエクスポート。
  - 既存の recharts 利用箇所（ダッシュボード等）を `chartTheme.ts` の定数を使うよう更新。
    新規チャートライブラリは追加しない。
  - テスト（Vitest + Testing Library）: 既存チャートテストを維持しつつ、閾値線の色が
    対応系列と一致すること（NG率のような単系列チャートは赤）を検証。
  - Refs: R5 ／ commit: `feat(ui-redesign): add shared chart theme utility`

- [ ] **5. ダッシュボードページの再構成**
  - `frontend/src/pages/Dashboard.tsx` を design.md §6.1 に合わせて再構成
    （PageHeader → 期間/号機/色番/サイズのフィルタ行 → KPI4タイル（StatTile・全タイル藍系スパークライン）
    → チャート3面（検査数/NG率2カラム、虚報率・見逃し率全幅）→ 日次明細テーブル）。
  - フィルタ・API呼び出し・データ取得ロジックは無変更。共通UI部品（タスク2）・chartTheme（タスク4）を使用。
  - テスト（Vitest + Testing Library）: 既存テストを維持。KPIタイルの状態チップ・スパークライン描画を追加検証。
  - 代替検証: `npm run dev`（バックエンド接続）で実データ表示を目視確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle dashboard page`

- [ ] **6. タスクページの再構成**
  - `frontend/src/pages/TaskList.tsx` を design.md §6.2 に合わせて再構成
    （状態 SegmentedControl（未着手/対応中/完了）→ テーブル（StatusChip・行アクション））。
    状態遷移・コメント追記の操作ロジックは無変更。
  - テスト（`TaskList.test.tsx`）: 既存テストを維持。SegmentedControl・StatusChip の描画を追加検証。
  - 代替検証: `npm run dev` で目視確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle task page`

- [ ] **7. 閾値ページの再構成**
  - `frontend/src/pages/ThresholdManagement.tsx` を design.md §6.3 に合わせて再構成
    （PageHeader 右端に「閾値を登録」primary Button → 一覧テーブル（有効/無効チップ・無効化アクション））。
  - テスト（`ThresholdManagement.test.tsx`）: 既存テストを維持。Button/StatusChip の描画を追加検証。
  - 代替検証: `npm run dev` で目視確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle threshold page`

- [ ] **8. 色マスターページの再構成**
  - `frontend/src/pages/ColorMaster.tsx` を design.md §6.4 に合わせて再構成
    （検索行＋「CSV取り込み」→ テーブル（色見本スウォッチ・ライフサイクル StatusChip：
    実生産=ok／量産検証=warn系／未実施=neutral））。
  - テスト（`ColorMaster.test.tsx`）: 既存テストを維持。ライフサイクル別 StatusChip 変種の描画を追加検証。
  - 代替検証: `npm run dev` で目視確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle color master page`

- [ ] **9. エッジPCページの再構成**
  - `frontend/src/pages/EdgePc.tsx` を design.md §6.5 に合わせて再構成
    （登録フォーム Panel ＋ 一覧テーブル（接続状態ドット・接続テスト/有効化/削除アクション））。
  - テスト（`EdgePc.test.tsx`）: 既存テストを維持。接続状態表示の描画を追加検証。
  - 代替検証: `npm run dev` で目視確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle edge pc page`

- [ ] **10. AI学習（再学習）ページの再構成**
  - `frontend/src/pages/Retraining.tsx` を design.md §6.6 に合わせて再構成
    （上段: 起票フォーム Panel ＋ 実行中ジョブカード（工程ステッパー・ライブログ＝
    `--color-indigo-deep` 地インセットコンソール／JetBrains Mono）、下段: ジョブ履歴・配信モデル一覧テーブル）。
    WebSocket ログ取得ロジックは無変更。
  - テスト（`Retraining.test.tsx`）: 既存テストを維持。ライブログコンソールの配色クラス付与を追加検証。
  - 代替検証: `npm run dev` で実行中ジョブがあれば目視確認、無ければジョブカードの静的表示を確認。
  - Refs: R4 ／ commit: `feat(ui-redesign): restyle retraining page`

- [ ] **11. 仕上げ: 廃止トークンの削除・一括確認・検証ゲート**
  - タスク1で残していた廃止トークン定義（`--color-accent-cyan` / `--color-accent-purple` /
    `--color-panel-header` / `--color-panel-sidebar` 等）を `tokens.css` から削除。
  - `grep -rn "accent-cyan\|accent-purple\|panel-header\|panel-sidebar" frontend/src` で
    参照が残っていないことを確認（R1.2, R8.4）。
  - `tsc --noEmit`・`eslint .`・`vitest run` をグリーンに。
  - `npm run dev` で全6ページを通し目視確認し、スクリーンショットを提示（R8.2）。
  - commit: `chore(ui-redesign): remove deprecated tokens and satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- R1（デザイントークン全面差し替え）→ 1, 11
- R2（共通UI部品の新設）→ 2
- R3（共通シェルの刷新）→ 3
- R4（ページ別レイアウト再構成）→ 5, 6, 7, 8, 9, 10
- R5（チャート共通仕様）→ 4
- R6（フォント刷新）→ 1
- R7（変更範囲の制約）→ 1–10（各タスクの実装制約として常時適用）
- R8（検証ゲート）→ 11

> 後追い: なし。
