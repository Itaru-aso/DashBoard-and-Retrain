# 検査結果ダッシュボード — Design

> spec: `検査結果ダッシュボード (inspection-results-dashboard)`
> 配置想定: `.kiro/specs/inspection-results-dashboard/design.md`
> 上流: `requirements.md`（R1–R7）／ steering: `product.md`・`tech.md`・`structure.md`
> 依存 spec: `閾値管理`（`ThresholdService.resolve_effective` を重ね描きに利用）

## 概要・方針 (Overview)

読み取り専用。**推移・集計**は `日次集計基盤` が貯めた ver2 の **`daily_metrics`** を読み、率は共有 `services/metrics.py` で算出する。
**明細**のみ app_db（`annotation.image_base`・読み取り専用）をオンザフライ参照する。NG率・KPI のグラフには
`閾値管理`（ver2 DB）の有効閾値ラインを重ねる。3層（API → Service → Repository → DB）に沿う。
`daily_metrics` と閾値はともに ver2 DB だが、重ね描きは**日次の有効閾値を Service 層で系列に重ねる**（集計は基盤側で完了済み）。
明細参照する app_db は**変更しない**（索引追加もしない）。本機能は**集計テーブルを新設しない**。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/repositories/daily_metrics_repository.py` … **日次集計基盤が所有**（ver2）。推移/集計はこの集計テーブルを読む（期間/フルタプル/号機）
- `src/repositories/inspection_detail_repository.py` … **明細のみ** app_db（`annotation.image_base`）を読み取り専用（`get_inspection_db`）・キーセット
- `src/services/metrics.py` … **日次集計基盤が所有**する共有メトリクス算出（件数→率）。本機能は呼び出して使う
- `src/services/dashboard_service.py` … `daily_metrics` を読み `metrics.py` で率算出、重ね描き用に `ThresholdService`（ver2 DB）を Service 層で突合。明細は detail repository
- `src/schemas/dashboard.py` … フィルタ／系列／明細の入出力スキーマ
- `src/api/dashboard_endpoint.py` … FastAPI ルーター（`main.py` 登録）

本機能は**集計テーブルを新設しない**（`日次集計基盤` の `daily_metrics` を読む）。明細参照する app_db は**変更しない＝索引追加もしない**。
app_db はライブのため、**明細の到達不能・接続断時もダッシュボードが致命的に落ちない**ハンドリングを設ける。

## データ源（`schema-spec-mapping.md` 準拠）

- **推移・集計**: ver2 の **`daily_metrics`**（`日次集計基盤` が日次で貯めた件数。JST日×フルタプル×号機）。
- **明細**: app_db `annotation.image_base`（読み取り専用）。実列 ── `image_id`・`inspect_timestamp`・`unit`（号機）・
  `camera_model`・`judgment_result`（0:OK/1:NG）・`extra_info`(jsonb) の `colorNo`/`size`/`chain`/`tape`。

## 推移・集計の読み出し（R2 / R4 / R7）

- `daily_metrics` から **期間・フルタプル・号機**で件数を読む（集計は基盤側で実施済み）。
- 率は `services/metrics.py` で算出: `NG率=ng/monochro`・`虚報率=annotated==0?NULL:fp/monochro`・
  `見逃し率=annotated==0?NULL:miss/monochro`・`スループット=monochro`（`monochro=0` 除外）。
- **号機フィルタ**: `daily_metrics.unit` で絞る（指定なし＝**全号機合算**）。号機は**表示専用**で粒度に加えない。
  ※ `保守タスク`（逸脱判定）・`色ライフサイクル`（昇格）は集計基盤の**号機合算**を色単位で用いる（号機で絞らない）。閾値は色レベル。

## 明細の読み出し（R4.2）

- app_db `annotation.image_base` を**オンザフライ**（期間内パーティション）で読み、**キーセット**（カーソル
  `(inspect_timestamp, image_id)`）でページング。フルタプル絞り込みは `extra_info->>'...'`、号機は `unit`。

## 閾値重ね描き連携（R3）

- 対象メトリクス: NG率・虚報率・見逃し率（スループットは閾値なし）。
- 色が**フルタプルで一意に定まる選択時のみ**重ね描き（R3.2）。
- 閾値は有効期間を持つため、期間内で変わりうる。`DashboardService` は範囲内の各日について
  `ThresholdService.resolve_effective(metric, fulltuple, day)` を解決し、**日次の閾値系列（階段状）**として返す。
- メトリクス（`daily_metrics`）と閾値（閾値テーブル）はともに ver2 だが、**Service 層で日次系列に突き合わせる**
  （集計は基盤側で完了済み・閾値は有効期間で解決）。
- 解決が「閾値なし」の日は線を引かない（R3.3。`閾値管理` の下流契約）。

## API 設計 (Endpoints)

すべて GET・読み取り専用。推移/集計は ver2 `daily_metrics`、明細は app_db（`get_inspection_db`・読み取り専用）、
重ね描きの閾値解決は ver2（`ThresholdService`）。Basic 認証ゲート通過。

- `GET /api/dashboard/trends` … params: `from,to,color_no?,size?,chain?,tape?,machine_ids?`（号機・複数可・既定 全号機）。
  日次のメトリクス系列（throughput / ng_rate / false_alarm_rate / miss_rate、NULL を含む）を返す（R2）。`daily_metrics` を読む。
- `GET /api/dashboard/summary` … 同フィルタ（号機含む）の集計表データ（R4.1）。`daily_metrics`。
- `GET /api/dashboard/records` … 明細一覧（号機フィルタ可）。**app_db をキーセット（カーソル）ページング**（R4.2）。
- `GET /api/dashboard/threshold-overlay` … params: `metric,color_no,size,chain,tape,from,to`。
  日次の有効閾値系列を返す（R3）。内部で `ThresholdService.resolve_effective` を利用（**号機に依存しない**＝色レベル）。
- `GET /api/dashboard/machines` … 号機一覧（フィルタ選択肢。`エッジPC管理` の登録、または `daily_metrics.unit` から）。

## 明細のキーセットページング（R4.2）

- ソートキー兼カーソル: `(inspect_timestamp, image_id)`（一意・単調。app_db `annotation.image_base`）。
- レスポンスに `next_cursor` を含め、`limit` 件＋次カーソルを返す。OFFSET は使わない（`tech.md`）。

## 索引・性能（R7）

- **推移・集計**は ver2 `daily_metrics`（索引可・高速）。重い jsonb 集計は `日次集計基盤` が日次で済ませている。
- **明細**は app_db を**当日/期間パーティション**に絞ってオンザフライ（`inspect_timestamp` で日次パーティション化済み）。
  app_db は**変更しない**（索引追加不可）。明細は1画面ぶん（キーセット）に限定するため、全期間の重い集計は走らせない。

## バリデーション・エラー処理

- 期間未指定／終了 < 開始 → 422（Pydantic、R1.2）。
- 読み取り専用のため更新系エラーは無い。

## フロント構成 (`structure.md` 準拠)

- `frontend/src/api/dashboardApi.ts`（axios）、`frontend/src/hooks/`（TanStack Query フック）。
- `frontend/src/pages/Dashboard.tsx`：フィルタ（期間・色・**号機〔複数選択・既定 全号機〕**）、
  推移グラフ（**recharts**、閾値ラインを重ね描き）、集計表、明細一覧（**react-window** で仮想化）。
- KPI が NULL の点はグラフで欠損として扱う（線をつながない）。

## テスト設計 (Testing — 検証ゲートにマップ)

- **integration**（DB・conftest のトランザクション ROLLBACK）:
  - 集計: NG率／虚報率／見逃し率／スループットの算出、分母＝monochro 件数、monochro=0 単位の除外、
    フルタプル（tape 含む）での GROUP BY、ラベル0件単位は KPI=NULL、一部ラベルは 分子/monochro。
  - フィルタ: 期間・各色項目・**号機**での絞り込み（号機は集計前 WHERE・粒度に加えない・既定 全号機）。
  - 明細: キーセットページングの境界・next_cursor・安定順序。
- **integration**（`閾値管理` 連携）: 重ね描き系列が日次で解決される／期間内で閾値が変わると階段状／
  閾値なしの日は欠損。フルタプル未指定時は重ね描きしない。
- **api**（TestClient）: 各エンドポイントのステータス・系列形状・NULL 表現・認証ゲート。
- **frontend**（Vitest + Testing Library）: 系列描画・NULL 欠損・閾値ライン・表の仮想化・フィルタ送信。

## 依存・前提 (Dependencies)

- **`日次集計基盤`**（最重要）: 推移・集計は `daily_metrics` を読む。本機能は集計を行わない（基盤が日次で実施）。
  共有 `services/metrics.py`（件数→率）も基盤所有。
- **`閾値管理`**（`resolve_effective` 利用可能）であること。
- **実スキーマ（`schema-spec-mapping.md`）**: フルタプル＝`extra_info` の colorNo/size/chain/tape（**tape 含む**・確定）、
  日次＝`inspect_timestamp`（JST）、号機＝`unit`、明細は app_db `annotation.image_base`。
- **接続断ハンドリング**: 明細参照する app_db はライブのため、到達不能・接続断時もダッシュボードが致命的に落ちないこと。
  推移/集計は ver2 `daily_metrics` なので app_db 断でも表示できる。
- **テスト**: app_db 相当は dump 由来の固定スナップショットから立てる（`structure.md`）。

## 確定した設計判断 (Resolved)

- 推移・集計＝ver2 `daily_metrics`（`日次集計基盤`）。**明細のみ** app_db オンザフライ。
- `services/metrics.py` は `日次集計基盤` 所有。本機能は呼び出して使う。
- 明細カーソルは `(inspect_timestamp, image_id)`。app_db は変更しない（索引追加もしない）。
- フルタプルは **tape 含む**（`extra_info` jsonb）。号機フィルタは `daily_metrics.unit`（既定 全号機合算・表示専用）。
- 重ね描きは日次解決の階段系列（`daily_metrics` と閾値を Service 層で突合）。

## 画面デザイン刷新（2026-07-13 追記）

> 対象は**見た目のみ**（`ui-shell` の共通レイアウト・デザイントークンに乗せる）。API・Service・Repository・
> データモデルは無変更。参照 UI: `Shisui Dashboard (standalone).html`（ビジュアル参照。原則は
> `ui-spec-reconciliation.md` と同じ＝相違は UI を spec に合わせる）。

### モックアップとの相違・対応

モックアップには本 spec のデータで作れない要素（OK/NG 件数の実数チャート、ラベル入力率等の列）が
含まれるため、以下のように読み替える（brainstorming にて利用者承認済み）。

| モックアップの要素 | 対応 |
|---|---|
| 生産実績（OK/NG 件数）チャート | **スコープ外**。`throughput`（検査数）の日別チャートに置き換える |
| 日別 KPI 明細表（虚報率・見逃し率・ラベル入力率・ラベル数÷検査数） | **スコープ外**（`ラベル入力率`等は本 spec に無いデータ）。既存の画像単位の明細一覧（R4.2・仮想化）をそのまま残す |
| サイズ／チェーン／色番のドロップダウン選択 | **不採用**。候補一覧を返す API が無いため、既存の自由入力（テキスト）を維持し見た目のみ変更 |

### 追加するチャート構成（既存データのみ・API 追加なし）

3枠すべて **recharts**（既存依存）で実装する。

1. **検査数（スループット）日別チャート**: `GET /trends` の `throughput` を系列にした棒グラフ。
2. **NG率推移**: 既存の `ng_rate` 折れ線＋ `threshold-overlay`（`metric=ng_rate`）重ね描き（見た目のみ変更）。
3. **虚報率・見逃し率チャート**: `false_alarm_rate` と `miss_rate` の2系列折れ線＋各々の閾値重ね描き。
   `threshold-overlay` を `metric=false_alarm_rate` と `metric=miss_rate` でそれぞれ呼ぶ
   （エンドポイントは既存のまま `metric` を変えるだけ。バックエンド変更なし）。

### フロント構成の追加

- `frontend/src/pages/Dashboard.tsx` はモックアップのダーク配色・カード型 KPI サマリー・3チャートレイアウトに
  作り直す。`useThresholdOverlay` をチャート2・3それぞれで呼ぶ（フルタプルが一意に定まる場合のみ。R3.2 のまま）。
  フィルタ・明細一覧・API 呼び出しのロジックは無変更。
- スタイルは `ui-shell` の CSS Modules・デザイントークン（`tokens.css`）に合わせる。
