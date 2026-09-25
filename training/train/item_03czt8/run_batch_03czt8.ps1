# 03CZT8向け複数色番の一括学習バッチスクリプト(Windows PowerShell版)。
# `run_batch_03czt8.sh`(Git Bash版)と同内容。既存の `training/run_batch.sh` は
# 一切変更しない（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` 決定3の
# 精神を踏襲）。
#
# 前提: 841番はmonochroのexport_root/export_root_marginデータが無いため、
# 841番を含める場合は事前にmonochroデータが揃っていることを確認すること
# (揃うまでは $Colors = @("053") のみで実行する)。
#
# 使い方:
#   1. 下の $Colors と $BatchName を編集する
#   2. GPUが空いていることを確認する (nvidia-smi)。1色番の学習でGPU2枚を使い切るため、
#      複数色番を並列に投げない(このスクリプトは色番を順次処理する設計)。
#   3. バックグラウンド実行する場合:
#      Start-Process powershell -ArgumentList '-File', '.\run_batch_03czt8.ps1' -WindowStyle Hidden
#      通常実行する場合はそのまま `.\run_batch_03czt8.ps1` を実行する。

$TrainingDir = "D:\0032011\GitLab\shisui\app_ver2\training"
$Python = "C:\Users\0032011\.pyenv\pyenv-win\versions\3.10.5\python3.exe"
$DatasetMono = "03CZT8-monochro"
$DatasetColor = "03CZT8-color"
$DatasetMonoMargin = "03CZT8-monochro"

$BatchName = "batch_03czt8_053_841"     # ← ログファイル名に使う識別子。バッチごとに変える
$Colors = @("053", "841")               # ← 対象色番。841はmonochroデータが揃うまで外しておくこと
                                          #   (現時点ではエラーになる)。

$LogsDir = Join-Path $TrainingDir "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
$Progress = Join-Path $LogsDir "chain_$BatchName.progress.log"

foreach ($c in $Colors) {
    $Log = Join-Path $LogsDir "pipeline_${c}_$BatchName.out.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $Progress -Value "$timestamp [START] color=$c"

    Push-Location $TrainingDir
    $env:PYTHONUTF8 = "1"
    & $Python -m train.item_03czt8.pipline `
        "common.target_color=$c" `
        "common.dataset_id_monochro=$DatasetMono" `
        "common.dataset_id_color=$DatasetColor" `
        "common.dataset_id_monochro_margin=$DatasetMonoMargin" `
        "common.pipeline_mode=train" `
        "common.skip_download=true" `
        "common.skip_upload=true" `
        "color.mlflow.enabled=false" `
        "monochro.mlflow.enabled=false" `
        *> $Log
    $rc = $LASTEXITCODE
    Pop-Location

    $monoOnnx = Join-Path $TrainingDir "6_model_03czt8\$c\monochro\${c}_monochro_model.onnx"
    $colorOnnx = Join-Path $TrainingDir "6_model_03czt8\$c\color\${c}_color_model.onnx"

    $marker = "NG"
    if (Test-Path $Log) {
        if (Select-String -Path $Log -Pattern "パイプライン完了" -Quiet) { $marker = "OK" }
    }
    $monoOk = if (Test-Path $monoOnnx) { "OK" } else { "NG" }
    $colorOk = if (Test-Path $colorOnnx) { "OK" } else { "NG" }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $Progress -Value "$timestamp [END] color=$c rc=$rc completion_marker=$marker mono_onnx=$monoOk color_onnx=$colorOk"
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $Progress -Value "$timestamp [ALL_DONE] $BatchName のチェーン処理が終了しました"
