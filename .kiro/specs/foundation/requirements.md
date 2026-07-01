# 基盤整備 — Requirements

> spec: `基盤整備 (foundation)`  ── すべての機能 spec が前提にする「spec 0」
> 配置想定: `.kiro/specs/foundation/requirements.md`
> 前提 steering: `tech.md`（技術スタック・2 DB・スケジューラ・コンテナ）, `structure.md`（配置・命名・テスト配線）
> 依存される spec: `閾値管理` / `検査結果ダッシュボード` / `保守タスク自動生成・管理`（各 tasks の前提）

## 概要 (Introduction)

機能実装の土台を用意する。プロジェクト雛形、2エンジンの DB 接続、ver2 DB の Alembic、認証ゲート、
アプリ内スケジューラ基盤、設定・ロギング、テスト配線、アプリ骨格、コンテナ構成 ── これらを
`tech.md`／`structure.md` の確定事項どおりに整備し、各機能 spec が「前提」として乗れる状態にする。
ユーザ向け機能（具体テーブル・画面・エンドポイント）は含まない。

### スコープ (In Scope)
- 設定 / ロギング / 2エンジン DB 接続 / ver2 Alembic / 業者外部モデル基盤 / 認証ゲート /
  スケジューラ基盤 / アプリ骨格 / テスト配線 / フロント骨格 / コンテナ・ビルド一式。

### スコープ外 (Out of Scope)
- 機能固有のテーブル・モデル・エンドポイント・画面・定期ジョブ本体（各機能 spec）。
- 業者検査 DB の**具体スキーマに対応する外部モデルの完成**（棚卸し依存。本 spec は**接続とパターン**を用意）。

---

## 要件 (Requirements)

### F1. 設定 (Settings)
1. `pydantic-settings` で `.env` から設定を読み込む（`config.py`）。必須未設定は**起動時に明確に失敗**する（SHALL）。
2. 接続 URL を2系統（`DATABASE_URL`=ver2／`INSPECTION_DATABASE_URL`=業者・読み取り専用）保持する（SHALL）。
3. その他 env（`DEBUG`/`ENVIRONMENT`/認証/`LOG_LEVEL`/`TRAINING_*`/`BREACH_EVAL_*`）を保持する（SHALL）。

### F2. 2エンジン DB 接続 (Dual Engine)
1. SQLAlchemy エンジン/セッションを2系統用意する: `get_db`（ver2・読み書き）と `get_inspection_db`（業者・**読み取り専用**）（SHALL）。
2. セッションはリクエスト単位（ver2 は正常時 commit／例外時 rollback／finally close）（SHALL）。
3. 業者 DB はライブ・リモートのため、**到達不能・接続断時もアプリが致命的に落ちない**（SHALL）。

### F3. ver2 DB マイグレーション (Alembic)
1. Alembic を **ver2 DB のみ**を対象に設定する（`alembic.ini`・`alembic/`。業者 DB は対象外）（SHALL）。
2. **空の初期マイグレーション（ベースライン）**を起点に置く。テーブル追加は各機能 spec が積む（SHALL）。
3. `alembic upgrade` が通り、テスト DB のスキーマは **migration を正**とする（SHALL）。

### F4. 業者検査 DB 読み取り専用モデル基盤 (External Models)
1. `models/external/` を**読み取り専用・Alembic 対象外**として用意する（SHALL）。
2. 実スキーマから**手書きの読み取り専用モデル**を起こす（型・列を明示。Alembic 対象外）。具体モデルは棚卸し後（各機能）。

### F5. 認証ゲート (Auth)
1. Basic 認証の依存を用意し、API に適用できる（**ロール制御なし**・**単一共有クレデンシャル**）（SHALL）。
2. `ENABLE_BASIC_AUTH` で有効/無効を切り替えられる（SHALL）。

### F6. アプリ内スケジューラ基盤 (Scheduler)
1. `main.py` 起動時にアプリ内スケジューラ（**APScheduler**）を開始し、`src/jobs/` のジョブを登録できる基盤を用意する（SHALL）。
2. **単一ワーカ所有**を前提とし、`*_ENABLED` で無効化できる（SHALL）。ジョブ本体は各機能 spec が追加する。

### F7. アプリ骨格 (App Skeleton)
1. FastAPI アプリを生成し、ルーター登録の仕組みと `/health` を持つ。`/health` は **ver2 DB の疎通（必須）** と
   **業者 DB の疎通（参考・失敗は致命としない）** を確認する（SHALL。F2.3 と整合）。
2. `ENVIRONMENT=production` でフロントの `dist/` を配信（SPA フォールバック）、開発は `/api` プロキシで動く（SHALL）。

### F8. ロギング (Logging)
1. `LOG_LEVEL` で制御できる共通ロガーを用意する（形式は**プレーン**。逸脱判定の WARN 等で使用）（SHALL）。

### F9. テスト配線 (Test Wiring)
1. `pytest` マーカー（`unit`/`integration`/`api`）とカバレッジ設定を用意する（SHALL）。
2. `conftest.py` が **ver2 テスト DB**（トランザクション ROLLBACK・migration を正）の fixture を提供する（SHALL）。
3. **業者検査 DB 相当**を **dump 由来のスナップショット**から立てる fixture を提供する（ライブは再現不可）（SHALL）。

### F10. フロント骨格 (Frontend Skeleton)
1. React + Vite + TS の雛形、axios クライアント、TanStack Query プロバイダ、ルーティング、`build → dist` を用意する（SHALL）。

### F11. コンテナ・ビルド (Container & Build)
1. **ver2 バックエンド**の `Dockerfile`（API＋スケジューラ＋再学習・GPU 対応・単一インスタンス）を用意する（SHALL）。
2. `docker-compose`（dev: ver2 バックエンド＋ver2 DB〔独立・ボリューム〕＋業者 DB 代役〔dump〕）を用意する（SHALL）。
3. `black`/`flake8`/`mypy`/`pytest`、front の `tsc`/`eslint`/`vitest` を設定する（`tech.md` 検証ゲート）（SHALL）。

---

## 確定事項 (Resolved)

- Q1 業者外部モデル＝**手書きの読み取り専用モデル**（型・列を明示・Alembic 対象外）。
- Q2 Alembic＝**空のベースライン**（テーブル追加は各機能 spec）。
- Q3 `/health`＝**ver2 DB（必須）＋業者 DB（参考・非致命）**の疎通確認。
- Q4 ロギング＝**プレーン**。
- Q5 認証＝**単一共有クレデンシャル**（ロールなし）。
- Q6 スケジューラ＝**APScheduler**（アプリ内・単一プロセス）。

> 棚卸し依存: 業者外部モデルの**具体スキーマ**は棚卸し後に各機能で実装する（本 spec は接続・パターンまで）。
