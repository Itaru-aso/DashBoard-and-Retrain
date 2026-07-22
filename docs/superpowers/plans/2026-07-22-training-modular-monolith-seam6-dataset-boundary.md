# training/ モジュラモノリス移行 Seam6: datasetの境界確立 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/pipline.py`の`DatasetManager`・`FTPManager`・`MultiFTPManager`を新規`training/dataset/`パッケージへ抽出し、`training/pipline.py`は`dataset`の公開APIのみを呼ぶ形にする。これがモジュラモノリス移行の最後のSeamである。

**Architecture:** strangler-fig方式。各クラスについて「現状のpipline.py上のコードにcharacterization testを書いてpass確認 → `dataset/`パッケージへ verbatim移動（未結線dead codeの4メソッドのみ削除） → テストのimport先を切替えて再pass確認（抽出前後の一致証明） → CI gateで境界を固定」を行う。設計根拠は `docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md` §2・§8（Seam6）、および先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-16-modular-monolith-seam6-dataset-boundary.md`）を参照。

**注記**: EfficientAD側のSeam6計画には設計書更新タスク（ADR-7追記等）が含まれるが、app_ver2の設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）は初回作成時（2026-07-21）から既に`preprocessing`独立モジュール化を見送る方針・モジュールマップ・依存図・境界契約・抽出順序をすべて反映済みのため、本計画では設計書更新タスクは不要（対応するタスクを含めない）。

**Tech Stack:** Python, pytest, OmegaConf, unittest.mock, cv2/numpy（characterization testの画像fixture用）

## Global Constraints

- strangler-fig: characterization test作成 → 抽出 → import切替後再検証 → CI gate。Seam1/2/4/5と同じ流れ
- `process_annotated_images`・`split_pool_to_dataset`・`backup_model`・`_backup`・`_copy_if_new`・`FTPManager`・`MultiFTPManager`のロジックは1文字も変更しない（コピー移動のみ）
- `accumulate_pool`・`stage_defect`・`backup_dataset`・`backup_annotated_data`の4メソッドは削除する（app_ver2の`training/`配下で呼び出し元ゼロを確認済み。EfficientADのADR-7と同じ結論）。付随して`DatasetManager.__init__`内の`mode_paths`・`download_paths`属性（削除対象メソッド専用で他から未参照）も削除する
- `utils/paths.py`・`conf/config.yaml`の`splits_dir`設定は本Seamの対象外。削除もフック付けも行わない（スコープ外、変更しない）
- `TrainingPipeline.execute()`のMLflow生成・並列学習・ONNXエクスポート/評価/アップロード部分は一切変更しない
- `バックアップ作成中`等のstdout文言保存対象（設計書ADR-app2）は本Seamの対象範囲には直接含まれないが、`DatasetManager.process_annotated_images`・`split_pool_to_dataset`内のprint文言も1文字も変更しない
- CI gateの走査対象は`training/`配下に限定する（設計書ADR-app4）
- `training/pipline.py`には本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が作業ツリーに残っている。Task3のコミット前に混入がないことを確認する
- 日本語コミットメッセージ、Conventional Commits形式（`<type>(<scope>): <subject>`）
- `training/tests/`配下に`__init__.py`は作らない（Seam3の`tests/model/`と同方針。`training/tests/dataset/`にも作らない）
- 自分の変更で未使用になったimportは削除する。元から未使用だったimport（`training/pipline.py`の`model_handler.ONNXModelHandler`等）はこのSeamでは触らない
- 対象ファイルの現状（2026-07-21時点、Seam1〜5完了後の状態、app_ver2の実ソースで確認済み）:
  - `training/pipline.py`の`DatasetManager`は**48-307行目**、`FTPManager`は**310-374行目**、`MultiFTPManager`は**377-396行目**
  - ベースラインテスト: `cd training && python -m pytest tests/ -v` で **43 passed**（2026-07-21時点、Seam1〜5完了後。実測済み）

---

## Task 1: DatasetManagerを`training/dataset/manager.py`へ抽出

**Files:**
- Create: `training/dataset/manager.py`
- Create: `training/dataset/__init__.py`
- Test: `training/tests/dataset/test_manager_characterization.py`

**Interfaces:**
- Consumes: なし
- Produces: `dataset.DatasetManager`（後続Task2が`training/dataset/__init__.py`を拡張、Task3が`training/pipline.py`からこの公開APIをimportする）

現状の`training/pipline.py:48-307`の`DatasetManager`のうち、以下4メソッドと関連する未使用化する属性を削除して移動する:
- `backup_dataset`(103-105)、`backup_annotated_data`(111-118)、`accumulate_pool`(120-149)、`stage_defect`(151-185) — 削除
- `__init__`内の`self.mode_paths`（`backup_dataset`専用）・`self.download_paths`（`backup_annotated_data`専用）属性 — 削除
- `_backup`・`backup_model`・`_copy_if_new`・`process_annotated_images`・`split_pool_to_dataset`・`__init__`の残り部分 — ロジック変更なしで移動

- [ ] **Step 1: characterization testを書く（現状の`pipline.DatasetManager`を対象に）**

`training/tests/dataset/test_manager_characterization.py`を新規作成:

```python
"""現状の pipline.DatasetManager の挙動を固定するテスト。

Seam6移行(datasetパッケージへの切り出し)前の挙動を記録し、
Task1で移動する dataset.DatasetManager が同じ結果を出すことの比較対象とする。

実行: cd training && python -m pytest tests/dataset/test_manager_characterization.py -v
"""
import os

