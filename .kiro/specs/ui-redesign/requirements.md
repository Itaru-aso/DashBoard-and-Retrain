# UIリデザイン — 藍染テキスタイル — Requirements

> spec: `UIリデザイン (ui-redesign)`
> 配置: `.kiro/specs/ui-redesign/requirements.md`
> 前提 steering: `product.md`（6ページ構成・利用者像）, `tech.md`, `structure.md`
> 前提資料: `design.md`（ADR。デザイン方向「藍染テキスタイル」は承認済み・2026-07-31）
> 本書は design.md で先行確定した決定事項を、cc-sdd の要件フォーマット（EARS）に
> 事後整理したものである。内容の齟齬があれば design.md を正とする。

## 概要 (Introduction)

フロントエンド全6ページ＋共通シェルの視覚デザインを一新し、ページ間のレイアウト・
共通部品を統一する。対象は検査運用担当者が日常的に使う業務アプリであり、長時間の
KPI監視・タスク処理でも疲れにくく、状態（正常/注意/逸脱）が一目で判別できる見た目へ
刷新することが目的。

### スコープ (In Scope)
- 共通デザイントークン（色・タイポグラフィ・形状）の全面差し替え。
- 共通UI部品（Panel / PageHeader / StatTile / StatusChip / Button / SegmentedControl /
  DataTable様式 / EmptyState）の新設。
- 共通シェル（ヘッダ・サイドバー）の視覚刷新。
- 6ページ（ダッシュボード・タスク・閾値・色マスター・エッジPC・AI学習）のレイアウト再構成。
- チャート共通仕様（配色・凡例・閾値線）の統一。
- 和文フォント（Zen Kaku Gothic New）の自前ホスト化。

### スコープ外 (Out of Scope)
- `frontend/src/api/`・`hooks/`・ルーティング・バックエンド全体の変更。
- 新規API・新規データ項目の追加（表示要素は既存レスポンスから導出できるものに限る）。
- 業務ロジック・状態遷移・操作フローの変更（様式のみ共通部品化する）。

### 用語・前提
- 6ページ: ダッシュボード／タスク／AI学習（再学習）／設定＞色マスター・閾値・エッジPC
  （`product.md` の機能構成に対応）。
- デザイン方向: 5案（A〜F）の比較検討の結果、E「藍染テキスタイル」を採用（design.md §2.1）。

## 要件 (Requirements)

### R1. デザイントークン全面差し替え
**User Story**: 検査運用担当者として、現行のダーク＋シアン/パープル配色を、長時間見ても
疲れにくい落ち着いた配色に変えてほしい。

**受け入れ基準 (EARS)**
1. システムは `frontend/src/styles/tokens.css` の色・タイポグラフィ・形状トークンを
   design.md §3 の定義（生成り地の本文・藍のブランド面・状態3点セット等）に置き換える（SHALL）。
2. 廃止トークン（`--color-accent-cyan` / `--color-accent-purple` / `--color-panel-*` 等）への
   参照は、置き換え後にコードベース中に残存しない（SHALL。grep で検証）。
3. 影・`backdrop-filter`・グラデーションを新規トークン／スタイルとして追加しない（SHALL。
   フラット＋細罫線の方針。design.md §3）。

### R2. 共通UI部品の新設
**User Story**: 開発者として、ページ間で見た目が揃うよう、共通の部品を使ってページを組み立てたい。

**受け入れ基準 (EARS)**
1. システムは `frontend/src/components/ui/` に `Panel` / `PageHeader` / `StatTile` /
   `StatusChip` / `Button` / `SegmentedControl` / `DataTable` 用スタイル / `EmptyState` を
   新設する（SHALL。責務は design.md §4 の表に従う）。
2. 各部品は既存の関数コンポーネント＋CSS Modules 規約（TypeScript strict・named export）に
   従う（SHALL）。
3. `StatusChip` は ok/warn/bad/neutral の4状態を表現できる（SHALL）。

### R3. 共通シェルの刷新
**User Story**: 検査運用担当者として、どのページにいてもヘッダ・サイドバーで自分の位置と
システム状態が分かるようにしたい。

**受け入れ基準 (EARS)**
1. ヘッダは高さ46px・`--color-indigo-deep` 地とし、ロゴ・エッジPC稼働状態・LAN情報を
   表示する（SHALL。design.md §5）。
2. サイドバーは幅148px・`--color-indigo` 地とし、現行のナビ構造
   （ダッシュボード・AI学習・タスク・設定＞色マスター/閾値/エッジPC）を維持する（SHALL）。
