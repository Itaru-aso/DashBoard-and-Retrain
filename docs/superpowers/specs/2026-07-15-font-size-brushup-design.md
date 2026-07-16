# UI画面フォントサイズ・ブラッシュアップ 設計

## 背景・目的

検査PC/現場での視認性を優先し、フロントエンド全画面のフォントサイズが小さすぎる（現状 10.5〜13px 前後、要素によっては小数点px）問題を解消する。合わせて、ボタン・入力欄の大きさ、表の行の高さ・余白、アイコン・図形の大きさも見やすく調整する。

## 現状

- スタイリングは CSS Modules（`*.module.css`）+ グローバルCSS。UIライブラリ（MUI等）や Tailwind は未使用。
- `frontend/src/styles/tokens.css` に色トークンは存在するが、フォントサイズ・スペーシングのトークンは未整備。
- 各ページ・コンポーネントの CSS Modules に `font-size` が px でハードコードされており、値は 10〜24px の範囲でページごとにバラバラ（rem は未使用）。
- 対象ファイル: `components/Header.module.css`, `components/Sidebar.module.css`, `layouts/AppLayout.module.css`, `pages/Dashboard.module.css`, `pages/TaskList.module.css`, `pages/ThresholdManagement.module.css`, `pages/EdgePc.module.css`, `pages/Retraining.module.css`, `pages/ColorMaster.module.css`
- レスポンシブ対応（メディアクエリ）はほぼ無し。`TaskList.module.css` に表の `min-width: 920px` のみ存在。

## 対象範囲

- アプリ全体（6画面: Dashboard, TaskList, ThresholdManagement, EdgePc, Retraining, ColorMaster）
- フォントサイズに加え、ボタン・入力欄の大きさ、表の行の高さ・余白、アイコン・図形の大きさも対象

## 設計

### 1. フォントサイズトークン（`tokens.css` に追加）

5段階のセマンティックトークンを新設し、px固定で定義する（rem化はしない。現状 rem 未使用のコードベースに合わせ、将来の全体スケール機能が要件にない限りシンプルに保つ）。

| トークン | 値 | 用途 |
|---|---|---|
| `--font-size-title` | 32px | ページタイトル |
| `--font-size-judgment` | 40px | 判定結果表示 |
| `--font-size-kpi` | 28px | KPI主要数値 |
| `--font-size-body` | 16px | 通常データ |
| `--font-size-caption` | 14px | 補足情報 |

### 2. 適用範囲

上記9ファイル + `tokens.css` の計10ファイルを対象に、ハードコードされた `font-size` を要素の役割ごとに上記トークンへ置き換える。

ボタン・入力欄の高さ、テーブル行の余白も文字拡大に合わせて拡大する。新規トークンは複数ページで共通化する価値がある値（標準ボタン高さ、標準テーブル行の余白など）のみ追加し、ページ固有の細かい調整は各CSS内で直接値を調整する（過剰な抽象化は作らない）。

### 3. レイアウト崩れへの対応方針

文字サイズが最大3倍近く大きくなるため、以下の方針で崩れを防ぐ。

- **テーブル**（TaskList等）: 既存の `min-width` 方式を維持し、コンテナの横スクロールを許容する（表の再構成・カラム設計変更はしない）
- **KPIカード等のグリッド要素**: 幅が不足する場合は折り返し（wrap）を許容する
- **サイドバー**: ラベル文字拡大でアイコン+ラベルが折り返る場合、サイドバー幅を必要最小限だけ拡張する

### 4. 検証方法

自動テストでは「見やすさ」「レイアウト崩れの有無」は確認できないため、以下を成功基準とする。

- 開発サーバーを起動し、6画面（Dashboard, TaskList, ThresholdManagement, EdgePc, Retraining, ColorMaster）をブラウザで目視確認する
- テーブル横溢れ・カード重なり・サイドバー折り返しなどのレイアウト崩れがないことを確認する
- 既存の `*.test.tsx`（vitest）が通ることを確認する

## 非対象・注意事項

- UIライブラリの導入、CSS設計手法（Tailwind化等）の変更は行わない
- モバイル対応・新規ブレークポイント設計は行わない（対象は検査PC/現場のPCブラウザ）
- ページ構成・機能自体の変更は行わない（見た目の調整のみ）

## 実装計画での確定事項（追記）

実装計画（`docs/superpowers/plans/2026-07-16-font-size-brushup.md`）作成時に、以下を確定した。

- 「判定結果表示（32〜48px）」トークンは、Dashboardの **NG率・虚報率・見逃し率のみ**（40px）に適用する。スループット等の通常KPIはKPIトークン（28px）のまま
- `<h2>` と `.panelTitle`（パネル内小見出し）用に、6つ目のトークン `--font-size-heading`（24px）を追加する