import cv2
import numpy as np
from omegaconf import OmegaConf


def _make_cfg(tmp_path, target_color="841"):
    return OmegaConf.create({
        "common": {
            "target_color": target_color,
            "download_dir": str(tmp_path / "1_download"),
            "pool_base": str(tmp_path / "2_pool"),
            "staging_dir": str(tmp_path / "3_staging"),
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
            "backup_dir": str(tmp_path / "7_backup"),
        },
        "color": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
            "defect_staging": {"auto_split_halves": True, "clear_before_download": False},
        },
        "monochro": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
            "defect_staging": {"auto_split_halves": True, "clear_before_download": False},
        },
    })


def _write_fake_image(path, shape):
    img = np.zeros(shape, dtype=np.uint8)
    cv2.imwrite(str(path), img)


def test_process_annotated_images_color_routes_good_and_defect(tmp_path):
    from pipline import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    download_base = tmp_path / "1_download" / color / "color"
    good_dir = download_base / "good"
    defect_dir = download_base / "defect"
    good_dir.mkdir(parents=True)
    defect_dir.mkdir(parents=True)
    # color crop は crop_rectangle=(215,0,1675,H) を rotate(90°CW)後の画像に適用する。
    # rotate後の列数は rotate前の行数(H0)に等しいため、H0>=1890 が必要 (215+1675)。
    # 形状(H0,W0,3)=(1900,60,3)。
    _write_fake_image(good_dir / "g1.png", (1900, 60, 3))
    _write_fake_image(defect_dir / "d1.png", (1900, 60, 3))

    mgr = DatasetManager(cfg)
    mgr.process_annotated_images(modes=("color",))

    pool_good = tmp_path / "2_pool" / color / "color" / "good_pool"
    staging = tmp_path / "3_staging" / color / "color"
    assert sorted(os.listdir(pool_good)) == ["g1_0.png", "g1_1.png"]
    assert sorted(os.listdir(staging)) == ["d1_0.png", "d1_1.png"]


def test_process_annotated_images_monochro_routes_good_and_defect(tmp_path):
    from pipline import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    download_base = tmp_path / "1_download" / color / "monochro"
    good_dir = download_base / "good"
    defect_dir = download_base / "defect"
    good_dir.mkdir(parents=True)
    defect_dir.mkdir(parents=True)
    # monochro crop は crop_rectangle=(485,0,1250,H) を rotate なしで適用するため、
    # 画像は列数(W0)>=1735 が必要 (485+1250)。形状(H0,W0,3)=(100,1740,3)。
    _write_fake_image(good_dir / "g1.png", (100, 1740, 3))
    _write_fake_image(defect_dir / "d1.png", (100, 1740, 3))

    mgr = DatasetManager(cfg)
    mgr.process_annotated_images(modes=("monochro",))

    pool_good = tmp_path / "2_pool" / color / "monochro" / "good_pool"
    staging = tmp_path / "3_staging" / color / "monochro"
    assert sorted(os.listdir(pool_good)) == ["g1_0.png", "g1_1.png"]
    assert sorted(os.listdir(staging)) == ["d1_0.png", "d1_1.png"]


