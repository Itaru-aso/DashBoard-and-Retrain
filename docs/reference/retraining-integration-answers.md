# モデル再学習ワークフロー連携 — 要件への回答

> 対象: `retraining-integration-requirements.md`（ver2 spec 側からの情報要件 A〜D）への回答。
> 既存学習パイプライン（本リポジトリ `retrain_app_CW`）の実コードに基づく。
> 日付: 2026-06-30 / 対象コミット: feature/ftp-download-redesign

---

## 0. 結論サマリ

- **起動口は2系統あり、spec の想定（`from pipline import` / subprocess）とほぼ一致**する。綴りは想定どおり `pipline`（typo ではなく実ファイル名）。
- **1回の起動で monochro と color の両方**を学習し、ONNX 出力→評価→FTP 配信まで `pipline.py` が一気通貫で行う。
- **対象色は `common.target_color` 単体（色番文字列）**。size/chain/tape は学習側では扱わない。
- **GPU はプログラム任せ**（`parallel_train=true` で2枚自動割当: monochro=GPU0 / color=GPU1）。
- ⚠️ **成功判定は「終了コード」では不十分**（並列時は子プロセスの失敗が親に伝播しない）。**ONNX 生成＋完了ログ**で判定するのが確実。
- ⚠️ **学習側に FTP 配信が既に組み込まれている**（完了時に自動アップロード）。ver2 が配信を制御するなら最小改修（スキップ flag）を推奨。
- ⚠️ **挙げられた4ファイルだけでは移植不可**。実際の依存は `model.py / model_exporter.py / model_handler.py / utils/ 一式 + 教師重み`。逆に `train_app.py`(GUI) は ver2 連携には**不要**。

---

## 1. 「この4ファイル＋config で移植できる」か？ → 部分的に NO

挙げられたファイル（`train_func_monochro.py` / `train_func_color.py` / `pipline.py` / `conf/config.yaml` / `train_app.py`）は**入口と設定**ではあるが、学習機能の**実行に必要な依存closure**は下記まで広がる。

### 移植に必要な最小ファイル集合（headless 連携用）

| 区分 | ファイル | 役割 |
|---|---|---|
| エントリ/統括 | `pipline.py` | パイプライン統括・CLIエントリ・FTP・並列学習・評価・配信 |
| 学習本体 | `train_func_monochro.py` / `train_func_color.py` | 各モードの学習ループ（重み・para.json 保存） |
| モデル定義 | `model.py` | `EfficientADFullModel`（推論統合モデル）・`load_para` |
| ONNX 出力 | `model_exporter.py` | 学習済み重み→統合 ONNX 書き出し |
| ONNX 補助 | `model_handler.py` | `ONNXModelHandler`（pipline が import） |
| 共通utils | `utils/` 一式 | `common, edge_mask, channel_weights, raw_shift_dataset, transforms, ftp_common, image_preprocessing, split_manager, mlflow_logger, evaluation_pipeline` ほか（相互依存あり） |
| 設定 | `conf/config.yaml` | ハイパラ・パス・FTP接続先 |
| **データ依存** | `0_pretraining/*.pth` | **教師(Teacher)重み。これが無いと学習不可** |

### ver2 連携に「不要」なもの

- **`train_app.py`（customtkinter GUI）** … 学習の呼び出し方の一例にすぎない。ver2 は独自のジョブ管理UIを持つため**移植不要**。headless 入口は `pipline.py`。
- `triage_manager.py` … GUI 仕分けタブ用ロジック。学習本体には不要。

> **推奨**: 個別ファイルを拾うより、**リポジトリの学習サブセット（上表）をまるごと**配置する方が確実。相互 import が多く、抜けると ImportError になる。

---

## 2. 各プログラムの説明

### `pipline.py`（707行・統括）
パイプライン全体を統括する中核。`TrainingPipeline(cfg).execute()` が以下を順に実行:
1. 既存モデルのバックアップ
2. FTP ダウンロード（`train` 時、monochro/color の good+defect を検査PCから取得）
3. 前処理・pool/staging 振り分け
4. pool→dataset split
5. **並列学習**（`_spawn_with_gpu_env` で物理GPUごとに子プロセス spawn、`run_trainer`→`Trainer.run`→`train_monochro`/`train_color`）
6. ONNX エクスポート（`ModelExporter`）＋評価（`Evaluator`）＋ **FTP アップロード**（`MultiFTPManager`）
- `pipeline_mode=stage_only` なら 2〜3 のみ（人手レビュー用に staging まで）。
- CLI エントリ: `python pipline.py key=value ...`（dotlist override、色番の8進数誤解釈を `_safe_cli_overrides` で回避）。

