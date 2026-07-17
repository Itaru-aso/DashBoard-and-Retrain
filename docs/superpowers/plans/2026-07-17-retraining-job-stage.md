# 再学習ジョブ全体のステージ表示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** モデル再学習画面の進捗パネルに、ジョブ全体が今どのステージ（バックアップ中/学習中/モデル出力・評価中/完了）にいるかをテキストで表示する。

**Architecture:** `training/pipline.py`/`model_exporter.py` が既に出力している既知のprint文をマーカーとして、フロントエンドで受信済みの生ログ行から検出する。バックエンド（WebSocket配信）・`training/`側は無変更。検出したステージは単調前進のみ（後退しない）。数値%の全体進行度は推定しない。

**Tech Stack:** React 18 / TypeScript（strict）/ Vite / Vitest + @testing-library/react。既存の `frontend/src/pages/retrainingProgress.ts`（[[2026-07-16-retraining-progress-readability]] で追加）を拡張する。

## Global Constraints

- `training/` 配下（学習ロジック本体・print文）は一切変更しない。
- バックエンド（`backend/src/services/training_service.py`・WebSocket配信仕様）は一切変更しない。
- 既存の `retrainingProgress.test.ts`・`Retraining.test.tsx` の既存テストケースは挙動を変えない（後方互換）。
- ステージは単調前進のみ（検出したステージが現在より後方の場合のみ更新、後退させない）。
- 数値%での全体進行度は実装しない（設計書のスコープ外節）。
- `npm run lint` / `npm run build`（`tsc --noEmit`含む）/ `npm test` がすべて通ること。
- コメントは日本語、WHYが非自明な箇所のみ。

---

## ファイル構成

- Modify: `frontend/src/pages/retrainingProgress.ts` — `Stage` 型・`STAGE_LABEL`・`STAGE_ORDER`・`detectStage` を追加。
- Modify: `frontend/src/pages/retrainingProgress.test.ts` — `detectStage` の単体テストを追加。
- Modify: `frontend/src/hooks/useRetraining.ts` — `useJobProgress` に `stage` を追加（単調前進ロジック）。
- Modify: `frontend/src/pages/Retraining.tsx` — `ProgressPanel` のステータス行にステージラベルを追加表示。
- Modify: `frontend/src/pages/Retraining.module.css` — ステージラベル用クラスを追加。
- Modify: `frontend/src/pages/Retraining.test.tsx` — ステージ表示・単調前進の新規テストケースを追加（既存ケースは変更しない）。

---

### Task 1: `Stage` 型・`detectStage` 純粋関数

**Files:**
- Modify: `frontend/src/pages/retrainingProgress.ts`
- Modify: `frontend/src/pages/retrainingProgress.test.ts`

**Interfaces:**
- Produces:
  - `export type Stage = "backup" | "training" | "export_eval" | "completed";`
  - `export const STAGE_LABEL: Record<Stage, string>`
  - `export const STAGE_ORDER: readonly Stage[]`（`["backup", "training", "export_eval", "completed"]`。他タスクは `STAGE_ORDER.indexOf(stage)` で前後関係を比較する）
  - `export function detectStage(raw: string): Stage | undefined`

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/retrainingProgress.test.ts` の末尾（既存の `describe("classifyLine", ...)` ブロックの後）に追加:

```ts
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
```

そして同ファイル先頭のimportを更新:

```ts
import { classifyLine, detectStage } from "./retrainingProgress";
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/retrainingProgress.test.ts`
Expected: FAIL（`detectStage` が存在しないため `is not a function` / import エラー）

- [ ] **Step 3: Write minimal implementation**

`frontend/src/pages/retrainingProgress.ts` の末尾に追加:

```ts
export type Stage = "backup" | "training" | "export_eval" | "completed";

export const STAGE_LABEL: Record<Stage, string> = {
  backup: "バックアップ中",
  training: "学習中",
  export_eval: "モデル出力・評価中",
  completed: "完了",
};

export const STAGE_ORDER: readonly Stage[] = ["backup", "training", "export_eval", "completed"];

// training/pipline.py・training/model_exporter.py が実際に出力するテキストをマーカーに使う
// （print文自体は変更しない）。並列学習では monochro/color どちらの開始行が来ても training
// ステージなので、複数マーカーが同一ステージを指すのは意図通り。
const STAGE_MARKERS: { stage: Stage; pattern: RegExp }[] = [
  { stage: "backup", pattern: /バックアップ作成中/ },
  { stage: "training", pattern: /(モノクロAIの学習を開始します|カラーAIの学習を開始します|並列学習 GPU 割当)/ },
  { stage: "export_eval", pattern: /^Exported ONNX:/ },
  { stage: "completed", pattern: /パイプライン完了/ },
];