def test_split_pool_to_dataset_produces_expected_file_lists(tmp_path):
    from pipline import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    good_pool = tmp_path / "2_pool" / color / "color" / "good_pool"
    defect_pool = tmp_path / "2_pool" / color / "color" / "defect_pool"
    good_pool.mkdir(parents=True)
    defect_pool.mkdir(parents=True)
    for i in range(10):
        (good_pool / f"good_{i}_0.png").write_bytes(b"")
    for i in range(4):
        (defect_pool / f"defect_{i}_0.png").write_bytes(b"")

    mgr = DatasetManager(cfg)
    result = mgr.split_pool_to_dataset(color, mode="color")

    dataset_path = tmp_path / "4_dataset" / color / "color"
    train_good = sorted(os.listdir(dataset_path / "train" / "good"))
    test_good = sorted(os.listdir(dataset_path / "test" / "good" / "images"))
    train_defect = sorted(os.listdir(dataset_path / "train" / "defect"))
    test_defect = sorted(os.listdir(dataset_path / "test" / "defect" / "images"))

    # seed=42固定・train_ratio=0.7での実測値(既存コードを実行して記録した値)
    assert train_good == [
        "good_2_0.png", "good_3_0.png", "good_5_0.png",
        "good_6_0.png", "good_7_0.png", "good_8_0.png", "good_9_0.png",
    ]
    assert test_good == ["good_0_0.png", "good_1_0.png", "good_4_0.png"]
    assert train_defect == ["defect_1_0.png", "defect_2_0.png", "defect_3_0.png"]
    assert test_defect == ["defect_0_0.png"]
    assert result["defect_to_train"] == 3
    assert result["defect_to_test"] == 1
    assert result["good_to_train"] == 7
    assert result["good_to_test"] == 3


def test_backup_model_copies_model_dir(tmp_path):
    from pipline import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    model_mono = tmp_path / "6_model" / color / "monochro"
    model_mono.mkdir(parents=True)
    (model_mono / "para.json").write_text("{}")

    mgr = DatasetManager(cfg)
    mgr.backup_model()

    backup_root = tmp_path / "7_backup" / "model" / color
    timestamps = os.listdir(backup_root)
    assert len(timestamps) == 1
    copied = backup_root / timestamps[0] / "monochro" / "para.json"
    assert copied.is_file()
```

- [ ] **Step 2: 現状の`pipline.DatasetManager`に対して実行し、passすることを確認**

Run: `cd training && python -m pytest tests/dataset/test_manager_characterization.py -v`
Expected: 4 passed（`from pipline import DatasetManager`のまま、抽出前の挙動が記録された状態でpass）

- [ ] **Step 3: `training/dataset/manager.py`を新規作成し、DatasetManagerを4メソッド削除して移動**

`training/dataset/manager.py`:

```python
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
```

- [ ] **Step 4: `training/dataset/__init__.py`を新規作成**

```python
"""dataset モジュールの公開API。

FTP取得〜pool/staging振分〜train/test分割までを担う。
"""
from dataset.manager import DatasetManager

__all__ = ["DatasetManager"]
```

- [ ] **Step 5: テストのimportを`dataset`パッケージへ切替え、再実行してpassを確認**

`training/tests/dataset/test_manager_characterization.py`の4箇所全ての`from pipline import DatasetManager`を`from dataset import DatasetManager`に置換する（アサーション本体は1文字も変更しない）。

Run: `cd training && python -m pytest tests/dataset/test_manager_characterization.py -v`
Expected: 4 passed（抽出前後でファイル一覧・result辞書が完全一致 = characterization成功）

- [ ] **Step 6: コミット**

```bash
git add training/dataset/manager.py training/dataset/__init__.py training/tests/dataset/test_manager_characterization.py
git commit -m "$(cat <<'EOF'
feat(training-dataset): DatasetManagerをdatasetパッケージへ抽出し未結線メソッドを削除

