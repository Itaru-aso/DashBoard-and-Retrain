# 保守タスク自動生成・管理 — Design

> spec: `保守タスク自動生成・管理 (maintenance-task)`
> 配置想定: `.kiro/specs/maintenance-task/design.md`
> 上流: `requirements.md`（R1–R6・確定事項）／ steering: `product.md`・`tech.md`・`structure.md`
> 依存 spec: `閾値管理`（`resolve_effective`）／ `日次集計基盤`（`daily_metrics` 号機合算・共有 `services/metrics.py`）

## 概要・方針 (Overview)

日次でメトリクス（NG率・虚報率・見逃し率）を有効閾値と比較し、`値 > 閾値` の単位に保守タスクを upsert する。
評価は**アプリ内日次スケジューラ**が起動し、**冪等**（直近一定期間を再評価しても重複しない）・**自動クローズ無し**。
タスクは **ver2 DB**（自前・Alembic）に置く。メトリクスは **`日次集計基盤` の `daily_metrics`（号機合算）**を読み、
率は共有 `services/metrics.py`（基盤所有）で算出する。閾値は ver2 DB の `閾値管理` から解決する。
`daily_metrics` も閾値もともに ver2 だが、突合は **Service 層**で行う（集計は基盤側で完了済み・越境結合なし）。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/task.py` … `task`（ver2 テーブル・Alembic。`comments` は JSONB）
- `src/repositories/task_repository.py` … タスクの upsert・検索・状態遷移・コメント・一覧（ver2 エンジン）
- `src/services/metrics.py`（**`日次集計基盤` 所有**・共有）… 件数→率算出・KPI の NULL 判定（本 spec は呼び出して使う）
- `src/services/breach_evaluation_service.py` … 逸脱判定（`daily_metrics` 号機合算読み出し ＋ `metrics.py` 率算出 ＋ `resolve_effective` 比較 ＋ upsert）
- `src/services/task_service.py` … タスク管理（状態遷移・コメント・再発防止メモ・一覧）
- `src/jobs/breach_eval_job.py` … 日次ジョブ（スケジューラから起動・Service を呼ぶ薄い層）
- `src/schemas/task.py` … 入出力スキーマ
- `src/api/task_endpoint.py` … FastAPI ルーター（`main.py` 登録）
- `alembic/versions/<rev>_create_task.py` … タスクテーブルのマイグレーション（ver2 DB）

## データモデル (Data Model — ver2 DB)

**task**
- `id`（PK）
- `color_no` / `size` / `chain` / `tape`（フルタプル。棚卸しで tape 無しなら除外＝`閾値`/`ダッシュボード`と連動）
- `task_type`（enum: `ng_rate` / `false_alarm_rate` / `miss_rate`）
- `status`（enum: `OPEN` / `IN_PROGRESS` / `DONE`。既定 `OPEN`）
- `detected_value` / `threshold_value` / `evaluation_date`（逸脱の内容。上書き時に最新化）
- `comments`（JSONB 配列・追記型。各要素 `{ body, created_at }`。**記入者は持たない＝匿名**。経過コメントを積む。**再発防止策もここに記録**）
- `created_at` / `updated_at`（timestamptz）
- **部分ユニーク制約**: `UNIQUE (color_no, size, chain, tape, task_type) WHERE status IN ('OPEN','IN_PROGRESS')`
  → 「同キーにアクティブなタスクは高々1件」を **DB レベルで担保**（多重発火・同時実行でも安全）。

## 逸脱判定フロー (Breach Evaluation — R1 / R2)

`breach_evaluation_service.evaluate(window)`（直近 `window` 日＝**JST 日付**を対象）:
1. **有効閾値の側から駆動する**: `閾値管理` から、対象期間に有効な閾値の `(metric, フルタプル)` を取得する
   （閾値が無い色は最初から評価対象に入らない＝無駄な集計をしない。結果は「閾値なしは判定しない」R1.2 と同じ）。
2. 対象の `(metric, フルタプル)` × 期間内の各 **JST 日** について、`daily_metrics` を**号機合算**で読み（全号機）、
   `services/metrics.py`（基盤所有）で率を算出する。
3. 各単位で `resolve_effective(metric, フルタプル, 日)` の閾値と比較:
   - メトリクスが NULL（KPI ラベル0件）→ **スキップ＋WARN ログ**（R1.3）。
   - `値 > 閾値` → **逸脱** → タスク upsert（`task_type = metric`）。
4. upsert（R2）: キー `(color_no,size,chain,tape,task_type)` でアクティブ（`OPEN`/`IN_PROGRESS`）を検索。
   - 無し（皆無 or 過去 `DONE` のみ）→ `OPEN` 新規作成（`DONE` は履歴として残す＝再発再起票）。
   - `OPEN` あり → 上書き（`detected_value`/`threshold_value`/`evaluation_date` を最新化）。
   - `IN_PROGRESS` あり → 保持（変更しない）。
   - 競合は部分ユニーク制約で吸収（INSERT 衝突時はアクティブを更新へフォールバック）。
- **冪等**: 同じ日を再評価しても上記により重複しない。**自動クローズしない**（閾値内に戻っても OPEN は閉じない）。

## スケジューラ (Scheduler — R1.4)

- `main.py` 起動時にアプリ内スケジューラ（例: APScheduler）を開始し、`jobs/breach_eval_job.py` を
  **日次**（`BREACH_EVAL_TIME`）で登録。ジョブは `breach_evaluation_service.evaluate(BREACH_EVAL_WINDOW_DAYS)` を呼ぶ。
- **単一ワーカが所有**（再学習 subprocess と同じ前提）。`BREACH_EVAL_ENABLED` で無効化可。
- **順序**: `日次集計基盤` の集計ジョブが当日分の `daily_metrics` を更新した**後**に逸脱判定が走る（集計 → 逸脱判定 → 昇格）。
- 多重発火しても冪等＋部分ユニークで安全。
- 手動トリガー `POST /api/tasks/evaluate` を設ける（テスト・即時実行用。確定）。

## タスク管理 (Task Management — R3 / R4 / R5)

- **状態遷移**（`task_service`）: `OPEN → IN_PROGRESS → DONE` の前進のみ許可。逆遷移・段飛ばしは拒否（**409 Conflict**）。
- **コメント**: `task.comments`（JSONB）に追記。**経過と再発防止策をここに記録**（R4）。
- **一覧**: `status` / 色 / `task_type` / 期間（`created_at`）で絞り込み（R5）。

## API 設計 (Endpoints)

`get_db`（ver2 DB）依存。Basic 認証ゲート。**手動作成のエンドポイントは設けない**（自動起票のみ）。

- `GET /api/tasks` … 一覧（filter: status, color_no, size, chain, tape, task_type, from, to）
- `GET /api/tasks/{id}` … 詳細（コメント含む）
- `PATCH /api/tasks/{id}/status` … 状態遷移（前進のみ。違反は 409）
- `POST /api/tasks/{id}/comments` … コメント追加（`comments` に追記。再発防止策もここに書く）
- `POST /api/tasks/evaluate` … 手動で逸脱判定を実行（テスト・即時実行用）

## バリデーション・エラー処理

- 状態遷移違反（逆遷移・段飛ばし）→ 409（R3）。
- スキーマ検証（enum・必須）→ 422。
- 逸脱判定の閾値未解決・KPI NULL は判定スキップ（エラーにしない。R1）。

## テスト設計 (Testing — 検証ゲートにマップ)

- **integration（ver2 DB・ROLLBACK fixture）**:
  - upsert: 無→新規／`OPEN`→上書き／`IN_PROGRESS`→保持／`DONE` のみ→新規（再発）。
  - 部分ユニーク: 同キーのアクティブは高々1件（重複 INSERT を DB が弾く）。
  - 状態遷移: 前進可・逆遷移/段飛ばし拒否（409）。コメント追記・一覧フィルタ。
- **integration（逸脱判定・2 DB）**:
  - メトリクス算出＋`resolve_effective` 比較で逸脱検知／閾値なしは判定せず／KPI NULL はスキップ＋WARN／
    `値 > 閾値` で起票／再実行で重複しない（冪等）／閾値内に戻っても自動クローズしない。
- **integration（スケジューラ）**: ジョブが評価サービスを呼ぶ／冪等。
- **api（TestClient）**: 各エンドポイントのステータス・遷移違反・コメント/メモ・一覧・認証ゲート。
- **frontend（Vitest）**: 一覧/フィルタ・状態遷移操作・コメント/メモ編集。

## フロント構成 (`structure.md` 準拠)

- `frontend/src/api/taskApi.ts`、TanStack Query フック（`frontend/src/hooks/`）、
  `frontend/src/pages/TaskList.tsx`（一覧・フィルタ・詳細・状態遷移・コメント/メモ編集）。

## 依存・前提 (Dependencies)

- `閾値管理`（`resolve_effective`）・**`日次集計基盤`（`daily_metrics` 号機合算読み出し＋共有 `services/metrics.py`）**が実装済み。
- **アプリ内スケジューラ基盤**（`tech.md`／`structure.md` に反映済み）。
- **棚卸し**: 実テーブル/列名のマッピング、tape の有無（無ければタスクキーから tape を除外＝`閾値`/`ダッシュボード`と連動）。

## 確定した設計判断 (Resolved)

- データモデル: `task` 単一テーブル＋`comments`（JSONB 追記）。**専用 `task_comment` テーブルは設けない**。
  **再発防止メモはコメントに統合**（独立フィールドは持たない。将来必要なら `recurrence_memo` 列を非破壊で追加可）。
- 逸脱内容（`detected_value` / `threshold_value` / `evaluation_date`）をタスクに保持し、上書き時に最新化。
- 手動トリガー `POST /api/tasks/evaluate` を設ける（テスト・即時実行用）。
- 状態遷移違反（逆遷移・段飛ばし）は **409 Conflict**。

> 棚卸し依存（実テーブル/列名・tape 有無）は「依存・前提」に残る。実装着手前に解消する。

## 画面デザイン刷新（2026-07-13 追記）

> 対象は**見た目のみ**（`ui-shell` の共通レイアウト・デザイントークンに乗せる）。API・Service・
> データモデルは無変更。参照 UI: `Shisui Dashboard (standalone).html`（ビジュアル参照）。

- モックアップの「OPENタスク数／今週完了／平均対応時間」サマリーカードは**スコープ外**
  （既存データから計算可能だが、今回は一覧・フィルタの見た目刷新に限定。brainstorming で確認済み）。
- モックアップの表にない「テープ」列は、フルタプル不変条件（R4・`colorNo/size/chain/tape`）に
  合わせて**残す**（色番の隣に列として表示）。
- 状態フィルタはモックアップのピル形式ではなく、既存の `<select>` をそのまま維持し見た目のみ変更する。
