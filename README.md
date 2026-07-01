# shisui app_ver2 — AI モデル管理 Web アプリ

[![CI](https://github.com/Itaru-aso/DashBoard-and-Retrain/actions/workflows/ci.yml/badge.svg)](https://github.com/Itaru-aso/DashBoard-and-Retrain/actions/workflows/ci.yml)

YKK のジッパー外観検査における **AI モデルの運用管理 Web アプリケーション**。検査結果の可視化から、モデルの再学習・配信・量産昇格までの一連の運用ループを一元管理する。利用者は検査運用の担当者。

## これは何か（解決する課題）

現場の AI 外観検査は「モデルを配って終わり」ではなく、精度の監視と改善を回し続ける必要がある。本アプリはその運用ループを仕組み化する。

```
検査結果の可視化(KPI)
      │
      ▼
閾値逸脱の検知  →  保守タスク化  →  モデル再学習  →  検査PCへ配信  →  色の量産昇格
```

- **可視化**: 3指標（NG率 / 虚報率 / 見逃し率）を日次・号機・同一性タプル単位で表示
- **検知〜保守**: 閾値を外れた対象を検知し、保守タスクとして起票
- **再学習〜配信**: 既存学習パイプラインで再学習し、検査PC へ配信
- **昇格**: 色ライフサイクル（未実施 → 量産検証 → 実生産）を一方向に進める

## アーキテクチャ（概要）

- **レイヤ**: `API → Service → Repository → Model`（上位は下位のみ呼ぶ）
- **2エンジン DB**: `ver2`（読み書き・Alembic 対象）と `app_db`（**読み取り専用**・スキーマ変更不可）の2系統。**app_db と ver2 を1つの SQL で越境結合しない**（2エンジンで読み、Service で突合）。
- **日次集計基盤**: app_db は索引不可のため、日次で ver2 の `daily_metrics` に件数を貯め、ダッシュボード/逸脱判定/昇格はこれを読む。
- **再学習**: `training/` の既存学習パイプラインを subprocess で起動（学習ロジックは触らない）。

> 詳細なディレクトリ構成・責務は [`.kiro/steering/structure.md`](.kiro/steering/structure.md)、ドメインの不変条件は [`docs/reference/schema-spec-mapping.md`](docs/reference/schema-spec-mapping.md) を参照。

## 技術スタック（要約）

- **バックエンド**: Python 3.11 / FastAPI + Uvicorn / SQLAlchemy 2.0 + psycopg2 / Alembic / Pydantic v2
- **フロントエンド**: React 18 + Vite + TypeScript / TanStack Query / recharts
- **DB**: PostgreSQL ×2（ver2＝読み書き / app_db＝読み取り専用）
- **インフラ**: Docker（`nvidia/cuda` ベース・PyTorch cu128 系）

> バージョン・環境変数・規約の詳細は [`CLAUDE.md`](CLAUDE.md) に集約。

## 現在の状況

**spec 駆動開発（cc-sdd）フェーズ**。仕様（`.kiro/specs/`）と参照実装（`docs/reference/`）を整備済みで、`backend/` / `frontend/` の本実装はこれから。

実装順（依存関係）:

```
foundation → daily-aggregation → threshold → dashboard → task → color → model-retraining → edge
```

各機能の要件・設計・タスクは [`.kiro/specs/<feature>/`](.kiro/specs/) の `requirements.md` / `design.md` / `tasks.md` で管理。

## 始め方（開発者向け）

> 現在は spec 駆動フェーズのため、下記コマンドは `backend/` / `frontend/` 実装後に使う想定。詳細・前提は [`CLAUDE.md`](CLAUDE.md) を参照。

```bash
# バックエンド起動（単一ワーカ必須＝スケジューラ・再学習キューの単一所有）
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1   # dev は --reload

# テスト（カバレッジゲート cov≥80）／コード品質
pytest --cov=src --cov-report=term-missing
black . && flake8 . && mypy src

# DB マイグレーション（ver2 のみ・app_db は対象外）
alembic upgrade head

# フロントエンド
npm run dev        # /api はバックエンドへプロキシ
npm run build

# Docker
docker compose up -d --build
```

実装は **1タスクずつ** `/kiro:spec-impl <feature> <task>`（TDD: RED→GREEN→REFACTOR）で進める。手順は [`docs/reference/cc-sdd-impl-playbook.md`](docs/reference/cc-sdd-impl-playbook.md)。

## ドキュメント案内

| 場所 | 内容 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | 技術スタック・開発コマンド・アーキテクチャ・コーディング規約・ドメイン不変（開発の正） |
| [`.kiro/specs/`](.kiro/specs/) | 機能ごとの requirements / design / tasks（仕様の正） |
| [`.kiro/steering/`](.kiro/steering/) | プロジェクト横断の技術方針・構成（steering） |
| [`docs/reference/`](docs/reference/) | 実スキーマ↔spec マッピング、既存パイプライン連携、参照実装 |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI 定義 |

## CI

`main` への push（と手動実行）で GitHub Actions が走る。**ガード付き**構成で、`backend/` / `frontend/` が未実装の間は該当ジョブを skip し、コードが揃うと自動で有効化される（backend: black/flake8/mypy/pytest、frontend: eslint/tsc/vitest/build）。
