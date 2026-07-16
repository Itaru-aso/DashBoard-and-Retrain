# UI画面フォントサイズ・ブラッシュアップ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** フロントエンド全6画面（Dashboard, TaskList, ThresholdManagement, EdgePc, Retraining, ColorMaster）のフォントサイズ・ボタン/入力欄の大きさ・表の行の高さ・アイコン/図形の大きさを、検査PC/現場での視認性に合わせて拡大する。

**Architecture:** `frontend/src/styles/tokens.css` にセマンティックなフォントサイズトークンを6段階追加し、各ページ・共通コンポーネントの CSS Modules 内にハードコードされた `font-size`（px直値）をトークン参照に置き換える。ボタン・入力欄のパディング、テーブル行の余白、アイコン/ドット等の図形サイズは、対応する各ルールで直接値を拡大する（新規トークンは追加しない）。

**Tech Stack:** React 18 + Vite + TypeScript、CSS Modules、vitest + @testing-library/react（既存テストの回帰確認用）。UIライブラリ・CSS設計手法の変更は行わない。

## Global Constraints

- 参照元設計書: `docs/superpowers/specs/2026-07-15-font-size-brushup-design.md`
- フォントサイズトークンは px 固定（rem化はしない）
- 対象は検査PC/現場のPCブラウザのみ。モバイル対応・新規ブレークポイントは追加しない
- ページ構成・機能（API呼び出し・状態管理）は変更しない。見た目の調整のみ
- テーブルは既存の `min-width` 方式を維持し、コンテナの横スクロールを許容する（表の再構成はしない）
- KPIカード等のグリッド要素は、幅が不足する場合は折り返し（wrap）を許容する
- 自動テストでは「見やすさ」「レイアウト崩れの有無」は検証できないため、各タスクの最終確認は開発サーバー起動 + ブラウザ目視で行う（このリポジトリには Playwright 等の E2E/ビジュアルテストは存在しない）

## トークン設計（全タスク共通の前提）

`frontend/src/styles/tokens.css` に以下6トークンを追加する（Task 1 で定義）。以降の全タスクはこのトークン名を使う。

| トークン | 値 | 用途 |
|---|---|---|
| `--font-size-title` | 32px | `<h1>`（画面タイトル） |
| `--font-size-heading` | 24px | `<h2>`（セクション見出し）、`.panelTitle`（パネル内小見出し） |
| `--font-size-judgment` | 40px | Dashboard の NG率・虚報率・見逃し率（判定結果の主要数値） |
| `--font-size-kpi` | 28px | KPIカードの主要数値（スループット、ColorMasterの集計数、EdgePcのIPアドレス等） |
| `--font-size-body` | 16px | 通常データ（テーブル本文、入力値、主要ボタン、ナビゲーション項目等） |
| `--font-size-caption` | 14px | 補足情報（ラベル、テーブル見出し、小さいピルボタン/バッジ、補助メタ情報等） |

---

### Task 1: トークン定義（`tokens.css`）

**Files:**
- Modify: `frontend/src/styles/tokens.css`

**Interfaces:**
- Produces: CSS変数 `--font-size-title` / `--font-size-heading` / `--font-size-judgment` / `--font-size-kpi` / `--font-size-body` / `--font-size-caption`（以降の全タスクが参照）。グローバル `h1`, `h2` セレクタのフォントサイズ指定。

- [ ] **Step 1: トークンを追加する**

`frontend/src/styles/tokens.css` を編集:

```diff
   --font-sans: "Noto Sans JP", system-ui, -apple-system, "Yu Gothic UI", "Meiryo", sans-serif;
   --font-mono: "JetBrains Mono", ui-monospace, monospace;
+
+  --font-size-title: 32px;
+  --font-size-heading: 24px;
+  --font-size-judgment: 40px;
+  --font-size-kpi: 28px;
+  --font-size-body: 16px;
+  --font-size-caption: 14px;
 }
```

- [ ] **Step 2: `h1`/`h2` のグローバルスタイルを追加する**

同ファイルの `body { ... }` ルールの直後に追記:

```css
h1 {
  font-size: var(--font-size-title);
  margin: 0 0 12px;
}

h2 {
  font-size: var(--font-size-heading);
  margin: 0 0 10px;
}
```

（現状 `h1`/`h2` にはCSS指定が一切なくブラウザ既定値に依存しているため、`margin` も明示して6画面で見た目を揃える。既定値は `h1`≈32px, `h2`≈24px 相当なので、どちらも数値としては変わらず、ブラウザ依存だった値を明示的なトークン管理に置き換える意味合いになる。`margin` の明示はフォントサイズ変更の副作用ではなく、見出し直後の間隔を6画面で揃えるための付随的な調整。）

- [ ] **Step 3: フロントエンドの型チェックとテストを実行し、既存動作に影響がないことを確認する**

```bash
cd frontend
npx tsc --noEmit
npx vitest run
```

Expected: 両方成功（既存の全テストが green のまま）。CSSのみの変更なので型チェック・テスト内容に変化は起きない想定。

- [ ] **Step 4: commit**

```bash
git add frontend/src/styles/tokens.css
git commit -m "$(cat <<'EOF'
feat(frontend): フォントサイズのセマンティックトークンを追加

- title/heading/judgment/kpi/body/captionの6段階を定義
- h1をタイトル、h2を見出しトークンに接続
EOF
)"
```

---

### Task 2: ヘッダー（`Header.module.css`）

**Files:**
- Modify: `frontend/src/components/Header.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .header {
-  height: 54px;
+  height: 62px;
   flex: none;
   display: flex;
   align-items: center;
   gap: 14px;
-  padding: 0 18px;
+  padding: 0 20px;
   border-bottom: 1px solid var(--color-border);
   background: var(--color-panel-header);
   backdrop-filter: blur(14px);
 }
```

```diff
 .logoIcon {
-  width: 28px;
-  height: 28px;
+  width: 32px;
+  height: 32px;
   border-radius: 8px;
   background: linear-gradient(140deg, var(--color-accent-cyan), var(--color-accent-purple));
   display: flex;
   align-items: center;
   justify-content: center;
 }

 .logoIcon span {
-  width: 9px;
-  height: 9px;
+  width: 10px;
+  height: 10px;
   background: var(--color-bg);
   transform: rotate(45deg);
   border-radius: 1.5px;
 }
```

```diff
 .appName {
-  font-size: 17px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   letter-spacing: 0.5px;
   color: var(--color-text-primary);
 }

 .subtitle {
-  font-size: 10px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-muted);
   letter-spacing: 1.5px;
 }
```

```diff
 .edgeStatus {
   display: flex;
   align-items: center;
   gap: 8px;
-  padding: 5px 11px;
+  padding: 6px 13px;
   border-radius: 999px;
   background: rgba(255, 255, 255, 0.05);
   border: 1px solid rgba(255, 255, 255, 0.09);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-secondary);
 }

 .edgeStatusDot {
-  width: 7px;
-  height: 7px;
+  width: 8px;
+  height: 8px;
   border-radius: 50%;
   background: var(--color-text-muted);
 }
```

```diff
 .lanBadge {
-  padding: 5px 11px;
+  padding: 6px 13px;
   border-radius: 999px;
   background: rgba(34, 211, 238, 0.1);
   border: 1px solid rgba(34, 211, 238, 0.22);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   color: #7fe3f3;
   letter-spacing: 0.5px;
 }
```

- [ ] **Step 2: `App.test.tsx`（Header経由でレンダリングされる箇所を含む）を実行して回帰がないことを確認する**

```bash
cd frontend
npx vitest run src/App.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/components/Header.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): ヘッダーのフォントサイズとアイコンを拡大

- ブランド名・バッジ類をトークン化し、ロゴ/ドットのサイズも拡大
EOF
)"
```

---

### Task 3: サイドバー（`Sidebar.module.css`）

