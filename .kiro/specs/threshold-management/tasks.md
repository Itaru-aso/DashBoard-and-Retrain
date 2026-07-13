# 閾値管理 — Tasks

> spec: `閾値管理 (threshold-management)` ／ 配置想定: `.kiro/specs/threshold-management/tasks.md`
> 上流: `requirements.md`（R1–R6）・`design.md` ／ 規約: `tech.md`（TDD・検証ゲート）, `structure.md`（配置）
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: vitest・tsc・eslint）が全グリーン。
> コミットは Conventional Commits（例: `feat(threshold): ...`）。

## 前提 (Preconditions)

- 基盤整備（DB 接続・Alembic ベースライン・Basic 認証ゲート・テスト DB の conftest fixture）が済んでいること。
  未了なら「基盤整備」を先行させる。
- 棚卸しで業者 DB に閾値テーブルが無いことを確認（あれば実スキーマに追従し本タスクを調整）。
- 命名（テーブル名・enum 値）の業者規約照合（`design.md` 依存）。

---

## タスク (Tasks)

- [x] **1. 補填マイグレーション: `threshold` テーブル**
  - `alembic/versions/<rev>_create_threshold.py` を作成。冒頭で `CREATE EXTENSION IF NOT EXISTS btree_gist`。
  - カラム・`CHECK`（値域・期間逆転・metric/scope enum・スコープ整合）・**部分排他制約2本**（per_color / global）・索引。
  - テスト（integration / 使い捨てまたはテスト DB）: upgrade/downgrade が通る。
    制約が効く＝重複・値域外・期間逆転・スコープ不整合の INSERT が DB に弾かれる。
  - Refs: R1.2–R1.5, R3.5 ／ commit: `feat(threshold): add threshold table migration with exclusion constraints`

- [x] **2. ORM モデル `Threshold`**
  - `src/models/threshold.py`。全カラム・enum・timestamptz をマッピング。
  - テスト（integration）: 保存→取得の round-trip、型・enum の往復。
  - Refs: data model ／ commit: `feat(threshold): add Threshold ORM model`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/threshold.py`: 作成/更新/出力。バリデーション（metric enum・値域 0–100・`valid_to > valid_from`・
    スコープ整合: per_color なら色4項目必須・global なら色項目無し）。
  - テスト（unit）: 各バリデーションの正常／異常。
  - Refs: R1.3–R1.5, R6 ／ commit: `feat(threshold): add threshold pydantic schemas`

- [x] **4. Repository: CRUD + `find_active`**
  - `src/repositories/threshold_repository.py`: `create` / `get` / `list`(filter) / `update` /
    `find_active(metric, scope, color, at)`（有効判定は半開区間 `valid_from <= at < valid_to`、`valid_to` NULL は無期限）。
  - テスト（integration）: CRUD 各種、`find_active` の境界（`valid_from==at` 有効・`valid_to==at` 無効）、
    フルタプル一致のみヒット（`size` 違いは不一致）、結果は高々1件。
  - Refs: R1.1, R3.1–R3.5, R5 ／ commit: `feat(threshold): add threshold repository with active lookup`

- [x] **5. Service: 検証・解決・supersede**
  - `src/services/threshold_service.py`:
    `resolve_effective`（色別→global→None）、`create`（検証→repo、排他制約違反 IntegrityError を Conflict 例外へ変換）、
    `update`、`supersede`（現行を close＋新規作成で履歴保持）、`disable`（`valid_to` 設定）。
  - テスト（integration）: 解決の優先順位／fallback／None、両方有効→色別、supersede で過去保持、
    無効化後は解決対象外、未有効化レコードの in-place 訂正、重複時に Conflict。
  - Refs: R2, R3, R4 ／ commit: `feat(threshold): add threshold service (resolve, supersede, validation)`

- [x] **6. API: エンドポイント + ルーター登録**
  - `src/api/threshold_endpoint.py`（`get_db` 依存）を作り `main.py` に登録:
    `POST /api/thresholds`・`GET /api/thresholds`・`GET /api/thresholds/{id}`・`PATCH /api/thresholds/{id}`・
    `GET /api/thresholds/effective`（query: metric, color_no, size, chain, tape, at）。
  - テスト（api / TestClient）: ステータス（201/200/409/422）、`effective` の解決結果、Basic 認証ゲート通過。
  - Refs: R1, R2, R4, R5, R6 ／ commit: `feat(threshold): add threshold API endpoints`

- [x] **7. フロント: 閾値管理画面**（backend 先行なら後回し可）
  - `frontend/src/api/thresholdApi.ts`、TanStack Query フック（`frontend/src/hooks/`）、
    `frontend/src/pages/ThresholdManagement.tsx`（一覧・登録・無効化）。ルーティング登録。
  - テスト（Vitest + Testing Library）: 一覧表示・登録フォームの送信・バリデーション表示。
  - Refs: R1, R2, R5 ／ commit: `feat(threshold): add threshold management screen`

- [x] **8. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc --noEmit`/`eslint`/`vitest` をグリーンに。
    カバレッジ 80% 以上を確認。
  - commit: `chore(threshold): satisfy verification gate`

- [x] **9. フロント: 画面デザイン刷新（`ui-shell` 準拠・見た目のみ）**
  - モックアップ（`Shisui Dashboard (standalone).html`）を参照し `ThresholdManagement.tsx` をダーク基調に
    作り直す（情報バナー・登録フォームのパネル化・一覧表のダーク化）。
    モックアップは「3指標カードのinline編集＋一括保存」だが、色別スコープ・有効開始日時による履歴管理
    （R2/R3）を持つ現行機能はそのまま残す（brainstormingで確認済み。モックアップ構造への簡略化は不採用）。
  - テスト: 既存3テストが無変更で通ることを確認。
  - 代替検証: `npm run dev`（バックエンド接続）で目視確認。
  - Refs: R1, R2, R5 ／ commit: `feat(threshold): restyle threshold management screen with ui-shell design`

---

## トレーサビリティ (Requirements ↔ Tasks)

- R1（登録・検証）→ 1, 3, 4, 6, 9
- R2（更新・無効化・履歴）→ 5, 6, 7, 9
- R3（有効閾値解決・優先順位・境界）→ 4, 5
- R4（下流提供）→ 5, 6
- R5（一覧）→ 4, 6, 7, 9
- R6（認証・記録）→ 3, 6
