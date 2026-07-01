# 技術スタック (Technology Stack)

> ⚠️ **コード未着手（ver1 参照の下書き）**: 本ファイルは現行 `shisui/app`（ver1）の
> 実装から技術選定を抽出した下書き。**ver2 は ver1 と同じ技術選定を踏襲する前提**で
> 記載している。ver2 の実装が始まったら `/kiro:steering`（Sync）で実態に合わせて
> 確定・更新すること。`product.md` の「確定済みの外部制約」（オンプレ／LAN・FTP・ONNX・
> monochro/color 2モデル）を満たすことが前提。

## アーキテクチャ (Architecture)

Web 三層アーキテクチャ + 1つの独立プロセス（モデル再学習）+ **アプリ内日次スケジューラ**（保守タスクの逸脱判定）。
**ver2 スタック（API・ver2 DB・再学習・スケジューラ）は単一ホストに同居**する（オンプレ）。検査結果は
**業者所有の別 PostgreSQL インスタンス**（LAN 内・ライブ・読み取り専用）から読む。検査PC（エッジPC）とは FTP で連携する。

- **プレゼンテーション層**: React (SPA) + FastAPI REST API
- **アプリケーション層**: Service（ビジネスロジック）+ Schema（Pydantic 検証）
- **データ層**: Repository + SQLAlchemy ORM。**2つの PostgreSQL に接続**:
  ① **検査 DB（app_db・アノテーション/AI プラットフォーム本番）**: 外部・ライブ・**読み取り専用 SELECT のみ**・
     Alembic 管理外・**ver2 は索引を張れない**。検査結果は `annotation.image_base`、**フルタプルは `extra_info`(jsonb)**、
     正解は `annotation_item`→`dataset_category_item.on_class`（`schema-spec-mapping.md`）。
  ② ver2 DB（自前・読み書き・Alembic 管理。閾値・ジョブ・タスク・色・エッジPC・再学習ジョブ・**日次集計テーブル**）。
- **独立プロセス**: モデル再学習（`training/`、Web から `subprocess` 起動される ML パイプライン）
- **アプリ内スケジューラ**: 日次ジョブを定期実行（API プロセス内・単一ワーカ所有・冪等）。
  順序は **日次集計（app_db→ver2 集計テーブル）→ 逸脱判定 → 色昇格**（集計後に判定/昇格が読む）。
- **取り込み（外部・スコープ外）**: ログ取り込みは**外部の別プロセス**が担い、ver2 は実装しない。
  ver2 は取り込み結果 DB を**読み取るのみ**（`product.md` スコープ外と整合）。
- **外部連携（FTP）**: 再学習パイプラインが検査PC（エッジPC）へ **ONNX モデルを FTP 配信**する（アプリ → エッジ）。
  **学習用画像は同一 PC 上の別機能が所定パスへ用意**するため、ver2 は FTP 収集を行わない（ローカルパスを読むだけ）。
  FTP 接続先（エンドポイント）の**登録・管理は Web 側**（Service/Repository）で行い、
  接続情報は**環境変数ではなく DB で管理**する（`product.md` の「エッジPC管理」機能と整合）。

データフロー: Web リクエスト経路（API → Service → Repository）と再学習プロセスは疎結合。
再学習は API から subprocess として起動し、進捗は WebSocket で配信する。
検査PC との実 I/O は FTP（モデル形式は ONNX）。
検査結果の参照は業者検査 DB への読み取り専用接続で行う。業者 DB は ver2 と別インスタンスのため
**1本の SQL で ver2 テーブルと結合しない**（メトリクス集計は業者 DB 内で完結し、閾値等との突合は Service 層で行う）。
業者 DB はライブ・リモートのため、**到達不能・接続断時もアプリが致命的に落ちない**ハンドリングを設ける。

> 配信方式（WebSocket）・ジョブ実行方式（subprocess）・フレームワーク・言語・DB は、
> `product.md` が tech.md に委ねた選定事項であり、本書で確定する。

