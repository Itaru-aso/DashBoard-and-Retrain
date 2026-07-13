# 検査結果ダッシュボード — Tasks

> spec: `検査結果ダッシュボード (inspection-results-dashboard)`
> 配置想定: `.kiro/specs/inspection-results-dashboard/tasks.md`
> 上流: `requirements.md`（R1–R7）・`design.md` ／ 規約: `tech.md`（TDD・検証ゲート・2 DB）, `structure.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: vitest・tsc・eslint）が全グリーン。
> コミットは Conventional Commits（例: `feat(dashboard): ...`）。本機能は read-only・**新規テーブルを作らない**。

## 前提 (Preconditions)

- **棚卸し完了（必須・着手前）**: `inventory.sql` を実行し、
  ① tape の有無（無ければ集計粒度を `color_no×size×chain` にし `閾値管理` も揃える）、
  ② 論理名→実テーブル/列名のマッピング（検査結果・画像マスタ・色分類）、
  ③ 既存索引（検査結果の日時列・color 系・image_id）、
  ④ **号機（検査機台）の識別列**の有無（号機フィルタ R1.3 の前提）、を確定しておく。
- **2エンジン基盤**: `database.py` の業者検査 DB 用（読み取り専用 `get_inspection_db`）＋ ver2 DB 用が整備済み
  （未了なら「基盤整備」または下記タスク1で用意）。
- **`閾値管理` 実装済み**: `ThresholdService.resolve_effective` が利用可能。

---

## タスク (Tasks)

- [x] **1. 業者検査 DB 接続・読み取り専用モデル**（基盤整備で未了の場合）
  - `database.py` に業者エンジン/セッション（**読み取り専用**）＋ `get_inspection_db`、接続断ハンドリング。
  - `src/models/external/` に検査結果・画像マスタ・色分類の**読み取り専用モデル**（棚卸しの実スキーマから・Alembic 対象外）。
  - テスト（integration / 業者 DB スナップショット）: 業者エンジンで読める／接続断時に致命的に落ちない。
  - Refs: `tech.md` 2エンジン ／ commit: `feat(dashboard): add inspection DB engine and read-only models`

- [x] **2. Repository: 集計クエリ + 明細クエリ**
  - `src/repositories/inspection_result_repository.py`（業者エンジン・読み取り専用）:
    - 集計: 期間・色・**号機（任意・複数可・既定 全号機）**で絞り `日次 × color_no × size × chain (× tape)` で
      `monochro_count` / `ng_count` / `fp_num` / `miss_num` / `label_count` を取得（`HAVING monochro_count > 0`）。
      **号機は集計前 WHERE（GROUP BY に含めない）**。号機一覧の取得も用意。
    - 明細: キーセットページング（カーソル `(inspection_datetime, image_id)`・`next_cursor`）。
  - テスト（integration）: 件数集計の正しさ、monochro=0 除外、フィルタ（色・**号機**）、
    キーセット境界・next_cursor・安定順序、（tape あり時）フルタプル粒度。
  - Refs: R1, R2, R4, R7 ／ commit: `feat(dashboard): add inspection result aggregation & detail queries`

- [x] **3. 率算出（共有 `services/metrics.py`）・NULL 判定・重ね描き突合**
  - `src/services/metrics.py`（**共有**：`保守タスク`／`色ライフサイクル` と共通）: 件数→率算出
    （`NG率`・`スループット`、KPI は `label_count==0 → NULL`・monochro 分母・monochro=0 除外）。
  - `src/services/dashboard_service.py`: `metrics.py` で率算出し、重ね描きは範囲内の各日について
    `ThresholdService.resolve_effective(metric, fulltuple, day)` を解決し **Service 層で突合**（越境結合なし）。
    閾値なしの日は欠損。フルタプル未指定時は重ね描きしない。
  - テスト（integration）: 率算出／KPI=NULL／monochro=0 除外／重ね描きの日次解決・階段・欠損・フルタプル条件。
  - Refs: R2, R3, R5 ／ commit: `feat(dashboard): add shared metrics and dashboard service`

- [x] **4. Pydantic スキーマ**
  - `src/schemas/dashboard.py`: フィルタ（期間必須・色任意・**号機任意/複数**）／系列／明細の入出力。期間未指定・終了<開始 → 422。
  - テスト（unit）: バリデーションの正常／異常。
  - Refs: R1, R6 ／ commit: `feat(dashboard): add dashboard schemas`

- [x] **5. API: エンドポイント + ルーター登録**
  - `src/api/dashboard_endpoint.py`（`main.py` 登録）:
    `GET /api/dashboard/trends`（`machine_ids?` 含む）・`/summary`・`/records`（キーセット）・`/threshold-overlay`・`/machines`（号機一覧）。
    検査結果参照は `get_inspection_db`、閾値解決は `ThresholdService`。Basic 認証ゲート。
  - テスト（api / TestClient）: ステータス・系列形状・NULL 表現・**号機フィルタ**・認証ゲート・業者 DB 接続断時の挙動。
  - Refs: R1–R7 ／ commit: `feat(dashboard): add dashboard API endpoints`

- [x] **6. フロント: ダッシュボード画面**
  - `frontend/src/api/dashboardApi.ts`、TanStack Query フック（`frontend/src/hooks/`）、
    `frontend/src/pages/Dashboard.tsx`：フィルタ（期間・色・**号機〔複数選択・既定 全号機〕**）、推移グラフ（**recharts**・閾値ライン重ね描き）、集計表、
    明細一覧（**react-window** 仮想化）。KPI が NULL の点は欠損として描画（線をつながない）。
  - テスト（Vitest + Testing Library）: 系列描画・NULL 欠損・閾値ライン・表の仮想化・フィルタ送信。
  - Refs: R2, R3, R4 ／ commit: `feat(dashboard): add dashboard screen`

- [x] **7. 仕上げ: 検証ゲート確認**
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc --noEmit`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(dashboard): satisfy verification gate`

- [ ] **8. フロント: 画面デザイン刷新（`ui-shell` 準拠・見た目のみ）**
  - `design.md`「画面デザイン刷新」節に従い `Dashboard.tsx` を作り直す。
    - フィルタバー・KPIサマリーカード・3チャート（検査数日別／NG率推移／虚報率・見逃し率）・明細一覧を
      `ui-shell` のデザイントークン・CSS Modules でダーク基調に統一。
    - チャートは既存の `recharts` のみ使用（新規ライブラリ追加なし）。
    - フィルタ入力（自由入力）・明細一覧のロジック・API呼び出しは無変更。
  - テスト（Vitest + Testing Library）: 既存テストを維持しつつ、虚報率・見逃し率チャートの閾値重ね描き
    （`metric=false_alarm_rate`/`metric=miss_rate` の呼び出し）を追加検証。
  - 代替検証: `npm run dev`（バックエンド接続）で実データ表示を目視確認。
  - Refs: R2, R3, R4 ／ commit: `feat(dashboard): restyle dashboard screen with ui-shell design`

---

## トレーサビリティ (Requirements ↔ Tasks)

- R1（フィルタ）→ 2, 4, 5, 6
- R2（推移）→ 2, 3, 5, 6, 8
- R3（閾値重ね描き）→ 3, 5, 6, 8
- R4（集計表・明細／キーセット）→ 2, 5, 6, 8
- R5（対象範囲・KPI ゲート）→ 3
- R6（read-only・認証）→ 4, 5
- R7（性能・オンザフライ）→ 1, 2, 5
