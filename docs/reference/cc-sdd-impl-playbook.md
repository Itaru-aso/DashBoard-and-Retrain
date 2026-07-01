# cc-sdd 実装プレイブック（shisui app_ver2）

> 目的: `/kiro:spec-impl <feature> <task>` で **1タスクずつ TDD** 実装する際に、毎回コマンドへ添える
> 指示文の雛形と、着手前チェック・実行順・守るべき不変をまとめる。コマンド名/引数は環境の cc-sdd 仕様に従う。

---

## 0. 着手前チェック（最初に一度）

- [ ] steering を `.kiro/steering/`（product.md / tech.md / structure.md）に配置
- [ ] 各 spec を `.kiro/specs/<feature>/{requirements,design,tasks}.md` に配置
- [ ] 参照実装を `docs/reference/<feature>/...`（src と同じ構成でミラー）に配置（src には置かない）
- [ ] 資料の正を `docs/reference/` に常設: `schema-spec-mapping.md`・`retraining-integration-answers.md`
- [ ] `uvicorn --workers 1` 前提を確認（スケジューラ・再学習キューの単一所有）
- [ ] 最初の数タスク（基盤整備）は `-y` を控え、生成物を目視確認

## 1. 実行順（依存順）

`foundation` → `daily-aggregation` → `threshold` → `dashboard` → `task` → `color` → `model-retraining` → `edge`
（spec フォルダ名は実際の `.kiro/specs/` に合わせる）

各 spec は tasks.md を上から1つずつ。前の spec が緑になってから次へ。

---

## 2. コマンド＋添える指示文（毎回これを貼る）

```
/kiro:spec-impl <feature> <task番号>
```

上のコマンドに続けて、または直後の指示として以下を貼る（{ } を埋める）:

```
{feature}/tasks.md のタスク{N} を TDD で1つだけ実装してください。

前提（厳守）:
- design.md と docs/reference/schema-spec-mapping.md（実列・不変）に従う。
- 参照実装: docs/reference/{feature}/{該当ファイル}（コピーせず、本プロジェクトの
  import 規約・DI・config に合わせて実装し直す）。
- 越境結合しない（app_db と ver2 を1 SQL で結合しない。2エンジンで読み Service で突合）。

手順:
1) 失敗するテストを先に書く（RED）。tasks のテスト方針・トレーサビリティに沿う。
2) 実装して通す（GREEN）。
3) 整える（REFACTOR・テストは緑のまま）。
4) 検証ゲートを通す: pytest(cov≥80) / black / flake8 / mypy
   （フロントは tsc / eslint / vitest）。
5) Conventional Commits でコミット（例: feat({feature}): ...）。

このタスクだけ進めて、完了したら結果（テスト名・コミット）を報告して、次の指示を待ってください。
```

## 3. 不変（全タスク共通・design/schema-spec-mapping 準拠）

- フルタプル ＝ `annotation.image_base.extra_info`(jsonb) の `colorNo`/`size`/`chain`/`tape`（**tape 含む・空文字可**）
- 日次 ＝ `inspect_timestamp::date`（**JST 保存**）／ 号機 ＝ `unit`
- monochro（分母）＝ `camera_model='camera1_image'` ／ AI判定 ＝ `judgment_result`（0:OK/1:NG）
- 正解 ＝ `image_id`→`annotation_item`→`dataset_category_item.on_class`（1つでもNGならNG・全OKでOK・無ければなし。**use_flg では絞らない**）
- 3指標とも **分子=全カメラ・分母=monochro**。注釈なしは虚報/見逃しの母数から除外（その日0なら NULL）
- 日次ジョブ順 ＝ **集計 → 逸脱判定 → 昇格**
- app_db は**読み取り専用・索引不可**。集計は ver2 `daily_metrics` に貯める（明細のみ app_db オンザフライ）
- `services/metrics.py` は **日次集計基盤が所有**（他機能は呼ぶだけ）

## 4. 着手前に合わせる調整点（参照実装→本体）

- import パス: `from database import Base` / `models.*` / `repositories.*` / `services.*` / `api.*` / `auth` / `dependencies`
- DI 実体: `get_db`・`verify_basic_auth`・`get_color_master_repo`(`exists_by_tuple`)・`get_deployment_service`・`SessionLocal`
- config: `DATABASE_URL`/`INSPECTION_DATABASE_URL`・`training_dir`/`training_model_dir`/`training_python`・各 `*_ENABLED`/時刻
- マイグレーション: `down_revision` を現行 head に接続（複数 head 回避）
- CUDA: 学習側 torch を cu121 → **cu128 系**（Blackwell）
- WebSocket 認証: ブラウザ WS の Basic 代替（Cookie セッション or クエリトークン）
- エッジPC repo: `find_enabled()`（host/username/password/model_port）

## 5. 進捗管理

- tasks のチェックボックスが唯一の台帳: `[ ]` 未着手 / `[~]` 参照実装あり・要結合 / `[x]` 緑化済み
- 1コミット＝1タスク（テスト＋実装をセット）。複数タスクを混ぜない
- spec と実装が食い違ったら **spec を直してから**実装（コードに引きずられない）
- spec 完了時に schema-spec-mapping と突き合わせ、不変が崩れていないか確認

## 6. spec 別メモ

- **foundation**: config→database(2エンジン)→Alembic 空ベースライン→認証→スケジューラ→main→ロギング→conftest→フロント骨格→Docker。土台なので目視確認推奨
- **daily-aggregation**: `daily_metrics`・`aggregation_service`（app_db CTE 集計／冪等 delete→insert／直近7日再集計）・`metrics.py`（所有）・スケジューラ
- **model-retraining**: タスク0（学習側 pipline.py の skip_download/skip_upload ガード）から。番号は最新 tasks.md に一致するか先に確認（0始まり）。依存（foundation/edge/color）緑化後に結合
- **threshold/dashboard/task/color/edge**: ダッシュボード/保守タスク/色は `daily_metrics`（号機合算）＋`metrics.py` を読む。閾値は色レベル

## 7. つまずきやすい点

- 参照実装を src に丸ごとコピーしない（RED が成立しない・二重管理）
- 検証ゲートを後回しにしない（タスクごとに通す）
- `uvicorn --workers 1` を外さない
- タスク番号が最新 tasks.md と一致するか（更新済み spec＝再学習/ダッシュボード/保守/色）を実行前に確認