training/pipline.py内のDatasetManagerをtraining/dataset/manager.pyへ抽出。
呼び出し元ゼロと確認済みの未結線メソッド4つ(accumulate_pool/stage_defect/
backup_dataset/backup_annotated_data)は削除。backup_model・
process_annotated_images・split_pool_to_datasetのロジックは1文字も変更なし
（tests/dataset/test_manager_characterization.pyで移動前後の一致を検証）。
EOF
)"
```

---

## Task 2: FTPManager/MultiFTPManagerを`training/dataset/ftp_download.py`へ抽出

**Files:**
- Create: `training/dataset/ftp_download.py`
- Modify: `training/dataset/__init__.py`
- Test: `training/tests/dataset/test_ftp_download.py`

**Interfaces:**
- Consumes: なし
- Produces: `dataset.FTPManager`, `dataset.MultiFTPManager`（Task3が`training/pipline.py`から`MultiFTPManager`をimportする）

`FTPManager.download_images()`は実際のFTP接続を行うため、`ftplib.FTP`と`utils.ftp_common.AnnotationDownloader`をモックした挙動固定テストを新規に書く（既存テストはゼロだったため、これは「新規追加」であり「抽出前後比較」ではない。ただし移動前後でテストのpatchターゲットが`pipline.FTP`→`dataset.ftp_download.FTP`に切り替わり、同じアサーションが通ることで移動の正しさを証明する）。

- [ ] **Step 1: 現状の`pipline.FTPManager`/`pipline.MultiFTPManager`を対象にテストを書く**

`training/tests/dataset/test_ftp_download.py`を新規作成:

```python
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
    from pipline import FTPManager

    cfg = _make_ftp_cfg(tmp_path, mode="monochro")
    host_cfg = _make_host_cfg()
    mgr = FTPManager(cfg, host_cfg)

    fake_ftp_instance = MagicMock()
    fake_downloader = MagicMock()
    fake_downloader.download.return_value = {
        "downloaded": 3, "skipped": 1, "errors": 0, "unknown_kinds": set(),
    }
    with patch("pipline.FTP", return_value=fake_ftp_instance), \
         patch("pipline.AnnotationDownloader", return_value=fake_downloader) as mock_downloader_cls:
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
    from pipline import FTPManager

    cfg = _make_ftp_cfg(tmp_path, mode="color")
    host_cfg = _make_host_cfg()
    mgr = FTPManager(cfg, host_cfg)

    fake_ftp_instance = MagicMock()
    fake_downloader = MagicMock()
    fake_downloader.download.return_value = {
        "downloaded": 0, "skipped": 0, "errors": 0, "unknown_kinds": set(),
    }
    with patch("pipline.FTP", return_value=fake_ftp_instance), \
         patch("pipline.AnnotationDownloader", return_value=fake_downloader) as mock_downloader_cls:
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
    from pipline import FTPManager, MultiFTPManager

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
```

- [ ] **Step 2: 現状の`pipline.FTPManager`/`pipline.MultiFTPManager`に対して実行し、passすることを確認**

Run: `cd training && python -m pytest tests/dataset/test_ftp_download.py -v`
Expected: 3 passed

- [ ] **Step 3: `training/dataset/ftp_download.py`を新規作成し、FTPManager・MultiFTPManagerをそのまま移動**

```python
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
```

- [ ] **Step 4: `training/dataset/__init__.py`を拡張**

```python
"""dataset モジュールの公開API。

FTP取得〜pool/staging振分〜train/test分割までを担う。
"""
from dataset.manager import DatasetManager
from dataset.ftp_download import FTPManager, MultiFTPManager

__all__ = ["DatasetManager", "FTPManager", "MultiFTPManager"]
```

- [ ] **Step 5: テストのimportとpatchターゲットを`dataset.ftp_download`へ切替え、再実行してpassを確認**

`training/tests/dataset/test_ftp_download.py`について:
- `from pipline import FTPManager` → `from dataset import FTPManager`（2箇所）
- `from pipline import FTPManager, MultiFTPManager` → `from dataset import FTPManager, MultiFTPManager`
- `patch("pipline.FTP", ...)` → `patch("dataset.ftp_download.FTP", ...)`（2箇所）
- `patch("pipline.AnnotationDownloader", ...)` → `patch("dataset.ftp_download.AnnotationDownloader", ...)`（2箇所）

アサーション本体は変更しない。

Run: `cd training && python -m pytest tests/dataset/test_ftp_download.py -v`
Expected: 3 passed（抽出前後で同一の呼び出し形状が保たれていることを確認）

- [ ] **Step 6: コミット**

```bash
git add training/dataset/ftp_download.py training/dataset/__init__.py training/tests/dataset/test_ftp_download.py
git commit -m "$(cat <<'EOF'
feat(training-dataset): FTPManager/MultiFTPManagerをdatasetパッケージへ抽出

