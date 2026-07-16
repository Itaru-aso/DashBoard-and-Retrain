# 再学習進捗パネル可読化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** モデル再学習画面（`frontend/src/pages/Retraining.tsx`）の進捗パネルを、tqdm進捗ノイズを進捗バーに集約し、重要ログのみを既定表示、元の生ログは折りたたみ表示にする。

**Architecture:** バックエンドのWebSocket配信（素通し・揮発、`.kiro/specs/retraining` M-R6）は無変更。フロントエンドに行分類の純粋関数（`retrainingProgress.ts`）を追加し、`useJobProgress` フックで受信した各行をその場で「進捗」か「その他」に分類、`Retraining.tsx` の `ProgressPanel` を3段構成（進捗バー2本＋重要ログ＋元ログ展開）に変更する。

**Tech Stack:** React 18 / TypeScript（strict）/ Vite / Vitest + @testing-library/react。既存の `frontend/src/pages/dashboardChart.ts`（ページ横並びの純粋関数モジュール）と同じ配置パターンに従う。

## Global Constraints

- `training/` 配下（学習ロジック本体・tqdm呼び出し・print文）は一切変更しない。
- バックエンド（`backend/src/services/training_service.py`・WebSocket配信仕様）は一切変更しない。
- 既存の `Retraining.test.tsx` の既存テストケースは挙動を変えない（後方互換）。
- コードスタイル: `npm run lint`（eslint）・`npm run build`（`tsc --noEmit` 含む）・`npm test`（`vitest run`）がすべて通ること。
- コメントは日本語、WHYが非自明な箇所のみ（既存ファイルの記法に合わせる）。

---

## ファイル構成

- Create: `frontend/src/pages/retrainingProgress.ts` — 行分類の純粋関数 `classifyLine` と型定義。
- Create: `frontend/src/pages/retrainingProgress.test.ts` — `classifyLine` の単体テスト。
- Modify: `frontend/src/hooks/useRetraining.ts` — `useJobProgress` に `importantLines`・`progress` を追加。
- Modify: `frontend/src/pages/Retraining.tsx` — `ProgressPanel` を3段構成に変更、`ProgressBar` 小コンポーネントを追加。
- Modify: `frontend/src/pages/Retraining.module.css` — 進捗バー用・元ログ折りたたみ用のクラスを追加。
- Modify: `frontend/src/pages/Retraining.test.tsx` — 進捗バー表示・元ログ折りたたみの新規テストケースを追加（既存ケースは変更しない）。

---

### Task 1: 行分類の純粋関数 `classifyLine`

**Files:**
- Create: `frontend/src/pages/retrainingProgress.ts`
- Test: `frontend/src/pages/retrainingProgress.test.ts`

**Interfaces:**
- Produces:
  - `export type Phase = "monochro" | "color";`
  - `export interface ProgressState { percent: number; current: number; total: number; loss?: number; eta?: string; }`
  - `export type ClassifiedLine = ({ kind: "progress" } & ProgressState & { phase?: Phase; raw: string }) | { kind: "other"; phase?: Phase; raw: string };`
  - `export function classifyLine(raw: string): ClassifiedLine`

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/retrainingProgress.test.ts` を新規作成する:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/retrainingProgress.test.ts`
Expected: FAIL（`retrainingProgress.ts` が存在しないため `Cannot find module './retrainingProgress'`）

- [ ] **Step 3: Write minimal implementation**

`frontend/src/pages/retrainingProgress.ts` を新規作成する:

```ts
export type Phase = "monochro" | "color";

/** tqdm進捗1件ぶんの状態（%・現在ステップ/全ステップ・loss・ETA文字列）。 */
export interface ProgressState {
  percent: number;
  current: number;
  total: number;
  loss?: number;
  eta?: string;
}

export type ClassifiedLine =
  | ({ kind: "progress" } & ProgressState & { phase?: Phase; raw: string })
  | { kind: "other"; phase?: Phase; raw: string };

const PHASE_PREFIX = /^\[(monochro|color)\]\s*/;

// tqdm既定フォーマット: "{desc}: {percent}%|{bar}| {n}/{total} [{elapsed}<{remaining}, {rate}]"
// descはtqdmが空文字のとき省略されるため任意（training/ 側のtqdm呼び出しは変更しない前提で
// 両方のパターンを受け付ける）。
const TQDM_PATTERN =
  /^(?:(?<desc>.*?):\s*)?(?<percent>\d+)%\|.*?\|\s*(?<current>\d+)\/(?<total>\d+)\s*\[(?<elapsed>[^<]*)<(?<remaining>[^,]*),\s*(?<rate>[^\]]*)\]\s*$/;

const LOSS_PATTERN = /Current loss:\s*([\d.]+)/;

/** WebSocketで受信した1行を、tqdm進捗行かそれ以外（重要ログ）かに分類する。 */
export function classifyLine(raw: string): ClassifiedLine {
  const phaseMatch = raw.match(PHASE_PREFIX);
  const phase = phaseMatch ? (phaseMatch[1] as Phase) : undefined;
  const rest = phaseMatch ? raw.slice(phaseMatch[0].length) : raw;

  const m = TQDM_PATTERN.exec(rest);
  if (!m?.groups) {
    return { kind: "other", phase, raw };
  }

  const percent = Number(m.groups.percent);
  const current = Number(m.groups.current);
  const total = Number(m.groups.total);
  if (Number.isNaN(percent) || Number.isNaN(current) || Number.isNaN(total)) {
    return { kind: "other", phase, raw };
  }

  const lossMatch = m.groups.desc?.match(LOSS_PATTERN);
  const loss = lossMatch ? Number(lossMatch[1]) : undefined;
  const eta = `${m.groups.elapsed.trim()}<${m.groups.remaining.trim()}, ${m.groups.rate.trim()}`;

  return { kind: "progress", phase, raw, percent, current, total, loss, eta };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/retrainingProgress.test.ts`
Expected: PASS（5件すべて成功）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/retrainingProgress.ts frontend/src/pages/retrainingProgress.test.ts
git commit -m "feat(frontend): 再学習ログ行をtqdm進捗/その他に分類するclassifyLineを追加"
```

---

### Task 2: `useJobProgress` に `importantLines`・`progress` を追加

**Files:**
- Modify: `frontend/src/hooks/useRetraining.ts:76-101`（`useJobProgress` 関数全体）

**Interfaces:**
- Consumes: Task 1 の `classifyLine(raw: string): ClassifiedLine`、`Phase`、`ProgressState`（`@/pages/retrainingProgress` からimport）
- Produces: `useJobProgress(jobId, active)` の戻り値に `importantLines: string[]` と `progress: Partial<Record<Phase, ProgressState>>` を追加（既存の `lines: string[]`・`state: WsState` は変更しない）

このタスクにはフック単体のテストファイルは作らない（このリポジトリのフックは全てページテスト経由で検証する既存方針。`useRetraining.ts` 内の他フックにもテストファイルは無い）。動作確認は Task 4 の `Retraining.test.tsx` で行う。

- [ ] **Step 1: 既存コードを読み、変更箇所を確認する**

`frontend/src/hooks/useRetraining.ts` の先頭 import 群と `useJobProgress` (L70-101) が対象。

- [ ] **Step 2: import を追加する**

`frontend/src/hooks/useRetraining.ts` の先頭 import 群に追加:

```ts
import { classifyLine, type Phase, type ProgressState } from "@/pages/retrainingProgress";
```

- [ ] **Step 3: `useJobProgress` を書き換える**

既存の関数全体（`export function useJobProgress(...) { ... }`）を次に置き換える:

```ts
export function useJobProgress(jobId: number | null, active: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [importantLines, setImportantLines] = useState<string[]>([]);
  const [progress, setProgress] = useState<Partial<Record<Phase, ProgressState>>>({});
  const [state, setState] = useState<WsState>("closed");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (jobId == null || !active) return;
    setLines([]);
    setImportantLines([]);
    setProgress({});
    setState("connecting");
    const ws = new WebSocket(progressWsUrl(jobId));
    wsRef.current = ws;

    ws.onopen = () => setState("open");
    ws.onmessage = (ev) => {
      const raw = String(ev.data);
      setLines((prev) => [...prev, raw]);

      const classified = classifyLine(raw);
      if (classified.kind === "progress") {
        // phase不明の進捗行は表示先が定まらないため無視する（並列学習では常に
        // [monochro]/[color] 接頭辞が付くため実運用では発生しない）。
        if (classified.phase) {
          const phase = classified.phase;
          setProgress((prev) => ({
            ...prev,
            [phase]: {
              percent: classified.percent,
              current: classified.current,
              total: classified.total,
              loss: classified.loss,
              eta: classified.eta,
            },
          }));
        }
      } else {
        setImportantLines((prev) => [...prev, raw]);
      }
    };
    ws.onerror = () => setState("closed");
    ws.onclose = () => setState("closed");

    return () => {
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    };
  }, [jobId, active]);

  return { lines, importantLines, progress, state };
}
```

- [ ] **Step 4: 型チェックを実行する**

Run: `cd frontend && npx tsc --noEmit`
Expected: エラー無し（`Retraining.tsx` はまだ新フィールドを使っていないので既存部分は変化なし）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useRetraining.ts
git commit -m "feat(frontend): useJobProgressにimportantLines/progressを追加"
```