/** 生ログ1行から検出できるジョブ全体のステージを返す（該当なしはundefined）。 */
export function detectStage(raw: string): Stage | undefined {
  for (const { stage, pattern } of STAGE_MARKERS) {
    if (pattern.test(raw)) return stage;
  }
  return undefined;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/retrainingProgress.test.ts`
Expected: PASS（既存8件＋新規5件＝13件すべて成功）

- [ ] **Step 5: 型チェック・lintを実行する**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/pages/retrainingProgress.ts src/pages/retrainingProgress.test.ts`
Expected: エラー無し

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/retrainingProgress.ts frontend/src/pages/retrainingProgress.test.ts
git commit -m "feat(frontend): ジョブ全体のステージを検出するdetectStageを追加"
```

---

### Task 2: `useJobProgress` に `stage` を追加（単調前進）

**Files:**
- Modify: `frontend/src/hooks/useRetraining.ts:1-132`（import と `useJobProgress` 関数）

**Interfaces:**
- Consumes: Task 1 の `detectStage(raw: string): Stage | undefined`、`STAGE_ORDER: readonly Stage[]`、`Stage`（`@/pages/retrainingProgress` からimport）
- Produces: `useJobProgress(jobId, active)` の戻り値に `stage: Stage | undefined` を追加（既存の `lines`/`importantLines`/`progress`/`state` は変更しない）

このタスクにはフック単体のテストファイルは作らない（既存方針: フックはページテスト経由で検証。Task 3 で動作確認する）。

- [ ] **Step 1: import を更新する**

`frontend/src/hooks/useRetraining.ts` の既存のimport行

```ts
import { classifyLine, type Phase, type ProgressState } from "@/pages/retrainingProgress";
```

を次に置き換える:

```ts
import {
  classifyLine,
  detectStage,
  STAGE_ORDER,
  type Phase,
  type ProgressState,
  type Stage,
} from "@/pages/retrainingProgress";
```

- [ ] **Step 2: `useJobProgress` を書き換える**

既存の関数全体（`export function useJobProgress(...) { ... }`、現在77-132行目）を次に置き換える:

```ts
export function useJobProgress(jobId: number | null, active: boolean) {
  const [lines, setLines] = useState<string[]>([]);
  const [importantLines, setImportantLines] = useState<string[]>([]);
  const [progress, setProgress] = useState<Partial<Record<Phase, ProgressState>>>({});
  const [stage, setStage] = useState<Stage | undefined>(undefined);
  const [state, setState] = useState<WsState>("closed");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (jobId == null || !active) return;
    setLines([]);
    setImportantLines([]);
    setProgress({});
    setStage(undefined);
    setState("connecting");
    const ws = new WebSocket(progressWsUrl(jobId));
    wsRef.current = ws;

    ws.onopen = () => setState("open");
    ws.onmessage = (ev) => {
      const raw = String(ev.data);
      setLines((prev) => [...prev, raw]);

      const detectedStage = detectStage(raw);
      if (detectedStage) {
        // 単調前進のみ（後退しない）。並列学習で monochro/color どちらの行が
        // 来ても同じ training ステージなので後退は起きない。
        setStage((prev) =>
          prev === undefined || STAGE_ORDER.indexOf(detectedStage) > STAGE_ORDER.indexOf(prev)
            ? detectedStage
            : prev,
        );
      }

      const classified = classifyLine(raw);
      if (classified.kind === "progress") {
        // phase不明、または学習ループ本体以外（閾値計算・中間処理など）の進捗行は
        // バーに反映しない。totalが小さくすぐ100%に達するため、学習ループ本体の
        // 進捗と混ぜると「学習が完了した」ように誤認させる（phase不明は並列学習では
        // 常に[monochro]/[color]接頭辞が付くため実運用では発生しない）。
        if (classified.phase && classified.isMainLoop) {
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

  return { lines, importantLines, progress, stage, state };
}
```

- [ ] **Step 3: 型チェックを実行する**

Run: `cd frontend && npx tsc --noEmit`
Expected: エラー無し（`Retraining.tsx` はまだ `stage` を使っていないので既存部分は変化なし）

- [ ] **Step 4: lintを実行する**

Run: `cd frontend && npx eslint src/hooks/useRetraining.ts`
Expected: エラー無し

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useRetraining.ts
git commit -m "feat(frontend): useJobProgressにジョブ全体のstage（単調前進）を追加"
```

---

### Task 3: `ProgressPanel` にステージラベルを表示

**Files:**
- Modify: `frontend/src/pages/Retraining.tsx`（import と `ProgressPanel` 関数、現在123-163行目）
- Modify: `frontend/src/pages/Retraining.module.css`（末尾に新規クラスを追加）
- Modify: `frontend/src/pages/Retraining.test.tsx`（新規テストケースを追加）

**Interfaces:**
- Consumes: Task 2 で `useJobProgress` が返す `stage: Stage | undefined`。Task 1 の `STAGE_LABEL`, `Stage`（`@/pages/retrainingProgress` からimport）。
- Produces: `ProgressPanel` の見た目（ステータス行にステージラベルを追加）。他タスクからは参照されない（末端）。

- [ ] **Step 1: CSSクラスを追加する**

`frontend/src/pages/Retraining.module.css` の末尾に追加:

```css
.stageLabel {
  font-size: var(--font-size-caption);
  color: var(--color-text-secondary);
  opacity: 0.85;
}
```

- [ ] **Step 2: `Retraining.tsx` の import を更新する**

既存の

```ts
import type { Phase, ProgressState } from "@/pages/retrainingProgress";
```

を次に置き換える:

```ts
import { STAGE_LABEL, type Phase, type ProgressState } from "@/pages/retrainingProgress";
```

（`Stage` 型は `STAGE_LABEL[stage]` の添字アクセスで暗黙的に使われるだけで、JSX側で型注釈として明示する箇所が無いため import しない。`tsconfig.json` の `noUnusedLocals: true` により未使用importはビルドエラーになるため、実際に使う識別子だけをimportすること。）

- [ ] **Step 3: `ProgressPanel` を書き換える**

既存の `ProgressPanel` 関数（現在123-163行目）を次に置き換える:

```tsx
function ProgressPanel({ job }: { job: Job }) {
  const active = !isTerminal(job.status);
  const { lines, importantLines, progress, stage, state } = useJobProgress(job.id, active);

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
        {active && (
          <span className={styles.stageLabel}>
            現在の処理: {stage ? STAGE_LABEL[stage] : "起動中…"}
          </span>
        )}
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

- [ ] **Step 4: 型チェック・lintを実行する**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/pages/Retraining.tsx`
Expected: エラー無し

- [ ] **Step 5: Write the failing tests**

`frontend/src/pages/Retraining.test.tsx` の `describe("Retraining 画面", () => { ... })` 内、既存の最後の `it(...)` の後（`});` の直前）に追加:

```tsx
  it("ステージ表示: マーカー行に応じて「現在の処理」ラベルが更新される", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 14, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    expect(screen.getByText("現在の処理: 起動中…")).toBeInTheDocument();

    ws.emit("バックアップ作成中...");
    await waitFor(() => expect(screen.getByText("現在の処理: バックアップ中")).toBeInTheDocument());

    ws.emit("並列学習 GPU 割当: monochro=GPU0, color=GPU1 (検出: 2枚)");
    await waitFor(() => expect(screen.getByText("現在の処理: 学習中")).toBeInTheDocument());
  });

  it("ステージ表示: 単調前進のみで、前段のマーカーが遅延到着しても後退しない", async () => {
    mocked.listJobs.mockResolvedValue({
      items: [job({ id: 15, status: "RUNNING" })],
      limit: 50,
      offset: 0,
    });
    render(<Retraining />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: "進捗" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    await waitFor(() => expect(ws.readyState).toBe(1));

    ws.emit("Exported ONNX: /model_dir/501/monochro/501_monochro_model.onnx");
    await waitFor(() =>
      expect(screen.getByText("現在の処理: モデル出力・評価中")).toBeInTheDocument(),
    );

    // 並列学習中のcolor側の開始行が遅れて届いても、export_evalより前段のtrainingへは戻らない。
    ws.emit("🔵 カラーAIの学習を開始します... (物理 GPU: 1, 論理 cuda:0, color: 501)");
    await waitFor(() =>
      expect(screen.getByText("現在の処理: モデル出力・評価中")).toBeInTheDocument(),
    );
    expect(screen.queryByText("現在の処理: 学習中")).not.toBeInTheDocument();
  });
```

- [ ] **Step 6: Run test to verify it fails (if applying before Step 3) — 通常はStep3実装済みなので直ちにPASSする**

Run: `cd frontend && npx vitest run src/pages/Retraining.test.tsx`
Expected: PASS（Step 3 が既に適用済みのため。もしまだ適用していない場合はここでFAILし、Step 3を適用後に再実行する）

- [ ] **Step 7: 既存テストを含め全件確認する**

Run: `cd frontend && npx vitest run src/pages/Retraining.test.tsx`
Expected: 既存10件＋新規2件＝12件すべて PASS

- [ ] **Step 8: 全体テスト・ビルドを実行する**

Run: `cd frontend && npm test && npm run build && npm run lint`
Expected: すべて成功

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/Retraining.tsx frontend/src/pages/Retraining.module.css frontend/src/pages/Retraining.test.tsx
git commit -m "feat(frontend): 再学習の進捗パネルにジョブ全体のステージ表示を追加"
```

---

## Self-Review Notes

- **Spec coverage:** 設計書（`docs/superpowers/specs/2026-07-17-retraining-job-stage-design.md`）の「ステージ定義」→Task 1、「検出ロジック（単調前進）」→Task 1・2、「UI」→Task 3、「テスト方針」→Task 1・3で網羅。「スコープ外」（数値%推定なし・training/無変更・バックエンド無変更）はいずれのタスクでも実施していない。
- **Placeholder scan:** 各ステップに実コードを記載済み。TBD/TODOなし。
- **Type consistency:** `Stage`（`"backup" | "training" | "export_eval" | "completed"`）・`STAGE_LABEL`・`STAGE_ORDER`はTask 1で定義し、Task 2・3で同じ名前・形をimportして使用している。`useJobProgress` の戻り値 `{ lines, importantLines, progress, stage, state }` はTask 2で定義し、Task 3の分割代入と一致させた。