**Files:**
- Modify: `frontend/src/components/Sidebar.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .sidebar {
-  width: 228px;
+  width: 250px;
   flex: none;
   border-right: 1px solid var(--color-border);
   background: var(--color-panel-sidebar);
   backdrop-filter: blur(10px);
   padding: 15px 12px;
   display: flex;
   flex-direction: column;
   gap: 3px;
   overflow-y: auto;
 }

 .sectionLabel {
-  font-size: 10px;
+  font-size: var(--font-size-caption);
   font-weight: 700;
   letter-spacing: 1.6px;
   color: var(--color-text-muted);
   padding: 4px 10px 8px;
 }

 .navItem {
   display: flex;
   align-items: center;
   gap: 11px;
-  padding: 9px 10px;
+  padding: 11px 12px;
   border-radius: 9px;
   color: var(--color-text-secondary);
   text-decoration: none;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   background: transparent;
 }
```

```diff
 .settingsToggle {
   display: flex;
   align-items: center;
   gap: 11px;
-  padding: 9px 10px;
+  padding: 11px 12px;
   border-radius: 9px;
   color: var(--color-text-secondary);
   background: transparent;
   border: none;
   font-family: inherit;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   cursor: pointer;
   width: 100%;
   text-align: left;
 }
```

```diff
 .subNavItem {
   display: flex;
   align-items: center;
   gap: 9px;
-  padding: 8px 10px;
+  padding: 9px 11px;
   border-radius: 9px;
   color: var(--color-text-secondary);
   text-decoration: none;
-  font-size: 12.5px;
+  font-size: var(--font-size-caption);
 }
```

- [ ] **Step 2: `App.test.tsx` を実行して回帰がないことを確認する**

```bash
cd frontend
npx vitest run src/App.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/components/Sidebar.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): サイドバーのフォントサイズを拡大し幅を調整

- ナビゲーション項目・見出しをトークン化、拡大文字に合わせて幅を228px→250pxに拡張
EOF
)"
```

---

### Task 4: Dashboard（`Dashboard.module.css` + `Dashboard.tsx`）

**Files:**
- Modify: `frontend/src/pages/Dashboard.module.css`
- Modify: `frontend/src/pages/Dashboard.tsx:150-164,175,187,202,222`
- Test: `frontend/src/pages/Dashboard.test.tsx`（既存。新規テスト追加はしない）

**Interfaces:**
- Consumes: Task 1 の全トークン
- Produces: `.cardValueJudgment`（`Dashboard.module.css` 新規クラス。NG率・虚報率・見逃し率の3カードでのみ `.cardValue` と併用する）

- [ ] **Step 1: `Dashboard.module.css` を編集する**

```diff
 .filterField label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .filterField input,
 .filterField select {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.12);
   color: var(--color-text-primary);
-  padding: 7px 10px;
+  padding: 9px 12px;
   border-radius: 9px;
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   font-family: var(--font-mono);
   color-scheme: dark;
 }

 .applyButton {
-  padding: 9px 24px;
+  padding: 11px 26px;
   border-radius: 9px;
   background: linear-gradient(120deg, var(--color-accent-cyan), #38bdf8);
   border: none;
   color: #04141a;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   letter-spacing: 0.5px;
   cursor: pointer;
   font-family: inherit;
 }
```

```diff
 .cardLabel {
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-secondary);
   font-weight: 500;
 }

 .cardValue {
   font-family: var(--font-mono);
-  font-size: 24px;
+  font-size: var(--font-size-kpi);
   font-weight: 700;
   color: var(--color-text-primary);
 }
+
+.cardValueJudgment {
+  font-size: var(--font-size-judgment);
+}
```

```diff
 .panelTitle {
-  font-size: 13.5px;
+  font-size: var(--font-size-heading);
   font-weight: 700;
   color: var(--color-text-primary);
 }

 .panelSubtitle {
-  font-size: 11px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-muted);
 }
```

```diff
 .recordRow {
-  padding: 8px 12px;
+  padding: 10px 14px;
   font-family: var(--font-mono);
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   border-bottom: 1px solid rgba(255, 255, 255, 0.05);
 }
```

