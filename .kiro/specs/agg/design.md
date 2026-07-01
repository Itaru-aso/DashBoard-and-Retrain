# 日次集計基盤 — Design

> spec: `日次集計基盤 (daily-aggregation)`
> 配置想定: `.kiro/specs/daily-aggregation/design.md`
> 上流: `requirements.md`（A-R1〜A-R6・確定）／ 基準: `schema-spec-mapping.md` ／ steering: `tech.md`・`structure.md`
> 依存される spec: `検査結果ダッシュボード`・`保守タスク自動生成`・`色マスター/ライフサイクル`

## 概要・方針 (Overview)

app_db（読み取り専用・索引不可・フルタプルは jsonb）から **JST日 × フルタプル × 号機** の件数を**日次で集計**し、
**ver2 DB の `daily_metrics`** に貯める。アノテーションが後追いで付くため**直近7日を毎日再集計**する。
件数→率は**共有 `services/metrics.py`**。消費側（ダッシュボード/逸脱判定/色昇格）はこの集計を読む。
**2エンジン（`get_inspection_db` 読み取り／`get_db` 書き込み）・越境結合なし**（app_db 内の結合のみ）。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/daily_metrics.py` … `daily_metrics`（ver2・Alembic）
- `src/repositories/daily_metrics_repository.py` … upsert（日単位）・読み出し（期間/タプル/号機）・**号機合算**読み出し
- `src/services/aggregation_service.py` … app_db 集計（`get_inspection_db`）→ `daily_metrics` 書き込み（`get_db`）・再集計・バックフィル
- `src/services/metrics.py` … **共有メトリクス算出**（件数→率・NULL 判定・monochro=0 除外）
- `src/jobs/aggregation_job.py` … 日次スケジューラ（JST 早朝・直近7日を再集計・冪等）
- `src/api/aggregation_endpoint.py` … 集計トリガー（テスト・バックフィル用）
- `src/schemas/aggregation.py`、`alembic/versions/<rev>_create_daily_metrics.py`

## データモデル (Data Model — ver2 DB)

**daily_metrics**
- `id`（PK）
- `jst_date`（date）・`color_no`・`size`・`chain`・`tape`（フルタプル。`tape` は空文字も保持）・`unit`（号機）
- `monochro_count`・`ng_count`・`fp_num`・`miss_num`・`annotated_count`（整数）
- `computed_at`（timestamptz）
- **ユニーク**: `(jst_date, color_no, size, chain, tape, unit)`

## 集計 (A-R2 / A-R3 / A-R4 — `aggregation_service`)

- `aggregate_day(jst_date)`:
  1. `get_inspection_db` で **app_db の当日パーティション**を集計（下記クエリ）。結果（タプル×号機ごとの件数）をメモリに取得。
  2. `get_db` で `daily_metrics` の当日分を **delete → insert**（同一トランザクション）。**冪等**（再実行で一意・重複なし。
     消えたタプルも残さない）。
- `aggregate_window(n=AGG_WINDOW_DAYS=7)`: 直近 n 日について `aggregate_day` を実行（後追いアノテーション反映。A-R3）。
- `backfill(from, to)`: 期間を日ごとに `aggregate_day`（初期構築・復旧。A-R4）。
- **越境結合なし**: app_db 側の結合（image_base × annotation_item × dataset_category_item）は app_db 内で完結。
  ver2 への書き込みは別セッション。SQL を跨いだ結合はしない。

### 集計クエリ（app_db・1日パーティション）
アノテーションの正解は **`image_id` 単位に集約**してから `image_base` に LEFT JOIN（当日分にスコープ）:
```sql
WITH ann AS (   -- 当日画像の正解: '1'が1つでもNG / 全'0'でOK / 無ければNULL（use_flg では絞らない）
  SELECT ai.image_id, MAX(dci.on_class) AS correct
  FROM annotation.annotation_item ai
  JOIN admin.dataset_category_item dci
    ON dci.dataset_id = ai.dataset_id AND dci.item_id = ai.item_id
  WHERE ai.image_id IN (SELECT image_id FROM annotation.image_base
                        WHERE inspect_timestamp >= :d AND inspect_timestamp < :d1)
  GROUP BY ai.image_id
)
SELECT
  ib.extra_info->>'colorNo' AS color_no, ib.extra_info->>'size' AS size,
  ib.extra_info->>'chain'  AS chain,    ib.extra_info->>'tape' AS tape,
  ib.unit AS unit,
  COUNT(*) FILTER (WHERE ib.camera_model='camera1_image')              AS monochro_count,
  COUNT(*) FILTER (WHERE ib.judgment_result=1)                         AS ng_count,        -- 全カメラ
  COUNT(*) FILTER (WHERE ib.judgment_result=1 AND a.correct='0')       AS fp_num,          -- 虚報(全カメラ)
  COUNT(*) FILTER (WHERE ib.judgment_result=0 AND a.correct='1')       AS miss_num,        -- 見逃し(全カメラ)
  COUNT(*) FILTER (WHERE a.correct IS NOT NULL)                        AS annotated_count
