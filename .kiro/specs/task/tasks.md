# 保守タスク自動生成・管理 — Tasks

> spec: `保守タスク自動生成・管理 (maintenance-task)`
> 配置想定: `.kiro/specs/maintenance-task/tasks.md`
> 上流: `requirements.md`（R1–R6・確定事項）・`design.md` ／ 規約: `tech.md`（TDD・検証ゲート・2 DB・スケジューラ）, `structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: vitest・tsc・eslint）が全グリーン。
> コミットは Conventional Commits（例: `feat(task): ...`）。

## 前提 (Preconditions)

- **棚卸し完了**: 実テーブル/列名のマッピング、tape の有無（無ければタスクキーから tape を除外＝`閾値`/`ダッシュボード`と連動）。
- **基盤整備**: 2エンジン（`get_db` / `get_inspection_db`）・ver2 DB の Alembic ベースライン・
  **アプリ内スケジューラ基盤**・conftest の 2 DB テスト配線。
- **`閾値管理` 実装済み**: `ThresholdService.resolve_effective`。
- **`検査結果ダッシュボード` の共有メトリクス**: `services/metrics.py`・検査結果の集計（無ければタスク5で切り出す）。

---

## タスク (Tasks)

- [x] **1. マイグレーション: `task` テーブル + 部分ユニーク制約**（ver2 DB）
  - `alembic/versions/<rev>_create_task.py`: カラム（フルタプル・`task_type`/`status` enum・
    `detected_value`/`threshold_value`/`evaluation_date`・`comments` JSONB・timestamps）、
    **部分ユニーク** `UNIQUE (color_no,size,chain,tape,task_type) WHERE status IN ('OPEN','IN_PROGRESS')`。
  - テスト（integration）: upgrade/downgrade、制約が効く（同キーのアクティブ重複 INSERT を DB が弾く）。
  - Refs: R2.5 ／ commit: `feat(task): add task table migration with partial unique constraint`

- [x] **2. ORM モデル `Task`**
  - `src/models/task.py`（全カラム・enum・`comments` JSONB・timestamptz）。
  - テスト（integration）: 保存→取得の round-trip、enum、JSONB の往復。
  - commit: `feat(task): add Task ORM model`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/task.py`: 一覧フィルタ・タスク出力（コメント含む）・状態遷移リクエスト・コメント追加・evaluate。
  - テスト（unit）: enum・状態遷移入力・フィルタの検証（正常／異常）。
  - Refs: R3, R5 ／ commit: `feat(task): add task schemas`

- [x] **4. Repository: upsert・状態遷移・コメント・一覧**
  - `src/repositories/task_repository.py`（ver2 エンジン）: `find_active(key)`・`create`・`overwrite`・
    `transition_status`（前進のみ）・`append_comment`・`list`(filter)。
  - テスト（integration）: upsert 4 系統（無→新規／`OPEN`→上書き／`IN_PROGRESS`→保持／`DONE` のみ→新規＝再発）、
    部分ユニーク（アクティブ高々1件）、状態遷移の前進可・逆遷移/段飛ばし拒否、コメント追記、一覧フィルタ。
  - Refs: R2, R3, R4, R5 ／ commit: `feat(task): add task repository (upsert, transitions, comments, list)`

- [x] **5. 共有メトリクス算出 `services/metrics.py`**（ダッシュボード未実装の場合に切り出し）
  - ※ 日次集計基盤（agg）で実装済み（`services/metrics.py`＝所有・`test_metrics.py`）。本 spec は呼び出して使う。
  - 件数→率算出（`NG率`・KPI＝ラベル0件 NULL・`スループット`）。JST 日次・フルタプル。
  - テスト（unit/integration）: 率算出・KPI NULL・monochro=0 除外。
  - Refs: R1（メトリクス）／ commit: `feat(metrics): extract shared metric computation`

- [x] **6. Service: 逸脱評価（閾値駆動・冪等）**
  - `src/services/breach_evaluation_service.py`: 対象期間に**有効な閾値の `(metric, フルタプル)` を取得**し、
    各 **JST 日**でメトリクス算出（`services/metrics.py`）→ `resolve_effective` と比較 →
    KPI NULL はスキップ＋WARN → `値 > 閾値` で `task_repository` に upsert。**冪等・自動クローズ無し**。
  - テスト（integration・2 DB）: 閾値駆動で対象が絞られる／KPI NULL スキップ＋WARN／`値 > 閾値`で起票／
    再実行で重複しない（冪等）／閾値内に戻っても自動クローズしない。
  - Refs: R1, R2 ／ commit: `feat(task): add breach evaluation service (threshold-driven, idempotent)`

- [x] **7. スケジューラ: 日次ジョブ**
  - `src/jobs/breach_eval_job.py`（`breach_evaluation_service.evaluate(BREACH_EVAL_WINDOW_DAYS)` を呼ぶ薄い層）、
    `main.py` 起動時にアプリ内スケジューラへ日次登録（`BREACH_EVAL_TIME`／`BREACH_EVAL_ENABLED`）。単一ワーカ所有。
  - テスト（integration）: ジョブが評価サービスを呼ぶ／無効化フラグ／多重実行でも冪等。
  - Refs: R1.4 ／ commit: `feat(task): add daily breach-eval scheduler job`

- [x] **8. API: エンドポイント + ルーター登録**
  - `src/api/task_endpoint.py`（`main.py` 登録）: `GET /api/tasks`（filter）・`GET /api/tasks/{id}`・
    `PATCH /api/tasks/{id}/status`（前進のみ・違反 409）・`POST /api/tasks/{id}/comments`・
    `POST /api/tasks/evaluate`（手動）。**手動作成は無し**。Basic 認証ゲート。
  - テスト（api / TestClient）: ステータス（200/409/422）、状態遷移違反 409、コメント追加、evaluate、一覧、認証。
  - Refs: R1.4, R3, R4, R5, R6 ／ commit: `feat(task): add task API endpoints`

- [x] **9. フロント: タスク管理画面**
  - `frontend/src/api/taskApi.ts`、TanStack Query フック、`frontend/src/pages/TaskList.tsx`
    （一覧・フィルタ・詳細・状態遷移・コメント追記）。
  - テスト（Vitest + Testing Library）: 一覧/フィルタ・状態遷移操作・コメント追記。
  - Refs: R3, R4, R5 ／ commit: `feat(task): add task management screen`

- [ ] **10. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc --noEmit`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(task): satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- R1（逸脱判定・日次スケジュール）→ 5, 6, 7
- R2（自動起票・upsert・重複防止）→ 1, 4, 6
- R3（状態遷移・前進のみ）→ 3, 4, 8
- R4（コメント＝再発防止策含む）→ 4, 8, 9
- R5（一覧）→ 3, 4, 8, 9
- R6（認証・日時保持）→ 1, 8
