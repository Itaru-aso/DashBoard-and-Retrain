# プロジェクト構造 (Project Structure)

> ⚠️ **コード未着手（ver1 参照の下書き）**: ver2 はディレクトリ／レイヤ構成を ver1 から踏襲するが、
> **取り込み（watchdog）は外部・スコープ外**として持たず、DB は **2 構成**（業者検査 DB＝外部・読み取り専用／
> ver2 DB＝自前・読み書き）とする（`product.md`／`tech.md` の確定事項を反映）。実装が始まったら
> `/kiro:steering`（Sync）で実態に合わせて確定・更新すること。

## 現状 (Current State)

- リポジトリパス: `shisui/app_ver2`（YKK社内 GitLab）
- 既存内容: `.kiro/`（Kiro 設定）, `.omc/`（oh-my-claudecode 状態）のみ
- ソースコード: 未着手（下記は ver1 を踏襲する想定構成）
- DB（`tech.md` 参照）: **業者検査 DB**（外部・別インスタンス・ライブ・**読み取り専用**）＋
  **ver2 DB**（自前・読み書き・Alembic 管理）の 2 構成。
  開発では業者検査 DB の **dump をローカルに立てて代役**とし、ver2 DB を別に用意する（ローカルも 2 DB）。

## ディレクトリ構成 (Directory Organization)

```
backend/
  src/
    api/            # FastAPI ルーター（プレゼンテーション層）  例: task_endpoint.py
    services/       # ビジネスロジック（アプリケーション層）    例: task_service.py
    repositories/   # DB 操作（データ層）。エンジン別に紐づく   例: task_repository.py
    models/         # ver2 ORM モデル（自前テーブル・Alembic 管理）例: threshold.py
      external/     # 業者検査DBの読み取り専用モデル（実スキーマ反映のみ・Alembic 対象外）例: inspection_result.py
    schemas/        # Pydantic 入出力スキーマ                   例: task.py
    jobs/           # アプリ内スケジューラの定期ジョブ（日次の逸脱判定など。main.py で起動）例: breach_eval_job.py
    config.py       # pydantic-settings による設定（接続URL 2系統・スケジューラ設定）
    database.py     # 2エンジン/2セッション（業者=読み取り専用／ver2=読み書き）・Base（ver2用）
    main.py         # FastAPI アプリ・ルーター登録・起動処理・スケジューラ起動
  tests/
    unit/           # 単体テスト（@pytest.mark.unit）
    integration/    # 統合テスト（DB 使用、@pytest.mark.integration）
    api/            # API テスト（TestClient）
    conftest.py     # 共有 fixture（ver2 テスト DB のトランザクション ROLLBACK・seed／業者DBスナップショット）
  alembic/          # マイグレーション（**ver2 DB のみ対象**。業者検査DBは対象外）
    versions/       # ver2 テーブルのマイグレーションを置く
  alembic.ini       # Alembic 設定（backend/ で実行・ver2 DB を指す）
  training/         # 【独立プロセス】再学習パイプライン（conf/, dataset/, model/, ONNX配信(FTP) ほか）
  scripts/          # seed・一括投入・dump インポート補助等の単発スクリプト

frontend/
  src/
    pages/          # 画面単位コンポーネント（PascalCase）例: TaskList.tsx + TaskList.css
    components/      # 再利用 UI コンポーネント            例: LogViewer.tsx
    api/            # API クライアント                    例: taskApi.ts, client.ts
    hooks/          # カスタムフック（TanStack Query のデータ取得フック含む）
    App.tsx, main.tsx

（プロジェクト直下）
  Dockerfile          # ver2 バックエンド（API＋スケジューラ＋再学習・GPU・単一）
  docker-compose.yml  # dev: ver2バックエンド＋ver2 DB（独立・ボリューム）＋業者DB代役（dump）。tech.md コンテナ構成参照
```

「3層（api/services/repositories + models/schemas）」と「1つの独立プロセス（`training/`）」が
構成の骨子。新しいコードはこのパターンに従って配置する。
**ログ取り込みは外部プロセスが担い、ver2 リポジトリには含めない**（`product.md` スコープ外と整合）。

## 命名規約 (Naming Conventions)

**バックエンド (Python)**
- ファイル: snake_case。レイヤを接尾辞で表す
  — `*_endpoint.py`（API）/ `*_service.py`（Service）/ `*_repository.py`（Repository）
- モデル: 単数形のテーブル名ファイル（例: `task.py`, `color_master.py`）
- クラス: PascalCase（例: `TaskService`, `ColorMasterRepository`）

**フロントエンド (TypeScript)**
- 画面・コンポーネント: PascalCase（`TaskDetail.tsx`）、CSS は同名で同居（`TaskDetail.css`）
- API クライアント: `<機能>Api.ts`（例: `thresholdApi.ts`）

## import 規約 (Import Conventions)

- **バックエンド**: `src.` からの**絶対 import**（例: `from src.repositories import TaskRepository`）。
  `repositories/__init__.py` で主要クラスを再エクスポートし、まとめて import 可能にしている。
- **フロントエンド**: パスエイリアス `@/*` → `src/*`（tsconfig / vite で設定）。
- **例外（training/）**: 再学習は `cwd=backend/training` で `subprocess` 起動されるため、
  `from pipline import ...` のような **cwd 相対 import** を使う。`src.` 配下とは import
  規約が異なる点に注意（パイプラインを単独 CLI としても実行できるようにするため）。
  ※ モジュール名は `pipline`（ver1 実装の実名で**確定**。`pipeline` ではないので自動補正しないこと）。

