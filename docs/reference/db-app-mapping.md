# ver2 DB テーブル ↔ アプリ処理 対応表

> 対象 DB: ver2 DB（自前・読み書き・Alembic 管理）の全7テーブル。
> app_db（読み取り専用・外部）側の対応は `@docs/reference/schema-spec-mapping.md` を参照（対象外・重複させない）。
> 目的: 各テーブルを使う Repository/Service/API・Job と、重複・対応する外部 config（`training/conf/config.yaml`）・
> env（`.env`）を一覧化する。実装を読まずに対応関係を把握するためのリファレンス。

## 一覧

| テーブル | 使用する Repository/Service | 使用する API・Job | 外部 config/env との対応 |
|---|---|---|---|
| `color_master` | `color_master_repository`, `color_lifecycle_service` | `color_master_endpoint`, `color_lifecycle_job` | なし |
| `daily_metrics` | `daily_metrics_repository`, `aggregation_service`, `metrics.py`, `breach_evaluation_service`, `color_lifecycle_service` | `aggregation_endpoint`, `dashboard_endpoint`, `aggregation_job` | env: `AGG_RUN_TIME` / `AGG_WINDOW_DAYS`（`aggregation_job` の実行時刻・再集計窓） |
| `threshold` | `threshold_repository`, `threshold_service` | `threshold_endpoint`, `breach_eval_job`（`breach_evaluation_service` 経由） | env: `BREACH_EVAL_ENABLED` / `BREACH_EVAL_TIME` / `BREACH_EVAL_WINDOW_DAYS` |
| `task` | `task_repository` | `task_endpoint`（起票元は `breach_evaluation_service`） | なし |
| `edge_pc` | `edge_pc_repository`（`find_enabled`）, `edge_pc_service` | `edge_pc_endpoint`, `deployment_service`（配信先解決） | `training/conf/config.yaml` の `common.ftp_hosts`（★下記「既知のギャップ」参照） |
| `retraining_job` | `retraining_repository`, `training_service` | `retraining_endpoint` | env: `TRAINING_DIR` / `TRAINING_MODEL_DIR` / `TRAINING_PYTHON`（★下記「既知のギャップ」参照） |
| `deployed_model` | `retraining_repository`, `deployment_service` | `retraining_endpoint` | `edge_pc`（配信先）と `retraining_job`（`job_id` FK）に依存。config/env 直接対応なし |

## 既知のギャップ

実装調査で判明した、DB と外部 config/env が二重管理・記載不一致になっている箇所。**修正はせず記録のみ**
（`edge_pc` は `.kiro/specs/edge/design.md` で意図的にスコープを絞った確定事項であり、安易に「直す」対象ではない）。

### 1. `edge_pc`（DB） ↔ `common.ftp_hosts`（config.yaml）

`edge_pc` と `config.yaml` の `common.ftp_hosts` は `host`/`username`/`password`/`model_port` が意味的に重複する。

- **アプリ（ver2）とエッジPC間の通信はモデル配信（upload）のみ**。画像収集（download）は本アプリのスコープ外
  （別機能が担う）。したがって `ftp_hosts` の3ポート項目（`monochro_port`／`color_port`／`model_port`）のうち、
  `edge_pc`・アプリの「エッジPC管理」画面と対応するのは **`model_port` のみ**。
- **ver2 起動フローでは `ftp_hosts` は使われない**。`training_service.build_command()` が常に
  `common.skip_download=true` `common.skip_upload=true` を付与するため、`pipline.py` は FTP ダウンロード・
  アップロードの両方をスキップする（`.kiro/specs/retraining/tasks.md` タスク0）。モデル配信は ver2 の
  `deployment_service` が `edge_pc.model_port` を使って ftplib で直接行う。
- `ftp_hosts` が実際に読まれるのは、`pipline.py` を **skip フラグ無しで単独実行**した場合のみ。
  この場合に限り、DB の `edge_pc` 登録内容と `config.yaml` の静的リストがズレるリスクがある
  （例: ver2 UI で検査PCを追加しても `config.yaml` には反映されない）。
- `edge_pc` が `monochro_port`／`color_port`／`local_root` を持たないのは**仕様上の意図的な決定**
  （`.kiro/specs/edge/design.md:35`, `requirements.md:38`）。画像収集用ポートは別機能のスコープ外という
  確定事項であり、「対応が取れていない」ではない。

### 2. `TRAINING_MODEL_DIR`（env） ↔ `common.model_dir`（config.yaml）— 対応済み

- `training/pipline.py` は学習成果物（ONNX）を `config.yaml` の `common.model_dir`（既定 `./6_model`、
  `training_dir` 相対パス）配下に**書き込む**。
- ver2 の `deployment_service`／`training_service` は `TRAINING_MODEL_DIR`（env・絶対パス）配下から
  `{color_no}/{mode}/{color_no}_{mode}_model.onnx` を**読み込む**（`TrainingConfig.onnx_path()`）。
- 元は `training_service.build_command()` が `common.model_dir` を上書きしておらず、書き込み先
  （config.yaml の既定値）と読み込み先（env）が同じ場所を指すことを運用者が手動で一致させる前提だった。
  → **対応**: `build_command()` に `common.model_dir=<TRAINING_MODEL_DIR>` の dotlist override を追加し、
  env（`TRAINING_MODEL_DIR`）を単一の正とした（`training_service.py`）。

### 3. `backend/.env.example` の記載漏れ・記載過多 — 対応済み

- `config.py` は `TRAINING_DIR` / `TRAINING_MODEL_DIR` / `TRAINING_PYTHON`（**実際に `main.py` が使用**）に加え、
  `TRAINING_DATASET_PATH` / `TRAINING_PIPELINE_DIR`（**実装のどこからも参照されていない dead config**）を定義する。
- 元は `backend/.env.example` が **dead な2項目のみ記載**し、**live な3項目が記載漏れ**だった。
  → **対応**: `.env.example` を live な3項目（`TRAINING_DIR`／`TRAINING_MODEL_DIR`／`TRAINING_PYTHON`）に置き換えた。
- 残課題: `config.py` 自体の `TRAINING_DATASET_PATH` / `TRAINING_PIPELINE_DIR`（dead config）は本対応では削除して
  いない（指摘のみ・別タスク）。
