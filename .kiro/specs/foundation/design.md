# 基盤整備 — Design

> spec: `基盤整備 (foundation)`
> 配置想定: `.kiro/specs/foundation/design.md`
> 上流: `requirements.md`（F1–F11・確定事項）／ steering: `tech.md`・`structure.md`

## 概要・方針 (Overview)

`tech.md`／`structure.md` の確定事項を、各機能 spec が乗れる土台として実装する。
DB は2エンジン（ver2＝読み書き／業者＝読み取り専用）、Alembic は ver2 のみ・空ベースライン、
認証は Basic（単一共有）、定期実行は APScheduler（アプリ内・単一プロセス）。
機能固有のテーブル・画面・ジョブ本体は含まない（接続・パターン・骨格まで）。

## 設定 (F1 — `src/config.py`)

- `pydantic-settings` の `BaseSettings` で `.env` を読み込む。**必須未設定は起動時に例外**（fail-fast）。
- フィールド: `DATABASE_URL`・`INSPECTION_DATABASE_URL`・`DEBUG`・`ENVIRONMENT`・
  `ENABLE_BASIC_AUTH`/`BASIC_AUTH_USER`/`BASIC_AUTH_PASS`・`LOG_LEVEL`・`TRAINING_*`・`BREACH_EVAL_*`。
- 単一の `settings` インスタンスを各所で参照。

## 2エンジン DB 接続 (F2 — `src/database.py`)

- `ver2_engine`（`DATABASE_URL`・読み書き）と `inspection_engine`（`INSPECTION_DATABASE_URL`・**読み取り専用**）。
  両者に `pool_pre_ping=True`（接続断検知）。業者用は将来 read-only ユーザで接続（依存参照）。
- `SessionLocal`（ver2）／`InspectionSessionLocal`（業者）。
- 依存: `get_db`（ver2・正常時 commit／例外時 rollback／finally close）、
  `get_inspection_db`（業者・**commit しない**・SELECT 専用・finally close）。
- **接続断ハンドリング**: 業者 DB の `OperationalError` 等は Repository/Service で捕捉し、
  呼び出し側（ダッシュボード等）が **503 相当**で握りつぶせるようにする（アプリは落とさない。F2.3）。
- `Base`（ver2 declarative base。**Alembic の対象**）。

## 業者外部モデル基盤 (F4 — `src/models/external/`)

- **手書きの読み取り専用モデル**を置く（型・列を明示）。具体テーブルは棚卸し後に各機能が追加。
- **ver2 の `Base` とは別の宣言基盤**（`ExternalBase`）に載せ、**Alembic の `target_metadata` に含めない**
  （autogenerate が業者テーブルを管理対象と誤認しないため）。
- 読み取り専用は「業者エンジン＋（できれば）RO ユーザ＋リポジトリで書かない」で担保。

## Alembic (F3 — `alembic/`, `alembic.ini`)

- `env.py` の `target_metadata = Base.metadata`（**ver2 のみ**。`ExternalBase` は含めない）。接続は `DATABASE_URL`。
- **空の初期マイグレーション（ベースライン）**を1つ置く。以降テーブル追加は各機能 spec。
- `alembic upgrade head` が通ること。テスト DB のスキーマは migration を正とする。

## 認証ゲート (F5 — `src/api/security.py` ほか)

- `HTTPBasic` 依存で `BASIC_AUTH_USER`/`PASS`（**単一共有**）と定数時間比較。`ENABLE_BASIC_AUTH=false` で無効化。
- ルーター単位の依存として全 API に適用（`/health` は除外）。ロール制御なし。

## スケジューラ基盤 (F6 — `src/scheduler.py`, `src/jobs/`)

- **APScheduler**（`BackgroundScheduler` もしくは `AsyncIOScheduler`）を1つ生成し、`main.py` の lifespan で
  **起動／停止**する。`src/jobs/` のジョブを登録する関数を提供（ジョブ本体は各機能 spec が追加）。
- **単一プロセス・単一ワーカ所有**前提（`uvicorn --workers 1`／単一バックエンドコンテナ。`tech.md`）。
- `*_ENABLED` で各ジョブを無効化可能。

## アプリ骨格 (F7 — `src/main.py`)

