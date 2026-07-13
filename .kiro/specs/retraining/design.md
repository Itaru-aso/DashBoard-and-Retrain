# モデル再学習ワークフロー — Design

> spec: `モデル再学習ワークフロー (model-retraining)`
> 配置想定: `.kiro/specs/model-retraining/design.md`
> 上流: `requirements.md`（M-R1〜M-R9・確定事項）／ steering: `product.md`・`tech.md`・`structure.md`
> 依存 spec: `基盤整備`（単一ワーカ・ver2 DB・lifespan）／ `エッジPC管理`（FTP 配信先を利用）

## 概要・方針 (Overview)

色（フルタプル）に対する再学習を**オーケストレーション**する。ジョブは ver2 DB に記録（状態・時刻・結果＝DB を正）、
キューは**アプリ内（asyncio）・単一ワーカ所有・FIFO・同時1本**。実行は `training/` を **subprocess** で起動し、
**2枚の GPU** で monochro/color を学習。進捗・ログは **WebSocket**（揮発）。学習用画像は**同一 PC 上の所定パス**
（外部が用意）から読む。学習成果（ONNX）は **FTP でエッジへ配信**（v1 は完了時自動・将来は手動）。
**学習と配信は別ステップに分離**しておき、将来の手動配信へ非破壊で移行できるようにする。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/retraining.py` … `retraining_job` / `deployed_model`（ver2 テーブル・Alembic）
- `src/repositories/retraining_repository.py` … ジョブ記録・履歴・現行配信モデルの読み書き（ver2 エンジン）
- `src/services/training_service.py` … **シングルトン**。キュー・ワーカ・subprocess ライフサイクル・状態遷移・キャンセル
- `src/services/deployment_service.py` … ONNX の **FTP 配信**（`training/` の FTP I/O を利用）＋現行配信モデル更新（**学習と分離**）
- `src/api/retraining_endpoint.py` … 起票・一覧・詳細・キャンセル＋ **WebSocket 進捗**（`main.py` 登録）
- `src/schemas/retraining.py`
- `alembic/versions/<rev>_create_retraining.py`
- `training/` … 学習パイプライン（subprocess・`from pipline import ...`・ONNX 出力・FTP I/O）
- フロント: `frontend/src/api/retrainingApi.ts` / `frontend/src/pages/Retraining.tsx`（WS 進捗）

## データモデル (Data Model — ver2 DB)

**retraining_job**
- `id`（PK）・`color_no`/`size`/`chain`/`tape`（対象色）
- `status`（enum: `QUEUED`/`RUNNING`/`COMPLETED`/`FAILED`/`CANCELLED`。既定 `QUEUED`）
- `queued_at` / `started_at` / `finished_at`・`result` / `error_message`
- `onnx_monochro_path` / `onnx_color_path`（成果物の参照。ローカル所定パス）
- `created_at` / `updated_at`（timestamptz）

**deployed_model**（色ごとの現行配信モデル・最小管理。M-R8.3）
- `id`（PK）・`color_no`/`size`/`chain`/`tape`（**ユニーク**）
- `job_id`（FK→retraining_job）・`deployed_at`

## キュー・実行 (M-R2 / M-R3 / M-R4 / M-R5 — `training_service`)

- **シングルトン**の `training_service` が、`main.py` の lifespan で **in-process の asyncio キュー＋単一ワーカ**を開始
  （`uvicorn --workers 1` 前提・`基盤整備`）。**FIFO・同時1本**（`RUNNING` は高々1つ）。
- 起票: `retraining_job` を `QUEUED` で作成しキュー投入。
- 実行: ワーカが取り出し → `RUNNING`（`started_at`）→ `training/` を **subprocess** 起動（対象色・データセットパス・
  **2 GPU** 構成を渡す）→ 正常終了で `COMPLETED`、異常で `FAILED`、キャンセルで `CANCELLED`（`finished_at`・結果/エラー）。
- 進捗: subprocess の標準出力（1行ずつの進捗・ログ）を読み、接続中の **WebSocket** へブロードキャスト（**揮発**）。
- キャンセル（M-R5）: `QUEUED` はキューから除去して `CANCELLED`。`RUNNING` は**プロセスツリー kill** → `CANCELLED`。
- 状態は **DB を正**として都度永続（再接続・履歴参照に必要。M-R7）。

## 配信・現行モデル (M-R8 — `deployment_service`／学習と分離)

- `COMPLETED` 時、`training_service` が `deployment_service.deploy(job)` を呼ぶ（**v1 は自動**）。
- `deploy(job)`: `エッジPC管理` の接続先（DB）へ、2つの ONNX を **FTP 配信**（FTP I/O は `training/`）。
  成功後、`deployed_model` を色キーで upsert（`job_id`・`deployed_at`）。
- **将来の手動配信**: `deploy` を**独立メソッド/サービス**にしておき、将来は自動呼び出しを外して
  手動エンドポイント（`POST /api/retraining/jobs/{id}/deploy`）から呼ぶだけで移行できる（非破壊）。

## WebSocket 進捗 (M-R6)

- `WS /api/retraining/jobs/{id}/progress`: 実行中ジョブの進捗・ログを配信。永続しない。
- 同時実行は1本のため、実質「現在 RUNNING のジョブ」を購読する形。切断・再接続は許容（揮発）。

## API 設計 (Endpoints)

`get_db`（ver2）依存。Basic 認証ゲート。

- `POST /api/retraining/jobs` … 起票（color 指定・**`color_master` 存在チェック**・作業者の手動。M-R1）→ `QUEUED`
- `GET /api/retraining/jobs` … 一覧・履歴（filter: status, color）
- `GET /api/retraining/jobs/{id}` … 詳細
- `POST /api/retraining/jobs/{id}/cancel` … キャンセル（QUEUED 除去／RUNNING kill）
- `WS /api/retraining/jobs/{id}/progress` … 進捗・ログ（揮発）
- `GET /api/retraining/deployed` … 色ごとの現行配信モデル一覧
- （将来）`POST /api/retraining/jobs/{id}/deploy` … 手動配信（v1 は自動のため未使用。seam のみ用意）

## バリデーション・エラー処理

- 起票時、対象色が **`color_master` に存在しない**場合は拒否（404/422）。画面は色マスターから選択させる。
- 終了済みジョブのキャンセル要求 → 409。
- スキーマ検証（color 必須・enum）→ 422。
- FTP 配信失敗 → ジョブは `COMPLETED` のまま配信を失敗として記録（再配信可能に）。配信失敗で学習結果は失わない。

## テスト設計 (Testing — 検証ゲートにマップ)

- **integration（ver2 DB）**: 状態遷移（QUEUED→RUNNING→COMPLETED/FAILED/CANCELLED）、FIFO・同時1本、
  キャンセル（QUEUED 除去／RUNNING kill）、記録の永続、`deployed_model` の upsert。
  ※ subprocess・FTP は**モック**（実学習・実配信はしない）。
- **integration（配信分離）**: `COMPLETED` で `deploy` が自動呼び出しされる／`deploy` 単体で現行モデル更新／配信失敗の記録。
- **api/WS**: 起票・一覧・詳細・キャンセルのステータス、WS で進捗が流れる、認証ゲート。
- **frontend（Vitest）**: ジョブ一覧/起票・WS 進捗表示・キャンセル・現行配信モデル表示。

## フロント構成

- `pages/Retraining.tsx`（ジョブ一覧/履歴・色を選んで起票・**WS でライブ進捗**・キャンセル・現行配信モデル表示）、
  `api/retrainingApi.ts`、WS フック、TanStack Query フック。

## 依存・前提 (Dependencies)

- `基盤整備`（単一ワーカ・ver2 DB・lifespan でのワーカ起動）。
- `training/` パイプライン（subprocess・`from pipline import`・ONNX 出力・FTP I/O）。GPU 2枚。
- `エッジPC管理`（FTP 配信先の接続情報。DB 管理）。
- `色マスター・色ライフサイクル`（起票時の color 存在チェック）。
- 学習用画像は**同一 PC 上の所定パス**（外部が用意・収集はスコープ外）。

## 確定した設計判断 (Resolved)

- データモデル: `retraining_job`（履歴）＋ `deployed_model`（色ごと現行・最小）の **2テーブル**。
- 配信: `deploy` を**独立サービス**に分離。**v1 は `COMPLETED` で自動呼び出し**（将来は手動エンドポイントへ非破壊移行）。
- 起票: 対象色は **`color_master` に存在する色のみ**（存在チェックあり）。
- 成果物 ONNX: **ローカル所定パスに出力し `retraining_job` にパス参照**を保持（DB にバイナリは入れない）。

## 画面デザイン刷新（2026-07-13 追記）

> 対象は**見た目のみ**（`ui-shell` の共通レイアウト・デザイントークンに乗せる）。API・Service・
> データモデルは無変更。参照 UI: `Shisui Dashboard (standalone).html`（ビジュアル参照）。

- モックアップは「サイズ/チェーン/色番を複数選択してまとめて1回実行」という単一パネルだが、
  本 spec は単一フルタプルごとのジョブ起票モデル（履歴一覧・WSライブ進捗・キャンセル・現行配信モデル
  一覧を含む）のため、モックアップの構造には簡略化しない。既存機能はすべて残し、見た目のみ合わせる。
- モックアップの「AIメトリクス」カード（データソース不明）は本 spec に無いデータのためスコープ外。