- [ ] **Step 2: `Dashboard.tsx` の該当箇所を読み、NG率・虚報率・見逃し率カードに `.cardValueJudgment` を追加する**

`frontend/src/pages/Dashboard.tsx:150-164` を編集:

```diff
           <div className={styles.card}>
             <span className={styles.cardLabel}>スループット</span>
             <span className={styles.cardValue}>{summary.data.throughput}</span>
           </div>
           <div className={styles.card}>
             <span className={styles.cardLabel}>NG率</span>
-            <span className={styles.cardValue}>{fmtPct(summary.data.ng_rate)}</span>
+            <span className={`${styles.cardValue} ${styles.cardValueJudgment}`}>
+              {fmtPct(summary.data.ng_rate)}
+            </span>
           </div>
           <div className={styles.card}>
             <span className={styles.cardLabel}>虚報率</span>
-            <span className={styles.cardValue}>{fmtPct(summary.data.false_alarm_rate)}</span>
+            <span className={`${styles.cardValue} ${styles.cardValueJudgment}`}>
+              {fmtPct(summary.data.false_alarm_rate)}
+            </span>
           </div>
           <div className={styles.card}>
             <span className={styles.cardLabel}>見逃し率</span>
-            <span className={styles.cardValue}>{fmtPct(summary.data.miss_rate)}</span>
+            <span className={`${styles.cardValue} ${styles.cardValueJudgment}`}>
+              {fmtPct(summary.data.miss_rate)}
+            </span>
           </div>
```

- [ ] **Step 3: グラフの高さと明細リストの行サイズを、拡大後の文字サイズに合わせて調整する**

`Dashboard.tsx:175` (`BarChart`):

```diff
-          <BarChart width={480} height={236} data={throughputChartData}>
+          <BarChart width={480} height={260} data={throughputChartData}>
```

`Dashboard.tsx:187` (`LineChart`):

```diff
-          <LineChart width={480} height={236} data={ngChartData}>
+          <LineChart width={480} height={260} data={ngChartData}>
```

`Dashboard.tsx:202` (`LineChart`):

```diff
-        <LineChart width={980} height={248} data={faMissChartData}>
+        <LineChart width={980} height={270} data={faMissChartData}>
```

`Dashboard.tsx:222` (`FixedSizeList`、明細一覧。`.recordRow` の実測行高は `font-size: 16px` の行の高さ約19px + 上下padding 20px + 下線1px ≈ 40px になるため `itemSize` をそれに合わせる。ズレると行が重なったり隙間が空くため、必ず一致させる):

```diff
-        <FixedSizeList height={200} width={980} itemCount={recordList.length} itemSize={30}>
+        <FixedSizeList height={240} width={980} itemCount={recordList.length} itemSize={40}>
```

- [ ] **Step 4: 既存テストと型チェックを実行する**

```bash
cd frontend
npx tsc --noEmit
npx vitest run src/pages/Dashboard.test.tsx
```

Expected: 両方成功。`Dashboard.test.tsx` はクラス名やpx値をアサートしていないため、DOM構造・表示テキストの変化がなければそのままPASSする想定。

- [ ] **Step 5: commit**

```bash
git add frontend/src/pages/Dashboard.module.css frontend/src/pages/Dashboard.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): Dashboardのフォントサイズを拡大し判定結果カードを強調

- NG率・虚報率・見逃し率のみ--font-size-judgment(40px)で強調表示
- グラフの高さと明細リストの行高を拡大後の文字サイズに合わせて調整
EOF
)"
```

---

### Task 5: TaskList（`TaskList.module.css`）

**Files:**
- Modify: `frontend/src/pages/TaskList.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .filterBar label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .filterBar select {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.12);
   color: var(--color-text-primary);
-  padding: 7px 10px;
+  padding: 9px 12px;
   border-radius: 9px;
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   color-scheme: dark;
   width: fit-content;
 }
```

