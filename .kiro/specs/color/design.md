# 色マスター・色ライフサイクル管理 — Design

> spec: `色マスター・色ライフサイクル管理 (color-lifecycle)`
> 配置想定: `.kiro/specs/color-lifecycle/design.md`
> 上流: `requirements.md`（C-R1〜C-R6・確定事項）／ steering: `product.md`（不変条件4）・`tech.md`・`structure.md`
> 依存 spec: `日次集計基盤`（`daily_metrics` 号機合算・共有 `services/metrics.py`）／ `基盤整備`（スケジューラ・2 DB）

## 概要・方針 (Overview)

色マスター（同一性タプル・色見本 RGB/Lab・ライフサイクル状態）を **ver2 DB** で管理する。
登録は**一覧ファイルの取り込み**。状態遷移は**日次の自動判定**（`未実施 → 量産検証 → 実生産`、一方向）。
判定は `日次集計基盤` の **`daily_metrics`（号機合算）**を読み、共有 `services/metrics.py`（基盤所有）で率を算出して行う。
**基盤整備のアプリ内スケジューラ**の日次ジョブで実行する（集計 → 逸脱判定 → **昇格** の順・冪等）。
`daily_metrics`（ver2）と色マスター（ver2）の突合は **Service 層**で行う（集計は基盤側で完了済み）。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/color_master.py` … `color_master`（ver2 テーブル・Alembic）
- `src/repositories/color_master_repository.py` … 登録・upsert・状態更新・検索（ver2 エンジン）
- `src/services/color_import_service.py` … 一覧ファイルのパース→登録（バリデーション・結果レポート）
- `src/services/color_lifecycle_service.py` … 日次の自動遷移判定（検査実績検知・昇格判定）
- `src/services/metrics.py`（**`日次集計基盤` 所有**・共有）… 件数→率算出（本 spec は呼び出して使う）
- `src/jobs/color_lifecycle_job.py` … 日次ジョブ（スケジューラから起動・Service を呼ぶ薄い層）
- `src/schemas/color_master.py` / `src/api/color_master_endpoint.py`
- `alembic/versions/<rev>_create_color_master.py`
- フロント: `frontend/src/api/colorApi.ts` / `frontend/src/pages/ColorMaster.tsx`

## データモデル (Data Model — ver2 DB)

**color_master**
- `id`（PK）
- `color_no` / `size` / `chain` / `tape`（同一性タプル）。**ユニーク制約** `UNIQUE (color_no,size,chain,tape)`
- 色見本: `rgb`（R・G・B の3列）/ `lab`（L・a・b の3列）（**列で保持**・1色1基準値）
- `status`（enum: `未実施` / `量産検証` / `実生産`。既定 `未実施`）
- `verification_at` / `production_at`（各遷移の発生時刻。**時刻のみ・履歴テーブルは作らない**）
- `created_at` / `updated_at`（timestamptz）

## 一覧ファイル取り込み (C-R1 — `color_import_service`)

- 一覧ファイル（**xlsx・`Sheet1`**）をパースし、同一性タプル＋色見本を抽出 → `color_master` に upsert（新規は `未実施`）。
- **列マッピング（確定）**: `size`→size・`chain`→chain・`tape`→tape（空欄可）・`color_no`→color_no・`R/G/B`→rgb・`L/a/b`→lab。
  - `color_no`・`size` は**文字列**で保持（ゼロ埋め維持。`001`/`03`。数値化しない）。`color_no` は**前後空白を trim**（例 `"  001"`→`"001"`）。
  - **`status`・`update_date` 列は無視**。status は既定 `未実施`、時刻は**取り込み時刻**（status は自動管理）。
- バリデーション（必須列・タプル整合）。同一タプルは色見本を更新し **status は保持**。
- 結果レポート（作成/更新/スキップ/エラー行）を返す。
- API: `POST /api/colors/import`（multipart）。

## ライフサイクル自動遷移 (C-R3 / C-R4 — `color_lifecycle_service`)

`evaluate(window)`（直近 `window` 日＝JST 日次。日次スケジューラから）:
- **未実施 → 量産検証**（C-R3）: `未実施` の色について、`daily_metrics` に**当該フルタプルの行が存在**すれば
  （検査実績あり＝対象期間に集計行がある）`量産検証` へ遷移（`verification_at` 記録）。
- **量産検証 → 実生産**（C-R4）: `量産検証` の色について、`daily_metrics` を**号機合算**で読み、対象期間の各 JST 日の率を
  `services/metrics.py` で算出。**いずれかの日**が `虚報率 ≤ 1.5%` かつ `見逃し率 ≤ 0.05%` を**同時達成**したら
  `実生産` へ即時昇格（`production_at` 記録）。**固定基準**（`閾値管理` 非依存）。
  - KPI はアノテーション（正解）が要るため、**`annotated_count > 0` の日のみ判定対象**（注釈0件の日は昇格判定に使えない）。
  - 判定母数はその日の生産数（＝monochro 件数）。絶対値・最小サンプル下限なし・人手承認なし。
- **一方向・冪等**: 既に `実生産` は対象外。再評価しても後戻りしない（C-R2）。
- `daily_metrics`（ver2）→ status 更新（ver2）は **Service 層**で行う（集計は基盤側で完了済み）。
- （任意）`未実施` 未登録だが集計行がある色を **WARN/レポート**（登録漏れ検知）。

## スケジューラ相乗り (基盤整備)

- `jobs/color_lifecycle_job.py` を `main.py` 起動時に**日次**登録。順序は **集計 → 逸脱判定 → 昇格**
  （`daily_metrics` 更新後に昇格判定が読む）。
- 日次メトリクスは `日次集計基盤` 所有の `services/metrics.py` を共有。単一ワーカ所有・冪等。

## API 設計 (Endpoints)

`get_db`（ver2）依存。検査実績/メトリクス参照は `get_inspection_db`（読み取り専用）。Basic 認証ゲート。

- `GET /api/colors` … 一覧（filter: status, color_no, size, chain, tape）
- `GET /api/colors/{id}` … 詳細
- `POST /api/colors/import` … 一覧ファイル取り込み
- `PATCH /api/colors/{id}` … 色見本（RGB/Lab）の更新（**status は自動管理・手動変更不可**）
- `POST /api/colors/evaluate` … 手動でライフサイクル判定（テスト・即時実行用）

## バリデーション・エラー処理

- 取り込み: 不正行を報告（全体は落とさず結果レポート）。同一タプル重複は upsert（status 保持）。
- ユニーク制約違反（同一タプル）は取り込み側で upsert に解決。
- status の手動変更は受け付けない（自動管理）。

## テスト設計 (Testing — 検証ゲートにマップ)

- **integration（ver2 DB）**: 取り込み（未実施で作成・タプル重複は upsert・色見本更新）、ユニーク制約、一覧フィルタ。
- **integration（2 DB・ライフサイクル）**:
  - 未実施→量産検証（検査実績の有無）。
  - 量産検証→実生産（ある日が両基準同時達成で昇格／片方未達は昇格せず／ラベル0件日は判定対象外）。
  - 一方向（実生産は対象外・後戻りなし）／冪等（再評価で重複遷移しない）。
- **integration（スケジューラ）**: ジョブが評価サービスを呼ぶ／冪等。
- **api**: 一覧・取り込み・evaluate・詳細・色見本更新・認証。
- **frontend（Vitest）**: 一覧/フィルタ・取り込み UI・色見本表示/編集・ステータス表示。

## フロント構成

- `pages/ColorMaster.tsx`（一覧・ステータス絞り込み・ファイル取り込み・色見本の表示/編集）、
  `api/colorApi.ts`、TanStack Query フック。

## 依存・前提 (Dependencies)

- `日次集計基盤`（`daily_metrics` 号機合算・共有 `services/metrics.py`）・`基盤整備`（スケジューラ・2 DB）が実装済み。

## 確定事項 (Resolved)

- D1 色見本＝`rgb`(R/G/B)・`lab`(L/a/b) を**列で保持**（1色1基準値）。
- D2 遷移は `verification_at`/`production_at` の**時刻のみ**（履歴テーブルは作らない）。
- D3 一覧ファイル＝**xlsx・`Sheet1`**。列マッピング確定（size/chain/tape/color_no/R/G/B/L/a/b）。
  `color_no`・`size` は文字列・`color_no` は trim。**`status`・`update_date` は無視**（status 既定 未実施・取り込み時刻）。重複タプルは upsert（色見本更新・status 保持）。
- D4 `status` は**自動管理のみ**（手動変更なし。不変条件4 と整合）。

## 画面デザイン刷新（2026-07-13 追記）

> 対象は**見た目のみ**（`ui-shell` の共通レイアウト・デザイントークンに乗せる）。API・Service・
> データモデルは無変更。参照 UI: `Shisui Dashboard (standalone).html`（ビジュアル参照）。

- サマリーカード（登録色数／未実施／量産検証／実生産）は既存の `status` 集計で作る（フロント側の
  クライアント集計。バックエンド変更なし）。
- モックアップの「色番を追加」モーダル（手動登録）は**登録 API が無いため不採用**（一覧ファイル取り込み
  ＝D3 のみが登録経路であることは不変。brainstorming で確認済み）。
- モックアップの「色名」「表示色（hex）」「直近NG率」列は本 spec に無いデータのため**スコープ外**。
  「色見本」は既存の `rgb_r/rgb_g/rgb_b` からスウォッチ色を算出して表示に使う（新規データではない）。
- 色番の検索は取得済み一覧をフロントで `color_no` 部分一致フィルタする（バックエンド変更なし）。
