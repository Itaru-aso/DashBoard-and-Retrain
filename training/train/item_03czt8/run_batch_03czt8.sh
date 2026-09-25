#!/bin/bash
# 03CZT8向け複数色番の一括学習バッチスクリプト。
# `training/run_batch.sh`(既存)のコピーであり、既存ファイルは一切変更しない
# (`.kiro/specs/retraining/new-item-03czt8-model-creation.md` 決定3の精神を踏襲)。
#
# 既存run_batch.shとの差分:
#   - pipline.py直接実行ではなく `-m train.item_03czt8.pipline`(パッケージ実行、
#     絶対import `from train.item_03czt8...` を解決するために必須)。
#   - dataset_id は03CZT8固定値(UUIDではなくアイテムコード文字列)。
#     色番(053/841)はbinary/{color}/サブディレクトリで区別されるため、
#     dataset_id自体は色番間で共通。
#   - common.skip_upload=true(edge側C#対応は別タスクのため配信スキップ、決定9)。
#   - ONNX完了判定パスは 6_model_03czt8 (出力パス分離、決定4)。
#
# 前提: 841番はmonochroのexport_root/export_root_marginデータが無いため、
# 841番を含める場合は事前にmonochroデータが揃っていることを確認すること
# (揃うまでは COLORS="053" のみで実行する)。
#
# 使い方:
#   1. 下の COLORS と BATCH_NAME を編集する
#   2. GPUが空いていることを確認する (nvidia-smi)。1色番の学習でGPU2枚を使い切るため、
#      複数色番を並列に投げない(このスクリプトは色番を順次処理する設計)。
#   3. nohup bash run_batch_03czt8.sh > /dev/null 2>&1 &  disown
set -u

TRAINING_DIR="D:/0032011/GitLab/shisui/app_ver2/training"
PYTHON="/c/Users/0032011/.pyenv/pyenv-win/versions/3.10.5/python3.exe"
DATASET_MONO="03CZT8-monochro"
DATASET_COLOR="03CZT8-color"
DATASET_MONO_MARGIN="03CZT8-monochro"

BATCH_NAME="batch_03czt8_053_841"       # ← ログファイル名に使う識別子。バッチごとに変える
COLORS="053 841"                        # ← 対象色番（スペース区切り）。841はmonochroデータが
                                         #   揃うまで外しておくこと(現時点ではエラーになる)。

PROGRESS="$TRAINING_DIR/logs/chain_${BATCH_NAME}.progress.log"

mkdir -p "$TRAINING_DIR/logs"

for c in $COLORS; do
  LOG="$TRAINING_DIR/logs/pipeline_${c}_${BATCH_NAME}.out.log"
  echo "$(date '+%F %T') [START] color=$c" >> "$PROGRESS"

  (
    cd "$TRAINING_DIR" || exit 1
    PYTHONUTF8=1 "$PYTHON" -m train.item_03czt8.pipline \
      common.target_color=$c \
      common.dataset_id_monochro=$DATASET_MONO \
      common.dataset_id_color=$DATASET_COLOR \
      common.dataset_id_monochro_margin=$DATASET_MONO_MARGIN \
      common.pipeline_mode=train \
      common.skip_download=true \
      common.skip_upload=true \
      color.mlflow.enabled=false \
      monochro.mlflow.enabled=false \
      > "$LOG" 2>&1
  )
  rc=$?

  mono_onnx="$TRAINING_DIR/6_model_03czt8/${c}/monochro/${c}_monochro_model.onnx"
  color_onnx="$TRAINING_DIR/6_model_03czt8/${c}/color/${c}_color_model.onnx"
  marker="NG"; grep -q "パイプライン完了" "$LOG" 2>/dev/null && marker="OK"
  mono_ok="NG"; [ -f "$mono_onnx" ] && mono_ok="OK"
  color_ok="NG"; [ -f "$color_onnx" ] && color_ok="OK"

  echo "$(date '+%F %T') [END] color=$c rc=$rc completion_marker=$marker mono_onnx=$mono_ok color_onnx=$color_ok" >> "$PROGRESS"
done

echo "$(date '+%F %T') [ALL_DONE] ${BATCH_NAME} のチェーン処理が終了しました" >> "$PROGRESS"
