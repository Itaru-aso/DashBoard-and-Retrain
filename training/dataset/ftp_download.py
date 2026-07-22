import os
from ftplib import FTP

from utils.ftp_common import AnnotationDownloader


class FTPManager:
    def __init__(self, cfg, host_config):
        self.cfg = cfg
        self.name = host_config.name
        self.host = host_config.host
        self.username = host_config.username
        self.password = host_config.password
        self.monochro_port = host_config.monochro_port
        self.color_port = host_config.color_port
        self.local_root = cfg.common.ftp_common.local_root

    def download_images(self):
        """検査PC にFTP接続し、アノテーション領域を走査して good/defect に振り分けてダウンロード。

        リモート階層: /cameraN_image/annotated_data/{color}/{year}/{month}/{day}/{PR_id}/{kind}/
        ローカル:     {download_dir}/{color}/{mode}/{good|defect}/<PC名>_<YYYYMMDD>_<kind>_<元名>
        """
        mode = self.cfg.common.mode
        target_color = str(self.cfg.common.target_color)

        if mode == "monochro":
            port = self.monochro_port
            remote_root = "/camera1_image/annotated_data"
        elif mode == "color":
            port = self.color_port
            remote_root = "/camera2_image/annotated_data"
        else:
            print(f"⚠ 未対応モード: {mode}")
            return

        local_good = os.path.join(
            self.cfg.common.download_dir, target_color, mode, "good"
        )
        local_defect = os.path.join(
            self.cfg.common.download_dir, target_color, mode, "defect"
        )
        os.makedirs(local_good, exist_ok=True)
        os.makedirs(local_defect, exist_ok=True)

        ftp = FTP()
        ftp.encoding = "utf-8"
        try:
            ftp.connect(self.host, port, timeout=10)
            ftp.login(user=self.username, passwd=self.password)
            downloader = AnnotationDownloader(
                ftp=ftp,
                remote_root=remote_root,
                target_color=target_color,
                local_good=local_good,
                local_defect=local_defect,
                pc_name=self.name,
            )
            result = downloader.download()
            print(
                f"📥 [{self.name}/{mode}] downloaded={result['downloaded']}, "
                f"skipped={result['skipped']}, errors={result['errors']}, "
                f"unknown_kinds={sorted(result['unknown_kinds'])}"
            )
        except Exception as e:
            print(f"⚠ [{self.name}/{mode}] 取得失敗 (skip): {e}")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass


class MultiFTPManager:
    """複数検査PCへの一括FTP操作"""
    def __init__(self, cfg):
        self.cfg = cfg
        self.managers = [
            FTPManager(cfg, host_cfg)
            for host_cfg in cfg.common.ftp_hosts
        ]

    def download_images(self):
        # rmtree 廃止: AnnotationDownloader の差分ダウンロード (size+MDTM) を活かす。
        # ファイル名は <PC名>_<YYYYMMDD>_<kind>_<元名> でユニーク化されるため、
        # 複数 PC からのマージで衝突しない (同一画像なら上書きしても無害)。
        for mgr in self.managers:
            try:
                print(f"📥 [{mgr.name}] からダウンロード中...")
                mgr.download_images()
                print(f"✅ [{mgr.name}] ダウンロード完了")
            except Exception as e:
                print(f"⚠ [{mgr.name}] からのダウンロード失敗（スキップ）: {e}")
