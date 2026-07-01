# shisui app_ver2

YKK のジッパー外観検査における **AI モデル管理 Web アプリケーション**。検査結果の可視化（KPI）→ 閾値逸脱の検知 →
保守タスク化 → モデル再学習 → 検査PC への配信 → 色の量産昇格、という運用ループを管理する。利用者は検査運用の担当者。

> 個人の作法（日本語で回答/コミット、方針提示→承認、最小変更、動作証明で完了 等）は**グローバル CLAUDE.md** に定義済み。
> 本ファイルは**本プロジェクト固有**の規約・コマンド・禁止事項のみを記載する（重複させない）。

## 技術スタック
- **バックエンド**: Python 3.11 / FastAPI + Uvicorn（`--workers 1`）/ SQLAlchemy 2.0 + psycopg2 / Alembic / Pydantic v2
- **フロントエンド**: React 18 + Vite + TypeScript / TanStack Query / recharts
- **DB**: PostgreSQL ×2（モデルB。ver2＝読み書き／app_db＝読み取り専用）
- **インフラ**: Docker（base `nvidia/cuda:12.8+-runtime-ubuntu22.04` + Python 3.11 + PyTorch cu128 系・Blackwell 対応）
- **開発手法**: cc-sdd（Spec-Driven Development）/ TDD

---

## 開発コマンド

```bash
# 起動（単一ワーカ必須＝スケジューラ・再学習キューの単一所有）
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1   # dev は --reload

# テスト / カバレッジ（ゲート: cov≥80）
pytest
pytest --cov=src --cov-report=term-missing
pytest -m "unit | integration | api"

# コード品質（Python）
black .            # 行長 100
flake8 .
mypy src

# フロント
npm run dev        # Vite devserver（/api はバックエンドへプロキシ）
npm run build      # dist 生成（本番は FastAPI が静的配信）
tsc --noEmit && eslint . && vitest run

# DB マイグレーション（ver2 のみ）
alembic upgrade head
alembic revision --autogenerate -m "..."   # ※ app_db は対象外

# Docker
docker compose up -d --build
```

---

## アーキテクチャ

### レイヤ（責務）
`API（*_endpoint.py）→ Service（*_service.py）→ Repository（*_repository.py）→ Model`。上位は下位のみ呼ぶ。

### 2エンジン DB（モデルB）
- `get_db`（ver2・読み書き・正常 commit/例外 rollback）／`get_inspection_db`（app_db・**読み取り専用・commit しない**）。
- `Base`＝ver2（Alembic 対象）／`ExternalBase`＝app_db 読み取り専用モデル（**Alembic 非対象**・`models/external/`）。
- **越境結合しない**（app_db と ver2 を1 SQL で結合しない。2エンジンで読み Service で突合）。

### ディレクトリ（要点・詳細は @.kiro/steering/structure.md）
```
backend/src/{api,services,repositories,models,models/external,schemas,jobs,config.py,database.py,main.py}
backend/alembic/versions/        # ver2 のみ
frontend/src/{api,hooks,pages,components}
training/                        # 既存学習パイプライン（pipline.py 等）。ver2 は subprocess 起動のみ
```

### 主要パターン
- **日次集計基盤**: app_db は索引不可・フルタプルが jsonb のため、日次で ver2 `daily_metrics` に件数を貯める。
  ダッシュボード/逸脱判定/昇格はこれを読み、明細のみ app_db オンザフライ。`services/metrics.py` は本基盤が所有。
- **日次ジョブ順**: 集計 → 逸脱判定 → 昇格（APScheduler・単一所有）。
- **再学習**: `training/pipline.py` を subprocess 起動（学習ロジックは触らない）。配信は ver2 `deployment_service`。

---

## コーディング規約

### 文字エンコーディング
- すべて **UTF-8**。

### コードスタイル（ツールで強制）
- フォーマッタ **black（行長 100）** / リンタ **flake8** / 型 **mypy**（新規コードは型ヒント必須）。
- フロント: **eslint** / **tsc**（strict）。

### Python の書き方（参照実装に準拠）
- `from __future__ import annotations` を付ける。
- SQLAlchemy は **2.0 記法**（`Mapped` / `mapped_column`）。スキーマ I/O は **Pydantic v2**（`model_config = ConfigDict(...)`）。
- docstring は **Google 形式**（言語はグローバル規約どおり日本語）。公開クラス・関数に必須。

### 命名規則
| 対象 | スタイル | 例 |
|---|---|---|
| クラス | PascalCase | `TrainingService` |
| 関数・変数 | snake_case | `get_inspection_db` |
| 定数 | UPPER_SNAKE_CASE | `AGG_WINDOW_DAYS` |
| プライベート | 先頭 `_` | `_session_scope` |
| ファイル | レイヤ接尾辞 | `*_endpoint.py` / `*_service.py` / `*_repository.py` |