---

### Task 3: `Retraining.tsx` の `ProgressPanel` を3段構成に変更

**Files:**
- Modify: `frontend/src/pages/Retraining.tsx:85-115`（`ProgressPanel` 関数、新規に `ProgressBar` 関数を追加）
- Modify: `frontend/src/pages/Retraining.module.css`（末尾に新規クラスを追加）

**Interfaces:**
- Consumes: Task 2 で `useJobProgress` が返す `{ lines, importantLines, progress, state }`。Task 1 の `Phase`, `ProgressState`（`@/pages/retrainingProgress` からimport）。
- Produces: `ProgressPanel` の見た目（進捗バー2本→重要ログ→`<details>`元ログ）。他タスクからは参照されない（末端）。

- [ ] **Step 1: CSSクラスを追加する**

`frontend/src/pages/Retraining.module.css` の末尾に追加:

```css
.progressBars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progressBarRow {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--font-size-body);
  color: var(--color-text-secondary);
}

.progressBarLabel {
  flex: none;
  width: 84px;
  font-weight: 600;
}

.progressBarTrack {
  flex: 1;
  height: 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.progressBarFill {
  height: 100%;
  background: linear-gradient(120deg, var(--color-accent-cyan), #38bdf8);
  border-radius: 999px;
  transition: width 0.2s ease;
}

.progressBarText {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  white-space: nowrap;
}

.progressBarWaiting {
  flex: 1;
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  opacity: 0.7;
}

.rawLogDetails summary {
  cursor: pointer;
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}
```

- [ ] **Step 2: `Retraining.tsx` の import を更新する**

`frontend/src/pages/Retraining.tsx` の先頭 import 群、

```ts
import { isTerminal, type Job, type JobStatus } from "@/api/retrainingApi";
```

の下に追加:

```ts
import type { Phase, ProgressState } from "@/pages/retrainingProgress";
```

- [ ] **Step 3: `ProgressBar` コンポーネントを追加する**

`ProgressPanel` 関数の直前に追加:

```tsx
const PHASE_LABEL: Record<Phase, string> = { monochro: "モノクロAI", color: "カラーAI" };

function ProgressBar({ phase, state }: { phase: Phase; state?: ProgressState }) {
  const label = PHASE_LABEL[phase];
  if (!state) {
    return (
      <div className={styles.progressBarRow}>
        <span className={styles.progressBarLabel}>{label}</span>
        <span className={styles.progressBarWaiting}>待機中…</span>
      </div>
    );
  }
  const detail = [
    `${state.percent}% (${state.current}/${state.total})`,
    state.loss != null ? `loss=${state.loss}` : null,
    state.eta ?? null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={styles.progressBarRow}>
      <span className={styles.progressBarLabel}>{label}</span>
      <div
        className={styles.progressBarTrack}
        role="progressbar"
        aria-label={`${label}進捗`}
        aria-valuenow={state.percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={styles.progressBarFill} style={{ width: `${state.percent}%` }} />
      </div>
      <span className={styles.progressBarText}>{detail}</span>
    </div>
  );
}
```

- [ ] **Step 4: `ProgressPanel` を書き換える**

既存の `ProgressPanel` 関数全体を次に置き換える:

```tsx
function ProgressPanel({ job }: { job: Job }) {
  const active = !isTerminal(job.status);
  const { lines, importantLines, progress, state } = useJobProgress(job.id, active);

  return (
    <div className={styles.progressCard}>
      <span className={styles.panelTitle}>
        進捗 — ジョブ #{job.id}（{job.color_no}/{job.size}/{job.chain}/{job.tape || "—"}）
      </span>
      <div className={styles.statusRow}>
        <span className={styles.pulseDot} />
        <span>
          {STATUS_LABEL[job.status]}
          {active ? (state === "open" ? " 配信中" : " 接続中…") : " 学習は終了しています"}
        </span>
      </div>
      <div className={styles.progressBars}>
        <ProgressBar phase="monochro" state={progress.monochro} />
        <ProgressBar phase="color" state={progress.color} />
      </div>
      <pre aria-live="polite" aria-label="学習ログ" className={styles.logBox}>
        {importantLines.length
          ? importantLines.join("\n")
          : active
            ? "ログ待機中…"
            : "ライブログはありません（終了済み）。"}
      </pre>
      <details className={styles.rawLogDetails}>
        <summary>元ログを表示</summary>
        <pre aria-label="元ログ" className={styles.logBox}>
          {lines.length ? lines.join("\n") : "ログはありません。"}
        </pre>
      </details>
      {job.status === "FAILED" && job.error_message && (
        <p role="alert" className={styles.error}>
          失敗理由: {job.error_message}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 型チェック・lintを実行する**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/pages/Retraining.tsx src/hooks/useRetraining.ts`
