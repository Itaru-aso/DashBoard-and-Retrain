# モデル再学習ワークフロー — Tasks

> spec: `モデル再学習ワークフロー (model-retraining)`
> 配置想定: `.kiro/specs/model-retraining/tasks.md`
> 上流: `requirements.md`（M-R1〜M-R9・確定事項）・`design.md`（学習側連携の確定含む） ／ 規約: `tech.md`・`structure.md`
> 連携の事実: `2026-06-30-retraining-integration-answers.md`・`schema-spec-mapping.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: tsc・eslint・vitest）。
> コミットは Conventional Commits（例: `feat(retraining): ...`）。
>
> 進捗印: `[ ]` 未着手／`[~]` **参照実装あり（要結合）** ＝ コードは作成済みだが import パス調整・実環境での結合・
> テスト緑化は未了／`[x]` 完了（TDD 緑化・ゲート通過）。本セッションでタスク 0〜9 の参照実装を作成（`[~]`）。
>
> **参照実装あり**: 本機能は ver2 実装コードの素案を作成済み（`retraining_job.py`・`deployed_model.py`・
> `xxxx_create_retraining.py`・`retraining_repository.py`・`training_service.py`・`deployment_service.py`・
> `retraining_endpoint.py`・`retraining_schemas.py`・`retraining_wiring_example.py`、テスト5本）。
> import パス・DI・config は本プロジェクトのレイアウトに合わせて調整する。

## 前提 (Preconditions)

- **基盤整備**: 単一ワーカ（`uvicorn --workers 1`）・ver2 DB・**lifespan でのワーカ起動/停止**・conftest（2 DB）。
- **`エッジPC管理`**: 有効エッジPC（host/username/password/**model_port**）を `find_enabled()` で取得。
- **`色マスター・色ライフサイクル`**: 起票時の `color_master` 存在チェック（`exists_by_tuple`）。
- **`training/` パイプライン**（`pipline.py` を **subprocess**・CWD=`training/`・**GPU 2枚**は学習側が自動割当）。
- **同一性はフルタプル（案A）**。学習起動は **color_no のみ**渡す（学習側は size/chain/tape 未使用）。
- 画像は**別機能が `1_download` に事前配置**（収集スコープ外）。成果物 ONNX は所定パス。
- テストでは **subprocess・FTP・プロセス kill はモック**（実学習・実配信はしない）。

---

## タスク (Tasks)

- [~] **0. 学習側の薄い改修（`training/pipline.py`・ロジック不変）**
  - `execute()` の **FTP ダウンロードを `common.skip_download` でガード**（608–613）、
    **FTP アップロードを `common.skip_upload` でガード**（689–690）。`conf/config.yaml` の `common` に両既定 `false` を追記。
  - （任意）末尾の `パイプライン完了` 前に **ONNX 未生成なら `sys.exit(1)`**、節目に `[PROGRESS] ...` を print。
  - テスト（学習リポジトリ側・任意）: skip_download/skip_upload で DL/配信が呼ばれないこと（FTP モック）。
  - commit: `feat(training): add skip_download/skip_upload flags (no logic change)`

- [x] **1. マイグレーション: `retraining_job` ＋ `deployed_model`**（ver2 DB）
  - `retraining_job`（フルタプル・`status`〔CHECK 制約〕・各時刻・error・ONNX パス・created_by・索引）、
    `deployed_model`（**フルタプル ユニーク**・`job_id` FK・ONNX パス・`deploy_status`・`deploy_detail`・`deployed_at`）。
  - テスト（integration）: upgrade/downgrade、`deployed_model` のフルタプル ユニークを制約が弾く。
  - Refs: M-R7, M-R8.3 ／ commit: `feat(retraining): add retraining_job and deployed_model migration`

- [x] **2. ORM モデル**
  - `src/models/retraining_job.py`（`RetrainingJob`・`JobStatus`・`TERMINAL_STATUSES`）、
    `src/models/deployed_model.py`（`DeployedModel`・`DeployStatus`）。
  - テスト（integration）: round-trip・status CHECK・FK・`is_terminal`。
  - commit: `feat(retraining): add ORM models`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/retraining.py`: 起票（フルタプル＋created_by）・一覧/詳細・キャンセル・現行配信・配信結果。
  - テスト（unit）: 検証（正常／異常）。
  - Refs: M-R1 ／ commit: `feat(retraining): add schemas`

- [x] **4. Repository**
  - `src/repositories/retraining_repository.py`（ver2）: ジョブ作成（QUEUED）・状態更新（running/completed/failed/cancelled）・
    履歴一覧（filter/paging）・`list_active`（復旧用）・`deployed_model` upsert（フルタプル）・現行取得。
  - テスト（integration）: 作成・状態遷移の永続・一覧/絞り込み/ページング・list_active 順序・deployed upsert（上書き・ユニーク）・取得。
  - Refs: M-R7, M-R8.3 ／ commit: `feat(retraining): add retraining repository`