### インポート順序
1. 標準ライブラリ → 2. サードパーティ → 3. ローカル（各グループ内は昇順）。

---

## ドメインの不変（厳守・@docs/reference/schema-spec-mapping.md が正）

- **フルタプル** ＝ `annotation.image_base.extra_info`(jsonb) の `colorNo`/`size`/`chain`/`tape`（**tape 含む・空文字可**）
- **日次** ＝ `inspect_timestamp::date`（**JST 保存**）／ **号機** ＝ `unit`
- **monochro（分母）** ＝ `camera_model='camera1_image'` ／ **AI 判定** ＝ `judgment_result`（0:OK / 1:NG）
- **正解** ＝ `image_id`→`annotation_item`→`dataset_category_item.on_class`
  （**1つでもNGならNG / 全OKでOK / 無ければなし**・**use_flg では絞らない**）
- **3指標とも 分子=全カメラ・分母=monochro**。注釈なしは虚報/見逃しの母数から除外（その日0なら NULL）
- 同一性タプルでモデルは monochro/color の **1対**。色ライフサイクル＝未実施→量産検証→実生産（一方向）

---

## やってはいけないこと

- **app_db への書き込み・索引追加・スキーマ変更**（読み取り専用・Alembic 非対象）
- **越境結合**（app_db と ver2 を 1 SQL で JOIN）
- **`use_flg` で正解を絞る**（use_flg は AI 学習対象フラグであって正解判定ではない）
- **`uvicorn` を `--workers 1` 以外で起動**（スケジューラ・再学習キューが多重化する）
- **参照実装（`docs/reference/`）を `src` に丸ごとコピー**（TDD の RED が成立しない・二重管理）
- **学習ロジック（`training/` の学習本体）を改変**（許可された薄いラッパ改修＝`skip_download`/`skip_upload` のみ）
- spec と実装が食い違ったとき、**spec を直さずコードを優先**すること

---

## ワークフロー（cc-sdd）

- 実装は **`/kiro:spec-impl <feature> <task>` を 1タスクずつ**。手順・指示文雛形は @docs/reference/cc-sdd-impl-playbook.md。
- 実装順（依存）: `foundation → daily-aggregation → threshold → dashboard → task → color → model-retraining → edge`。
- 各タスクは TDD（RED→GREEN→REFACTOR）＋検証ゲート通過＋1コミット（`種別: 概要`）。
- **基盤が固まるまで OMC の自動進行（autopilot/ultrawork 等）は使わない**（1タスクずつ目視確認）。
- 進捗は各 `tasks.md` のチェックボックスが台帳: `[ ]` 未着手 / `[~]` 参照実装あり・要結合 / `[x]` 緑化済み。

---

## 設定（環境変数・抜粋）

| 変数 | 説明 |
|---|---|
| `DATABASE_URL` | ver2 DB 接続（読み書き） |
| `INSPECTION_DATABASE_URL` | app_db 接続（読み取り専用） |
| `ENABLE_BASIC_AUTH`/`BASIC_AUTH_USER`/`BASIC_AUTH_PASS` | Basic 認証（単一共有・有効時パス必須） |
| `AGG_RUN_TIME`/`AGG_WINDOW_DAYS` | 日次集計の実行時刻・再集計窓（既定 7） |
| `BREACH_EVAL_*` | 逸脱判定ジョブ |
| `TRAINING_DIR`/`TRAINING_MODEL_DIR`/`TRAINING_PYTHON` | 再学習（`training/` 連携） |

---

## ドキュメント INDEX（`@` で参照可能）

### Spec（正・`.kiro/specs/<feature>/`）
- requirements / design / tasks を機能ごとに保持（foundation・daily-aggregation・threshold・dashboard・task・color・model-retraining・edge）

### 資料の正・参照（`docs/reference/`）
| ファイル | 概要 |
|---|---|
| `@docs/reference/schema-spec-mapping.md` | 実スキーマ↔spec マッピング（実列・不変の正） |
| `@docs/reference/retraining-integration-answers.md` | 既存学習パイプライン連携の事実 |
| `@docs/reference/retraining-file-index.md` | 実装ファイルの配置先インデックス |
| `@docs/reference/cc-sdd-impl-playbook.md` | cc-sdd 実装手順・指示文雛形 |
| `@docs/reference/<feature>/...` | 各機能の参照実装（src と同構成・コピー禁止） |

> 新規ドキュメント作成時は本 INDEX に追記する。