- `FastAPI` 生成、lifespan でスケジューラ起動/停止、ルーター登録の集約。
- `/health`: **ver2 DB 疎通＝必須**（失敗で unhealthy）、**業者 DB 疎通＝参考**（失敗は致命にしない・結果に併記）。
- `ENVIRONMENT=production`: フロント `dist/` を静的配信＋SPA フォールバック。開発は Vite devserver＋`/api` プロキシ。

## ロギング (F8 — `src/logging_config.py`)

- 標準 `logging` をプレーン形式で初期化（`LOG_LEVEL`）。各モジュールは `getLogger(__name__)`。

## テスト配線 (F9 — `tests/conftest.py`, `pyproject.toml`)

- マーカー（`unit`/`integration`/`api`）とカバレッジ（cov≥80）を設定。
- **ver2 テスト DB**: マイグレーション適用済みのテスト DB に接続し、各テストを
  **コネクション＋トランザクションで囲み終了時 ROLLBACK**（migration を正）。
- **業者検査 DB 相当**: **dump 由来のスナップショット**からテスト DB を立て、fixture で検査データを投入。
- `TestClient` fixture（api テスト用。依存の DB セッションをテスト DB へ差し替え）。

## フロント骨格 (F10 — `frontend/`)

- React + Vite + TS 雛形。`src/api/client.ts`（axios・`baseURL=/api`）、TanStack Query の `QueryClientProvider`、
  ルーティング、`App.tsx`/`main.tsx`。`build → dist`（本番は FastAPI が配信）。

## コンテナ・ビルド (F11)

- **`Dockerfile`（ver2 バックエンド）**: 非 root・`/health` ヘルスチェック。
  API＋スケジューラ＋再学習を同一プロセス/コンテナで動かす（`uvicorn --workers 1`。dev は `--reload`）。
  **ベース＝`nvidia/cuda:<12.8+>-runtime-ubuntu22.04`（ver1 踏襲）＋ apt で Python 3.11 ＋ pip で PyTorch（cu128 系・Blackwell 対応）**。
  GPU は `docker-compose` の `deploy.resources.reservations.devices`（nvidia/all/gpu）で渡す（ver1 compose 実績）。
  ※ ver1 は A5000 用に CUDA 12.2／torch cu121 だったが、**Blackwell のため CUDA/torch を更新**する。
- **`docker-compose.yml`（dev）**: ver2 バックエンド＋ver2 DB（独立・永続ボリューム）＋業者 DB 代役（dump ロード）
  （＋任意 pgAdmin）。
- ツール: `black`/`flake8`/`mypy`/`pytest(+cov)`、front の `tsc`/`eslint`/`vitest`（`tech.md` 検証ゲート）。

## テスト設計 (Testing)

- **unit**: 設定の必須欠如で fail-fast／認証の合否／ロギング初期化。
- **integration**: `alembic upgrade` で空ベースラインが適用される／`get_db` の commit・rollback／
  `get_inspection_db` が読み取りできる・業者 DB 断で例外を捕捉できる／conftest の ROLLBACK 隔離。
- **api**: `/health`（ver2 必須・業者参考）／認証ゲート（401／無効化時通過）。

## 依存・前提 (Dependencies)

- **棚卸し**: 業者外部モデルの具体スキーマは棚卸し後（各機能）。本 spec は接続・`ExternalBase` パターンまで。
- **業者 DB の RO ユーザ**: 業者から SELECT のみの読み取り専用ユーザを発行してもらえると、読み取り専用を権限で担保できる（依存）。

## 確定事項・残課題 (Resolved & Deferred)

確定:
- **`uvicorn --workers 1`**（単一バックエンドコンテナ）でスケジューラ単一所有を担保。
- **認証＝単一共有クレデンシャル**（例: `username=shisui`・共通パスワード。ロールなし）。コメントは匿名のまま。

後日決定（非ブロッキング・本 spec の他部分は進められる）:
- **業者 DB の RO ユーザ**: 発行されれば読み取り専用を権限で担保。無くても**業者エンジン＋セッション非 commit＋
  リポジトリで書かない**で担保するため、design は両対応。

確定（image / GPU・ver1 踏襲）:
- バックエンド image ＝ **`nvidia/cuda` ランタイム（CUDA 12.8+）＋ Python 3.11 ＋ PyTorch cu128 系**（Blackwell 対応）。
  GPU は `docker-compose` の `deploy.resources`（nvidia/all/gpu）で渡す。CUDA/torch の厳密なピンはビルド時に確定。