```diff
 .table {
   width: 100%;
   border-collapse: collapse;
-  min-width: 920px;
+  min-width: 1100px;
 }

 .table th {
   text-align: left;
-  padding: 9px 12px;
-  font-size: 11px;
+  padding: 11px 14px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   color: var(--color-text-secondary);
   letter-spacing: 0.5px;
   border-bottom: 1px solid rgba(255, 255, 255, 0.1);
   background: rgba(16, 22, 34, 0.7);
 }

 .table td {
-  padding: 9px 12px;
-  font-size: 12.5px;
+  padding: 11px 14px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   border-bottom: 1px solid rgba(255, 255, 255, 0.05);
 }
```

```diff
 .commentCell input {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.12);
   color: var(--color-text-primary);
-  padding: 5px 8px;
+  padding: 6px 10px;
   border-radius: 7px;
-  font-size: 12px;
+  font-size: var(--font-size-caption);
 }

 .actionButton {
-  padding: 5px 12px;
+  padding: 6px 14px;
   border-radius: 999px;
   background: rgba(34, 211, 238, 0.14);
   color: #7fe3f3;
   border: 1px solid rgba(34, 211, 238, 0.25);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   cursor: pointer;
   font-family: inherit;
 }
```

- [ ] **Step 2: 既存テストを実行する**

```bash
cd frontend
npx vitest run src/pages/TaskList.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/TaskList.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): TaskListのフォントサイズと表の余白を拡大

- 表のmin-widthを920px→1100pxに拡張し、横スクロールで対応
EOF
)"
```

---

### Task 6: ThresholdManagement（`ThresholdManagement.module.css`）

**Files:**
- Modify: `frontend/src/pages/ThresholdManagement.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .infoBanner {
-  padding: 14px 18px;
+  padding: 16px 20px;
   border-radius: 14px;
   background: rgba(34, 211, 238, 0.06);
   border: 1px solid rgba(34, 211, 238, 0.16);
   display: flex;
   align-items: center;
   gap: 11px;
-  font-size: 12px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   line-height: 1.5;
   margin-bottom: 16px;
 }

 .infoDot {
-  width: 7px;
-  height: 7px;
+  width: 8px;
+  height: 8px;
   border-radius: 50%;
   background: var(--color-accent-cyan);
   flex: none;
 }
```

```diff
 .field label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .field select,
 .field input {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.14);
   color: var(--color-text-primary);
-  padding: 8px 10px;
+  padding: 10px 12px;
   border-radius: 9px;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   color-scheme: dark;
 }
```

```diff
 .submitButton {
-  padding: 9px 22px;
+  padding: 11px 24px;
   border-radius: 9px;
   background: linear-gradient(120deg, var(--color-accent-cyan), #38bdf8);
   border: none;
   color: #04141a;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   cursor: pointer;
   font-family: inherit;
 }

 .error {
   color: #fda4af;
   background: rgba(244, 63, 94, 0.1);
   border: 1px solid rgba(244, 63, 94, 0.28);
-  padding: 9px 12px;
+  padding: 10px 14px;
   border-radius: 9px;
-  font-size: 11.5px;
+  font-size: var(--font-size-body);
   margin-bottom: 16px;
 }
```

```diff
 .table th {
   text-align: left;
-  padding: 9px 12px;
-  font-size: 11px;
+  padding: 11px 14px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   color: var(--color-text-secondary);
   letter-spacing: 0.5px;
   border-bottom: 1px solid rgba(255, 255, 255, 0.1);
   background: rgba(16, 22, 34, 0.7);
 }

 .table td {
-  padding: 8px 12px;
-  font-size: 12.5px;
+  padding: 10px 14px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   border-bottom: 1px solid rgba(255, 255, 255, 0.05);
 }
```

```diff
 .disableButton {
-  padding: 5px 12px;
+  padding: 6px 14px;
   border-radius: 999px;
   background: rgba(255, 255, 255, 0.05);
   color: var(--color-text-secondary);
   border: 1px solid rgba(255, 255, 255, 0.12);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   cursor: pointer;
   font-family: inherit;
 }
```

- [ ] **Step 2: 既存テストを実行する**