Expected: エラー無し

- [ ] **Step 6: 既存テストを実行し、後方互換を確認する**

Run: `cd frontend && npx vitest run src/pages/Retraining.test.tsx`
Expected: 既存の全ケースが PASS（"履歴を一覧表示し、進捗を開くと WS の行が素通し表示される" は "学習開始"/"パイプライン完了" が `other` 分類のため `importantLines` 経由で同じ aria-label="学習ログ" に表示され、変更なしで通る）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Retraining.tsx frontend/src/pages/Retraining.module.css
git commit -m "feat(frontend): 再学習の進捗パネルを進捗バー+重要ログ+元ログ展開の3段構成に変更"
```

---

### Task 4: 進捗バー・元ログ展開の新規テストを追加

**Files:**
- Modify: `frontend/src/pages/Retraining.test.tsx`（既存のケースは変更せず、末尾に新規 `it` を追加）

**Interfaces:**
- Consumes: Task 3 で変更した `ProgressPanel`（`role="progressbar"` の `aria-label` が `"モノクロAI進捗"`/`"カラーAI進捗"`、元ログの `aria-label` が `"元ログ"`、`<details><summary>元ログを表示</summary></details>` で折りたたまれている）。

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Retraining.test.tsx` の `describe("Retraining 画面", () => { ... })` 内、既存の最後の `it(...)` の後（`});` の直前）に追加:

```tsx
  it("tqdm進捗行は進捗バーに反映され、学習ログには重要行のみ表示される", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 11, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit("[monochro] 🟢 モノクロAIの学習を開始します...");
    ws.emit(
      "[monochro] Current loss: 0.37  :  91%|████████ | 22001/24120 [1:05:02<5:39:04,  9.60s/it]",
    );

    const bar = await screen.findByRole("progressbar", { name: "モノクロAI進捗" });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "91"));

    const log = screen.getByLabelText("学習ログ");
    expect(within(log).getByText(/モノクロAIの学習を開始します/)).toBeInTheDocument();
    expect(within(log).queryByText(/Current loss/)).not.toBeInTheDocument();
  });

  it("元ログは既定で折りたたまれ、開くと全行（進捗行含む）が見える", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 12, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit(
      "[color] Current loss: 0.10  :  10%|█ | 100/1000 [00:10<01:30, 10.0it/s]",
    );

    expect(screen.queryByLabelText("元ログ")).not.toBeVisible();
    fireEvent.click(screen.getByText("元ログを表示"));
    await waitFor(() => expect(screen.getByLabelText("元ログ")).toBeVisible());
    expect(within(screen.getByLabelText("元ログ")).getByText(/Current loss/)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Retraining.test.tsx`
Expected: FAIL（Task 3 が未適用の場合は `role="progressbar"` や `aria-label="元ログ"` が無く失敗する。Task 3 適用後にこのタスクを行う場合は、下記Step4で先にPASSすることを確認してから逆にTask3側の実装を一時的に戻す必要はない——通常はTask 3のコミット後にこのテストを書くため、そのままPASSする状態になる。その場合はStep2は省略しStep4のみ実施する）

- [ ] **Step 3: （Task 3 実装済みのため）追加実装は不要**

Task 3 で `ProgressPanel` は既に3段構成になっているため、テスト追加のみでこのタスクは完結する。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/Retraining.test.tsx`
Expected: PASS（既存ケース＋新規2件すべて成功）

- [ ] **Step 5: 全体テスト・ビルドを実行する**

Run: `cd frontend && npm test && npm run build && npm run lint`
Expected: すべて成功

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Retraining.test.tsx
git commit -m "test(frontend): 再学習の進捗バー表示と元ログ展開のテストを追加"
```

---

## Self-Review Notes

- **Spec coverage:** 設計書（`docs/superpowers/specs/2026-07-16-retraining-progress-readability-design.md`）の「分類ロジック」→Task 1、「フック」→Task 2、「UI」→Task 3、「テスト方針」→Task 1/4 で網羅。「スコープ外」節（200行バッファ制約・training/ 不変・バックエンド不変）はいずれのタスクでも変更対象にしていない。
- **Placeholder scan:** 各ステップに実コードを記載済み。TBD/TODOなし。
- **Type consistency:** `Phase`（`"monochro" | "color"`）・`ProgressState`（`percent`/`current`/`total`/`loss?`/`eta?`）・`ClassifiedLine` はTask 1で定義し、Task 2・3で同じ名前・形をimportして使用している。`useJobProgress` の戻り値 `{ lines, importantLines, progress, state }` はTask 2で定義し、Task 3の分割代入と一致させた。