3. 選択中のナビ項目は地を `--color-indigo-deep` にし、左縁に `3px dashed var(--color-stitch)`
   の縫い目装飾を表示する（SHALL。アプリ内で唯一の装飾モチーフとする）。

### R4. ページ別レイアウト再構成
**User Story**: 検査運用担当者として、各ページで「見出し→絞り込み→内容」の一定の順序で
情報を探せるようにしたい。

**受け入れ基準 (EARS)**
1. 各ページは `PageHeader` → フィルタ/アクション行 → コンテンツ（Panel群）の共通パターンで
   構成する（SHALL。design.md §6）。
2. ダッシュボードは KPI 4タイル（検査数・NG率・虚報率・見逃し率）を状態チップ・スパークライン
   付きで表示する（SHALL。値は既存APIレスポンスからのみ導出する）。
3. タスク・閾値・色マスター・エッジPC・AI学習の各ページは、design.md §6.2〜§6.6 に定めた
   構成要素（状態チップ・登録フォーム・ライブログコンソール等）を用いる（SHALL）。
4. 既存の操作フロー（状態遷移・登録・削除・接続テスト等）の挙動は変更しない（SHALL。
   様式のみ共通部品化する）。

### R5. チャート共通仕様
**User Story**: 検査運用担当者として、どのグラフでも同じ色・凡例規則で状態を判別したい。

**受け入れ基準 (EARS)**
1. システムは `frontend/src/styles/chartTheme.ts` にチャート共通定数
   （グリッド線・軸文字・線幅・マーカー・閾値線様式・ツールチップ様式）を集約する（SHALL）。
2. 閾値線（`ReferenceLine`）は対応する系列と同色の破線 `6 4` とする（SHALL。
   系列が1本のチャートの閾値は赤 `--chart-threshold` とする）。
3. 辛子色 `--chart-series-2` と閾値の赤 `--chart-threshold` を同一チャートに同時使用しない
   （SHALL。design.md §2.3 のアクセシビリティ制約）。
4. 凡例は系列が2つ以上あるチャートにのみ表示する（SHALL）。

### R6. フォント刷新
**User Story**: 検査運用担当者として、工場LAN環境でも和文フォントが正しく表示されるように
したい。

**受け入れ基準 (EARS)**
1. 和文本文フォントは Zen Kaku Gothic New（400/500/700）とし、woff2 サブセットを
   `frontend/public/fonts/` に配置し `@font-face` で自前配信する（SHALL。CDN 非依存）。
2. 数値表示（KPI大数字・テーブル・ID・ログ）は JetBrains Mono を継続使用する（SHALL）。
3. 和文フォントのフォールバックは `system-ui, "Yu Gothic UI", "Meiryo", sans-serif` の順とする
   （SHALL）。

### R7. 変更範囲の制約
**User Story**: 開発者として、視覚デザインの変更でAPI・業務ロジックが壊れないようにしたい。

**受け入れ基準 (EARS)**
1. `frontend/src/api/`・`hooks/`・ルーティング・バックエンド全体には変更を加えない（SHALL）。
2. 表示要素の追加は既存APIレスポンスから導出可能なものに限る。導出できない要素は
   実装せずに落とす（SHALL。新規APIを追加しない）。
3. 既存テストの意図は変更しない。class名・文言変更に伴うテスト修正は表示仕様の追随修正として
   許容する（SHALL）。

### R8. 検証ゲート
**User Story**: 開発者として、デザイン刷新が既存機能を壊していないことを確認できるようにしたい。

**受け入れ基準 (EARS)**
1. `tsc --noEmit` / `eslint .` / `vitest run` はすべて成功する（SHALL）。
2. `npm run dev` で全6ページを目視確認できる（SHALL。スクリーンショットで確認結果を残す）。
3. チャート配色は dataviz バリデータ（OKLab ΔE・CVDシミュレーション・コントラスト）で
   PASS していること。実装時に色値を変更した場合は再検証する（SHALL）。
4. 旧トークン（cyan/purple/panel系）への参照が残っていないことを grep で確認する（SHALL）。

## design への申し送り (Notes for Design)

- design.md は本書に先行して作成・承認済みのため、設計判断（代替案A〜Fの比較・却下理由、
  トークン値、部品責務、ページ別構成）はすべて design.md を正とする。
- 本書は追加の設計判断を要求しない。次工程は `/kiro:spec-tasks ui-redesign` によるタスク分割。
