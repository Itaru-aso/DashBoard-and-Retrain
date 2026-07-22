"""現状の pipline.FTPManager / pipline.MultiFTPManager の挙動を固定するテスト。

実行: cd training && python -m pytest tests/dataset/test_ftp_download.py -v
"""
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf


def _make_ftp_cfg(tmp_path, mode="monochro"):
    return OmegaConf.create({
        "common": {
            "mode": mode,
            "target_color": "841",
            "download_dir": str(tmp_path / "1_download"),
            "ftp_common": {"local_root": str(tmp_path / "1_download")},
        }
    })


def _make_host_cfg(name="PC1", host="192.0.2.1"):
    return OmegaConf.create({
        "name": name,
        "host": host,
        "username": "user",
        "password": "pass",
        "monochro_port": 21,
        "color_port": 22,
    })


def test_ftp_manager_download_images_monochro_connects_and_downloads(tmp_path):
    from dataset import FTPManager

    cfg = _make_ftp_cfg(tmp_path, mode="monochro")
    host_cfg = _make_host_cfg()
    mgr = FTPManager(cfg, host_cfg)

    fake_ftp_instance = MagicMock()
    fake_downloader = MagicMock()
    fake_downloader.download.return_value = {
        "downloaded": 3, "skipped": 1, "errors": 0, "unknown_kinds": set(),
    }
    with patch("dataset.ftp_download.FTP", return_value=fake_ftp_instance), \
         patch("dataset.ftp_download.AnnotationDownloader", return_value=fake_downloader) as mock_downloader_cls:
        mgr.download_images()

    fake_ftp_instance.connect.assert_called_once_with("192.0.2.1", 21, timeout=10)
    fake_ftp_instance.login.assert_called_once_with(user="user", passwd="pass")
    mock_downloader_cls.assert_called_once_with(
        ftp=fake_ftp_instance,
        remote_root="/camera1_image/annotated_data",
        target_color="841",
        local_good=str(tmp_path / "1_download" / "841" / "monochro" / "good"),
        local_defect=str(tmp_path / "1_download" / "841" / "monochro" / "defect"),
        pc_name="PC1",
    )
    fake_downloader.download.assert_called_once()
    fake_ftp_instance.quit.assert_called_once()


def test_ftp_manager_download_images_color_uses_color_port_and_root(tmp_path):
    from dataset import FTPManager

    cfg = _make_ftp_cfg(tmp_path, mode="color")
    host_cfg = _make_host_cfg()
    mgr = FTPManager(cfg, host_cfg)

    fake_ftp_instance = MagicMock()
    fake_downloader = MagicMock()
    fake_downloader.download.return_value = {
        "downloaded": 0, "skipped": 0, "errors": 0, "unknown_kinds": set(),
    }
    with patch("dataset.ftp_download.FTP", return_value=fake_ftp_instance), \
         patch("dataset.ftp_download.AnnotationDownloader", return_value=fake_downloader) as mock_downloader_cls:
        mgr.download_images()

    fake_ftp_instance.connect.assert_called_once_with("192.0.2.1", 22, timeout=10)
    mock_downloader_cls.assert_called_once_with(
        ftp=fake_ftp_instance,
        remote_root="/camera2_image/annotated_data",
        target_color="841",
        local_good=str(tmp_path / "1_download" / "841" / "color" / "good"),
        local_defect=str(tmp_path / "1_download" / "841" / "color" / "defect"),
        pc_name="PC1",
    )


def test_multi_ftp_manager_iterates_all_hosts(tmp_path):
    from dataset import FTPManager, MultiFTPManager

    cfg = OmegaConf.create({
        "common": {
            "mode": "color",
            "target_color": "841",
            "download_dir": str(tmp_path / "1_download"),
            "ftp_common": {"local_root": str(tmp_path / "1_download")},
            "ftp_hosts": [
                {"name": "PC1", "host": "192.0.2.1", "username": "u1", "password": "p1",
                 "monochro_port": 21, "color_port": 22},
                {"name": "PC2", "host": "192.0.2.2", "username": "u2", "password": "p2",
                 "monochro_port": 21, "color_port": 22},
            ],
        }
    })

    with patch.object(FTPManager, "download_images") as mock_download:
        mgr = MultiFTPManager(cfg)
        mgr.download_images()

    assert mock_download.call_count == 2