FROM annotation.image_base ib
LEFT JOIN ann a ON a.image_id = ib.image_id
WHERE ib.inspect_timestamp >= :d AND ib.inspect_timestamp < :d1   -- :d=対象JST日, :d1=翌日
GROUP BY 1,2,3,4,5;
```
> 分子は全カメラ・分母は monochro（`schema-spec-mapping.md` 準拠）。`jst_date` は呼び出し側（`:d`）で確定。

## 共有メトリクス (A-R5 — `services/metrics.py`)

- `compute_rates(counts)` → `{throughput, ng_rate, false_alarm_rate, miss_rate}`:
  - `throughput = monochro_count`
  - `ng_rate = ng_count / monochro_count`
  - `false_alarm_rate = annotated_count==0 ? NULL : fp_num / monochro_count`
  - `miss_rate = annotated_count==0 ? NULL : miss_num / monochro_count`
  - `monochro_count==0` は除外（呼び出し側で集計単位ごとに適用）。
- **ダッシュボード・保守タスク・色ライフサイクルが共有**。

## 集計参照 (A-R6 — `daily_metrics_repository`)

- `read(from, to, color_no?, size?, chain?, tape?, unit_ids?)`: 期間・フルタプル・号機で `daily_metrics` を読む（ダッシュボード）。
- `read_unit_aggregated(from, to, color_no, size, chain, tape)`: **号機合算**（unit を畳んで件数合算）。
  逸脱判定・色昇格は全号機合算で評価（号機フィルタはダッシュボード表示のみ）。
- 率は呼び出し側で `metrics.py` を通して算出（リポジトリは件数を返す）。

## スケジューラ (A-R2 / A-R3 — `aggregation_job`)

- アプリ内スケジューラで **毎日 JST 早朝**（`AGG_RUN_TIME`）に `aggregate_window(AGG_WINDOW_DAYS)` を実行。冪等。
- 既存の逸脱判定・色ライフサイクルの日次ジョブと同じスケジューラ基盤に載る。**集計 → 逸脱判定 → 昇格**の順で動かす
  （集計が当日分を更新してから判定・昇格が読む）。

## API（テスト・運用補助）

- `POST /api/aggregation/run` … params: `date`（単日）または `from,to`（バックフィル）。手動集計トリガー。Basic 認証。

## env / config

- `AGG_WINDOW_DAYS`（既定 7）・`AGG_RUN_TIME`。`get_inspection_db`（app_db 読み取り）／`get_db`（ver2 書き込み）。

## テスト設計 (Testing)

- **integration（2-DB）**: `aggregate_day` の件数正しさ（monochro 分母・全カメラ分子・正解集約 MAX(on_class)・use_flg 無視・
  アノテーションなし→annotated_count 除外）、冪等（同日2回で重複なし・delete→insert）、再集計で後追いアノテーション反映、
  バックフィル、号機合算読み出し。
- **unit**: `metrics.py`（率・NULL〔annotated=0〕・monochro=0 除外）。
- **api**: `run`（単日/期間）・認証。

## 依存・前提 (Dependencies)

- `基盤整備`（2エンジン・スケジューラ・ver2 DB・Alembic）。
- app_db スキーマ（`schema-spec-mapping.md`）。読み取り専用・索引不可。
- 消費: `検査結果ダッシュボード`・`保守タスク`・`色ライフサイクル`（本基盤の read＋`metrics.py` を使う）。

## 確認したい設計判断 (Design Decisions to Confirm)

1. **冪等化**: 対象日を **delete → insert**（トランザクション）でよいか（消えたタプルも残さない）。
2. **キー**: `(jst_date, color_no, size, chain, tape, unit)` ユニーク・`tape` 空文字保持でよいか。
3. **正解の集約**: `image_id` 単位に `MAX(on_class)`（'1'優先）で集約 → `image_base` に LEFT JOIN（当日スコープ）でよいか。
4. **ジョブ順序**: 日次で **集計 → 逸脱判定 → 昇格** の順に動かす前提でよいか。
