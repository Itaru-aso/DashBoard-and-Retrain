"""pipline.execute() の薄いラッパ改修（retraining task0）テスト。

`common.skip_download` / `common.skip_upload` で FTP ダウンロード / アップロードを
ガードできること、既定（false）では従来どおり呼ばれること（後方互換）を検証する。
学習本体・重い依存は import 段階でのみ必要で、execute() 内の学習/エクスポート/評価は
モック・パッチで無害化する（実学習・実 FTP は行わない）。

実行: cd training && python -m pytest tests/test_pipline_skip_flags.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import pipline


def _make_pipeline(skip_download: bool, skip_upload: bool):
    cfg = OmegaConf.create(
        {
            "common": {
                "target_color": "501",
                "pipeline_mode": "train",
                "parallel_train": False,
                "skip_download": skip_download,
                "skip_upload": skip_upload,
                "mode": "color",
            },
            "color": {"mlflow": {"enabled": False}},
            "monochro": {"mlflow": {"enabled": False}},
        }
    )
    p = pipline.TrainingPipeline.__new__(pipline.TrainingPipeline)
    p.cfg = cfg
    p.dataset_manager = MagicMock()
    p.ftp_manager = MagicMock()
    return p


def _run(pipe):
    # 学習・ONNX エクスポート・評価は task0 の対象外。実行を無害化する。
    with patch.object(pipline, "run_trainer"), patch.object(
        pipline, "build_sub_cfg", return_value=OmegaConf.create({})
    ), patch.object(pipline, "ModelExporter"), patch.object(pipline, "Evaluator"):
        pipe.execute()


def test_skip_download_true_skips_ftp_download():
    pipe = _make_pipeline(skip_download=True, skip_upload=False)
    _run(pipe)
    pipe.ftp_manager.download_images.assert_not_called()


def test_skip_upload_true_skips_ftp_upload():
    pipe = _make_pipeline(skip_download=False, skip_upload=True)
    _run(pipe)
    pipe.ftp_manager.upload_onnx_model.assert_not_called()


def test_flags_false_preserves_behavior():
    pipe = _make_pipeline(skip_download=False, skip_upload=False)
    _run(pipe)
    # 従来どおり monochro / color の2回ずつ呼ばれる（後方互換）。
    assert pipe.ftp_manager.download_images.call_count == 2
    assert pipe.ftp_manager.upload_onnx_model.call_count == 2
