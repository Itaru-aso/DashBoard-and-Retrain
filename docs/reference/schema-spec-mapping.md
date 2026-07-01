# 実スキーマ ↔ spec マッピング（棚卸し結果）

> 対象 DB: `app_db`（本番・アノテーション/AI プラットフォーム）／ dump: `app_db_20260629_152011.dump`
> 目的: 実スキーマと spec（ダッシュボード・閾値・保守タスク・色・再学習）の対応を確定し、各 spec を実スキーマ準拠へ更新する基準とする。

## DB 構成（モデルB の実体）

- **① app_db（読み取り専用・`get_inspection_db`）**: 検査・注釈の本番 DB。スキーマ `admin`・`annotation`。
  **ver2 は索引を張れない**（式インデックス不可）。検査結果の参照元はここ。
- **② ver2 DB（自前・RW・Alembic・`get_db`）**: 閾値・保守タスク・色マスター・エッジPC・再学習ジョブ
  ＋**日次集計テーブル**（後述）を持つ。
- 越境結合はしない。app_db 内の結合（image_base × annotation_item × dataset_category_item）は app_db で完結し、
  閾値だけ ver2 DB から重ねる。

## 主要テーブル（app_db）

- `annotation.image_base`（**inspect_timestamp で日次パーティション**）: `image_id`・`image_path`・
  `inspect_timestamp`・`unit`（号機）・`camera_model`・`judgment_result`（判定 0/1）・`judgment_category`・
  `lot_no`・`extra_info`(jsonb)・`model_info`。
- `annotation.annotation_item`: `image_id`・`dataset_id`・`item_id`・`gray`・`use_flg`（**学習対象フラグ**）。
- `admin.dataset_category_item`: `dataset_id`・`item_id`・`category_label_name`・`on_class`（**0=正解OK / 1=正解NG**）・`output_id`。
- `annotation.image_score`: `image_id`・`model_id`・`model_version`・`model_name`・`score_value`・`threshold`。

## 同一性・粒度

- **フルタプル**＝`image_base.extra_info` の **`colorNo`／`size`／`chain`／`tape`**（jsonb 抽出。`extra_info->>'colorNo'` 等）。
  例: `colorNo=501, size=05, chain=CZT8, tape=GHI789841`。
- **JST 日次**＝`inspect_timestamp::date`（**JST 保存**・そのまま丸め）。
- **号機**＝`image_base.unit`（ネイティブ列）。

## メトリクス対応

- **monochro（本検査・分母）**＝`camera_model = 'camera1_image'`（`camera2_image` は color）。
- **AI 判定（judge）**＝`judgment_result`（**0:OK / 1:NG**。ネイティブ列）。
- **正解（ground truth）**＝注釈から導出: `image_id` → `annotation_item.item_id` → `dataset_category_item.on_class`。
  集約規則: **`on_class='1'` が1つでもあれば正解NG／注釈ありで全て `'0'` なら正解OK／注釈なしは正解なし**。
  **`use_flg` では絞らない**（`use_flg` は学習対象フラグでありメトリクスの母集団ではない）。
- **注釈なし画像**は虚報率/見逃し率の判定から**外す**（その日 注釈ありが0件なら両率は **NULL**）。

### 件数（集計単位＝JST日 × フルタプル × 号機）
> **規約**: 3指標とも**分子は全カメラ**（monochro＋color 両方を数える）・**分母は monochro 件数**（camera1_image）。原典 `calculate_ngrate_KPI.md` 準拠。
- `monochro_count` = COUNT(`camera_model='camera1_image'`)
- `ng_count`       = COUNT(`judgment_result=1`)（全カメラ）
- `fp_num`（虚報） = COUNT(`judgment_result=1` AND 正解=OK)
- `miss_num`（見逃し）= COUNT(`judgment_result=0` AND 正解=NG)
- `annotated_count`= COUNT(正解 IS NOT NULL)