### `train_func_monochro.py`（813行）/ `train_func_color.py`（685行）
各モードの**学習本体**。`train_monochro(cfg, mgr=None)` / `train_color(cfg, mgr=None)` が flat な sub_cfg を受け取り:
- データセット構築（monochro は raw 画像から crop shift augmentation `RawShiftImageFolder`）
- EfficientAD（Teacher-Student + AutoEncoder）学習、val_interval ごとに validation、early stopping
- best 更新時に `teacher/student/autoencoder_state_best.pth` と `para.json`（正規化統計・閾値・channel_weights・cand1）を `6_model/{color}/{mode}/` に保存
- 進捗は `print()` で標準出力に随時出力

### `model.py` / `model_exporter.py` / `model_handler.py`
- `model.py`: 推論用統合モデル `EfficientADFullModel`（ST/AE スコア統合・閾値・channel_weights・edge_mask・cand1 を内包）。
- `model_exporter.py`: 学習済み重み＋para.json から統合モデルを構築し、**`{color}_{mode}_model.onnx`**（opset11, input/output, メタデータに threshold 等）を書き出す。
- `model_handler.py`: ONNX 取り扱い補助（pipline が import）。

### `conf/config.yaml`（254行・OmegaConf）
`common`（対象色・各ステージパス・FTP接続先・GPU・並列フラグ）、`monochro`/`color`（画像サイズ・学習ハイパラ・augmentation・channel_weights・MLflow）を保持。

### `train_app.py`（450行・GUI）※ver2連携には不要
customtkinter 製 GUI。「学習」「仕分け」タブを持ち、内部で `OmegaConf.load → cfg.common.target_color 設定 → TrainingPipeline(cfg).execute()` をスレッド実行するだけ。ver2 はこの GUI を**自前のジョブ管理に置き換える**ので移植対象外。

---

## 3. 要件への回答

### A. 最優先

**A-1. 起動インターフェース** — 両対応:
- **CLI（推奨）**: `python pipline.py common.target_color=501 common.pipeline_mode=train`
  - dotlist override で任意の config 値を上書き可。色番は `_safe_cli_overrides` が自動でクォートし `'076'→62` の8進数誤変換を防止。
- **関数 import**: `from pipline import TrainingPipeline` → `TrainingPipeline(cfg).execute()`（`cfg = OmegaConf.load("conf/config.yaml")` 後に `cfg.common.target_color` 等を設定）。
- 綴りは spec 想定どおり **`pipline`**（実ファイル名がこの綴り）。

**A-2. 入力パラメータ**:
- **対象色**: `common.target_color` の**単体（色番文字列、例 `'501'`/`'076'`）**。size/chain/tape は学習側では未使用。
- **画像の所在**: **固定 config パス**（`common.download_dir=./1_download`, `dataset_path=./4_dataset` 等、すべて CWD 相対）。`--data-dir` 相当の専用引数は無いが、dotlist で `common.download_dir=...` のように上書き可能。
- **monochro/color**: **1回の起動で両方**を学習（`execute()` が両 mode をループ。別々2回起動ではない）。
- **GPU 指定**: **プログラム任せ**。`common.parallel_train=true`（既定）で GPU 枚数を自動検出し、**2枚以上なら monochro=GPU0 / color=GPU1**（`CUDA_VISIBLE_DEVICES` を子プロセスごとに切替えて spawn）、1枚なら両方 GPU0。`--gpus` 引数は無い。`parallel_train=false` で直列。
- **実コマンド例**: `python pipline.py common.target_color=501 common.pipeline_mode=train`

**A-3. 出力（成果物）** — `6_model/{color}/{mode}/`（`model_dir` 既定 `./6_model`）:
- **ONNX**: `{color}_{mode}_model.onnx`
  - 例: `6_model/501/color/501_color_model.onnx`、`6_model/501/monochro/501_monochro_model.onnx`
  - ⚠️ mode 文字列は **`monochro`**（spec 例の `501_mono_model.onnx` は誤り。正しくは `501_monochro_model.onnx`）。
  - opset 11、input `input` / output `output`、dynamic batch、metadata に `threshold` / `channel_weights_enabled` / `edge_mask_w` / `cand1_*` / `score_type`。
- 併せて `teacher/student/autoencoder_state_best.pth`、`para.json`。
- **成功/失敗判定**: ⚠️ **終了コードは信頼できない**（A-2 並列時、子プロセスの例外は親 exit code に伝播しない／内部で多くの例外を握って続行）。**推奨判定: 当該 ONNX ファイルの生成有無**（＋標準出力末尾の `パイプライン完了` マーカー）。

### B. 重要

**B-1. 進捗・ログ**:
- **標準出力（print）**。**行テキスト・日本語**（例 `Validation Loss: 0.1234`、`Early stopping triggered...`、絵文字つき状態行、`Exported ONNX: ...`）。
- JSON 行・進捗率の数値出力は**無し**。`epoch n/N` の整形も無し（val_interval ごとの loss 等が出る）。
- 並列時は monochro/color 2子プロセスの出力が**混在**して stdout に流れる。
- → WebSocket 配信は「そのまま流す」か、主要マーカー（`Validation Loss` / `Exported ONNX` / `パイプライン完了` / 例外トレース）を**抽出整形**する方式を推奨。

