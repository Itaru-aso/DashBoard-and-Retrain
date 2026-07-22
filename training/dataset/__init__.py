"""dataset モジュールの公開API。

FTP取得〜pool/staging振分〜train/test分割までを担う。
"""
from dataset.manager import DatasetManager

__all__ = ["DatasetManager"]