### 率（読み出し時に算出・分母は monochro_count）
- `NG率` = `ng_count / monochro_count`
- `虚報率` = `annotated_count==0 ? NULL : fp_num / monochro_count`
- `見逃し率` = `annotated_count==0 ? NULL : miss_num / monochro_count`
- `スループット` = `monochro_count`
- monochro_count=0 の単位は除外。

### 集計クエリ骨子（app_db・当日パーティション）
```sql
SELECT
  ib.inspect_timestamp::date AS jst_date,
  ib.extra_info->>'colorNo' AS color_no, ib.extra_info->>'size' AS size,
  ib.extra_info->>'chain'  AS chain,    ib.extra_info->>'tape' AS tape,
  ib.unit AS unit,
  COUNT(*) FILTER (WHERE ib.camera_model='camera1_image')          AS monochro_count,
  COUNT(*) FILTER (WHERE ib.judgment_result=1)                     AS ng_count,
  COUNT(*) FILTER (WHERE ib.judgment_result=1 AND ans.correct='0') AS fp_num,
  COUNT(*) FILTER (WHERE ib.judgment_result=0 AND ans.correct='1') AS miss_num,
  COUNT(*) FILTER (WHERE ans.correct IS NOT NULL)                  AS annotated_count
FROM annotation.image_base ib
LEFT JOIN LATERAL (
  SELECT MAX(dci.on_class) AS correct   -- '1'が1つでもNG／全'0'でOK／無ければNULL
  FROM annotation.annotation_item ai
  JOIN admin.dataset_category_item dci
    ON dci.dataset_id=ai.dataset_id AND dci.item_id=ai.item_id
  WHERE ai.image_id = ib.image_id       -- use_flg では絞らない
) ans ON true
WHERE ib.inspect_timestamp >= DATE '<日>' AND ib.inspect_timestamp < DATE '<翌日>'
GROUP BY 1,2,3,4,5,6;
```

## 集計戦略（ver2 日次集計テーブル）

- **app_db に索引を張れず・フルタプルが jsonb** のため、巨大テーブルへの任意期間オンザフライ集計は不可。
- **日次スケジューラ**が各日パーティションを上記クエリで集計し、**ver2 DB の日次集計テーブル**へ
  `(jst_date, color_no, size, chain, tape, unit, monochro_count, ng_count, fp_num, miss_num, annotated_count)` を書き出す。過去分はバックフィル。
- **ダッシュボードの推移/集計・逸脱判定・色昇格**は **ver2 集計テーブル**を読む（索引可・高速）。
  号機フィルタは `unit` で絞る（既定 全号機合算）。**明細表示のみ** app_db を当日パーティションでオンザフライ（キーセット）。

## モデル情報（再学習・モデル平台）

- `image_base.extra_info`: `model_id`・`model_name`・`model_version`・onnx パス（例 `501_color_model.onnx`）。
- `image_score`: `model_id`・`model_version`・`score_value`・`threshold`。

## 影響を受ける spec と更新方針

- **tech.md**: モデルB の実体（app_db＝読み取り専用・索引不可）・**日次集計テーブル方式**・jsonb 同一性を明記。
- **検査結果ダッシュボード**: 集計元を ver2 日次集計テーブルへ。実列マッピング（jsonb 抽出・camera1_image・judgment_result・
  正解アノテーション結合）。号機＝unit。明細のみ app_db。
- **保守タスク（逸脱判定）／色ライフサイクル（昇格）**: 同集計テーブルを号機合算で読む。
- **取り込み状況の可視化**: 後述（未解決）。

## 残課題

- **取り込み管理（ingestion I1）**: app_db に `import`/`ingest` 等のテーブルは**見当たらなかった**。
  ファイル単位の取り込み状態・件数・エラーの所在は**未解決**（別システム/ログの可能性）。取り込み spec の design は保留継続。
- 集計テーブルのバックフィル範囲・スケジュール時刻（既存 `BREACH_EVAL_*` と整合）。
- `lot_no` は存在するが**不使用**（日次×フルタプルに統一）。