## 主要フレームワーク・ライブラリ (Frameworks & Libraries)

**バックエンド (Python 3.11)**
- FastAPI + Uvicorn（ASGI）: REST API・WebSocket
- SQLAlchemy 2.0（ORM）+ psycopg2-binary + Alembic（マイグレーション）
- Pydantic v2 + pydantic-settings（スキーマ検証・設定管理）
- FTP クライアント: 標準 `ftplib`（`from ftplib import FTP`、平文 FTP）── ver1 踏襲で確定

**ML・再学習パイプライン**
- PyTorch / torchvision（CUDA 版は Dockerfile で直接導入）
- ONNX / onnxscript / onnxruntime-gpu（推論モデルのエクスポート）
- OmegaConf（`conf/config.yaml` ベースの設定）、opencv-python-headless、tqdm

**フロントエンド (TypeScript 5, strict)**
- React 18 + Vite 5（ビルド・開発サーバ）
- react-router-dom 6（ルーティング）、axios（HTTP クライアント）、TanStack Query（サーバ状態の取得・キャッシュ・再取得）
- recharts（グラフ）、react-window（大量データの仮想化）

**テスト**
- バックエンド: pytest（マーカー: `unit` / `integration` / `api`）、pytest-cov、
  pytest-mock、pytest-asyncio、httpx（FastAPI TestClient）
- フロントエンド: Vitest + Testing Library（jsdom）

## 技術選定の判断 (Key Decisions)

- **PostgreSQL / スキーマ方針（2 DB 構成）**: 将来 1e8 レコード級を想定し RDB を選定。集計クエリは
  Repository 層で ORM／関数（`func`）を用いて DB 側で実行。
  - **業者検査 DB（＝ `app_db`・アノテーション/AI プラットフォーム本番）**（外部・別インスタンス・ライブ・読み取り専用）: ver2 は **SELECT のみ**。
    検査結果は `annotation.image_base`、フルタプルは `extra_info`(jsonb)、**索引を張れない**（`schema-spec-mapping.md`）。
    ORM は**実スキーマから反映するだけ**で **Alembic 管理対象外**（業者がスキーマを管理。ver2 は ALTER も索引追加もしない）。
  - **ver2 DB**（自前・読み書き）: 閾値・再学習ジョブ・保守タスク等の **ver2 テーブルのみ**を置き、
    **Alembic で管理**（ver2 テーブルの greenfield マイグレーション。migration を正）。
  - アプリ仕様は ver1 と同一だが、**ver1 で独自設計した DB／テーブルは一切使わない**（ver1→ver2 のデータ移行は発生しない）。
  - 開発では業者検査 DB の **dump をローカルに立てて代役**とし、ver2 DB を別に用意する（ローカルも 2 DB 構成）。
  - **集計方針（確定）**: 検査 DB（app_db）は **索引を張れず**・フルタプルが **jsonb**・日次パーティション。
    任意期間のオンザフライ jsonb 集計は非現実的なため、**`日次集計基盤` が日次で ver2 集計テーブルに件数を貯める**
    （JST日×フルタプル×号機）。ダッシュボード推移/集計・逸脱判定・色昇格はこの集計テーブルを読み、
    **明細表示のみ** app_db を当日パーティションでオンザフライ参照する。アノテーション後追いのため**直近7日を毎日再集計**。
- **Repository パターン + FastAPI DI（2エンジン）**: Service 層を DB 非依存にし単体テストを容易化。
  **SQLAlchemy エンジン/セッションを2系統**持つ ── 業者検査 DB 用（**読み取り専用**）と ver2 DB 用（読み書き）。
  検査結果系リポジトリは業者エンジン、閾値・ジョブ・タスク系は ver2 エンジンに紐づける。
  セッションは依存（`get_db` 系）で**リクエスト単位**に発行（ver2 側は正常時 commit／例外時 rollback、業者側は読み取り専用）。
