import json
import os
import shutil
import datetime

import cv2
import numpy as np

from utils.image_preprocessing import load_image_as_byte_array
from utils.split_manager import split_pool_to_train_test

IMAGE_EXTENSIONS = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')
# pool 同期で1クラスから消す枚数がこの比率と枚数を両方超えたら削除を止める（一覧の部分取得対策）
POOL_SYNC_MAX_DELETE_RATIO = 0.2
POOL_SYNC_MAX_DELETE_COUNT = 10


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

        - monochro/good   → pool/{color}/monochro/good_pool/   (同期)
        - monochro/defect → pool/{color}/monochro/defect_pool/ (同期)
        - color/good      → pool/{color}/color/good_pool/      (同期)
        - color/defect    → pool/{color}/color/defect_pool/    (同期)

        pool は export_root に同期する。付け替え・削除・invalid 化で export_root の対応クラスに
        無くなった画像は pool から削除する。デコード失敗でスキップした画像は export_root に存在する
        ため削除しない。export_root のそのクラスの画像が1枚も無いとき、metadata に無いカテゴリの
        フォルダがあるとき、1クラスの削除が上限（既定 20% かつ 10 枚超。
        `common.pool_sync_max_delete_ratio` で変更可）を超えるときは削除しない
        （@.kiro/specs/retraining/pool-dataset-sync-split.md 決定3）。

        Args:
            modes: 処理対象 mode の iterable (既定 monochro+color)。
                   特定 mode のみ処理したい場合に絞り込む (例: ("monochro",))。
        """
        color = str(self.target_color)
        export_root = self.cfg.common.export_root
        max_ratio = float(self.cfg.common.get("pool_sync_max_delete_ratio",
                                              POOL_SYNC_MAX_DELETE_RATIO))
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
            expected = {pool_good: set(), pool_defect: set()}
            unknown_categories = []

            for category_id in sorted(os.listdir(binary_dir)):
                category_dir = os.path.join(binary_dir, category_id)
                if not os.path.isdir(category_dir):
                    continue
                category = category_map.get(category_id)
                if category is None:
                    unknown_categories.append(category_id)
                    continue
                if category.get("invalid_flg") == "1":
                    continue
                dest = pool_good if category.get("on_class") == "0" else pool_defect

                for f in sorted(os.listdir(category_dir)):
                    if not f.lower().endswith(IMAGE_EXTENSIONS):
                        continue
                    src = os.path.join(category_dir, f)
                    normalized = self._normalize_export_filename(f)
                    expected[dest].add(normalized.lower())
                    # 1 枚の破損 (0 byte / decode 失敗) で色番全体が落ちないよう個別捕捉してスキップ
                    try:
                        image_data = load_image_as_byte_array(src)
                        img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)
                        resized = cv2.resize(img, (img_w, img_h), interpolation=cv2.INTER_AREA)
                    except Exception as e:  # noqa: BLE001
                        print(f"⚠ [{mode}] スキップ {f}: {type(e).__name__}: {e}", flush=True)
                        continue
                    self._copy_if_new(resized, os.path.join(dest, normalized))

            if unknown_categories:
                # metadata が古い・書き込み途中だと付け替え先を判定できないため、この mode は削除しない
                print(f"⚠ [{mode}] metadata に無いカテゴリがあるため同期削除をスキップ: {unknown_categories}",
                      flush=True)
                expected = {}
            for pool_dir, names in expected.items():
                if not names:
                    # export_root のクラスが空に見える場合（共有の同期途中・移動等）に pool を丸ごと消さない
                    print(f"⚠ [{mode}] export_root に画像が無いため同期削除をスキップ: {pool_dir}",
                          flush=True)
                    continue
                pool_files = [f for f in os.listdir(pool_dir)
                              if f.lower().endswith(IMAGE_EXTENSIONS)]
                # Windows はファイル名の大文字小文字を区別しないため小文字で比べる
                stale = [f for f in pool_files if f.lower() not in names]
                if (len(stale) > POOL_SYNC_MAX_DELETE_COUNT
                        and len(stale) > max_ratio * len(pool_files)):
                    print(f"⚠ [{mode}] 削除予定 {len(stale)}/{len(pool_files)} 枚が上限"
                          f"（{max_ratio:.0%}）を超えるため同期削除をスキップ: {pool_dir}"
                          f"（正当な付け替えなら common.pool_sync_max_delete_ratio を上げて再実行）",
                          flush=True)
                    continue
                for f in stale:
                    os.remove(os.path.join(pool_dir, f))
                    print(f"🗑 [{mode}] export_root に無いため pool から削除: {f}", flush=True)

            print(f"✅ {mode}: export_root→pool 振り分け完了 (dataset_id={dataset_id})")

    def split_pool_to_dataset(self, color: str, mode: str = "color"):
        """pool/{color}/{mode}/{good,defect}_pool/ → dataset/{color}/{mode}/{train,test}/* を生成。

        ディレクトリ構成 (color と monochro で対称):
            color:    pool/{color}/color/{good,defect}_pool/    → dataset/{color}/color/...
            monochro: pool/{color}/monochro/{good,defect}_pool/ → dataset/{color}/monochro/...

        utils.split_manager.split_pool_to_train_test を使って pool を train/test に振り分ける。
        dataset は pool に同期する（行き先と違う側・pool に無い画像は削除。pool-dataset-sync-split.md 決定2）。

        Args:
            color: 色番号 (例: "841")
            mode: "color" or "monochro"
        Returns:
            dict: 振り分け結果 {'good_to_train', 'good_to_test', 'defect_to_train', 'defect_to_test',
                'removed', 'files'}
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