training/pipline.py内のFTPManager・MultiFTPManagerをtraining/dataset/
ftp_download.pyへ抽出。ロジックは1文字も変更なし。既存テストがゼロだったため
新規characterization test(モックによる挙動固定)を追加し、patchターゲットが
pipline.FTP/AnnotationDownloader → dataset.ftp_download.FTP/AnnotationDownloader
に切り替わっても同じアサーションが通ることで移動の正しさを証明する。
EOF
)"
```

---

## Task 3: `training/pipline.py`を`dataset`パッケージ経由に切替え

**Files:**
- Modify: `training/pipline.py:1-28`（importブロック）
- Modify: `training/pipline.py:48-396`（`DatasetManager`・`FTPManager`・`MultiFTPManager`のクラス定義を削除）

**Interfaces:**
- Consumes: `dataset.DatasetManager`, `dataset.MultiFTPManager`（Task1・Task2で作成済み）
- Produces: なし（`TrainingPipeline.__init__`/`execute()`のインターフェースは無変更のため後続タスクなし）

- [ ] **Step 1: importブロックを更新**

`training/pipline.py`の1-28行目、現状:

```python
import os
import shutil
import datetime
import multiprocessing
import warnings

# pydantic V2 系のサードパーティ依存 (MLflow 等) が発する schema_extra → json_schema_extra
# 改名警告を抑制 (機能影響なし、アプリ側で修正不可)
warnings.filterwarnings(
    "ignore",
    message=r"Valid config keys have changed in V2.*",
    category=UserWarning,
    module=r"pydantic\..*",
)

from omegaconf import OmegaConf
from ftplib import FTP
import torch
import cv2
from utils.ftp_common import download_ftp_selected, is_directory, AnnotationDownloader
from utils.image_preprocessing import load_image_as_byte_array, process_image
from utils.split_manager import split_pool_to_train_test
from utils.mlflow_logger import MLflowManager
from utils.log_tailer import LogTailer
from train import train_color, train_monochro
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
```

修正後:

```python
import os
import multiprocessing
import warnings

# pydantic V2 系のサードパーティ依存 (MLflow 等) が発する schema_extra → json_schema_extra
# 改名警告を抑制 (機能影響なし、アプリ側で修正不可)
warnings.filterwarnings(
    "ignore",
    message=r"Valid config keys have changed in V2.*",
    category=UserWarning,
    module=r"pydantic\..*",
)

from omegaconf import OmegaConf
import torch
from utils.mlflow_logger import MLflowManager
from utils.log_tailer import LogTailer
from train import train_color, train_monochro
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
from dataset import DatasetManager, MultiFTPManager
```

（`shutil`/`datetime`/`ftplib.FTP`/`cv2`/`utils.ftp_common`の全import/`utils.image_preprocessing`/`utils.split_manager`は`DatasetManager`/`FTPManager`内部でのみ使われていたため削除。`download_ftp_selected`/`is_directory`は元から`pipline.py`内で未使用だったが、`utils.ftp_common`のimport行自体を削除するこのタイミングで一緒に消える。）

- [ ] **Step 2: `DatasetManager`・`FTPManager`・`MultiFTPManager`のクラス定義を削除**

`training/pipline.py`の**48行目**（`class DatasetManager:`）から**398行目**（`MultiFTPManager.download_images`末尾の空行2行を含む）までを削除する。`build_sub_cfg`直後の空行2行（46-47行目）はそのまま残す。削除後は、`build_sub_cfg`の`return sub`の直後に空行2行を挟んで`class Trainer:`（元399行目）が続く形になる。

- [ ] **Step 3: `TrainingPipeline.__init__`が新importで動作することを確認**

`training/pipline.py`内の`TrainingPipeline.__init__`（`self.dataset_manager = DatasetManager(self.cfg)`, `self.ftp_manager = MultiFTPManager(self.cfg)`）はコード変更不要（シンボル名が同一のため、Step1のimport更新だけで解決される）。

**重要（無関係WIPの分離）**: `git add`前に`git diff training/pipline.py`で、本Task3の変更（import更新・クラス削除の2箇所）のみが含まれ、本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が混入していないことを確認すること。Seam1〜5で行った「一時的にWIPを元に戻す→コミット→復元する」手順を同様に踏むこと。

- [ ] **Step 4: 全体テストを実行し、既存テストに影響がないことを確認**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(50件: Seam5完了時点で43件 + Task1で追加した4件(`tests/dataset/test_manager_characterization.py`) = 47件 + Task2で追加した3件(`tests/dataset/test_ftp_download.py`) = 50件)。失敗があれば`training/pipline.py`の削除範囲・import範囲を再確認する。

- [ ] **Step 5: コミット**

```bash
git add training/pipline.py
git commit -m "$(cat <<'EOF'
refactor(training-pipline): DatasetManager/FTPManager/MultiFTPManagerをdatasetパッケージ経由の呼び出しに置換