```bash
cd frontend
npx vitest run src/pages/ThresholdManagement.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/ThresholdManagement.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): ThresholdManagementのフォントサイズを拡大

- エラーメッセージ・案内バナーは視認性重視でbodyサイズに統一
EOF
)"
```

---

### Task 7: EdgePc（`EdgePc.module.css`）

**Files:**
- Modify: `frontend/src/pages/EdgePc.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-kpi`, `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .field label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .field input {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.14);
   color: var(--color-text-primary);
-  padding: 8px 10px;
+  padding: 10px 12px;
   border-radius: 9px;
-  font-size: 13px;
+  font-size: var(--font-size-body);
 }

 .submitButton {
-  padding: 9px 22px;
+  padding: 11px 24px;
   border-radius: 9px;
   background: linear-gradient(120deg, var(--color-accent-cyan), #38bdf8);
   border: none;
   color: #04141a;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   cursor: pointer;
   font-family: inherit;
 }
```

```diff
 .cardName {
-  font-size: 14px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   color: var(--color-text-primary);
   letter-spacing: 0.5px;
 }

 .badgeEnabled {
-  font-size: 11px;
-  padding: 3px 10px;
+  font-size: var(--font-size-caption);
+  padding: 4px 12px;
   border-radius: 999px;
   background: rgba(52, 211, 153, 0.14);
   color: var(--color-accent-success);
   border: 1px solid rgba(52, 211, 153, 0.3);
 }

 .badgeDisabled {
-  font-size: 11px;
-  padding: 3px 10px;
+  font-size: var(--font-size-caption);
+  padding: 4px 12px;
   border-radius: 999px;
   background: rgba(255, 255, 255, 0.05);
   color: var(--color-text-muted);
   border: 1px solid rgba(255, 255, 255, 0.1);
 }
```

```diff
 .ipLabel {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .ipValue {
   font-family: var(--font-mono);
-  font-size: 20px;
+  font-size: var(--font-size-kpi);
   font-weight: 700;
   color: var(--color-text-primary);
   letter-spacing: -0.5px;
 }

 .meta {
   font-family: var(--font-mono);
-  font-size: 12px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-secondary);
 }
```

```diff
 .actionButton {
-  padding: 5px 12px;
+  padding: 6px 14px;
   border-radius: 999px;
   background: rgba(34, 211, 238, 0.14);
   color: #7fe3f3;
   border: 1px solid rgba(34, 211, 238, 0.25);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   cursor: pointer;
   font-family: inherit;
 }
```

- [ ] **Step 2: 既存テストを実行する**

```bash
cd frontend
npx vitest run src/pages/EdgePc.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/EdgePc.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): EdgePcのフォントサイズを拡大

- IPアドレス表示をKPIサイズ(28px)に拡大
EOF
)"
```

---

### Task 8: Retraining（`Retraining.module.css`）

**Files:**
- Modify: `frontend/src/pages/Retraining.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-heading`, `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .panelTitle {
-  font-size: 13.5px;
+  font-size: var(--font-size-heading);
   font-weight: 700;
   color: var(--color-text-primary);
 }
```

```diff
 .field label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
 }

 .field input {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.14);
   color: var(--color-text-primary);
-  padding: 8px 10px;
+  padding: 10px 12px;
   border-radius: 9px;
-  font-size: 13px;
+  font-size: var(--font-size-body);
 }

 .submitButton {
-  padding: 9px 22px;
+  padding: 11px 24px;
   border-radius: 9px;
   background: linear-gradient(120deg, var(--color-accent-cyan), #38bdf8);
   border: none;
   color: #04141a;
-  font-size: 13px;
+  font-size: var(--font-size-body);
   font-weight: 700;
   cursor: pointer;
   font-family: inherit;
 }

 .submitButton:disabled {
   opacity: 0.5;
   cursor: not-allowed;
 }

 .error {
   color: #fda4af;
   background: rgba(244, 63, 94, 0.1);
   border: 1px solid rgba(244, 63, 94, 0.28);
-  padding: 9px 12px;
+  padding: 10px 14px;
   border-radius: 9px;
-  font-size: 11.5px;
+  font-size: var(--font-size-body);
 }
```

