# 日次集計基盤 — Requirements

> spec: `日次集計基盤 (daily-aggregation)`
> 配置想定: `.kiro/specs/daily-aggregation/requirements.md`
> 前提: `schema-spec-mapping.md`（実スキーマ対応）／ steering: `product.md`・`tech.md`・`structure.md`
> 依存される spec: `検査結果ダッシュボード`・`保守タスク自動生成`・`色マスター/ライフサイクル`（いずれも本基盤の集計を読む）

## 概要 (Introduction)

検査結果（app_db）から **JST日 × フルタプル × 号機** の件数を**日次で ver2 DB に集計**し、
ダッシュボード・逸脱判定・色昇格が共通で読めるようにする。app_db は**読み取り専用・索引を張れず**、
フルタプルが **`extra_info`(jsonb)** にあるため、巨大テーブルへの任意期間オンザフライ集計は非現実的。
そこで**日次スケジューラで集計を ver2 に貯め**、消費側はそれを読む（明細表示のみ app_db をオンザフライ参照）。
件数→率の算出は**共有モジュール `services/metrics.py`** に集約する。

### スコープ (In Scope)
- ver2 DB の**日次集計テーブル**（件数を保持）。
- **日次集計ジョブ**（app_db を読み、集計を upsert・冪等）＋**バックフィル**。
- **再集計**（後追いで付くアノテーションを反映するため直近期間を毎日再集計）。
- **共有メトリクス算出** `services/metrics.py`（件数→率・NULL 判定・monochro=0 除外）。
- 消費側が読む**集計参照リポジトリ**（期間・フルタプル・号機）。

### スコープ外 (Out of Scope)
- 各画面の表示・逸脱判定・昇格そのもの（各 spec が本基盤を読む）。
- 明細表示（app_db オンザフライ。ダッシュボード spec 側）。

### 用語・前提（`schema-spec-mapping.md` 準拠）
- フルタプル＝`image_base.extra_info`→`colorNo`/`size`/`chain`/`tape`。日次＝`inspect_timestamp::date`（JST）。号機＝`unit`。
- monochro＝`camera_model='camera1_image'`。AI 判定＝`judgment_result`（0:OK/1:NG）。
- 正解＝`image_id`→`annotation_item`→`dataset_category_item.on_class`（**1つでもNGならNG／全OKならOK／アノテーションなしはなし**・**use_flg では絞らない**）。
- 件数の規約: **分子は全カメラ・分母は monochro**（原典準拠）。

---

## 要件 (Requirements)

### A-R1. 日次集計テーブル（ver2 DB）
**受け入れ基準 (EARS)**
1. **JST日 × `color_no` × `size` × `chain` × `tape` × `unit`** を単位に、件数を保持する（SHALL）。
2. 保持件数: `monochro_count`・`ng_count`・`fp_num`（虚報）・`miss_num`（見逃し）・`annotated_count`（正解あり）（SHALL）。
3. 集計単位はユニーク（同単位は1行・upsert）（SHALL）。

### A-R2. 日次集計ジョブ
**受け入れ基準 (EARS)**
1. アプリ内スケジューラが日次で、対象日の app_db パーティションを集計し、A-R1 のテーブルへ upsert する（SHALL）。
2. ジョブは**冪等**（同じ日を再実行しても結果が一意・重複しない）（SHALL）。
3. app_db は**読み取り専用**で参照し、結合は app_db 内で完結する（越境結合しない。`get_inspection_db`/`get_db` の2エンジン）（SHALL）。

### A-R3. 再集計（後追いアノテーションの反映）
**受け入れ基準 (EARS)**
1. 正解（アノテーション）は検査後に付くため、**直近 7 日（最大遅延＝約1週間）を毎日再集計**して件数を更新する（SHALL）。
2. 日数は環境変数 `AGG_WINDOW_DAYS`（**既定 7**）で持つ。これは**アノテーションが付き終わる遅延**に基づくもので、
   逸脱判定の走査ウィンドウとは**別概念**（独立に持つ）（SHALL）。

### A-R4. バックフィル
**受け入れ基準 (EARS)**
1. 指定期間（または全期間）を一括集計できる（初期構築・復旧用）（SHALL）。

### A-R5. 共有メトリクス算出（`services/metrics.py`）
**受け入れ基準 (EARS)**
1. 件数から率を算出する: `NG率=ng/monochro`・`虚報率=annotated==0?NULL:fp/monochro`・
   `見逃し率=annotated==0?NULL:miss/monochro`・`スループット=monochro`（SHALL）。
2. `monochro_count=0` の単位は除外する（SHALL）。
3. 本モジュールを**ダッシュボード・保守タスク・色ライフサイクルが共有**する（SHALL）。

### A-R6. 集計参照リポジトリ
**受け入れ基準 (EARS)**
1. 消費側が **期間・フルタプル・号機**で集計を読める（SHALL）。
2. **号機合算**の読み出しを提供する（逸脱判定・昇格は全号機合算で評価。号機フィルタはダッシュボード表示のみ）（SHALL）。

---

## 確定方針・残課題 (Resolved & Open)

確定:
- 集計単位に **`tape` を含む**（フルタプル。空文字も値として保持）。
- `services/metrics.py` は**本基盤が所有**（ダッシュボードから移管）。消費側は read リポジトリ＋ metrics.py を使う。
- app_db 読み取り専用・索引不可のため **ver2 集計テーブル方式**（明細のみ app_db オンザフライ）。
- **再集計ウィンドウ＝7日**（`AGG_WINDOW_DAYS` 既定 7。アノテーション遅延 最大約1週間に基づく・逸脱判定ウィンドウとは独立）。
- **実行時刻**: 日次スケジューラで毎日 JST 早朝に、直近7日（前日確定ぶん含む）を再集計（`AGG_RUN_TIME` 等で設定）。