training/pipline.py内のDatasetManager/FTPManager/MultiFTPManagerのクラス
定義を削除し、training/dataset パッケージからのimportに置き換えた。
TrainingPipeline.__init__/execute()の挙動は変更なし（シンボル名が
同一のため呼び出しコードは無変更）。
EOF
)"
```

---

## Task 4: CI gateの追加（dataset境界の逆行防止）

**Files:**
- Create: `training/tests/ci_gates/test_dataset_boundary.py`

**Interfaces:**
- Consumes: なし（AST解析のみ、実行時import無し）
- Produces: なし（最終タスク。このSeam、およびモジュラモノリス移行全体の最後のタスク）

- [ ] **Step 1: CI gateテストを新規作成**

`training/tests/ci_gates/test_dataset_boundary.py`:

```python
"""datasetステージの境界を守るCI gate。

dataset.manager / dataset.ftp_download（dataset処理の低レベルモジュール）を
直接importできるのはdatasetパッケージ内のみであることを保証する。他の
モジュールは dataset.DatasetManager / dataset.FTPManager / dataset.MultiFTPManager
の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "dataset", "__pycache__"}
INTERNAL_MODULES = {"dataset.manager", "dataset.ftp_download"}


def _imported_module_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_pipline_does_not_import_dataset_internals_directly():
    """pipline.py は dataset.manager / dataset.ftp_download を直接importしては
    いけない。dataset処理は dataset の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_dataset_module_imports_dataset_internals():
    """dataset.manager / dataset.ftp_download を直接importしているのは
    dataset パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"dataset外からのdataset内部モジュール直接importを検出: {offenders}"
```

- [ ] **Step 2: 実行してpassすることを確認**

Run: `cd training && python -m pytest tests/ci_gates/test_dataset_boundary.py -v`
Expected: 2 passed

- [ ] **Step 3: プロジェクト全体のテストを実行する**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(52件: Task3完了時点で50件 + Task4で追加した2件(CI gate) = 52件)

- [ ] **Step 4: コミット**

```bash
git add training/tests/ci_gates/test_dataset_boundary.py
git commit -m "$(cat <<'EOF'
test(training-dataset): datasetパッケージ境界の逆行防止CI gateを追加

dataset.manager / dataset.ftp_download を直接importできるのは
datasetパッケージ内のみであることを検証するテストを追加。
Seam6（datasetの境界確立）の完了条件として、以後の境界逆行をCIで
検出できるようにする。これでtraining/のモジュラモノリス移行が完了する。
EOF
)"
```

---

## 完了条件（このSeamのDone）

- `dataset.DatasetManager`・`dataset.FTPManager`・`dataset.MultiFTPManager`が公開APIとして存在し、`training/pipline.py`はこれ経由でのみdataset処理を行う
- `training/pipline.py`から`DatasetManager`・`FTPManager`・`MultiFTPManager`のクラス定義が削除されている
- 呼び出し元ゼロの未結線メソッド4つ（`accumulate_pool`/`stage_defect`/`backup_dataset`/`backup_annotated_data`）が削除されている
- characterization test（`process_annotated_images`/`split_pool_to_dataset`/`backup_model`の数値・ファイル一覧一致、FTPダウンロードのモック挙動一致）が全てPASSしている
- CI gate（`training/tests/ci_gates/test_dataset_boundary.py`）が導入され、`dataset`内部モジュールの境界逆行を検出できる
- `cd training && python -m pytest tests/ -v` が全件PASS（52件）
- `training/pipline.py`の無関係な既存WIP（spawn-context修正）が本Seamのコミットに混入していない
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam6が完了としてマークできる状態になっている
- **モジュラモノリス移行全体（Seam1〜6）が完了する**
