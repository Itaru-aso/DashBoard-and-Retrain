# training/deploy/ftp_upload.py
"""deployステージ: 学習済みモデル(ONNX)を検査PCへFTP配布する。"""
import os

from utils.ftp_common import upload_file_to_ftp


def upload_model_to_host(host_cfg, model_dir, target_color, mode):
    """1台の検査PCへONNXモデルをFTPアップロードする。

    Args:
        host_cfg: cfg.common.ftp_hosts の要素1件
            (name/host/username/password/model_port等を含む)
        model_dir: ONNXモデルの格納ルート (cfg.common.model_dir)
        target_color: 色番号
        mode: "color" or "monochro"
    """
    target_color = str(target_color)
    model_file_name = f"{target_color}_{mode}_model.onnx"
    onnx_file_path = os.path.join(model_dir, target_color, mode, model_file_name)

    upload_file_to_ftp(
        host=host_cfg.host,
        port=host_cfg.model_port,
        username=host_cfg.username,
        password=host_cfg.password,
        local_file_path=onnx_file_path,
        remote_folder=os.path.join("./"),
    )


def upload_model(cfg, target_color, mode):
    """全検査PCへONNXモデルをFTPアップロードする（deployステージの公開API）。

    いずれかのホストへのアップロードが失敗しても、他のホストへの
    アップロードは継続する（1台の障害でパイプライン全体を止めない）。
    """
    for host_cfg in cfg.common.ftp_hosts:
        try:
            print(f"📤 [{host_cfg.name}] へアップロード中...")
            upload_model_to_host(host_cfg, cfg.common.model_dir, target_color, mode)
            print(f"✅ [{host_cfg.name}] アップロード完了")
        except Exception as e:
            print(f"⚠ [{host_cfg.name}] へのアップロード失敗（スキップ）: {e}")
