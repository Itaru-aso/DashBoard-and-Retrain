# training/tests/deploy/test_ftp_upload_characterization.py
"""現状の MultiFTPManager.upload_onnx_model() の挙動を固定するテスト。

Seam1移行（training/deployパッケージへの切り出し）前の挙動を記録し、
Task2で実装する新実装 (deploy.upload_model) が同じ値を出すことの比較対象とする。

実行: cd training && python -m pytest tests/deploy/test_ftp_upload_characterization.py -v
"""
import os
from unittest.mock import patch

from omegaconf import OmegaConf

import pipline


def _make_cfg():
    return OmegaConf.create({
        "common": {
            "model_dir": "./6_model",
            "target_color": "841",
            "mode": "color",
            "ftp_common": {"local_root": "./annotated_data"},
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


def test_multi_ftp_manager_uploads_onnx_to_every_host():
    cfg = _make_cfg()
    cfg.common.mode = "color"
    mgr = pipline.MultiFTPManager(cfg)

    with patch("pipline.upload_file_to_ftp") as mock_upload:
        mgr.upload_onnx_model()

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
