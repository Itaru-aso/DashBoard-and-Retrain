"""dataset モジュールの公開API。

export_root からの取得〜pool振分〜train/test分割までを担う。
"""
from dataset.manager import DatasetManager

__all__ = ["DatasetManager"]
