# 新規サイズアイテム(03CZT8)モデル作成マニュアル(Windows/PowerShell)

> `training/train/item_03czt8/` (新設フォルダ、既存の`training/`コードは無変更)を使い、
> 新規サイズアイテム03CZT8のTeacher pretraining〜学習パイプライン実行までを行うための
> 運用手順。設計判断・技術的前提の詳細は
> `.kiro/specs/retraining/new-item-03czt8-model-creation.md`(ADR)を参照。
> 実行環境はWindows(PowerShellまたはGit Bash)を対象とする。

## 1. 前提

- 03CZT8はcolor_no="053"を05CZT8と共有しているため、出力パス
  （`model_dir`/`pool_base`/`dataset_path`/`splits_dir`/`backup_dir`）は
  05CZT8等の既存色番と完全に分離されている（`6_model_03czt8`等、既存の`6_model`等とは別）。
- crop位置・overlap（monochro: x0=655/width=950/overlap=50、color: x0=418/width=1280/
  overlap=50）は実測済みの値であり、`training/train/item_03czt8/train_monochro.py`内の
  モジュール定数（`CROP_X0`/`CROP_WIDTH`/`OVERLAP`）に埋め込まれている。設定ファイルでの
  上書きは不要。
- リサイズサイズは`training/train/item_03czt8/conf_03czt8.yaml`の
  `monochro.image_size_height/width`（384×512）・`color.image_size_height/width`
  （384×384）で管理する。
- **色番841番は現時点でmonochroのexport_root/export_root_marginデータが存在しない**
  （colorのみ、3158ファイル・053番と同一のcrop設定で前処理済み）。841番のmonochro学習を
  行う場合は、データが揃っていることを事前に確認すること。
- `pipline.py` は1回の起動で1色番（monochro・color両方）を学習する。複数色番のバッチ機能は
  `pipline.py` 自体には無い。GPUは2枚（monochro用・color用）を1色番の学習で使い切るため、
  **複数色番を並列に投げない**（1色番ずつ順次実行する）。

## 2. Teacher pretraining（初回のみ・色番非依存）

03CZT8向けのリサイズサイズ（monochro 384×512, color 384×384）に対応する
pretraining済みTeacher重みが無い場合、`training/train/item_03czt8/`配下の
pretrainingスクリプトで新規作成する。**Teacher重みは色番非依存**（monochro/colorの
モード単位で1つ）のため、053・841どちらの学習でも同じファイルを使う。

### 2.1 事前確認

- ImageNetデータセット（`D:/0032011/ILSVRC/Data/CLS-LOC/train`）が存在すること。
- GPUが2枚空いていること（monochro用・color用を別GPUに割り当てて同時実行できる）。
- dry-run（数イテレーションのみの動作確認）は実装時に完了済み
  （teacher/student出力shapeの一致を確認済み）。

### 2.2 実行（PowerShell、2つのターミナルで並列実行）

```powershell
cd D:\0032011\GitLab\shisui\app_ver2\training

# ターミナル1: monochro (GPU 0)
python -m train.item_03czt8.pretraining_monochro --gpu_id 0 `
  -o train\item_03czt8\pretraining_output\monochro

# ターミナル2: color (GPU 1)
python -m train.item_03czt8.pretraining_color --gpu_id 1 `
  -o train\item_03czt8\pretraining_output\color
```

`-m train.item_03czt8.xxx` という**パッケージ実行形式**が必須（`train/item_03czt8/xxx.py`を
直接パスで実行すると`from train.item_03czt8...`の絶対importが解決できず
`ModuleNotFoundError: No module named 'train'`になる）。**カレントディレクトリを必ず
`training/`にしてから実行すること**。

monochroは150,000イテレーション、colorは60,000イテレーション（既存05CZT8等と同スケール）。
実行時間は数時間規模を想定。

### 2.3 Teacher重みの配置

実行完了後、出力フォルダに生成された`teacher_small_{mode}_final_state.pth`を、
`_resolve_teacher_weights_path()`が期待する命名規則でリネームし、
`training/0_pretraining/`（既存05CZT8等と共有ディレクトリ、ファイル名が異なるので
上書きはしない）に配置する。

| pretraining出力 | 配置先(リネーム) |
|---|---|
| `train\item_03czt8\pretraining_output\monochro\teacher_small_monochro_final_state.pth` | `0_pretraining\384_512_teacher_small_monochro_wide_resnet101_final_state.pth` |
| `train\item_03czt8\pretraining_output\color\teacher_small_color_final_state.pth` | `0_pretraining\384_384_teacher_small_color_wide_resnet101_final_state.pth` |

