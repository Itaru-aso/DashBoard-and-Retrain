# エッジPC管理 — Tasks

> spec: `エッジPC管理 (edge-pc)`
> 配置想定: `.kiro/specs/edge-pc/tasks.md`
> 上流: `requirements.md`（E-R1〜E-R6・確定事項）・`design.md` ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: tsc・eslint・vitest）。
> コミットは Conventional Commits（例: `feat(edge): ...`）。

## 前提 (Preconditions)

- **基盤整備**: ver2 DB・Alembic・認証・conftest。
- **後追い**: 接続情報の**具体列**（ver1 設定受領後にタスク1の列を確定・追補）。
- 接続テストの `ftplib` はテストで**モック**。

---

## タスク (Tasks)

- [x] **1. マイグレーション: `edge_pc` テーブル**（ver2 DB）
  - `name`（**ユニーク**）・`host`・`port`・`username`・`password`（任意・平文）・`remote_path`・`enabled`（既定 true）＋timestamps。
  - **列は ver1 設定受領後に確定**（追加項目があれば追補）。
  - テスト（integration）: upgrade/downgrade、`name` ユニークを制約が弾く。
  - Refs: E-R1 ／ commit: `feat(edge): add edge_pc table migration`

- [x] **2. ORM モデル `EdgePc`**
  - `src/models/edge_pc.py`。
  - テスト（integration）: round-trip。
  - commit: `feat(edge): add EdgePc ORM model`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/edge_pc.py`: 登録・更新・出力・一覧。
  - テスト（unit）: 検証（必須・型）。
  - Refs: E-R1 ／ commit: `feat(edge): add edge_pc schemas`

- [x] **4. Repository: CRUD ＋ `find_enabled`**
  - `src/repositories/edge_pc_repository.py`（ver2 エンジン）: create・update・delete・get・list・**`find_enabled()`**（配信先解決の参照点）。
  - テスト（integration）: CRUD・`name` ユニーク・`find_enabled()` が有効のみ返す。
  - Refs: E-R1, E-R3, E-R4 ／ commit: `feat(edge): add edge_pc repository (CRUD, find_enabled)`

- [x] **5. Service: CRUD ＋ 接続テスト（任意）**
  - `src/services/edge_pc_service.py`: 登録・更新・削除・一覧、`test_connection(id)`（`ftplib` で接続可否）。
  - テスト（integration・**ftplib モック**）: CRUD、接続テスト成功/失敗の判定。
  - Refs: E-R1, E-R5 ／ commit: `feat(edge): add edge_pc service (CRUD, connection test)`

- [x] **6. API: エンドポイント + ルーター登録**
  - `src/api/edge_pc_endpoint.py`（`main.py` 登録）: `GET /api/edge-pcs`・`GET /{id}`・`POST`・`PATCH /{id}`・
    `DELETE /{id}`・`POST /{id}/test`。Basic 認証ゲート。
  - テスト（api / TestClient）: CRUD のステータス・`name` 重複（409）・接続テスト・認証。
  - Refs: E-R1, E-R4, E-R5, E-R6 ／ commit: `feat(edge): add edge_pc API endpoints`

- [x] **7. フロント: エッジPC管理画面**
  - `frontend/src/api/edgePcApi.ts`、TanStack Query フック、`frontend/src/pages/EdgePc.tsx`
    （一覧・登録/編集/削除・有効フラグ・接続テストボタン）。
  - テスト（Vitest + Testing Library）: 一覧・登録/編集/削除・接続テスト。
  - Refs: E-R1, E-R4, E-R5 ／ commit: `feat(edge): add edge_pc management screen`

- [x] **8. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(edge): satisfy verification gate`

- [x] **9. フロント: 画面デザイン刷新（`ui-shell` 準拠・見た目のみ）**
  - モックアップ（`Shisui Dashboard (standalone).html`）を参照し `EdgePc.tsx` をダーク基調に作り直す。
    モックアップは「名前/稼働状態/IPアドレス」のみのカード並べだが、登録フォーム・有効フラグ切替・
    接続テスト・削除の既存機能はすべて残し、一覧を表からカードグリッド（2列）に変更するのみとする
    （ポート・FTP確認結果・操作ボタンはカード内に表示。brainstormingで確認済み）。
  - テスト: 既存5テストのうち、一覧表示アサーションを `role="cell"` からカード構造の `getByText` に更新。
    それ以外（登録・有効フラグ切替・削除・接続テスト）は無変更で通ることを確認。
  - 代替検証: `npm run dev`（バックエンド接続）で目視確認。
  - Refs: E-R1, E-R4, E-R5 ／ commit: `feat(edge): restyle edge PC management screen with ui-shell design`

---

## トレーサビリティ (Requirements ↔ Tasks)

- E-R1（登録・管理）→ 1, 3, 4, 5, 6, 9
- E-R2（平文・任意パスワード）→ 1
- E-R3（全台配信の参照点）→ 4（`find_enabled`。実配信は `モデル再学習` 側）
- E-R4（一覧・参照）→ 4, 6, 7, 9
- E-R5（接続テスト・任意）→ 5, 6, 7, 9
- E-R6（認証）→ 6

> 後追い: 接続情報の具体列（タスク1。ver1 設定受領後に確定）。
