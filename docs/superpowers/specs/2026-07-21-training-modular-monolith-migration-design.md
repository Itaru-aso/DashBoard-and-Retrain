# training/ モジュラモノリス移行設計

**日付**: 2026-07-21
**対象**: `app_ver2/training/`（既存学習パイプライン。ver2 backend からは subprocess 起動のみ）
**種別**: 既存モノリス → モジュラモノリス移行（migration-workflow）
**先行事例**: `D:\0032011\GitLab\shisui\EfficientAD`（同一ベースラインからモジュラモノリス移行済み。本設計は同リポジトリの
`docs/superpowers/specs/2026-07-14-modular-monolith-migration-design.md` を app_ver2 の制約に合わせて再適用したもの）

---

## 0. 前提パラメータ（Completeness Gate 解決結果）

| # | パラメータ | 結論 |
|---|---|---|
| 1 | 対象範囲 | `app_ver2/training/` 配下のみ。EfficientAD の「リポジトリルート」に相当する境界が `training/` |
| 2 | パイプラインフロー | `dataset → train → {evaluation, deploy}`（EfficientAD と同一。独立 `preprocessing` は作らない＝ADR-7 継承） |
| 3 | MODEL_COUNT | 複数（color / monochro）。今後も並行運用を継続 |
| 4 | サービング範囲 | 外部（検査PC上の ONNX Runtime）。本リポジトリの評価は held-out test set に対するオフライン評価のみ |
| 5 | deploy の終端 | FTP アップロード（検査PC配布）。MLflow Model Registry 登録（`model_handler.py`）は現状未接続のまま（ADR-3 継承） |
| 6 | アーティファクト保存 | 現状のファイルシステム分散管理（`./6_model/{color}/{mode}/` + `para.json`）を容認 |
| 7 | 内部アーキテクチャ | 全モジュール layered に統一（ADR-1 継承） |
| 8 | 現行構成 | Python 単一ディレクトリ。EfficientAD の移行前ベースラインとファイル単位で一致（`model.py` / `model_exporter.py` / `model_handler.py` / `pipline.py` / `train_func_color.py` / `train_func_monochro.py` / `utils/*`） |
| 9 | カップリング調査 | §1・§8 参照。EfficientAD の調査結果がそのまま適用可能（コード同一のため） |
| 10 | テストコード基盤 | `training/tests/test_pipline_skip_flags.py`（skip_download/skip_upload の薄いラッパ改修テスト）、`test_pipline_spawn_context.py`（spawn context 修正テスト）のみ存在。それ以外は characterization test が必須 |
| 11 | リスク許容度 | 低。big-bang 禁止、seam 単位で低結合から順に抽出（EfficientAD と同順） |
| 12 | CLAUDE.md 例外 | 承認済み。本移行に限り `training/` の学習本体を触ることを例外として許可する（ユーザー承認、2026-07-21）。学習アルゴリズム自体（数式・パラメータ）は変更しない |
| 13 | Seam3（スコアリング統合）の扱い | 含める（EfficientAD と完全に同じ構成にする）。cand1 有効時に評価指標（AUC/F1/miss_rate/false_alarm_rate）が変わり得ることを承認済み（ユーザー承認、2026-07-21） |

---

## 1. 現状のパイプラインフロー（`training/pipline.py: TrainingPipeline.execute()`）

EfficientAD の移行前ベースラインと同一構造。app_ver2 固有の差分のみ以下に記す（それ以外は
EfficientAD 設計書 §1 と同じ）。

**app_ver2 固有の追加（保持する。EfficientAD には存在しない）**:
- `common.skip_download` / `common.skip_upload`: ver2 backend 連携用の薄いラッパフラグ（`retraining-integration-answers.md` 記載の推奨改修）。デフォルト `false` で後方互換。
- `_spawn_with_gpu_env` が `multiprocessing.get_context("spawn")` を明示指定（Docker/Linux 環境での CUDA fork 問題対策）。EfficientAD は Windows 前提のためこの修正が無い。
- `pipeline_mode=stage_only`: FTP取得+前処理のみ実施して停止するモード。

**ver2 backend との結合契約（変更しない）**:
- `backend/src/services/training_service.py` が `cwd=training_dir` で
  `python pipline.py common.target_color=... common.pipeline_mode=...` を subprocess 起動する。
- 成功判定は「ONNX 生成の有無」＋ stdout の `パイプライン完了` マーカー。終了コードは信頼できない
  （並列時に子プロセスの例外が親に伝播しない）。
- **フロントエンド（`frontend/src/pages/retrainingProgress.ts`）が stdout の特定文言を正規表現でパースし、
  ジョブ全体のステージ（バックアップ中／学習中／モデル出力・評価中／完了）を検出している。**
  これは EfficientAD 設計書には存在しない制約であり、本移行で最も注意すべき挙動保存対象。