- **再学習を subprocess 化 + 進捗配信**: 学習は重く長時間・GPU 依存のため、API プロセスから
  切り離して `subprocess` で実行。途中キャンセルはプロセスツリー kill。
  進捗連携は、subprocess の出力を親（API）プロセスが読み取り、ライブ進捗・ログを WebSocket で
  配信する（**ライブ進捗は揮発でよく、DB へは記録しない**）。学習側は進捗を標準出力へ1行ずつ
  （`\r` 上書きでなく）出力する契約とする。
  一方、**ジョブ記録（状態 `QUEUED→RUNNING→COMPLETED/FAILED/CANCELLED`・開始/終了時刻・結果/エラー）は
  DB に永続化**する（`product.md` 不変条件5 に対応。再接続・履歴参照・完了後の ONNX 化／FTP 配信／昇格判定に必要）。
  subprocess とジョブ管理は単一の API ワーカが所有する（マルチワーカ構成にする場合は DB 等を介して連携）。
- **GPU 構成と再学習の同時実行**: GPU は RTX PRO 4000 Blackwell 24GB ×2（当該ホストに搭載）。
  1 回の再学習ジョブで monochro / color を 2 枚の GPU で学習し、2 枚を占有する。
  **再学習ジョブの同時実行は1本**（後続は QUEUED）。
  ジョブキューは **FIFO**、**QUEUED はキャンセル可**、RUNNING のキャンセルはプロセスツリー kill。
- **API ページング（テーブル単位で方針決定）**: ページング方針はテーブルの規模・アクセスパターンに応じ
  **テーブル単位**で定める。大規模テーブル（検査結果等、1e8 級）は**キーセット（カーソル）ページング**
  （OFFSET は深いページで劣化するため避ける）、小規模テーブル（マスタ・閾値・タスク等）は
  OFFSET/limit または全件取得でよい。各テーブルのカーソルキー・既定ページサイズは `structure.md`／spec で確定。
- **ONNX エクスポート**: 学習は PyTorch、検査PCへの配信・推論は ONNX に統一。
- **FTP 連携**: 検査PCへの**モデル配信**は FTP（`product.md` の確定済み外部制約）。
  **学習用画像の収集は不要**（同一 PC 上の別機能が所定パスへ用意。ver2 はローカルパスを読むだけ）。
  接続先は DB 管理とし、シークレットを env に置かない。平文 FTP（`ftplib.FTP`）で ver1 踏襲・確定。
  FTPS／SFTP は要件化されるまで採用しない。
- **取り込みは外部・スコープ外**: ログ取り込みは外部の別プロセスが担い、ver2 は取り込み処理を実装しない。
  取り込み先は**業者検査 DB（ライブ）**で、ver2 はそこを**読み取るのみ**（`product.md` スコープ外と整合）。
- **逸脱判定の定期実行（アプリ内スケジューラ）**: 保守タスクの逸脱判定は**日次でアプリ内スケジューラ**
  （例: APScheduler）から実行する。OS の cron 等に依存せず Docker（Linux コンテナ）で dev/prod 同一に動く。
  **単一ワーカが所有**（再学習 subprocess と同じ前提）。ジョブは**冪等**（直近一定期間を再評価し upsert で重複しない）で、
  実行漏れ・遅延データを次回実行で取り戻す。**自動クローズはしない**。これが ver2 初の定期処理（取り込みは外部のため）。
- **単一ホスト同居（ver2 スタック）**: API・ver2 DB・再学習 を 1 台に同居（オンプレ）。
  これにより「再学習が API と同一ホスト」が成立し、subprocess 起動が前提として成り立つ。
  **業者検査 DB は同居せず、LAN 内の別インスタンスへ読み取り接続**する。
