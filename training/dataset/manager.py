import json
import os
import shutil
import datetime

import cv2
import numpy as np

from utils.image_preprocessing import load_image_as_byte_array
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

    @staticmethod
    def _load_category_map(export_root, dataset_id):
        """`export_root/{dataset_id}/metadata.json` を読み、category_id→category dict を返す。"""
        metadata_path = os.path.join(export_root, dataset_id, "metadata.json")
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        return {c["category_id"]: c for c in metadata.get("category", [])}

    @staticmethod
    def _resolve_binary_dir(export_root, dataset_id, color):
        """`export_root/{dataset_id}/binary/{color}/` を解決する。無ければ明確なエラーとする。"""
        binary_dir = os.path.join(export_root, dataset_id, "binary", color)
        if not os.path.isdir(binary_dir):
            raise FileNotFoundError(
                f"binary/{color} が見つかりません: {binary_dir}"
                f" (common.target_color と export_root の色番フォルダ名が一致しているか確認してください)"
            )
        return binary_dir

    @staticmethod
    def _normalize_export_filename(filename):
        """export_root の `_top`/`_bottom` 接尾を `split_manager` が期待する `_0`/`_1` に正規化する。"""
        name, ext = os.path.splitext(filename)
        if name.endswith("_top"):
            return f"{name[:-len('_top')]}_0{ext}"
        if name.endswith("_bottom"):
            return f"{name[:-len('_bottom')]}_1{ext}"
        return filename

    def process_annotated_images(self, modes=("monochro", "color")):
        """export_root の画像を mode 別に good_pool/defect_pool へ直接振り分ける。

        `export_root/{dataset_id}/metadata.json` の on_class で good/defect を判定し、
        invalid_flg=1 のカテゴリは除外する。export_root の画像は crop・top/bottom 分割済み・
        リサイズ未適用のため、ここではファイル名正規化 (`_top`→`_0`、`_bottom`→`_1`) と
        リサイズ (config の image_size) のみを行う。

        - monochro/good   → pool/{color}/monochro/good_pool/   (差分追加)
        - monochro/defect → pool/{color}/monochro/defect_pool/ (差分追加)
        - color/good      → pool/{color}/color/good_pool/      (差分追加)
        - color/defect    → pool/{color}/color/defect_pool/    (差分追加)

        Args:
            modes: 処理対象 mode の iterable (既定 monochro+color)。
                   特定 mode のみ処理したい場合に絞り込む (例: ("monochro",))。
        """
        color = str(self.target_color)
        export_root = self.cfg.common.export_root
        dataset_ids = {
            "monochro": self.cfg.common.dataset_id_monochro,
            "color": self.cfg.common.dataset_id_color,
        }

        for mode in modes:
            img_h, img_w = self.image_sizes[mode]
            dataset_id = dataset_ids[mode]

            pool_good = os.path.join(self.cfg.common.pool_base, color, mode, "good_pool")
            pool_defect = os.path.join(self.cfg.common.pool_base, color, mode, "defect_pool")
            os.makedirs(pool_good, exist_ok=True)
            os.makedirs(pool_defect, exist_ok=True)

            category_map = self._load_category_map(export_root, dataset_id)
            binary_dir = self._resolve_binary_dir(export_root, dataset_id, color)

            for category_id in sorted(os.listdir(binary_dir)):
                category_dir = os.path.join(binary_dir, category_id)
                if not os.path.isdir(category_dir):
                    continue
                category = category_map.get(category_id)
                if category is None or category.get("invalid_flg") == "1":
                    continue
                dest = pool_good if category.get("on_class") == "0" else pool_defect

                for f in sorted(os.listdir(category_dir)):
                    if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                        continue
                    src = os.path.join(category_dir, f)
                    # 1 枚の破損 (0 byte / decode 失敗) で色番全体が落ちないよう個別捕捉してスキップ
                    try:
                        image_data = load_image_as_byte_array(src)
                        img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)
                        resized = cv2.resize(img, (img_w, img_h), interpolation=cv2.INTER_AREA)
                    except Exception as e:  # noqa: BLE001
                        print(f"⚠ [{mode}] スキップ {f}: {type(e).__name__}: {e}", flush=True)
                        continue
                    normalized = self._normalize_export_filename(f)
                    self._copy_if_new(resized, os.path.join(dest, normalized))

            print(f"✅ {mode}: export_root→pool 振り分け完了 (dataset_id={dataset_id})")

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
