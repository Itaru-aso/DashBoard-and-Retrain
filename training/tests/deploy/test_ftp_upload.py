# training/tests/deploy/test_ftp_upload.py
"""deploy.upload_model の公開APIテスト。

Task1のcharacterization testと同じ期待値（host/port/local_file_path/remote_folder）を
検証することで、旧実装(pipline.MultiFTPManager)との挙動の一致を保証する。

実行: cd training && python -m pytest tests/deploy/test_ftp_upload.py -v
"""
import os
from unittest.mock import patch

from omegaconf import OmegaConf

import deploy


def _make_cfg():
    return OmegaConf.create({
        "common": {
            "model_dir": "./6_model",
            "ftp_hosts": [
                {
                    "name": "PC1", "host": "10.0.0.1",
                    "username": "u1", "password": "p1",
                    "monochro_port": 2121, "color_port": 2122, "model_port": 2123,
                },
                {
                    "name": "PC2", "host": "10.0.0.2",
                    "username": "u2", "password": "p2",
                    "monochro_port": 3121, "color_port": 3122, "model_port": 3123,
                },
            ],
        }
    })


def test_upload_model_uploads_onnx_to_every_host():
    cfg = _make_cfg()

    with patch("deploy.ftp_upload.upload_file_to_ftp") as mock_upload:
        deploy.upload_model(cfg, target_color="841", mode="color")

    assert mock_upload.call_count == 2
    mock_upload.assert_any_call(
        host="10.0.0.1", port=2123, username="u1", password="p1",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )
    mock_upload.assert_any_call(
        host="10.0.0.2", port=3123, username="u2", password="p2",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )


def test_upload_model_continues_when_one_host_fails():
    """1台のアップロードが失敗しても他のホストへのアップロードを継続する
    （MultiFTPManager.upload_onnx_model()の現状挙動: try/exceptで1台ずつスキップ）。"""
    cfg = _make_cfg()

    with patch("deploy.ftp_upload.upload_file_to_ftp") as mock_upload:
        mock_upload.side_effect = [RuntimeError("接続失敗"), None]
        deploy.upload_model(cfg, target_color="841", mode="color")

    assert mock_upload.call_count == 2
