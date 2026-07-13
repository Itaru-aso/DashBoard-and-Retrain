# 共通レイアウト（UIシェル） — Design

> spec: `共通レイアウト（UIシェル） (ui-shell)`
> 配置想定: `.kiro/specs/ui-shell/design.md`
> 上流: `requirements.md`（UI-R1〜UI-R5・確定事項）／ steering: `structure.md`
> 対象: `frontend/` のみ（backend 変更なし）

## 概要・方針 (Overview)

全画面共通の `AppLayout`（ヘッダー＋サイドバー）を新設し、既存の各ページは `react-router-dom` の
`<Outlet/>` を通じて無変更のまま差し込む。デザイントークン（配色・フォント）は `styles/` に集約し、
今回導入する共通レイアウトだけでなく、今後各画面を作り直す際にも共有する基盤として定義する。
モックアップの `{{ }}` プレースホルダ（アクティブ状態のスタイル値等）は具体値が失われているため、
モックアップの他要素（シアン系アクセント）に合わせて独自に設計する。

## ディレクトリ構成 (Placement)

```
frontend/src/
  styles/
    tokens.css          # CSS変数（配色・フォントスタック）＋ body 既定スタイル
    fonts.css            # @font-face（JetBrains Mono 自前ホスト）
  layouts/
    AppLayout.tsx         # ヘッダー＋サイドバー＋<Outlet/>
    AppLayout.module.css
  components/
    Header.tsx
    Header.module.css
    Sidebar.tsx            # ナビ項目＋「設定」開閉ロジック
    Sidebar.module.css
  App.tsx                  # ルーティング変更（Home 削除、AppLayout をネスト）
  main.tsx                  # tokens.css / fonts.css を読み込み
frontend/public/fonts/
  jetbrains-mono-400.woff2
  jetbrains-mono-500.woff2
  jetbrains-mono-600.woff2
```

## デザイントークン (`styles/tokens.css`)

```css
:root {
  --color-bg: #070b14;
  --color-panel-header: rgba(9, 14, 24, 0.62);
  --color-panel-sidebar: rgba(9, 14, 24, 0.42);
  --color-border: rgba(255, 255, 255, 0.08);

  --color-text-primary: #f2f6fb;
  --color-text-secondary: #9fb0c4;
  --color-text-muted: #6f7c90;

  --color-accent-cyan: #22d3ee;
  --color-accent-purple: #a78bfa;
  --color-accent-success: #34d399;

  --font-sans: "Noto Sans JP", system-ui, -apple-system, "Yu Gothic UI", "Meiryo", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}

body {
  background: var(--color-bg);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
}
```

`fonts.css` は JetBrains Mono の 400/500/600（Latin のみ）を `@font-face` で定義し、
`public/fonts/*.woff2` を参照する。Noto Sans JP は自前ホストしない（フォールバックチェーンで代用）。

## コンポーネント設計 (Components)

### `AppLayout`
- レイアウト骨格: 縦方向に `Header`（固定高さ）→ 横方向に `Sidebar` ＋ `<main><Outlet/></main>`。
- 状態は持たない（純粋なレイアウトシェル）。

### `Header`
- ロゴ（グラデーション正方形アイコン）＋「Shisui」＋サブタイトル「外観検査モニタリング」。
- 右側: エッジPC稼働の**静的プレースホルダー**（例: 「エッジPC ―/― 稼働」、中立色・アニメーション無し）、
  「オンプレ LAN」バッジ（装飾テキストのみ）。
- ユーザーアバターは持たない（UI-R3.3）。

### `Sidebar`
- 上位3項目（ダッシュボード／AI学習／タスク）: クリックで対応ルートへ `navigate`。タスクの件数バッジは
  実データが無いため今回は表示しない。
- 「設定」トグル項目: クリックで色マスター／閾値／エッジPCの3項目を開閉。`useState` で開閉状態を保持し、
  初期値は現在ルートが設定配下なら `true`。
- アクティブ判定: `useLocation().pathname` と各項目のパスを比較。
- アクティブ時のスタイル: 背景 `rgba(34,211,238,0.10)`・アイコン色 `var(--color-accent-cyan)`。
  非アクティブ: 背景transparent・アイコン色 `var(--color-text-muted)`。
- フッターのモデルバージョン表示は実データが無いため今回は表示しない。

## ルーティング変更 (`App.tsx`)

```tsx
<Routes>
  <Route element={<AppLayout />}>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/dashboard" element={<Dashboard />} />
    <Route path="/tasks" element={<TaskList />} />
    <Route path="/colors" element={<ColorMaster />} />
    <Route path="/thresholds" element={<ThresholdManagement />} />
    <Route path="/edge-pcs" element={<EdgePc />} />
    <Route path="/retraining" element={<Retraining />} />
  </Route>
</Routes>
```

既存の `Home` コンポーネントは削除する。各ページコンポーネント自体は無変更。

## エラー処理

- 該当なし（純粋なレイアウト・ルーティング変更のため、業務エラー処理は発生しない）。
- 存在しないルートへのフォールバック（404）は本 spec では対象外（既存動作を変更しない）。

## テスト設計 (Testing)

CSS の見た目そのものは自動テスト対象とせず、**構造・ロジックのみ**をテストする（`tech.md` の検証ゲート
＝ front: `tsc`／`eslint`／`vitest`）。仕上げ確認は `npm run dev` での目視確認（各ルートで正しい
ナビ・アクティブ状態が表示されること）を代替検証として行う。

- **`Sidebar.test.tsx`**: 各ルートでの active 表示、「設定」クリックでの開閉、設定配下ルートでの自動展開。
- **`AppLayout.test.tsx`**: ヘッダーのロゴ・アプリ名、サイドバーの6ナビ項目（設定展開後）が描画されること。
- **`App.test.tsx`**（既存を更新）: `/` にアクセスすると `/dashboard` へリダイレクトされ `Dashboard` が
  描画されること。
- 既存の各ページの `*.test.tsx` は `AppLayout` に依存せず、そのままレンダーできることを確認（無変更）。

## 依存・前提 (Dependencies)

- backend 側の変更なし。既存の hooks / API クライアントは無変更。
- 新規 npm 依存なし（CSS Modules は Vite 標準機能）。

## 確定事項・残課題 (Resolved & Pending)

確定:
- スタイリング手法は CSS Modules（新規依存なし）。
- ナビ構成・トップページのリダイレクト・ヘッダー内容・フォント方針は `requirements.md` の確定事項と同じ。

残: なし（実装着手可）。