- **認証はアクセスゲートのみ（ロール制御なし）**: 任意の Basic 認証で LAN 内アクセスを保護する。
  `product.md` の 作業者／保守担当者 の区別は**運用上のもの**で、
  **ソフトウェアでの RBAC・権限制御は実装しない**（全ログインユーザが全機能にアクセス可）。

## コーディング規約 (Coding Conventions)

- **Python**: black（行長 88）、flake8（`extend-ignore = E203, W503`）、mypy。
  docstring・コメントは日本語。
- **TypeScript**: strict 有効、`noUnusedLocals` / `noUnusedParameters`、ESLint。
- **TDD**: 1タスク = 1テスト + 1実装 + 1コミット。カバレッジ目標 **80% 以上**
  （`--cov-fail-under=80`）。テストは RED → GREEN → REFACTOR。
- **コミットメッセージ**: Conventional Commits 形式 `<type>(<scope>): <subject>`
  （例: `feat(deploy): ...`）。本文は日本語可。
- **命名・配置の詳細**: `structure.md` を参照。

## 検証ゲート (Definition of Done)

各タスクは、以下がすべてグリーンになって初めて「完了」とする。
実装ループ（コード変更 → 検証 → 是正）はこのゲートを基準に回す。

**バックエンド**
- `pytest --cov=src --cov-fail-under=80`（マーカー絞り込み可: `pytest -m unit`）
- `black --check src tests`
- `flake8 src tests`
- `mypy src`

**フロントエンド**
- `npm run test`（Vitest）
- `tsc --noEmit`（型チェック。`npm run build` にも含まれる）
- ESLint（`npm run lint` ── スクリプト定義は `structure.md` / `package.json` で確定）

> CI／pre-commit フック等での自動実行は `structure.md` 側で配線する。
> 上記コマンド名は ver1 準拠の暫定。実態に合わせ Sync 時に確定すること。

## テスト方針 (Test Strategy)

- **テスト DB**: 本番とは別の専用 DB を用いる。
- **分離（基本）**: 各テストをトランザクションで囲み、終了時に ROLLBACK して独立性を担保する。
- **分離（例外）**: migration 検証など必要時は使い捨て DB を立てる。
- **初期データ**: fixture / seed データを用意する。
- **スキーマの正**: テスト DB のスキーマは **migration を正**とする（業者 dump は補助）。

## ビルド・テスト・実行 (Build / Test / Run)

**バックエンド**
- 起動（開発）: `uvicorn src.main:app --reload`
- テスト: `pytest`（`pytest -m unit` 等でマーカー絞り込み）
- 整形・静的解析: `black src tests` / `flake8 src tests` / `mypy src`

**フロントエンド**
- 開発: `npm run dev`（Vite。`/api` は `localhost:8000` へプロキシ、WebSocket 対応）
- ビルド: `npm run build`（`tsc && vite build` → `dist/`）
- テスト: `npm run test`（Vitest）

**デプロイ／実行環境**
- **Docker（Linux コンテナ）で統一**: 開発は **Windows ホスト上の Docker**、本番は **Linux**。
  アプリは**常に Linux コンテナ内**で動く（dev/prod 同一）。
- **バックエンド image（ver1 踏襲・Blackwell 対応へ更新）**: ベースは **`nvidia/cuda:<12.8+>-runtime-ubuntu22.04`**
  （ver1 は `nvidia/cuda:12.2.2-runtime-ubuntu22.04`／A5000・CUDA12.1 系だった）。apt で **Python 3.11** を入れ、
  **PyTorch は CUDA 対応 wheel を pip 導入**（ver1 は `torch==2.3.1+cu121`）。
  新ハードは **RTX PRO 4000 Blackwell** のため、**CUDA 12.8 以降・PyTorch は Blackwell 対応版（cu128 系）**へ更新する
  （ver1 の 12.2/cu121 のままでは不可）。非 root 実行・`/health` ヘルスチェック。
