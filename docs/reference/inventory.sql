-- ============================================================
-- 業者検査 DB 棚卸しスクリプト (inspection DB inventory)
-- 対象: dump をインポートしたローカル DB（pgAdmin / psql で実行）
-- すべて読み取り専用。実行後、各セクションの結果を貼り戻してください。
-- 手順1→2（2-2 含む）はテーブル名を知らなくても動きます。手順3以降は手順2で判明した
-- テーブル名・列名を ★置換 箇所に入れて実行してください。
-- 検査結果まわり（手順3〜7）に加え、号機（手順9）も探索します。
-- ※ 取り込み管理の探索（手順2-2・手順8）は、取り込み状況可視化が**スコープ外（取り下げ）**となったため**任意/不要**。
-- ============================================================

-- ===== 0. 接続先の確認 =====
SELECT current_database() AS db, version();

-- ===== 1. テーブル一覧 + 概算行数（どのテーブルが大きいか） =====
SELECT n.nspname AS schema,
       c.relname  AS table_name,
       c.reltuples::bigint AS approx_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY c.reltuples DESC;

-- ===== 2. 重要カラムの所在を横断検索（★最重要：tape の有無もここで判明） =====
-- 論理概念（検査結果・画像マスタ・色分類・色マスター）に対応する列が
-- どのテーブルにあるかを、テーブル名を知らずに発見する。
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND (
        column_name ILIKE '%color%'    OR column_name ILIKE '%size%'
     OR column_name ILIKE '%chain%'    OR column_name ILIKE '%tape%'     -- ← tape の有無
     OR column_name ILIKE '%image%'    OR column_name ILIKE '%defect%'
     OR column_name ILIKE '%camera%'   OR column_name ILIKE '%judge%'
     OR column_name ILIKE '%inspect%'  OR column_name ILIKE '%datetime%'
     OR column_name ILIKE '%date%'     OR column_name ILIKE '%lab%'
     OR column_name ILIKE '%rgb%'      OR column_name ILIKE '%status%'
     OR column_name ILIKE '%lot%'
     OR column_name ILIKE '%machine%'  OR column_name ILIKE '%device%'   -- ↓ 号機(検査機台)
     OR column_name ILIKE '%unit%'     OR column_name ILIKE '%line%'
     OR column_name ILIKE '%equip%'    OR column_name ILIKE '%gouki%'
     OR column_name ILIKE '%file%'     OR column_name ILIKE '%import%'   -- ↓ 取り込み管理
     OR column_name ILIKE '%ingest%'   OR column_name ILIKE '%load%'
     OR column_name ILIKE '%error%'    OR column_name ILIKE '%count%'
  )
ORDER BY table_name, ordinal_position;

-- ===== 2-2. 取り込み管理テーブルの探索（テーブル名から・取り込み状況可視化 spec の I1） =====
-- ファイル単位の取り込み状態・件数・エラーが記録されたテーブルを、名前パターンで発見する。
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND (
        table_name ILIKE '%import%'  OR table_name ILIKE '%ingest%'
     OR table_name ILIKE '%load%'    OR table_name ILIKE '%file%'
     OR table_name ILIKE '%log%'     OR table_name ILIKE '%batch%'
  )
ORDER BY table_name;

-- ===== 3. 主要テーブルの全カラム（手順2で判明したテーブル名を入れる） =====
-- 検査結果テーブル
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = '★検査結果テーブル名'
ORDER BY ordinal_position;

-- 画像マスタ（camera_type を持つテーブル）
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = '★画像マスタテーブル名'
ORDER BY ordinal_position;

-- 色分類（defect_id を持つテーブル）
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = '★色分類テーブル名'
ORDER BY ordinal_position;

-- （任意）色マスター（color_no×size×chain×tape・色見本 RGB/Lab・ステータス）
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = '★色マスターテーブル名'
ORDER BY ordinal_position;

-- ===== 4. 既存索引（オンザフライ集計の実用性を左右） =====
-- 手順2/3 で判明したテーブル名を IN (...) に入れる。
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND tablename IN ('★検査結果テーブル名', '★画像マスタテーブル名', '★色分類テーブル名')
ORDER BY tablename, indexname;
-- 着目点: 検査結果テーブルの「日時列」「color 系」、結合キー「image_id」に索引があるか。

-- ===== 5. 値の意味（手順3で判明した列名を入れる） =====
-- judge 値（'OK'/'NG' を確認）
SELECT ★judge列, COUNT(*) FROM ★検査結果テーブル名 GROUP BY ★judge列 ORDER BY 2 DESC;

-- camera_type 値（'monochro'/'color' を確認）
SELECT ★camera列, COUNT(*) FROM ★画像マスタテーブル名 GROUP BY ★camera列 ORDER BY 2 DESC;

-- defect_id 値分布（9=正解OK / それ以外=正解NG / NULL=未入力 を確認）
SELECT ★defect列, COUNT(*) FROM ★色分類テーブル名 GROUP BY ★defect列 ORDER BY 2 DESC;

-- ===== 6. データ量・期間（検査結果テーブル。1e8 規模とオンザフライ可否の判断材料） =====
SELECT MIN(★日時列) AS min_dt,
       MAX(★日時列) AS max_dt,
       COUNT(*)     AS total_rows
FROM ★検査結果テーブル名;

-- ===== 7. （任意）tape の実値分布（tape 列が存在した場合のみ） =====
-- tape が「基本空白」かどうかを実データで確認する。
SELECT ★tape列, COUNT(*) FROM ★検査結果テーブル名 GROUP BY ★tape列 ORDER BY 2 DESC;

-- ===== 8. 取り込み管理テーブルの詳細（手順2/2-2 で判明したテーブル名を入れる・取り込み spec 用） =====
-- 全カラム（ファイル名・取り込み日時・状態・件数・エラーの持ち方を確認）
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = '★取り込み管理テーブル名'
ORDER BY ordinal_position;

-- 状態（status）値の分布（成功／失敗／処理中 等の区分を確認）
SELECT ★状態列, COUNT(*) FROM ★取り込み管理テーブル名 GROUP BY ★状態列 ORDER BY 2 DESC;

-- 取り込み日時の範囲・件数（期間フィルタ・一覧の母数）
SELECT MIN(★取り込み日時列) AS min_dt, MAX(★取り込み日時列) AS max_dt, COUNT(*) AS total_rows
FROM ★取り込み管理テーブル名;

-- 直近の数件（ファイル名・状態・件数・エラーの持ち方を目視確認）
SELECT * FROM ★取り込み管理テーブル名 ORDER BY ★取り込み日時列 DESC LIMIT 20;

-- （エラー明細が別テーブルの場合）エラー関連テーブルの探索
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND (table_name ILIKE '%error%' OR table_name ILIKE '%reject%' OR table_name ILIKE '%fail%')
ORDER BY table_name;

-- ===== 9. 号機（検査機台）列の確認（ダッシュボードの号機フィルタ R1.3 用） =====
-- 手順2 で見つかった「号機/機台」候補列を ★ に入れ、値の分布を確認する（1〜4号機 等が出るはず）。
SELECT ★号機列, COUNT(*) FROM ★検査結果テーブル名 GROUP BY ★号機列 ORDER BY 1;
