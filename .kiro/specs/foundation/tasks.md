# 基盤整備 — Tasks

> spec: `基盤整備 (foundation)`
> 配置想定: `.kiro/specs/foundation/tasks.md`
> 上流: `requirements.md`（F1–F11・確定事項）・`design.md` ／ 規約: `tech.md`・`structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: tsc・eslint・vitest）。
> コミットは Conventional Commits（例: `feat(foundation): ...`）。これは各機能 spec の前提（spec 0）。

## 前提 (Preconditions)

- 棚卸しは**不要**（本 spec は接続・パターン・骨格まで。業者外部モデルの具体は各機能 spec で棚卸し後）。

---

## タスク (Tasks)

- [x] **1. プロジェクト雛形・ツール設定**（F11 ツール）
  - `backend/`・`frontend/` の雛形、`pyproject.toml`（`black`/`flake8`/`mypy`/`pytest`＋cov・マーカー
    `unit`/`integration`/`api`）、`.env.example`。
  - テスト: `pytest` が収集できる・lint/型チェックが走る（最小のダミーテスト）。
  - commit: `chore(foundation): project scaffolding and tooling`

- [x] **2. 設定 `config.py`**（F1）
  - `pydantic-settings` で全 env を定義。必須未設定は起動時例外（fail-fast）。`settings` 単一インスタンス。
  - テスト（unit）: 必須欠如で例外／値の読み込み。
  - Refs: F1 ／ commit: `feat(foundation): add settings (pydantic-settings)`

- [x] **3. ロギング `logging_config.py`**（F8）
  - `LOG_LEVEL` 連動のプレーン形式ロガー初期化。
  - テスト（unit）: 初期化・レベル反映。
  - Refs: F8 ／ commit: `feat(foundation): add plain logging config`

- [x] **4. ver2 `Base` ＋ Alembic（空ベースライン）**（F3）
  - `Base`（ver2 declarative）。`alembic.ini`・`alembic/env.py`（`target_metadata = Base.metadata`・`DATABASE_URL`）。
    **空の初期マイグレーション**を1つ。
  - テスト（integration）: `alembic upgrade head` がテスト DB に通る（空ベースライン適用）。
  - Refs: F3 ／ commit: `feat(foundation): set up ver2 Alembic with empty baseline`

- [x] **5. テスト配線 `conftest.py`**（F9）
  - ver2 テスト DB（migration 適用）＋**トランザクション ROLLBACK** fixture、業者検査 DB 相当（**dump スナップショット**）fixture、
    `TestClient` fixture、マーカー。
  - テスト（integration）: ROLLBACK 隔離が効く（テスト間でデータが残らない）。
  - Refs: F9 ／ commit: `test(foundation): add conftest db fixtures and wiring`

- [x] **6. 2エンジン DB 接続 `database.py`**（F2）
  - `ver2_engine`/`inspection_engine`（`pool_pre_ping`）・`SessionLocal`/`InspectionSessionLocal`・
    `get_db`（commit/rollback/close）・`get_inspection_db`（**非 commit・SELECT 専用**）。接続断の捕捉方針。
  - テスト（integration）: `get_db` の commit・rollback／`get_inspection_db` で読める／業者 DB 断で例外を捕捉できる。
  - Refs: F2 ／ commit: `feat(foundation): add dual-engine db connections`

- [x] **7. 業者外部モデル基盤 `models/external/`**（F4）
  - **別宣言基盤 `ExternalBase`**（**Alembic の `target_metadata` に含めない**）。手書き読み取り専用モデルのパターン
    （サンプル1つ・具体は各機能）。
  - テスト（unit/integration）: `ExternalBase` のテーブルが Alembic autogenerate の対象に**入らない**こと。
  - Refs: F4 ／ commit: `feat(foundation): add external read-only model base`

- [x] **8. 認証ゲート `api/security.py`**（F5）
  - `HTTPBasic` 依存で**単一共有クレデンシャル**を定数時間比較。`ENABLE_BASIC_AUTH` で無効化。API へ適用（`/health` 除外）。
  - テスト（api）: 認証なし→401／正しい資格→通過／無効化時は素通り。
  - Refs: F5 ／ commit: `feat(foundation): add basic auth gate (shared credential)`

- [x] **9. スケジューラ基盤 `scheduler.py`**（F6）
  - **APScheduler** を生成し、`main.py` の lifespan で起動/停止。`src/jobs/` のジョブ登録関数。`*_ENABLED` で無効化。
    `uvicorn --workers 1` 前提（単一所有）。
  - テスト（integration）: 起動/停止・ジョブ登録・無効化フラグ。
  - Refs: F6 ／ commit: `feat(foundation): add in-app scheduler base (APScheduler)`

- [x] **10. アプリ骨格 `main.py`**（F7）
  - `FastAPI` 生成・lifespan（スケジューラ起動/停止）・ルーター登録の集約・`/health`
    （**ver2 DB 必須＋業者 DB 参考**）・本番 `dist/` 静的配信＋SPA フォールバック。
  - テスト（api）: `/health`（ver2 必須・業者参考の表現）／起動が通る。
  - Refs: F7 ／ commit: `feat(foundation): add app skeleton and health endpoint`

- [x] **11. フロント骨格**（F10）
  - React + Vite + TS 雛形、`api/client.ts`（axios・`baseURL=/api`）、TanStack Query Provider、ルーティング、`build → dist`。
  - テスト（vitest）: ルート描画・client 構成の最小テスト。
  - Refs: F10 ／ commit: `feat(foundation): add frontend skeleton`

- [x] **12. コンテナ `Dockerfile` / `docker-compose.yml`**（F11）
  - バックエンド `Dockerfile`（非 root・`/health`・`uvicorn --workers 1`）、`docker-compose`
    （dev: ver2 バックエンド＋ver2 DB〔独立・ボリューム〕＋業者 DB 代役〔dump〕）。
  - **ベースイメージ・GPU/CUDA の取り込みは後日決定**（本タスクでは骨組みまで。GPU 確定後に追補）。
  - テスト: `docker compose` で起動し `/health` が応答（ver2 DB 疎通）。
  - Refs: F11 ／ commit: `chore(foundation): add Dockerfile and docker-compose (image/GPU TBD)`

- [x] **13. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(foundation): satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- F1 設定 → 2 ／ F2 2エンジン → 6 ／ F3 Alembic → 4 ／ F4 外部モデル基盤 → 7
- F5 認証 → 8 ／ F6 スケジューラ → 9 ／ F7 アプリ骨格 → 10 ／ F8 ロギング → 3
- F9 テスト配線 → 5 ／ F10 フロント骨格 → 11 ／ F11 コンテナ・ビルド → 1, 12

> 後日決定（非ブロッキング）: GPU／バックエンド image の具体、業者 DB の RO ユーザ。