- [x] **5. Service: `training_service`（キュー・実行・キャンセル）**
  - シングルトン。`main.py` lifespan で **asyncio キュー＋単一ワーカ**起動・**FIFO・同時1本**。復旧（消えた RUNNING→FAILED・QUEUED 再投入）。
  - 実行: `python pipline.py common.target_color=<color_no> common.pipeline_mode=train
    common.skip_download=true common.skip_upload=true color.mlflow.enabled=false monochro.mlflow.enabled=false`
    を **CWD=`training/`・`start_new_session=True`** で起動。標準出力を**1行ずつ素通し**で進捗配信（揮発）。
  - **成功判定（終了コード非依存）**: 両 mode の **ONNX 生成有無**＋標準出力の **`パイプライン完了`** マーカー。
  - キャンセル: QUEUED は除外、RUNNING は**プロセスグループごと kill**（SIGTERM→猶予→SIGKILL）。状態は DB を正に永続。
  - テスト（integration・**subprocess/kill モック**）: COMPLETED（ONNX＋マーカー）／FAILED（ONNX 欠落・マーカー欠落）／
    起動コマンド・cwd・start_new_session／FIFO・同時1本／QUEUED キャンセルは起動されず CANCELLED／進捗素通し。
  - Refs: M-R2, M-R3, M-R4, M-R5, M-R6, M-R7 ／ commit: `feat(retraining): add training_service (queue, subprocess, cancel)`

- [x] **6. Service: `deployment_service`（配信・現行モデル・学習と分離）**
  - `deploy_job(job_id)`: COMPLETED の ONNX を有効エッジPC全台へ **ver2 自前 ftplib** で送信（`model_port`・
    リモート名は検査PC互換の **`{color_no}_{mode}_model.onnx`** を FTP ルート直下）→ `deployed_model` をフルタプルで upsert。
    集約: 全台成功=SUCCESS／一部失敗=PARTIAL／全失敗=FAILED（再配信可・ジョブ成功は覆さない）。
  - v1 は `make_auto_deploy_hook` を `training_service.on_completed` に渡し **COMPLETED で自動配信**。
  - テスト（integration・**FTP フェイク注入**）: 全台成功 SUCCESS（送信数・色番名・model_port）／一部失敗 PARTIAL／全失敗 FAILED／
    エッジPCなし FAILED／非 COMPLETED は ValueError／ONNX 欠落は FileNotFoundError／deployed upsert。
  - Refs: M-R8 ／ commit: `feat(retraining): add deployment_service (ver2 ftplib, separated)`

- [x] **7. WebSocket 進捗**
  - `WS /api/retraining/jobs/{id}/progress`: `training_service.subscribe` を購読し**行を素通し**配信、None で close（揮発）。
  - テスト（api）: 行が流れる・None で閉じる・切断時 unsubscribe。
  - Refs: M-R6 ／ commit: `feat(retraining): add websocket progress`

- [x] **8. API: エンドポイント + ルーター登録**
  - `src/api/retraining_endpoint.py`（`main.py` 登録・Basic 認証ゲート）: `POST /jobs`（**color_master 存在チェック→404**）・
    `GET /jobs`（filter/paging）・`GET /jobs/{id}`・`POST /jobs/{id}/cancel`（終端は **accepted=false** で冪等）・
    `GET /deployed`・`POST /jobs/{id}/deploy`（将来の手動配信）。
  - テスト（api / TestClient）: 起票（存在チェック 404・enqueue 呼出）・一覧・詳細・キャンセル（終端は accepted=false）・
    現行配信・手動配信・認証。
  - Refs: M-R1, M-R5, M-R7, M-R8, M-R9 ／ commit: `feat(retraining): add retraining API endpoints`

- [x] **9. フロント: 再学習画面**
  - `frontend/src/api/retrainingApi.ts`、WS フック、TanStack Query フック、`frontend/src/pages/Retraining.tsx`
    （履歴一覧・色を選んで起票・**WS ライブ進捗（素通しログ）**・キャンセル・現行配信モデル表示）。
  - テスト（Vitest + Testing Library）: 一覧/起票・WS 進捗表示・キャンセル・現行配信表示。
  - Refs: M-R1, M-R5, M-R6, M-R7, M-R8 ／ commit: `feat(retraining): add retraining screen`

- [ ] **10. 配線・仕上げ: lifespan 配線＋検証ゲート**
  - `main.py` lifespan で `deployment_service` 生成→`init_training_service`（on_completed に自動配信フック）→`start()`、終了で `stop()`。
    `config.py` に `training_dir`/`training_model_dir`/`training_python`。`dependencies.py` に DI（color_master/deployment）。
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(retraining): wire lifespan and satisfy verification gate`

---

## トレーサビリティ (Requirements ↔ Tasks)

- M-R1（起票・手動・存在チェック）→ 3, 8 ／ M-R2（キュー・同時1）→ 5
- M-R3（subprocess・GPU・skip_download/upload）→ 0, 5 ／ M-R4（状態遷移・成功判定）→ 5 ／ M-R5（キャンセル）→ 5, 8
- M-R6（WS 進捗・素通し）→ 5, 7, 9 ／ M-R7（記録・履歴・復旧）→ 1, 2, 4, 8
- M-R8（配信・現行モデル・学習と分離）→ 0, 1, 6, 8 ／ M-R9（認証）→ 8

> 注: 実学習・実 FTP・プロセス kill はテストでモック。CUDA は学習側 cu121→**cu128 系へ入替**前提（Blackwell・`tech.md`）。
> 配信先 ONNX のリモート名は検査PC互換のため color_no ベース固定（ver2 の記録はフルタプル＝案A）。