```diff
 .table th {
   text-align: left;
-  padding: 9px 12px;
-  font-size: 11px;
+  padding: 11px 14px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   color: var(--color-text-secondary);
   letter-spacing: 0.5px;
   border-bottom: 1px solid rgba(255, 255, 255, 0.1);
   background: rgba(16, 22, 34, 0.7);
 }

 .table td {
-  padding: 8px 12px;
-  font-size: 12.5px;
+  padding: 10px 14px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   border-bottom: 1px solid rgba(255, 255, 255, 0.05);
 }

 .mono {
   font-family: var(--font-mono);
 }

 .actionButton {
-  padding: 5px 12px;
+  padding: 6px 14px;
   border-radius: 999px;
   background: rgba(34, 211, 238, 0.14);
   color: #7fe3f3;
   border: 1px solid rgba(34, 211, 238, 0.25);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   cursor: pointer;
   font-family: inherit;
   margin-right: 6px;
 }
```

```diff
 .statusRow {
   display: flex;
   align-items: center;
   gap: 10px;
-  padding: 10px 13px;
+  padding: 12px 15px;
   border-radius: 10px;
   background: rgba(34, 211, 238, 0.08);
   border: 1px solid rgba(34, 211, 238, 0.2);
-  font-size: 11.5px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
 }

 .pulseDot {
-  width: 9px;
-  height: 9px;
+  width: 10px;
+  height: 10px;
   border-radius: 50%;
   background: var(--color-accent-cyan);
   flex: none;
 }

 .logBox {
   background: rgba(0, 0, 0, 0.3);
   border: 1px solid var(--color-border);
   border-radius: 10px;
-  padding: 12px 14px;
+  padding: 14px 16px;
   font-family: var(--font-mono);
-  font-size: 12px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   white-space: pre-wrap;
   max-height: 260px;
   overflow-y: auto;
 }
```

- [ ] **Step 2: 既存テストを実行する**

```bash
cd frontend
npx vitest run src/pages/Retraining.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/Retraining.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): Retrainingのフォントサイズを拡大

- 進行状況・エラー表示をbodyサイズに統一し視認性を上げる
EOF
)"
```

---

### Task 9: ColorMaster（`ColorMaster.module.css`）

**Files:**
- Modify: `frontend/src/pages/ColorMaster.module.css`

**Interfaces:**
- Consumes: Task 1 の `--font-size-kpi`, `--font-size-body`, `--font-size-caption`

- [ ] **Step 1: 各ルールを編集する**

```diff
 .cardLabel {
-  font-size: 11px;
+  font-size: var(--font-size-caption);
   color: var(--color-text-secondary);
 }

 .cardValue {
   font-family: var(--font-mono);
   font-weight: 700;
-  font-size: 24px;
+  font-size: var(--font-size-kpi);
   color: var(--color-text-primary);
 }
```

```diff
 .toolbar label {
-  font-size: 10.5px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   letter-spacing: 0.5px;
   color: var(--color-text-secondary);
   margin-right: 6px;
 }

 .toolbar select,
 .toolbar input {
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.12);
   color: var(--color-text-primary);
-  padding: 7px 10px;
+  padding: 9px 12px;
   border-radius: 9px;
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   color-scheme: dark;
 }
```

```diff
 .pagerLabel {
-  font-size: 12px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   font-family: var(--font-mono);
 }
```

```diff
 .importResult {
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   margin: -6px 0 14px;
 }

 .importError {
-  font-size: 12.5px;
+  font-size: var(--font-size-body);
   color: var(--color-accent-danger, #f87171);
   margin: -6px 0 14px;
 }
```

```diff
 .table th {
   text-align: left;
-  padding: 9px 12px;
-  font-size: 11px;
+  padding: 11px 14px;
+  font-size: var(--font-size-caption);
   font-weight: 600;
   color: var(--color-text-secondary);
   letter-spacing: 0.5px;
   border-bottom: 1px solid rgba(255, 255, 255, 0.1);
   background: rgba(16, 22, 34, 0.7);
 }

 .table td {
-  padding: 8px 12px;
-  font-size: 12.5px;
+  padding: 10px 14px;
+  font-size: var(--font-size-body);
   color: var(--color-text-secondary);
   border-bottom: 1px solid rgba(255, 255, 255, 0.05);
 }
```