| 文言（正規表現相当） | 現在の出力元 | 移行後の出力元 |
|---|---|---|
| `バックアップ作成中` | `pipline.py` | `pipline.py`（変更なし） |
| `モノクロAIの学習を開始します` / `カラーAIの学習を開始します` / `並列学習 GPU 割当` | `pipline.py` | `pipline.py`（変更なし） |
| `^Exported ONNX:` | `model_exporter.py` | `deploy/model_export.py` |
| `パイプライン完了` | `pipline.py` | `pipline.py`（変更なし） |
| tqdm `Current loss:` desc書式 | `train_func_color.py` / `train_func_monochro.py` | `train/color.py` / `train/monochro.py` |

上記の文言・出現順序・改行仕様は１文字も変更しない。各 seam の characterization test には、
数値結果に加えてこれらの stdout 行の存在・文言一致を含める。

---

## 2. モジュールマップ（`training/` 配下、stage-primary / color・monochro=data-domain secondary）

```
training/
├── pipline.py             # composition root。import元のみ変更。skip_download/skip_upload/
│                          #   spawn context/stage_only は現状のまま維持
├── model.py                # 共有モデル定義 (EfficientADFullModel)。Seam3で forward() を
│                          #   utils/scoring_transform.py 呼び出しに置換
├── model_handler.py         # 現状未接続のまま維持（ADR-3継承、スコープ外）
├── conf/ , 0_pretraining/   # 変更なし
├── dataset/                 # 新設（Seam6）
│   ├── __init__.py           # 公開API: DatasetManager, MultiFTPManager, FTPManager(download専用)
│   ├── manager.py             # DatasetManager: backup_model, process_annotated_images,
│   │                          #   split_pool_to_dataset（accumulate_pool/stage_defect/
│   │                          #   backup_dataset/backup_annotated_data は呼び出し元ゼロを
│   │                          #   確認済み→ADR-7と同様に削除）
│   └── ftp_download.py         # FTPManager/MultiFTPManager の download_images 系のみ
├── train/                    # 新設（Seam5）。EfficientAD は "training/" だが、対象範囲自体が
│                             #   training/ のため入れ子回避のため train/ と命名（ADR-app1）
│   ├── __init__.py            # 公開API: train_color, train_monochro
│   ├── common.py               # train_func_color/monochro 間で完全重複していた低レベル関数
│   ├── color.py                 # train_func_color.py の内容（train_color）
│   └── monochro.py              # train_func_monochro.py の内容（train_monochro）
├── evaluation/                 # 新設（Seam2 + Seam3）
│   ├── __init__.py              # 公開API: Evaluator
│   ├── evaluator.py              # Evaluator クラス
│   └── scoring.py                 # utils/scoring_transform.py 経由のスコア計算（Seam3, ADR-6）
├── deploy/                       # 新設（Seam1 + Seam4）
│   ├── __init__.py                # 公開API: upload_model, export_model
│   ├── ftp_upload.py               # upload_model（ONNXのFTPアップロード）
│   └── model_export.py              # export_model（ONNXエクスポート、旧 model_exporter.py）
└── utils/                          # 既存 + scoring_transform.py 追加（Seam3）
```

**Cross-cutting配置**（EfficientAD §2 と同じ）:
- **orchestration**: `pipline.py` に限定。各stageモジュールはDAG/GPU割当/並列制御を知らない
- **lineage**: `utils/mlflow_logger.py`（`MLflowManager`）が一元管理
- **artifact registry**: ファイルシステム(`./6_model/{color}/{mode}/`)。単独書き手は「train が `.pth`+`para.json` を書く」「deploy が ONNX を書く」の二段

---

## 3. 依存方向（P5: acyclic, pipeline-forward only）

```
dataset → train → evaluation
                → deploy
```

- `evaluation` と `deploy` はいずれも `train` の出力（`.pth` + `para.json`）のみを読み、互いには依存しない
- 逆依存禁止。`preprocessing` は独立モジュール化しない（ADR-7継承）
- feedback loop は現状存在しない。将来追加する場合は orchestration（`pipline.py`）経由とする

---

## 4. 境界契約（スキーマ、EfficientAD §4 と同一）

