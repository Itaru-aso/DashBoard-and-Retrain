"""utils.split_manager の撮像単位分割のテスト。

@.kiro/specs/retraining/eval-calibration-leak-fixes.md 決定3・検証基準3 に対応。
1撮影は top/bottom の2ファイル（`_0`/`_1`）に分かれるが、両者は同一製品・同一照明・
同一瞬間に由来し強く相関する。良品側も不良側と同様に撮像単位で振り分けることで、
片面が学習・他面が評価/較正に入るリークを防ぐ。

実行: cd training && python -m pytest tests/utils/test_split_manager.py -v
"""
import os

from utils.split_manager import split_files_by_product, split_pool_to_train_test


def _paired_names(n_captures, prefix="cap"):
    """1撮影=2ファイル（`_0`/`_1`）のファイル名リストを返す。"""
    return [f"{prefix}{c}_{face}.bmp" for c in range(n_captures) for face in (0, 1)]


def _write_empty(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"")


def _product_ids(filenames):
    return {os.path.splitext(f)[0].rsplit("_", 1)[0] for f in filenames}


class TestSplitFilesByProduct:
    def test_keeps_both_faces_of_a_capture_on_the_same_side(self):
        names = _paired_names(10)

        train, test = split_files_by_product(names, train_ratio=0.7, seed=42)

        assert _product_ids(train) & _product_ids(test) == set()
        # 全ファイルがどちらかに入り、重複しない。
        assert sorted(train + test) == sorted(names)
        # 各 product は2面そろって同じ側にある。
        assert len(train) == 2 * len(_product_ids(train))
        assert len(test) == 2 * len(_product_ids(test))

    def test_splits_by_ratio_over_captures_not_files(self):
        names = _paired_names(10)  # 10撮像 / 20ファイル

        train, test = split_files_by_product(names, train_ratio=0.7, seed=42)

        # round(10*0.7)=7撮像がtrain -> 14ファイル、3撮像がtest -> 6ファイル。
        assert len(_product_ids(train)) == 7
        assert len(_product_ids(test)) == 3
        assert (len(train), len(test)) == (14, 6)

    def test_is_deterministic_for_same_seed(self):
        names = _paired_names(10)

        first = split_files_by_product(names, train_ratio=0.7, seed=42)
        second = split_files_by_product(names, train_ratio=0.7, seed=42)

        assert first == second

    def test_returns_empty_for_empty_input(self):
        assert split_files_by_product([], train_ratio=0.7, seed=42) == ([], [])

    def test_handles_names_without_face_suffix(self):
        """`_数字` 接尾を持たない名前は1ファイル=1撮像として扱う。"""
        names = ["a.bmp", "b.bmp", "c.bmp", "d.bmp"]

        train, test = split_files_by_product(names, train_ratio=0.75, seed=42)

        assert sorted(train + test) == sorted(names)
        assert len(train) == 3
        assert len(test) == 1


class TestSplitPoolToTrainTestGoodSide:
    """良品側が撮像単位で振り分けられること（S3・不良側との対称化）。"""

    def _make_pools(self, tmp_path, n_good_captures=10, n_defect_captures=4):
        good_pool = str(tmp_path / "3_pool" / "good_pool")
        defect_pool = str(tmp_path / "3_pool" / "defect_pool")
        for f in _paired_names(n_good_captures, prefix="g"):
            _write_empty(os.path.join(good_pool, f))
        for f in _paired_names(n_defect_captures, prefix="d"):
            _write_empty(os.path.join(defect_pool, f))
        return good_pool, defect_pool

    def _placed(self, dataset_path):
        train_good = os.listdir(os.path.join(dataset_path, "train", "good"))
        test_good = os.listdir(os.path.join(dataset_path, "test", "good", "images"))
        return train_good, test_good

    def test_same_product_never_straddles_train_and_test(self, tmp_path):
        """検証基準3: 同一 product_id が train/good と test/good に跨らない。"""
        good_pool, defect_pool = self._make_pools(tmp_path)
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")

        split_pool_to_train_test(
            defect_pool_path=defect_pool, good_pool_path=good_pool,
            dataset_path=dataset_path, train_ratio=0.7, seed=42,
        )

        train_good, test_good = self._placed(dataset_path)
        assert _product_ids(train_good) & _product_ids(test_good) == set()
        # 各撮像は2面そろって同じ側に置かれる。
        assert len(train_good) == 2 * len(_product_ids(train_good))
        assert len(test_good) == 2 * len(_product_ids(test_good))

    def test_reports_counts_and_places_every_file(self, tmp_path):
        good_pool, defect_pool = self._make_pools(tmp_path, n_good_captures=10)
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")

        result = split_pool_to_train_test(
            defect_pool_path=defect_pool, good_pool_path=good_pool,
            dataset_path=dataset_path, train_ratio=0.7, seed=42,
        )

        train_good, test_good = self._placed(dataset_path)
        # round(10*0.7)=7撮像=14ファイルがtrain、3撮像=6ファイルがtest。
        assert (result["good_to_train"], result["good_to_test"]) == (14, 6)
        assert len(train_good) == 14
        assert len(test_good) == 6

    def test_defect_side_still_grouped_by_product(self, tmp_path):
        """不良側の既存挙動（撮像単位）は変わらないこと。"""
        good_pool, defect_pool = self._make_pools(tmp_path, n_defect_captures=4)
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")

        split_pool_to_train_test(
            defect_pool_path=defect_pool, good_pool_path=good_pool,
            dataset_path=dataset_path, train_ratio=0.7, seed=42,
        )

        train_defect = os.listdir(os.path.join(dataset_path, "train", "defect"))
        test_defect = os.listdir(os.path.join(dataset_path, "test", "defect", "images"))
        assert _product_ids(train_defect) & _product_ids(test_defect) == set()

    def test_is_idempotent_on_rerun(self, tmp_path):
        """差分追加方式のため、再実行しても既存配置は動かず追加も起きない。"""
        good_pool, defect_pool = self._make_pools(tmp_path)
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")
        kwargs = dict(
            defect_pool_path=defect_pool, good_pool_path=good_pool,
            dataset_path=dataset_path, train_ratio=0.7, seed=42,
        )

        split_pool_to_train_test(**kwargs)
        first = self._placed(dataset_path)
        second_result = split_pool_to_train_test(**kwargs)

        assert self._placed(dataset_path) == first
        assert (second_result["good_to_train"], second_result["good_to_test"]) == (0, 0)