```powershell
Copy-Item train\item_03czt8\pretraining_output\monochro\teacher_small_monochro_final_state.pth `
  0_pretraining\384_512_teacher_small_monochro_wide_resnet101_final_state.pth
Copy-Item train\item_03czt8\pretraining_output\color\teacher_small_color_final_state.pth `
  0_pretraining\384_384_teacher_small_color_wide_resnet101_final_state.pth
```

`conf_03czt8.yaml`の`teacher_weights: null`のままでよい（`image_size_height/width`から
自動的にこのファイル名を解決する）。

## 3. 学習パイプライン単発実行

```powershell
cd D:\0032011\GitLab\shisui\app_ver2\training
python -m train.item_03czt8.pipline
```

`train\item_03czt8\conf_03czt8.yaml`がデフォルトで読み込まれ、
`common.target_color`（既定"053"）を対象に以下が順に実行される:

1. バックアップ作成（`backup_03czt8\`）
2. export_root→pool振り分け（metadata.jsonは`export_root/03CZT8-color(monochro)/`に
   作成済み、色番非依存の共通ファイル）
3. pool→dataset分割（`3_pool_03czt8\` → `4_dataset_03czt8\`）
4. monochro/color学習（GPU2枚で並列、`parallel_train: true`）
5. ONNX export（`6_model_03czt8\{color_no}\{monochro,color}\`）
6. 評価（defectサンプル無しのため`channel_weights`は`unsupervised`フォールバック、
   F1最大化ではなく99.5パーセンタイルで閾値決定）
7. `skip_upload: true`のため配信（FTPアップロード）はスキップ

色番を変える場合はCLI overrideで指定する:

```powershell
python -m train.item_03czt8.pipline common.target_color=841
```

（841番はmonochroデータが揃うまで実行しないこと。実行するとmonochro段階で
`FileNotFoundError`になる。）

## 4. 複数色番の一括学習（バッチ）

`training/run_batch.sh`(既存05CZT8等向け)と同じ運用パターンを、03CZT8向けに
`training/train/item_03czt8/run_batch_03czt8.ps1`（PowerShell版）・
`run_batch_03czt8.sh`（Git Bash版）として用意している。

### 4.1 PowerShellで実行する場合

```powershell
cd D:\0032011\GitLab\shisui\app_ver2\training\train\item_03czt8
notepad run_batch_03czt8.ps1   # $Colors・$BatchName を編集
.\run_batch_03czt8.ps1
```

バックグラウンド実行する場合:

```powershell
Start-Process powershell -ArgumentList '-File', '.\run_batch_03czt8.ps1' -WindowStyle Hidden
```

### 4.2 現時点の運用

841番のmonochroデータが揃っていないため、**当面は`$Colors = @("053")`のみで実行する**。
841番のmonochroデータが揃った時点で`$Colors = @("053", "841")`に戻せば、053→841の順に
自動で一括処理される（1色番ずつ順次実行、GPU排他は保たれる）。

### 4.3 進捗確認

- 全体進捗: `logs\chain_{バッチ名}.progress.log`（各色番の開始/終了、ONNX生成有無`OK`/`NG`、
  パイプライン完了マーカーを記録）
- 個別ログ: `logs\pipeline_{色番}_{バッチ名}.out.log`

## 5. トラブルシューティング

- **`ModuleNotFoundError: No module named 'train'`**: カレントディレクトリが`training/`に
  なっていない。`cd D:\0032011\GitLab\shisui\app_ver2\training`してから`-m`形式で実行する。
- **Teacher重みが見つからない（`FileNotFoundError`）**: `0_pretraining\`に
  `384_512_teacher_small_monochro_wide_resnet101_final_state.pth`/
  `384_384_teacher_small_color_wide_resnet101_final_state.pth`が配置されているか確認する
  （§2.3）。
- **`RuntimeError: Input type (torch.cuda.FloatTensor) and weight type (torch.FloatTensor)`**:
  pretrainingスクリプト内でモデルと入力テンソルのデバイスが不一致。
  `--gpu_id`を明示的に指定して実行しているか確認する（既定は`cuda:0`）。
- **841番の学習でmonochro段階がエラーになる**: monochroのexport_root/export_root_margin
  データが無い（§1参照）。データが揃うまで841番はcolorのみの実行に留める、または待つ。