| 境界 | 契約内容 |
|---|---|
| `dataset → train` | train/test分割済みデータセットのディレクトリ構造 + 画像フォーマット |
| `train → evaluation`, `train → deploy` | `para.json`スキーマ（`teacher_mean_1d`/`teacher_std_1d`, `q_st_start/end`, `q_ae_start/end`, `channel_weights`, `threshold`, `edge_mask_w`, `cand1_*`, `image_size_height/width`, `st_para`, `ae_para`）+ `.pth`×3（teacher/student/autoencoder） |
| `deploy → 外部検査PC` | ONNXグラフ（前処理・スコアリング完全内包）+ ONNXメタデータ（`threshold`, `edge_mask_w`, `cand1_enabled`, `cand1_T`, `score_type`）+ 入力テンソル契約（`(1,3,H,W)`, 0–255レンジ, RGB, HWC→CHW） |
| `deploy → ver2 backend`（app_ver2固有、pipeline-edge契約） | subprocess CLI契約: `cwd=training/`, `python pipline.py common.target_color=<str> common.pipeline_mode=<train\|stage_only> [key=value...]`。stdout: 上記stage markerの文言・順序・`パイプライン完了`終端行。成功判定はONNX生成有無 |

---

## 5. スキュー対策（P8）— Seam3（ADR-6相当）

EfficientAD と同一コードベースであるため、同じ不整合が存在する可能性が高い:
- `model.py: EfficientADFullModel.forward()`（deploy側）は cand1 有効時に `max(raw/A, zval/Z)` を計算するが、
  `utils/evaluation_pipeline.py`（evaluation側の現状実装）には cand1 ロジックが実装されていない。
- 結果として、cand1 有効な monochro モデルでは、`Evaluator.evaluate()` が記録する AUC/F1/miss_rate/
  false_alarm_rate が実際に検査PCへ配布されるモデルの判定ロジックを反映していない。

**対応方針（承認済み）**: EfficientAD ADR-6 と同じ統合を行う。
1. `model.py` のフォワード計算を `utils/scoring_transform.py` に共有ライブラリとして抽出
2. `evaluation/scoring.py` はこの共有ライブラリを呼ぶように変更し、独自の `_predict_st_only`/`predict()` 実装を廃止
3. transform-parityテスト（C-4）を追加: 同一画像・同一 `para.json` に対し、共有ライブラリ経由のスコアと
   （統合前の）`model.py` 直接呼び出しのスコアが一致することを保証
4. 統合作業前に、現状の evaluation と deploy の出力差分（cand1有効時の既知の不整合）を
   characterization test として記録 → 統合後に一致することを確認

**影響**: cand1 が有効な monochro モデルについて、移行前後で評価指標の値が変わる（悪化ではなく不整合の解消）。
ユーザー承認済み。

---

## 6. CI Gate（P12）

| Gate | 保護する原則 | app_ver2固有の実装上の注意 |
|---|---|---|
| stage間の逆依存禁止（evaluation/deploy → train/datasetへの逆import検出） | P5 | 走査対象は `training/` 配下のみに限定する（`PROJECT_ROOT` を `training/` に設定。`backend/`等の無関係なPythonコードを誤検出しないため。EfficientADはリポジトリ全体がtraining相当のためこの限定が不要だった） |
| 各モジュールのpublic API外からの内部import禁止 | P4 | 同上 |
| `utils.ftp_common.upload_file_to_ftp` を `deploy` 外から直接importできない | P4 | Seam1で導入 |
| transform-parityテスト: evaluationとdeployが同一スコアリングライブラリを使用 | P8（§5） | EfficientADの `tests/evaluation/test_scoring_parity.py` を移植・適応 |
| characterization test: 各seam抽出後、抽出前の実測値（数値＋stdout文言）との差分がないことを確認 | 移行の安全網 | 数値（AUC/F1/miss_rate/false_alarm_rate/ONNXスコア）に加え、§1の stdout マーカー文言・順序も検証対象に含める（app_ver2固有の追加） |

---

## 7. ADR（決定と根拠）

EfficientAD設計書のADR-1〜7をすべて継承する（内部アーキテクチャ統一・evaluationの非ゲート維持・
model_handler未接続維持・分散ストレージ容認・color/monochro並行運用維持・スコアリング統合・
preprocessing独立モジュール化見送り）。以下はapp_ver2固有の追加ADRのみ記す。

**ADR-app1: 学習ステージパッケージ名を `train/` にする**
- 決定: EfficientADの `training/`（リポジトリルート直下）ではなく `train/` と命名する
- 理由: app_ver2では対象範囲自体が `training/` ディレクトリのため、EfficientAD通りにすると
  `training/training/color.py` のような入れ子になり可読性が下がる
- トレードオフ: EfficientADとのファイルパス完全一致は失われるが、意味的な役割（学習ステージの公開API）は同一

**ADR-app2: stdout文言（stage検出マーカー・tqdm書式）を挙動保存の対象に追加する**
- 決定: `pipline.py`/`model_exporter.py`/`train_func_*.py` が出力する特定のprint文言・tqdmのdesc書式を、
  各seamのcharacterization testで数値結果と同様に厳密検証する