```diff
 .swatch {
-  width: 16px;
-  height: 16px;
+  width: 20px;
+  height: 20px;
   border-radius: 4px;
   border: 1px solid rgba(255, 255, 255, 0.2);
   flex: none;
 }

 .rgbInput {
-  width: 64px;
+  width: 72px;
   background: rgba(255, 255, 255, 0.04);
   border: 1px solid rgba(255, 255, 255, 0.12);
   color: var(--color-text-primary);
-  padding: 5px 8px;
+  padding: 6px 10px;
   border-radius: 7px;
-  font-size: 12px;
+  font-size: var(--font-size-caption);
 }

 .actionButton {
-  padding: 5px 12px;
+  padding: 6px 14px;
   border-radius: 999px;
   background: rgba(34, 211, 238, 0.14);
   color: #7fe3f3;
   border: 1px solid rgba(34, 211, 238, 0.25);
-  font-size: 11.5px;
+  font-size: var(--font-size-caption);
   cursor: pointer;
   font-family: inherit;
 }
```

- [ ] **Step 2: 既存テストを実行する**

```bash
cd frontend
npx vitest run src/pages/ColorMaster.test.tsx
```

Expected: PASS

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/ColorMaster.module.css
git commit -m "$(cat <<'EOF'
feat(frontend): ColorMasterのフォントサイズと色見本を拡大

- swatchを16px→20pxに拡大し、色の視認性も改善
EOF
)"
```

---

### Task 10: 全画面の最終確認

**Files:**
- なし（確認のみ。問題が見つかった場合のみ該当ファイルを追加修正する）

**Interfaces:**
- Consumes: Task 1〜9 の全変更

- [ ] **Step 1: ビルドが通ることを確認する**

```bash
cd frontend
npm run build
```

Expected: `tsc --noEmit` と `vite build` の両方が成功する

- [ ] **Step 2: 全テストを実行する**

```bash
cd frontend
npx vitest run
```

Expected: 既存の全テストが green

- [ ] **Step 3: 開発サーバーを起動し、6画面をブラウザで目視確認する**

```bash
cd frontend
npm run dev
```

以下の観点で各画面（Dashboard, TaskList, ThresholdManagement, EdgePc, Retraining, ColorMaster）を確認する:

- 文字が明らかに大きく見やすくなっているか
- Dashboard: NG率・虚報率・見逃し率が他のKPIより大きく強調表示されているか。明細一覧（`FixedSizeList`）の行が重なったり隙間が空いたりしていないか
- TaskList: 表が横スクロールで正しく表示され、崩れていないか
- 各画面: サイドバーのラベルが折り返れていないか。ボタン・入力欄が不自然に大きすぎたり、隣接要素と重なっていないか

- [ ] **Step 4: 問題が見つかった場合は該当タスクのファイルを修正し、再度コミットする**

問題がなければこのステップは不要。

---

## Self-Review 結果

- **spec カバレッジ:** 設計書の5(6)トークン・レイアウト崩れ対応方針（テーブル横スクロール・グリッド折り返し・サイドバー幅拡張）・検証方法（ブラウザ目視+既存テスト）は Task 1〜10 で全てカバーしている。
- **placeholder スキャン:** 「TBD」等のプレースホルダなし。全ステップに具体的なdiff・コマンド・期待結果を記載済み。
- **型/命名の一貫性:** `--font-size-*` トークン名は全タスクで統一。`.cardValueJudgment` は Task 4 で定義し、同タスク内でのみ使用（他タスクからの参照なし）。
- **スコープ:** 単一プランとして実行可能な範囲（CSS Modules 9ファイル + tokens.css + Dashboard.tsx の軽微なJSX変更）。追加のサブプロジェクト分割は不要と判断。
