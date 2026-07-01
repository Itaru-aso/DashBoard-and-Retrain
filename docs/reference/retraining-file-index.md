# モデル再学習ワークフロー — 実装ファイル配置インデックス

> 本セッションで作成した実装/テスト/参照ファイルの**配置先一覧**。
> import パス・DI・設定・ファイル名（マイグレーション revision）は本プロジェクトのレイアウトに合わせて調整する。
> 環境前提: ネットワーク無効・GPU/本番DB/検査PC 非接続のため、ここでは作成のみ。結合・実行はお手元（cc-sdd / Claude Code）で。

## バックエンド実装（ver2）

| 出力ファイル | 配置先 | 役割 |
|---|---|---|
| `retraining_job.py` | `backend/src/models/retraining_job.py` | `RetrainingJob`・`JobStatus`・`TERMINAL_STATUSES`（フルタプル・状態・時刻・ONNX パス） |
| `deployed_model.py` | `backend/src/models/deployed_model.py` | `DeployedModel`・`DeployStatus`（色フルタプル ユニークの現行配信モデル） |
| `xxxx_create_retraining.py` | `backend/alembic/versions/<rev>_create_retraining.py` | 2テーブル作成マイグレーション。**`down_revision` を現行 head に設定**・revision/ファイル名は採番に合わせる |
| `retraining_repository.py` | `backend/src/repositories/retraining_repository.py` | ジョブ作成/状態更新/履歴/`list_active`・現行モデル upsert/取得 |
| `training_service.py` | `backend/src/services/training_service.py` | asyncio キュー(FIFO/同時1)・subprocess 起動・進捗素通し・ONNX+マーカー成功判定・プロセスグループ kill・DB 永続 |
| `deployment_service.py` | `backend/src/services/deployment_service.py` | ver2 自前 ftplib 配信(model_port・色番名)・現行モデル upsert・v1 自動配信フック |
| `retraining_schemas.py` | `backend/src/schemas/retraining.py` | Pydantic v2 入出力スキーマ |
| `retraining_endpoint.py` | `backend/src/api/retraining_endpoint.py` | REST + WebSocket(進捗)・Basic 認証ゲート・起票時 color_master 存在チェック |
| `retraining_wiring_example.py` | （参照・取り込み例） | `main.py` lifespan 配線／`config.py`／`dependencies.py` の DI 例（概要） |
| `main_wiring.py` | （参照→ `backend/src/main.py` ＋ `backend/src/dependencies.py`） | **ルーター登録を含む配線の実コード**（create_app・lifespan・DI シングルトン・uvicorn 起動注記） |

## バックエンドテスト

| 出力ファイル | 配置先 | 対象 |
|---|---|---|
| `conftest.py` | `backend/tests/conftest.py`（既存があれば統合） | sqlite フィクスチャ・subprocess/kill/FTP/エッジPC モック |
| `test_retraining_repository.py` | `backend/tests/integration/test_retraining_repository.py` | リポジトリ（作成/遷移/一覧/現行モデル） |
| `test_training_service.py` | `backend/tests/integration/test_training_service.py` | キュー/実行/成功判定/FIFO/キャンセル（subprocess モック） |
| `test_deployment_service.py` | `backend/tests/integration/test_deployment_service.py` | 配信集約/色番名/エラー（FTP フェイク） |
| `test_retraining_api.py` | `backend/tests/api/test_retraining_api.py` | API/WS（依存 override） |

## フロントエンド（ver2）

| 出力ファイル | 配置先 | 役割 |
|---|---|---|
| `retrainingApi.ts` | `frontend/src/api/retrainingApi.ts` | 型 + fetch クライアント + 進捗 WS URL |
| `useRetraining.ts` | `frontend/src/hooks/useRetraining.ts` | TanStack Query フック + `useJobProgress`(WebSocket) |
| `Retraining.tsx` | `frontend/src/pages/Retraining.tsx` | 再学習画面（起票/履歴/進捗/キャンセル/現行モデル）。ルーティング登録が別途必要 |
| `Retraining.test.tsx` | `frontend/src/pages/Retraining.test.tsx` | Vitest + Testing Library |
| `frontend_route_registration.tsx` | （参照→ `frontend/src/App.tsx` 等） | **React Router へのルート登録**＋ナビ追加の実コード例 |

## 学習側（既存 `training/`・薄い改修のみ）

| 対象 | 改修 |
|---|---|
| `training/pipline.py` | `execute()` の FTP DL を `common.skip_download`、FTP アップロードを `common.skip_upload` でガード（608–613 / 689–690）。任意: ONNX 未生成で `sys.exit(1)`・`[PROGRESS]` print |
| `training/conf/config.yaml` | `common.skip_download: false` / `common.skip_upload: false` を追記（既定 false・後方互換） |
| 配置 | 学習サブセット一式（`pipline.py`・`train_func_*`・`model*.py`・`utils/*`・`conf/`・`0_pretraining/*.pth`）を `training/` にまるごと配置 |

## spec（更新済み・参照）

| ファイル | 配置先 | 備考 |
|---|---|---|
| `retraining-design.md` | `.kiro/specs/model-retraining/design.md` | 「学習側連携（確定）」追記済み |
| `retraining-tasks.md` | `.kiro/specs/model-retraining/tasks.md` | 実装実態に更新済み（タスク0=学習側改修ほか） |
| `retraining-integration-requirements.md` | （参照） | 情報要件 |
| `2026-06-30-retraining-integration-answers.md` | （参照・受領済み回答） | 連携の事実 |

## 取り込み順（依存）

1. 学習側 `training/` 配置 ＋ `pipline.py` 薄い改修（skip_download/skip_upload）
2. モデル（`retraining_job` / `deployed_model`）＋ Alembic マイグレーション（head へ接続）
3. `retraining_repository`
4. `training_service`（lifespan で start/stop）
5. `deployment_service`（`training_service.on_completed` に自動配信フック）
6. `schemas` → `retraining_endpoint`（`main.py` 登録）→ WebSocket
7. フロント（api → hooks → page → ルート登録）
8. テスト緑化（pytest cov≥80 / tsc・eslint・vitest）

## 調整が要る箇所（要対応）

- **import パス**: `from database import Base` / `models.*` / `repositories.*` / `services.*` / `api.*` / `auth` / `dependencies` をプロジェクト構成へ。
- **DI 実体**: `get_db`・`verify_basic_auth`・`get_color_master_repo`(`exists_by_tuple`)・`get_deployment_service`・`SessionLocal`。
- **config**: `training_dir` / `training_model_dir` / `training_python`（cu128 入り）。`uvicorn --workers 1`。
- **CUDA**: 学習側 torch を cu121→**cu128 系**へ（Blackwell）。
- **WebSocket 認証**: ブラウザ WS の Basic 代替（Cookie セッション or クエリトークン）。
- **マイグレーション**: `down_revision` を現行 head に設定。
- **エッジPC repo**: `find_enabled()`（host/username/password/model_port）を備える（`エッジPC管理` spec）。