- 理由: ver2フロントエンド（`retrainingProgress.ts`）がこれらの文言を正規表現でパースし、
  ジョブ全体のステージ表示に使っている。EfficientAD設計書にはこの制約が存在しない（EfficientADには
  stdoutを解釈する外部システムが無いため）
- 影響範囲: `バックアップ作成中` / `モノクロAIの学習を開始します` / `カラーAIの学習を開始します` /
  `並列学習 GPU 割当` / `^Exported ONNX:` / `パイプライン完了` / tqdm `Current loss:` desc

**ADR-app3: CLAUDE.mdの「training/学習本体改変禁止」規約に対する明示的例外**
- 決定: 本モジュラモノリス移行に限り、`training/`配下の構造変更（ファイル分割・パッケージ化）を許可する
- 理由: ユーザー承認済み（2026-07-21）。学習アルゴリズム自体（数式・パラメータ・学習ループの計算内容）は
  変更しない。変更対象は「どのファイルにどの関数が置かれているか」という構造のみ
- 適用範囲: 本移行タスクに限る。将来の別タスクでの学習本体改変には別途承認が必要

**ADR-app4: CI gateの走査対象を `training/` 配下に限定する**
- 決定: import境界検証・逆依存検出のCI gateは、`training/` 配下のみをrglob対象とする
- 理由: app_ver2はEfficientADと異なり、同一リポジトリに `backend/`（FastAPI）等の無関係なPythonコードを
  含むため、リポジトリ全体を走査すると誤検出・パフォーマンス低下を招く

---

## 8. 抽出順序（strangler-fig）と characterization test 計画

EfficientADと同じ順序（低結合・低リスクから）。各seam抽出後、CI gateを即座に導入する。

| 順序 | Seam | 内容 | characterization test（数値 + stdout文言） |
|---|---|---|---|
| 1 | `deploy`のFTPアップロード境界化 | `utils/ftp_common.py`のアップロード関数を`deploy.upload_model`に集約。CI gate即時導入 | アップロード先host/port/path一致。`skip_upload=true`時のスキップ文言保存 |
| 2 | `evaluation`のモジュール境界確立 | `utils/evaluation_pipeline.py`系を`evaluation`パッケージへ切り出し | 既存モデル(`.pth`+`para.json`)+固定テスト画像でのAUC/F1/miss_rate/false_alarm_rate実測値 |
| 3 | `evaluation`⇄`deploy`スコアリング統合（§5, ADR-6） | `model.py`のforward計算を`utils/scoring_transform.py`へ抽出し両者から呼ぶ。transform-parityテスト追加 | 統合前のevaluation出力とdeploy(ONNX相当)出力の差分を記録→統合後の一致を確認 |
| 4 | `deploy`（ONNXエクスポート）の境界確立 | `model_exporter.py`を`deploy/model_export.py`へ。`export_model`公開API化 | 固定入力でのONNX出力スコア一致。`Exported ONNX:`文言保存 |
| 5 | `train`の共通化 | `train_func_color.py`/`train_func_monochro.py`の完全重複関数を`train/common.py`へ集約 | seed固定・小規模データでの学習再現性（許容範囲内一致）。tqdm `Current loss:` desc書式保存 |
| 6 | `dataset`の境界確立（ADR-7相当） | FTP取得〜`split_pool_to_dataset`までを`dataset`パッケージへ抽出 | pool/staging振分・train/test分割結果のファイル一覧一致。`バックアップ作成中`等の文言保存 |

各seamの完了条件（EfficientAD migration-workflow Step6と同一）:
1. モジュール境界の公開APIを新設し、characterization testでPASSを確認（TDD red→green）
2. `pipline.py`を新APIへリダイレクトし、旧実装を削除
3. CI gate（境界の逆行防止）を追加し、逆行を意図的に起こしてFAILすることを確認
4. `training/tests/test_pipline_skip_flags.py` / `test_pipline_spawn_context.py` のパッチ対象を
   新しい境界に合わせて更新し、既存の意図（skip_download/skip_upload・spawn context）が保たれていることを確認

---

## 完了チェックリスト

- 各抽出モジュールが出力契約（モジュールマップ・依存規則・境界契約・CI gate）を満たす
- 抽出順序（§8）がSeam6までクローズまで追跡される
- クローズした各seamにCI gateが有効化されている
- `training/tests/test_pipline_skip_flags.py` / `test_pipline_spawn_context.py` が新しい境界に対して緑化されている
- §1のstdoutマーカー文言がすべて移行前後で一致する（フロントエンドのステージ検出が壊れていないことの証拠）
- ver2 backend（`training_service.py`）からのsubprocess起動が変更なく動作する（CLI契約の保存）
