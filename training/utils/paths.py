"""ステージディレクトリのパス解決を一元化するヘルパ。

config.common の各ステージ dir は ./6_model のような CWD 相対で書かれているが、
tools/ はプロジェクトルート絶対パス (ROOT) 起点で参照する。この差を吸収し、
常に root 基準の絶対 Path を返す。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from omegaconf import OmegaConf

# common の論理名 -> 返り値属性名
_KEYS = (
    "pretraining_dir",
    "download_dir",
    "staging_dir",
    "pool_base",
    "dataset_path",
    "splits_dir",
    "model_dir",
    "backup_dir",
)


def find_project_root(start: Optional[Path] = None) -> Path:
    """conf/config.yaml を持つ最近接の祖先を返す。

    frozen(PyInstaller exe) 時は __file__ がバンドル内部を指すため、
    探索せず exe のあるフォルダを root とする (train_app.py の
    os.chdir(dirname(sys.executable)) と基準を一致させる)。
    通常実行で見つからなければ utils/ の親 (= このリポジトリのルート想定) を返す。
    """
    if start is None and getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    base = Path(start).resolve() if start else Path(__file__).resolve()
    for cand in (base, *base.parents):
        if (cand / "conf" / "config.yaml").is_file():
            return cand

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def load_common_paths(cfg=None, root: Optional[Path] = None) -> SimpleNamespace:
    """config.common の各ステージ dir を root 基準の絶対 Path で返す。

    cfg 省略時は root/conf/config.yaml をロードする。
    """
    root = Path(root).resolve() if root else find_project_root()
    if cfg is None:
        cfg = OmegaConf.load(str(root / "conf" / "config.yaml"))
    common = cfg.common
    resolved = {key: (root / str(common[key])).resolve() for key in _KEYS}
    return SimpleNamespace(root=root, **resolved)
