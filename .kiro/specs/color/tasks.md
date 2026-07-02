# 色マスター・色ライフサイクル管理 — Tasks

> spec: `色マスター・色ライフサイクル管理 (color-lifecycle)`
> 配置想定: `.kiro/specs/color-lifecycle/tasks.md`
> 上流: `requirements.md`（C-R1〜C-R6・確定事項）・`design.md` ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: tsc・eslint・vitest）。
> コミットは Conventional Commits（例: `feat(color): ...`）。

## 前提 (Preconditions)

- **基盤整備**: 2エンジン・ver2 Alembic・**アプリ内スケジューラ**・conftest（2 DB）。
- **`日次集計基盤` 実装済み**: `daily_metrics`（号機合算）＋共有 `services/metrics.py`（基盤所有）。本 spec は読むだけ。
- **一覧ファイル形式（確定）**: xlsx・`Sheet1`・列 `status/size/chain/tape/color_no/R/G/B/L/a/b/update_date`
  （取り込みでは `status`・`update_date` は無視。タスク5参照）。

---

## タスク (Tasks)

- [x] **1. マイグレーション: `color_master` テーブル**（ver2 DB）
  - 同一性タプル＋`rgb`(R/G/B)＋`lab`(L/a/b)＋`status` enum（既定 `未実施`）＋`verification_at`/`production_at`＋timestamps。
    **ユニーク制約** `UNIQUE (color_no,size,chain,tape)`。
  - テスト（integration）: upgrade/downgrade、同一タプル重複 INSERT を制約が弾く。
  - Refs: C-R1.1 ／ commit: `feat(color): add color_master table migration`

- [x] **2. ORM モデル `ColorMaster`**
  - `src/models/color_master.py`（全カラム・status enum）。
  - テスト（integration）: round-trip・enum。
  - commit: `feat(color): add ColorMaster ORM model`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/color_master.py`: 出力・一覧フィルタ・取り込み結果・色見本更新。
  - テスト（unit）: 検証（正常／異常）。
  - Refs: C-R5 ／ commit: `feat(color): add color schemas`

- [x] **4. Repository: 登録・upsert・状態更新・検索**
  - `src/repositories/color_master_repository.py`（ver2 エンジン）: `create`(未実施)・`upsert_by_tuple`（色見本更新・status 保持）・
    `set_status`（前進のみ）・`list`(filter)・`find_by_status`。
  - テスト（integration）: 未実施作成／タプル upsert（色見本更新・status 保持）／ユニーク制約／status 前進／一覧フィルタ。
  - Refs: C-R1, C-R2, C-R5 ／ commit: `feat(color): add color_master repository`

- [x] **5. 取り込みサービス `color_import_service`**
  - 一覧ファイル（xlsx・`Sheet1`）をパース → タプル＋色見本を抽出 → `upsert_by_tuple`（新規は未実施）。バリデーション・結果レポート。
  - **列マッピング（確定）**: `size`→size・`chain`→chain・`tape`→tape（空欄可）・`color_no`→color_no・`R/G/B`→rgb・`L/a/b`→lab。
    - `color_no`・`size` は**文字列**として保持（ゼロ埋め維持。例 `001`/`03`。数値化しない）。
    - `color_no` は**前後空白を trim**してから保存（例 `"  001"`→`"001"`。キーになるため必須）。
    - **`status` 列と `update_date` 列は無視**。status は既定 **未実施**、時刻は**取り込み時刻**で登録（status は自動管理・`schema-spec-mapping`/色 spec 方針）。
  - テスト（integration）: 正常行で作成/更新・`color_no` の trim・文字列保持（`001`≠`1`）・tape 空欄・status 列無視（常に未実施）・
    不正行レポート・重複タプルは status 保持。
  - Refs: C-R1 ／ commit: `feat(color): add color list import service`

- [x] **6. Service: ライフサイクル自動遷移（日次・冪等）**
  - `src/services/color_lifecycle_service.py`: **未実施→量産検証**（`daily_metrics` に当該フルタプルの集計行が有れば遷移・`verification_at`）、
    **量産検証→実生産**（`daily_metrics` 号機合算を `services/metrics.py` で率算出し、`虚報率≤1.5%` かつ `見逃し率≤0.05%` を同時達成した日が
    1 日でも有れば昇格・`production_at`。ラベルのある日のみ・固定基準）。**一方向・冪等**。Service 層で突合（越境結合なし）。
  - テスト（integration・2 DB）: 未実施→量産検証／両基準同時達成日で昇格・片方未達は昇格せず・ラベル0件日は対象外／
    一方向（実生産は対象外・後戻りなし）／冪等。
  - Refs: C-R2, C-R3, C-R4 ／ commit: `feat(color): add lifecycle auto-transition service`

- [x] **7. スケジューラ: 日次ジョブ**
  - `src/jobs/color_lifecycle_job.py`（`color_lifecycle_service.evaluate(window)` を呼ぶ薄い層）、`main.py` 起動時に**日次**登録
    （保守タスクの逸脱判定と同じアプリ内スケジューラ・単一ワーカ所有・`*_ENABLED`）。
  - テスト（integration）: ジョブが評価サービスを呼ぶ／無効化／冪等。
  - Refs: C-R3, C-R4 ／ commit: `feat(color): add daily lifecycle scheduler job`

- [x] **8. API: エンドポイント + ルーター登録**
  - `src/api/color_master_endpoint.py`（`main.py` 登録）: `GET /api/colors`（filter）・`GET /api/colors/{id}`・
    `POST /api/colors/import`・`PATCH /api/colors/{id}`（色見本のみ・**status 手動変更不可**）・
    `POST /api/colors/evaluate`（手動）。Basic 認証ゲート。
  - テスト（api / TestClient）: 一覧・取り込み・evaluate・色見本更新・status 手動変更不可・認証。
  - Refs: C-R1, C-R5, C-R6 ／ commit: `feat(color): add color API endpoints`

- [x] **9. フロント: 色マスター画面**
  - `frontend/src/api/colorApi.ts`、TanStack Query フック、`frontend/src/pages/ColorMaster.tsx`
    （一覧・ステータス絞り込み・ファイル取り込み・色見本の表示/編集・ステータス表示）。
  - テスト（Vitest + Testing Library）: 一覧/フィルタ・取り込み UI・色見本編集・ステータス表示。
  - Refs: C-R5 ／ commit: `feat(color): add color master screen`

- [x] **10. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(color): satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- C-R1（登録・取り込み）→ 1, 4, 5, 8
- C-R2（ライフサイクル状態・一方向）→ 4, 6
- C-R3（量産検証へ自動遷移）→ 6, 7
- C-R4（実生産へ自動昇格・日次固定基準）→ 6, 7
- C-R5（一覧・参照）→ 3, 4, 8, 9
- C-R6（認証）→ 8

> 後追い: 一覧ファイルの列マッピング（タスク5。サンプル受領後に確定）。
