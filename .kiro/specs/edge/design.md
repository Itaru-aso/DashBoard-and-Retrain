# エッジPC管理 — Design

> spec: `エッジPC管理 (edge-pc)`
> 配置想定: `.kiro/specs/edge-pc/design.md`
> 上流: `requirements.md`（E-R1〜E-R6・確定事項）／ steering: `product.md`・`tech.md`・`structure.md`
> 依存される spec: `モデル再学習ワークフロー`（`deployment_service` が配信先として利用）

## 概要・方針 (Overview)

ONNX 配信先（エッジPC＝検査PC）の**接続情報を ver2 DB で CRUD 管理**する。配信は**有効な全エッジPCへ**行うため、
色→エッジPC のマッピングは持たない。パスワードは **ver1 踏襲で平文保管**（任意項目）。
**実 FTP 配信は `モデル再学習ワークフロー`／`training/`** が担い、本 spec は接続先の管理と
（任意の）接続テストのみ。接続情報の**具体列は ver1 設定受領後に確定**（後追い）。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/edge_pc.py` … `edge_pc`（ver2 テーブル・Alembic）
- `src/repositories/edge_pc_repository.py` … CRUD ＋ `find_enabled()`（**配信先解決の参照点**）
- `src/services/edge_pc_service.py` … 登録・更新・削除・一覧（＋任意: 接続テスト）
- `src/schemas/edge_pc.py` / `src/api/edge_pc_endpoint.py`
- `alembic/versions/<rev>_create_edge_pc.py`
- フロント: `frontend/src/api/edgePcApi.ts` / `frontend/src/pages/EdgePc.tsx`

## データモデル (Data Model — ver2 DB)

**edge_pc**（ver1 準拠・配信スコープ）
- `id`（PK）
- `name`（**ユニーク**。例 `検査PC_1`）・`host`（例 `169.254.93.171`）
- `username`（ドメイン付き可。例 `ykk\shisui_PJ`）・`password`（**平文**。例 `shisui@09`）
- `model_port`（**ONNX 配信用**。例 `2123`）
- `enabled`（bool・既定 true。ver2 で追加）
- `last_ftp_ok` / `last_ftp_checked_at`（**FTP 送信可否**の直近結果・確認時刻。E-R5）
- `created_at` / `updated_at`（timestamptz）

> `monochro_port`／`color_port`／`local_root` は ver1 の**画像収集用**で本スコープ外のため持たない。
> `remote_path` も ver1 に無いため持たない。配信は `deployment_service` が **`model_port`** を使う。

## 再学習との連携 (配信先の解決)

- `モデル再学習ワークフロー` の `deployment_service` は、配信時に `edge_pc_repository.find_enabled()` で
  **有効な全エッジPC**を取得し、各台へ ONNX を FTP 配信する（E-R3）。
- 本 spec は接続情報を提供するのみ（実 I/O は再学習側）。

## FTP 送信可否の監視（E-R5）

- `edge_pc_service.check_ftp(id)`: `ftplib` で対象の `host:model_port` に接続を試み（必要なら送信可否まで）、
  結果を `last_ftp_ok` / `last_ftp_checked_at` に記録。一覧・詳細で状態表示。
- オンデマンド（API）で実行。**定期チェックは任意**（基盤整備のスケジューラで周期実行する余地）。
- 監視対象は **FTP 到達性（送信可否）のみ**（CPU/メモリ/FPS 等のテレメトリは対象外）。
- テストでは `ftplib` を**モック**。

## API 設計 (Endpoints)

`get_db`（ver2）依存。Basic 認証ゲート。

- `GET /api/edge-pcs` … 一覧
- `GET /api/edge-pcs/{id}` … 詳細
- `POST /api/edge-pcs` … 登録
- `PATCH /api/edge-pcs/{id}` … 更新
- `DELETE /api/edge-pcs/{id}` … 削除
- `POST /api/edge-pcs/{id}/check-ftp` … FTP 送信可否の確認（結果を状態として記録・返却）

## バリデーション・エラー処理

- `name` の重複は 409（または 422）。
- スキーマ検証（必須・型）→ 422。
- 接続テスト失敗は結果として返す（500 にしない）。

## テスト設計 (Testing)

- **integration（ver2 DB）**: CRUD、`name` ユニーク、`find_enabled()`（有効のみ返す）。
- **integration（接続テスト・`ftplib` モック）**: 成功/失敗の判定。
- **api**: CRUD のステータス、認証ゲート。
- **frontend（Vitest）**: 一覧・登録/編集/削除・接続テストボタン。

## 依存・前提 (Dependencies)

- `基盤整備`（ver2 DB・Alembic・認証）。
- `モデル再学習ワークフロー` から `find_enabled()` を利用される（配信先解決）。
- **後追い**: 接続情報の具体列（ver1 設定受領後）。

## 確定事項・残課題 (Resolved & Pending)

確定:
- 配信先＝**有効な全台**（`find_enabled()` 参照）。配信ポート＝**`model_port`**。
- パスワード＝**平文**（ver1 踏襲・実値あり）。
- 接続項目＝name・host・username・password・`model_port`・enabled（収集用ポート・local_root・remote_path は持たない）。
- 監視＝**FTP 送信可否**（オンデマンド確認＋状態表示・`last_ftp_ok`。定期は任意）。

残: なし（実装着手可。実 FTP I/O は `モデル再学習`／`training/`、本 spec は接続管理＋送信可否確認）。