**B-2. 失敗時の挙動**:
- 学習中の例外 → 並列時は**子プロセスがクラッシュ**（親は `join` するだけで exit code に出ない）。直列時は親に例外伝播。
- **中途半端な ONNX**: ONNX 書き出しは学習完了後の段階なので、学習失敗時は **ONNX が生成されない**（＝生成有無で判定できる）。
- **再実行（上書き）**: `backup_model()` が先に既存をバックアップ、export は上書き。概ね**安全に再実行可**。

**B-3. 実行時間・リソース・同時実行**:
- 目安: `epochs` 40〜50、`max_train_step` monochro=30000 / color=25000。データ量・GPUで数十分〜数時間。
- **GPU 2枚を占有**（`parallel_train=true` 時）。
- ⚠️ **プログラム側に同時実行ガードは無い**。共有ディレクトリ（pool/dataset/model）と GPU を使うため、**同時複数実行は衝突する**。spec の「同時1本・FIFO」は **ver2 側で保証が必要**（学習側は前提にしていない）。

**B-4. キャンセル**:
- 並列時は **multiprocessing(spawn) で子プロセスを生む**。→ 親だけ kill しても子が残るため、**プロセスツリーごと kill** が必要。
- GPU メモリはプロセス終了で解放。残留ロックは無し（出力は best.pth/para.json で、途中状態は次回実行で上書き）。
- → キャンセルは「プロセスグループ単位の kill」で実装可能。

### C. 配信まわり

**C-1. ONNX の FTP 配信**:
- **学習側に既に実装済み**。`execute()` 末尾で mode ごとに `MultiFTPManager.upload_onnx_model()` を呼び、`config.common.ftp_hosts` の**全台**へ `model_port` 経由で `./`（FTPルート直下）にアップロードする。
- spec 方針（FTP 実 I/O は training 側）と**一致**。ただし現状 `execute()` は**配信を無条件実行**する。
- → ver2 が「配信トリガー・現行モデル記録」を持つなら、**配信をスキップする flag（例 `common.skip_upload=true`）を学習側に追加**するか、`execute()` を「学習＋ONNXまで」と「配信」に分割する**最小改修**を推奨。呼び出しは `mgr.upload_onnx_model()`（host ごと）/ `MultiFTPManager(cfg).upload_onnx_model()`（全台）。

### D. 環境・前提

**D-1. 学習用画像の用意**: ⚠️ **spec と乖離あり**。
- 現状の `train` モードは、**学習側が検査PCから FTP で画像を取得**する（別機能が所定パスに置く前提ではない）。
- 一方 `stage_only` モード＋人手レビュー後の `train` 再実行では、**`1_download` に配置済みの画像**を使う（FTP DL をスキップ）。
- → ver2 が「画像は別機能が用意（収集スコープ外）」とするなら、**FTP DL を行わない運用（pre-placed + DL スキップ）に寄せる**設計合意が必要。

**D-2. 依存・実行環境**:
- **Python 3.11 / torch 2.5.1+cu121 / CUDA**（onnx, onnxruntime, opencv, omegaconf, customtkinter[GUIのみ], mlflow 等）。
- ⚠️ spec 想定の Docker（cu128・Blackwell 対応）と **CUDA ビルドが不一致**（cu121）。Blackwell GPU で動かすなら **torch の cu128 系への入替/イメージ整合確認**が必要。
- customtkinter は **GUI 専用**で、headless 連携（pipline.py 直叩き）には不要。

**D-3. 設定ファイル**:
- `conf/config.yaml`（OmegaConf YAML, 254行）。
- **ジョブごとに差し替える項目**: `common.target_color`（必須）、`common.pipeline_mode`（`train`/`stage_only`）。必要に応じ `common.parallel_train`、各 `mlflow.enabled`、`common.*_dir` パス。
- すべて **CLI dotlist override で差し替え可**（ファイル書換え不要）。

---

## 4. ver2 連携でおすすめする最小改修（任意）

1. **配信分離 flag**: `common.skip_upload` を追加し、`execute()` の `upload_onnx_model()` 呼び出しをガード（C-1）。配信は ver2 の `deployment_service` が担当できる。
2. **成功判定の明確化**: 終了時に `pipline.py` で「ONNX 生成チェック→未生成なら `sys.exit(1)`」を追加すると、ver2 の成功/失敗判定が exit code で取れる（B-2）。
3. **進捗の機械可読化（任意）**: 主要節目で `[PROGRESS] mode=color step=…/…` のような1行マーカーを print すると WebSocket 配信が安定（B-1）。
4. **同時実行は ver2 で FIFO 保証**（学習側はガードしない・B-3）。

> 上記1〜3は「学習ロジックを変えない・出力互換を保つ」範囲の薄いラッパ改修で実現可能。