- **GPU の受け渡し**: `docker-compose` の `deploy.resources.reservations.devices`（`driver: nvidia`・`count: all`・
  `capabilities: [gpu]`）＋ `NVIDIA_VISIBLE_DEVICES=all`／`NVIDIA_DRIVER_CAPABILITIES=compute,utility`（ver1 compose で実績）。
  本番 Linux は NVIDIA Container Toolkit、dev の Windows+Docker は WSL2 経由。
- 本番では `ENVIRONMENT=production` で FastAPI がフロントの `dist/` を配信（SPA フォールバック）。

**コンテナ構成**
- **本番（Linux）**: 2 コンテナ。
  - **ver2 バックエンド**: FastAPI（API）＋アプリ内スケジューラ＋再学習 subprocess。**単一インスタンス**で GPU を渡す。
    フロントは FastAPI が `dist/` を配信（フロント専用コンテナは無し）。
  - **ver2 DB**: PostgreSQL（**独立コンテナ＋永続ボリューム**。状態を持つため、ステートレスなアプリと寿命を分ける）。
  - **業者検査 DB**: コンテナ化しない。外部のライブ DB へ `INSPECTION_DATABASE_URL` でリモート接続（読み取り専用）。
- **開発（Windows ホスト上の Docker）**: 上記2つ ＋ **業者 DB 代役**コンテナ（dump をロードした PostgreSQL。
  必要なら pgAdmin）。`docker-compose` で一括起動。
- **ver1 の docker-compose 踏襲**: `postgres:14`・backend・pgAdmin の構成を踏襲し、ver2 は **業者 DB 代役**コンテナと
  `INSPECTION_DATABASE_URL`（モデルB の2 DB 目）を追加する。env 名（`DATABASE_URL`/`DEBUG`/`ENVIRONMENT`/
  `ENABLE_BASIC_AUTH`/`BASIC_AUTH_USER`/`BASIC_AUTH_PASS`/`LOG_LEVEL`）は ver1 と一致（＋ ver2 で `BREACH_EVAL_*`/`TRAINING_*` を追加）。
- バックエンドが単一インスタンスのため、**アプリ内スケジューラの単一所有が成立**（再学習 subprocess 所有も同様）。
  将来 API を水平スケールする場合は、スケジューラを別コンテナへ切り出して1つに固定する。

> **実行環境の前提**: アプリは Linux コンテナで動く（dev/prod 同一）ため、OS 差を吸収する実装は不要。
> subprocess のプロセスツリー kill・パス処理は **Linux 前提**でよい。

## 環境変数 (Environment Variables)

> 名前のみ記述。値・シークレットは記述しない。`.env`（pydantic-settings）で読み込む。
> 検査PCの FTP 接続情報は env ではなく DB で管理する（アーキテクチャ参照）。

- `DATABASE_URL`: ver2 DB（自前・読み書き）の接続文字列
- `INSPECTION_DATABASE_URL`: 業者検査 DB（外部・**読み取り専用**）の接続文字列
- `DEBUG`: デバッグモード
- `ENVIRONMENT`: 実行環境（`development` / `production`。production で静的配信が有効）
- `ENABLE_BASIC_AUTH` / `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`: Basic 認証（任意）
- `LOG_LEVEL`: ログレベル（DEBUG/INFO/WARNING/ERROR/CRITICAL）
- `TRAINING_DATASET_PATH` / `TRAINING_PIPELINE_DIR`: 再学習のデータセット・パイプライン配置先
- `BREACH_EVAL_ENABLED` / `BREACH_EVAL_TIME` / `BREACH_EVAL_WINDOW_DAYS`: 逸脱判定ジョブの
  有効化・実行時刻・再評価窓（アプリ内スケジューラ。任意）
- `AGG_WINDOW_DAYS`（既定 7）/ `AGG_RUN_TIME`: 日次集計の再集計窓（アノテーション後追い反映）・実行時刻

