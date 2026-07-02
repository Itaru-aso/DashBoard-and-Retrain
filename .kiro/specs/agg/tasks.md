# 日次集計基盤 — Tasks

> spec: `日次集計基盤 (daily-aggregation)`
> 配置想定: `.kiro/specs/daily-aggregation/tasks.md`
> 上流: `requirements.md`（A-R1〜A-R6・確定）・`design.md` ／ 基準: `schema-spec-mapping.md` ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy）。コミットは Conventional Commits（`feat(agg): ...`）。

## 前提 (Preconditions)

- **基盤整備**: 2エンジン（`get_db`/`get_inspection_db`）・アプリ内スケジューラ・ver2 DB・Alembic・conftest（2-DB）。
- **`schema-spec-mapping.md`**: app_db スキーマ（image_base／annotation_item／dataset_category_item）。**読み取り専用・索引不可**。
- env: `AGG_WINDOW_DAYS`（既定 7）・`AGG_RUN_TIME`。
- app_db 内の結合のみ・**越境結合なし**。実 app_db は conftest の代役（dump）で検証。

---

## タスク (Tasks)

- [x] **1. マイグレーション: `daily_metrics`**（ver2 DB）
  - `jst_date`・`color_no`・`size`・`chain`・`tape`・`unit`・`monochro_count`・`ng_count`・`fp_num`・`miss_num`・
    `annotated_count`・`computed_at`。**ユニーク** `(jst_date,color_no,size,chain,tape,unit)`（`tape` 空文字可）。
  - テスト（integration）: upgrade/downgrade、ユニーク制約。
  - Refs: A-R1 ／ commit: `feat(agg): add daily_metrics migration`

- [ ] **2. ORM モデル `DailyMetrics`**
  - `src/models/daily_metrics.py`。
  - テスト（integration）: round-trip。
  - commit: `feat(agg): add DailyMetrics model`

- [ ] **3. 共有メトリクス `services/metrics.py`**
  - 件数→率: `throughput=monochro`・`ng_rate=ng/monochro`・`false_alarm_rate=annotated==0?NULL:fp/monochro`・
    `miss_rate=annotated==0?NULL:miss/monochro`。`monochro==0` 除外。**ダッシュボード/保守タスク/色 と共有**。
  - テスト（unit）: 率・NULL（annotated=0）・monochro=0 除外。
  - Refs: A-R5 ／ commit: `feat(agg): add shared metrics computation`

- [ ] **4. Repository: upsert（delete→insert）・読み出し・号機合算**
  - `src/repositories/daily_metrics_repository.py`（ver2）: `upsert_day(jst_date, rows)`（**対象日を delete→insert・同一トランザクション**・冪等）、
    `read(from,to,tuple?,unit_ids?)`、`read_unit_aggregated(from,to,tuple)`（号機合算）。
  - テスト（integration）: 冪等（同日2回で重複なし・消えたタプルが残らない）、期間/タプル/号機フィルタ、号機合算。
  - Refs: A-R1, A-R6 ／ commit: `feat(agg): add daily_metrics repository (idempotent upsert, reads)`

- [ ] **5. Service: 集計・再集計・バックフィル**
  - `src/services/aggregation_service.py`: `aggregate_day(jst_date)`（`get_inspection_db` で app_db 当日パーティションを
    CTE 集計〔正解は image_id 単位に `MAX(on_class)`・use_flg 無視〕→ 件数を取得 → `upsert_day` で ver2 へ）、
    `aggregate_window(AGG_WINDOW_DAYS)`、`backfill(from,to)`。**2エンジン・越境結合なし**。
  - テスト（integration・2-DB 代役）: 件数正しさ（monochro 分母／全カメラ分子／正解集約／use_flg 無視／アノテーションなし除外）、
    冪等再集計で後追いアノテーション反映、バックフィル。
  - Refs: A-R2, A-R3, A-R4 ／ commit: `feat(agg): add aggregation_service (aggregate, window, backfill)`

- [ ] **6. スケジューラジョブ**
  - `src/jobs/aggregation_job.py`: 日次（`AGG_RUN_TIME`・JST 早朝）に `aggregate_window` を実行・冪等。
    既存日次ジョブと**順序 集計 → 逸脱判定 → 昇格**で並べる（集計後に判定/昇格が読む）。
  - テスト（integration）: スケジュール起動で `aggregate_window` 呼び出し・順序。
  - Refs: A-R2, A-R3 ／ commit: `feat(agg): add daily aggregation scheduler job`

- [ ] **7. API: 集計トリガー**
  - `src/api/aggregation_endpoint.py`（`main.py` 登録）: `POST /api/aggregation/run`（`date` 単日／`from,to` 期間）。Basic 認証。
  - テスト（api / TestClient）: 単日・期間・認証。
  - Refs: A-R2, A-R4 ／ commit: `feat(agg): add aggregation run endpoint`

- [ ] **8. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(agg): satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- A-R1（集計テーブル）→ 1, 2, 4 ／ A-R2（日次ジョブ）→ 5, 6, 7
- A-R3（再集計）→ 5, 6 ／ A-R4（バックフィル）→ 5, 7
- A-R5（共有メトリクス）→ 3 ／ A-R6（参照・号機合算）→ 4

> 後続: `検査結果ダッシュボード`・`保守タスク`・`色ライフサイクル` を本基盤参照（read＋`metrics.py`）へ更新。
> 実装順: 基盤整備 → 棚卸し → **日次集計基盤** → ダッシュボード／保守タスク／色（本基盤を読む）。
