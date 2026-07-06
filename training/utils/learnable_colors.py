"""学習対象とすべき色番の列挙。

学習タブの色番リストは「pool に蓄積データがある or 既存 dataset がある」
色番の和集合であるべき。pool only (仕分け直後で未 split) も dataset only
(既存) もどちらも学習対象。
"""
from pathlib import Path


def get_learnable_colors(pool_root: Path, dataset_root: Path) -> list[str]:
    """pool または dataset に色番ディレクトリがあるものを和集合で返す (sorted)。"""
    def _list_dirs(root: Path) -> set[str]:
        if not root.is_dir():
            return set()
        return {p.name for p in root.iterdir() if p.is_dir()}

    return sorted(_list_dirs(pool_root) | _list_dirs(dataset_root))