## レイヤ分け・依存方向 (Layering & Dependencies)

- 依存方向は一方向: **API → Service → Repository → Model / DB**。
- Service は Repository を**注入**されて使う。Service 間依存は可
  （例: `TaskService` → `NgRateService` / `KpiService` / `ThresholdService`）。
- DB セッションは `api/dependencies.py` で**リクエスト単位**に2系統供給する:
  `get_db`（ver2 DB・読み書き。正常時 commit／例外時 rollback／finally で close）と
  `get_inspection_db`（業者検査 DB・**読み取り専用**）。
  検査結果系リポジトリは業者セッション、閾値・ジョブ・タスク系は ver2 セッションを受け取る。
  業者 DB はライブ・リモートのため、接続断時のハンドリングを設ける（`tech.md`）。
- `training/` は Web リクエスト経路から import されない独立プロセス。
  再学習は API から `subprocess` 経由で起動する（直接 import しない）。
- **再学習ジョブの実行**: `training_service` をシングルトン化し、起動時にワーカー（in-process の
  asyncio キュー）を開始して**順次実行**する（同時実行は1本・FIFO）。各ジョブは subprocess を起動し、
  進捗・ログは WebSocket で配信、**ジョブ記録（状態・開始/終了時刻・結果/エラー）は DB を正**として永続化する。
  QUEUED はキャンセル可、RUNNING はプロセスツリー kill（`tech.md` 参照）。
- **アプリ内スケジューラ（定期ジョブ）**: `main.py` の起動時にスケジューラを開始し、`src/jobs/` の定期ジョブを登録する。
  各ジョブは**Service を呼ぶだけの薄い層**（ロジックは Service・Repository に置く）。**単一ワーカが所有**し、
  ジョブは**冪等**（再実行・多重発火しても upsert で重複しない）。Web リクエスト経路とは独立。

## 配置のルール (Placement Rules)

- 新しい API → `src/api/<name>_endpoint.py` を作り `main.py` にルーター登録
- 新しいビジネスロジック → `src/services/<name>_service.py`
- 新しい **ver2 テーブル** → `src/models/<name>.py` + `src/repositories/<name>_repository.py`
  + `alembic/versions/` に ver2 DB のマイグレーションを追加（ver2 DB に作成）
- **業者検査 DB を読むだけ**のモデル → `src/models/external/<name>.py`（実スキーマ反映のみ・Alembic 対象外）。
  対応するリポジトリは業者エンジンに紐づける（**読み取り専用**）。
- 新しいリクエスト／レスポンス → `src/schemas/<name>.py`
- **エッジPC（FTP 接続先）管理** → 標準レイヤ（`api`/`services`/`repositories`/`models`）に配置（ver2 DB）。
  接続情報は DB 管理。**実 FTP I/O（モデル配信）は `training/`** に置く（`tech.md` の役割分担）。
  学習用画像は同一 PC 上の別機能が所定パスへ用意するため**FTP 収集は行わない**。
- ML・再学習関連 → `training/`
- **定期ジョブ（スケジューラ）** → `src/jobs/<name>_job.py`（`main.py` で登録・起動）。ロジックは Service に置き、ジョブは薄く保つ。
- マイグレーション → `alembic/versions/`（**ver2 DB のみ**。業者検査 DB は対象外）
- 一度きりの seed・一括投入・dump インポート補助 → `scripts/`（ver1→ver2 のデータ移行は発生しない）
- 新しい画面 → `frontend/src/pages/`、再利用 UI → `frontend/src/components/`、
  API 呼び出し → `frontend/src/api/<feature>Api.ts`、データ取得フック（TanStack Query）→ `frontend/src/hooks/`

## スキーマ・マイグレーション方針 (Schema & Migration)

- **業者検査 DB**（外部・読み取り専用）: 棚卸しで**スキーマ把握**し、`models/external/` に
  **読み取り専用 ORM を実スキーマから反映**する（**Alembic 対象外**。ver2 は ALTER も索引追加もしない）。
- **ver2 DB**（自前・読み書き）: 閾値・再学習ジョブ・保守タスク・色ライフサイクル状態等の **ver2 テーブルのみ**を置き、
  **Alembic で greenfield 管理**（最初から ver2 テーブルだけのマイグレーション。**migration を正**）。
- **パーティション・索引は保留**（実データに基づき後日確定。`tech.md`）。業者 DB には索引を足せないため、
  オンザフライ集計は業者 DB の既存索引に依存し、不足時は **ver2 DB 側の集計テーブル**で対応する。
- **ページングはテーブル単位**（大規模＝キーセット／小規模＝OFFSET・全件）で `repositories/` に実装。

## テスト配線 (Test Wiring)

- テストは `tests/`（`unit` / `integration` / `api`）。マーカーで絞り込み（`tech.md` 検証ゲート参照）。
- **ver2 テスト DB**: `conftest.py` が専用テスト DB への接続と、**各テストをトランザクションで囲み ROLLBACK**
  する fixture を提供。スキーマは **migration を正**。初期データは fixture / seed。
- **業者検査 DB 相当**: Alembic 管理外のため、**dump 由来のスキーマスナップショット**からテスト用検査 DB を立て、
  fixture で検査データを投入する（ライブ DB は再現性が無いのでテストでは固定スナップショットを使う）。
- migration 検証など必要時は使い捨て DB。
