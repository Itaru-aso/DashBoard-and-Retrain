import os
import shutil
import datetime

import cv2

from utils.image_preprocessing import load_image_as_byte_array, process_image
from utils.split_manager import split_pool_to_train_test


class DatasetManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.target_color = cfg.common.target_color
        # mode 別画像サイズ
        self.image_sizes = {
            "monochro": (cfg.monochro.image_size_height, cfg.monochro.image_size_width),
            "color": (cfg.color.image_size_height, cfg.color.image_size_width),
        }
        self.dataset_path = cfg.common.dataset_path
        self.model_dir = cfg.common.model_dir
        self.download_dir = cfg.common.download_dir
        self.backup_dir = cfg.common.backup_dir

        # モードごとのモデル保存パス
        self.model_paths = {
            "monochro": os.path.join(self.model_dir, str(self.target_color), "monochro"),
            "color": os.path.join(self.model_dir, str(self.target_color), "color"),
        }

    def _backup(self, source_paths, backup_root, subfolder, color_folder=True):
        """
        共通のバックアップ処理
        source_paths: モードごとのコピー元パス辞書
        backup_root: バックアップのルートディレクトリ
        subfolder: コピー先の末尾パス（例："train"）
        color_folder:色番のフォルダを作成するかどうか
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if color_folder:
            backup_base_dir = os.path.join(backup_root, str(self.target_color), timestamp)
        else:
            backup_base_dir = os.path.join(backup_root, timestamp)

        for mode, src_dir in source_paths.items():
            dst_dir = os.path.join(backup_base_dir, mode, subfolder)
            if os.path.exists(src_dir):
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                print(f"Copied from {src_dir} to {dst_dir}")
            else:
                print(f"Source directory {src_dir} does not exist.")

    def backup_model(self):
        """モデルファイルのバックアップ作成"""
        self._backup(self.model_paths, os.path.join(self.backup_dir, "model"), "")

    @staticmethod
    def _copy_if_new(image_array, dst_path):
        """OpenCV 画像配列を dst_path に書き込み (既存はスキップ)"""
        if not os.path.exists(dst_path):
            cv2.imwrite(dst_path, image_array)

    def process_annotated_images(self, modes=("monochro", "color")):
        """ダウンロード済み画像を前処理し、mode 別に pool/staging へ振り分け。

        - monochro/good   → pool/{color}/monochro/good_pool/   (差分追加)
        - monochro/defect → defect_staging_monochro/{color}/   (人手ゲート待ち)
        - color/good      → pool/{color}/color/good_pool/      (差分追加)
        - color/defect    → defect_staging/{color}/            (人手ゲート待ち)

        Args:
            modes: 処理対象 mode の iterable (既定 monochro+color)。
                   特定 mode のみ前処理したい場合に絞り込む (例: ("monochro",))。
        """
        color = str(self.target_color)

        for mode in modes:
            img_h, img_w = self.image_sizes[mode]
            if mode == "color":
                ds_cfg = self.cfg.color.defect_staging
            else:
                ds_cfg = self.cfg.monochro.defect_staging

            pool_good = os.path.join(self.cfg.common.pool_base, color, mode, "good_pool")
            staging = os.path.join(self.cfg.common.staging_dir, color, mode)
            os.makedirs(pool_good, exist_ok=True)
            os.makedirs(staging, exist_ok=True)

            base_dir = os.path.join(self.download_dir, color, mode)
            auto_split = ds_cfg.get("auto_split_halves", True)

            # good: 前処理 → pool に差分追加
            for root, dirs, files in os.walk(base_dir):
                parts = root.split(os.path.sep)
                if "good" in parts or "auto_good" in parts:
                    for f in files:
                        if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                            continue
                        p = os.path.join(root, f)
                        # 1 枚の破損 (0 byte / decode 失敗) で色番全体が落ちないよう個別捕捉してスキップ
                        try:
                            image_data = load_image_as_byte_array(p)
                            top, bottom, _ = process_image(image_data, img_w, img_h, mode)
                        except Exception as e:  # noqa: BLE001
                            print(f"⚠ [{mode}/good] スキップ {os.path.basename(p)}: {type(e).__name__}: {e}", flush=True)
                            continue
                        name, ext = os.path.splitext(os.path.basename(p))
                        self._copy_if_new(top, os.path.join(pool_good, f"{name}_0{ext}"))
                        self._copy_if_new(bottom, os.path.join(pool_good, f"{name}_1{ext}"))

            # defect: 前処理 → staging に追加 (auto_split_halves で分岐)
            clear_flag = ds_cfg.get("clear_before_download", False)
            if clear_flag:
                shutil.rmtree(staging, ignore_errors=True)
                os.makedirs(staging, exist_ok=True)
            for root, dirs, files in os.walk(base_dir):
                parts = root.split(os.path.sep)
                if "defect" in parts:
                    for f in files:
                        if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                            continue
                        p = os.path.join(root, f)
                        if auto_split:
                            try:
                                image_data = load_image_as_byte_array(p)
                                top, bottom, _ = process_image(image_data, img_w, img_h, mode)
                            except Exception as e:  # noqa: BLE001
                                print(f"⚠ [{mode}/defect] スキップ {os.path.basename(p)}: {type(e).__name__}: {e}", flush=True)
                                continue
                            name, ext = os.path.splitext(os.path.basename(p))
                            self._copy_if_new(top, os.path.join(staging, f"{name}_0{ext}"))
                            self._copy_if_new(bottom, os.path.join(staging, f"{name}_1{ext}"))
                        else:
                            dst = os.path.join(staging, f)
                            if not os.path.exists(dst):
                                shutil.copy2(p, dst)

            print(f"✅ {mode}: good→pool, defect→staging に振り分け完了")

    def split_pool_to_dataset(self, color: str, mode: str = "color"):
        """pool/{color}/{mode}/{good,defect}_pool/ → dataset/{color}/{mode}/{train,test}/* を生成。

        ディレクトリ構成 (color と monochro で対称):
            color:    pool/{color}/color/{good,defect}_pool/    → dataset/{color}/color/...
            monochro: pool/{color}/monochro/{good,defect}_pool/ → dataset/{color}/monochro/...

        utils.split_manager.split_pool_to_train_test を使って pool を train/test に振り分ける。
        既存の train/test データは保持し、pool のデータを差分追加する。

        Args:
            color: 色番号 (例: "841")
            mode: "color" or "monochro"
        Returns:
            dict: 振り分け結果 {'good_to_train', 'good_to_test', 'defect_to_train', 'defect_to_test', 'files'}
        """
        if mode not in ("color", "monochro"):
            raise ValueError(f"unknown mode: {mode}")

        good_pool = os.path.join(self.cfg.common.pool_base, str(color), mode, "good_pool")
        defect_pool = os.path.join(self.cfg.common.pool_base, str(color), mode, "defect_pool")
        dataset_path = os.path.join(self.cfg.common.dataset_path, str(color), mode)
        train_ratio = float(self.cfg[mode].get("pool_train_ratio", 0.7))
        seed = int(self.cfg.common.get("seed", 42))
        result = split_pool_to_train_test(
            defect_pool_path=defect_pool,
            good_pool_path=good_pool,
            dataset_path=dataset_path,
            train_ratio=train_ratio,
            seed=seed,
        )
        print(
            f"✅ {mode} split: {result['good_to_train']} good→train, "
            f"{result['good_to_test']} good→test, "
            f"{result['defect_to_train']} defect→train, "
            f"{result['defect_to_test']} defect→test"
        )
        return result
