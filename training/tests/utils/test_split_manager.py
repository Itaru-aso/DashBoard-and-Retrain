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
        # 比率は撮像ごとのハッシュによる期待値（pool-dataset-sync-split.md 決定1）。
        # 件数は厳密な round(n*0.7) ではないため、全ファイルが1回ずつ置かれ、報告と一致することを見る。
        assert sorted(train_good + test_good) == sorted(os.listdir(good_pool))
        assert result["good_to_train"] == len(train_good)
        assert result["good_to_test"] == len(test_good)

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


def _write_pool(pool_dir, names):
    for f in names:
        _write_empty(os.path.join(pool_dir, f))


def _dataset_dirs(dataset_path):
    return {
        "train_good": os.path.join(dataset_path, "train", "good"),
        "test_good": os.path.join(dataset_path, "test", "good", "images"),
        "train_defect": os.path.join(dataset_path, "train", "defect"),
        "test_defect": os.path.join(dataset_path, "test", "defect", "images"),
    }


def _listing(dataset_path):
    return {k: sorted(os.listdir(v)) for k, v in _dataset_dirs(dataset_path).items()}


def _capture_key(filename):
    """テスト側の撮像キー（OK_/NG_ 接頭辞と末尾の面番号を除く）。"""
    name = os.path.splitext(filename)[0]
    for p in ("OK_", "NG_"):
        if name.startswith(p):
            name = name[len(p):]
    return name.rsplit("_", 1)[0]


class TestSplitPoolToTrainTestSync:
    """pool が増えても分割が安定し、dataset が pool に同期されること。

    @.kiro/specs/retraining/pool-dataset-sync-split.md 決定1・2・検証基準。
    """

    def _run(self, good_pool, defect_pool, dataset_path):
        return split_pool_to_train_test(
            defect_pool_path=defect_pool, good_pool_path=good_pool,
            dataset_path=dataset_path, train_ratio=0.7, seed=42,
        )

    def _paths(self, tmp_path):
        return (str(tmp_path / "3_pool" / "good_pool"), str(tmp_path / "3_pool" / "defect_pool"),
                str(tmp_path / "4_dataset" / "001" / "color"))

    def test_existing_captures_keep_their_side_when_pool_grows(self, tmp_path):
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, _paired_names(30, prefix="OK_g"))
        _write_pool(defect_pool, _paired_names(10, prefix="NG_d"))
        self._run(good_pool, defect_pool, dataset_path)
        before = _listing(dataset_path)

        _write_pool(good_pool, _paired_names(30, prefix="OK_new"))
        _write_pool(defect_pool, _paired_names(10, prefix="NG_newd"))
        self._run(good_pool, defect_pool, dataset_path)
        after = _listing(dataset_path)

        for k, files in before.items():
            assert set(files) <= set(after[k]), f"{k} の既存画像が消えた"
        # 既存画像が反対側にも現れていない（差分追加で両側に残らない）
        assert set(before["train_good"]) & set(after["test_good"]) == set()
        assert set(before["test_good"]) & set(after["train_good"]) == set()
        assert set(before["train_defect"]) & set(after["test_defect"]) == set()
        assert set(before["test_defect"]) & set(after["train_defect"]) == set()

    def test_no_file_on_both_sides_after_repeated_growth(self, tmp_path):
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        for step in range(4):
            _write_pool(good_pool, _paired_names(15, prefix=f"OK_s{step}_"))
            _write_pool(defect_pool, _paired_names(5, prefix=f"NG_s{step}_"))
            self._run(good_pool, defect_pool, dataset_path)

        ls = _listing(dataset_path)
        assert set(ls["train_good"]) & set(ls["test_good"]) == set()
        assert set(ls["train_defect"]) & set(ls["test_defect"]) == set()
        assert sorted(ls["train_good"] + ls["test_good"]) == sorted(os.listdir(good_pool))
        assert sorted(ls["train_defect"] + ls["test_defect"]) == sorted(os.listdir(defect_pool))

    def test_stale_copy_on_wrong_side_is_removed(self, tmp_path):
        """旧方式で両側に置かれた画像は、行き先と違う側のコピーが消える。"""
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        names = _paired_names(20, prefix="OK_g")
        _write_pool(good_pool, names)
        dirs = _dataset_dirs(dataset_path)
        for f in names:  # 旧方式の残骸: 全画像が train と test の両方にある
            _write_empty(os.path.join(dirs["train_good"], f))
            _write_empty(os.path.join(dirs["test_good"], f))

        result = self._run(good_pool, defect_pool, dataset_path)

        ls = _listing(dataset_path)
        assert set(ls["train_good"]) & set(ls["test_good"]) == set()
        assert sorted(ls["train_good"] + ls["test_good"]) == sorted(names)
        assert result["removed"] == len(names)

    def test_files_gone_from_pool_are_removed_from_dataset(self, tmp_path):
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, _paired_names(20, prefix="OK_g"))
        _write_pool(defect_pool, _paired_names(5, prefix="NG_d"))
        self._run(good_pool, defect_pool, dataset_path)

        gone = ["OK_g3_0.bmp", "OK_g3_1.bmp", "NG_d1_0.bmp"]
        for f in gone:
            pool = good_pool if f.startswith("OK_") else defect_pool
            os.remove(os.path.join(pool, f))
        result = self._run(good_pool, defect_pool, dataset_path)

        all_placed = [f for files in _listing(dataset_path).values() for f in files]
        assert not set(gone) & set(all_placed)
        assert result["removed"] == len(gone)

    def test_good_face_and_defect_face_of_a_capture_go_to_the_same_side(self, tmp_path):
        """片面だけ不良の撮像は良品面と不良面が同じ側に入る（接頭辞が違っても同一撮像）。"""
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        # 良品は全撮像、不良は一部の撮像のみ（撮像数を変えて偶然の一致を避ける）
        _write_pool(good_pool, [f"OK_cap{c}_0.bmp" for c in range(40)])
        _write_pool(defect_pool, [f"NG_cap{c}_1.bmp" for c in range(0, 40, 3)])

        self._run(good_pool, defect_pool, dataset_path)

        ls = _listing(dataset_path)
        train_caps = {_capture_key(f) for f in ls["train_good"] + ls["train_defect"]}
        test_caps = {_capture_key(f) for f in ls["test_good"] + ls["test_defect"]}
        assert train_caps & test_caps == set()
        assert train_caps and test_caps

    def test_small_pool_places_every_file_exactly_once(self, tmp_path):
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, ["OK_a_0.bmp"])
        _write_pool(defect_pool, ["NG_b_0.bmp", "NG_b_1.bmp", "NG_c_0.bmp"])

        self._run(good_pool, defect_pool, dataset_path)

        ls = _listing(dataset_path)
        assert sorted(ls["train_good"] + ls["test_good"]) == ["OK_a_0.bmp"]
        assert sorted(ls["train_defect"] + ls["test_defect"]) == sorted(os.listdir(defect_pool))
        # 同一撮像 b の2面は同じ側
        assert ("NG_b_0.bmp" in ls["train_defect"]) == ("NG_b_1.bmp" in ls["train_defect"])

    def test_ratio_is_close_to_train_ratio_over_many_captures(self, tmp_path):
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, _paired_names(1000, prefix="OK_g"))

        self._run(good_pool, defect_pool, dataset_path)

        n_train = len(_listing(dataset_path)["train_good"]) / 2
        assert 0.65 <= n_train / 1000 <= 0.75

    def test_missing_pool_dir_does_not_wipe_dataset(self, tmp_path):
        """pool フォルダが無い（パス誤り等）ときは、そのクラスの dataset を消さない。"""
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, _paired_names(10, prefix="OK_g"))
        _write_pool(defect_pool, _paired_names(5, prefix="NG_d"))
        self._run(good_pool, defect_pool, dataset_path)
        before = _listing(dataset_path)

        result = self._run(str(tmp_path / "missing_good"), str(tmp_path / "missing_defect"),
                           dataset_path)

        assert _listing(dataset_path) == before
        assert result["removed"] == 0

    def test_empty_pool_class_does_not_wipe_dataset_class(self, tmp_path):
        """pool のクラスが空（フォルダはある）なら、dataset のそのクラスを消さない。他クラスは同期する。"""
        good_pool, defect_pool, dataset_path = self._paths(tmp_path)
        _write_pool(good_pool, _paired_names(10, prefix="OK_g"))
        _write_pool(defect_pool, _paired_names(5, prefix="NG_d"))
        self._run(good_pool, defect_pool, dataset_path)
        before = _listing(dataset_path)

        for f in os.listdir(good_pool):
            os.remove(os.path.join(good_pool, f))
        os.remove(os.path.join(defect_pool, "NG_d0_0.bmp"))
        self._run(good_pool, defect_pool, dataset_path)

        after = _listing(dataset_path)
        assert after["train_good"] == before["train_good"]
        assert after["test_good"] == before["test_good"]
        assert "NG_d0_0.bmp" not in after["train_defect"] + after["test_defect"]


# 撮像キー → train か（seed=42, train_ratio=0.7）。実装を変えて値が変わるなら全色番の分割が入れ替わる。
PINNED_SIDES = {
    "image_111412_118": False,
    "image_111412_314": True,
    "image_140037_003": True,
    "image_160651_131": True,
    "image_102332_793": True,
    "image_093532_400": True,
    "image_112225_152": True,
    "image_140321_082": True,
    "image_101503_207": False,
    "image_123344_129": False,
    "image_155901_456": False,
}


class TestCaptureAssignmentIsPinned:
    """撮像の行き先を固定する（ハッシュ式・seed の受け渡しが黙って変わるのを検出する）。"""

    def test_known_capture_keys_land_on_pinned_sides(self):
        from utils.split_manager import _capture_key, _is_train_capture

        sides = {k: _is_train_capture(_capture_key(f"OK_{k}_0.bmp"), 0.7, 42) for k in PINNED_KEYS}

        assert sides == PINNED_SIDES

    def test_different_seed_changes_assignment(self):
        from utils.split_manager import _is_train_capture

        keys = [f"cap{i}" for i in range(200)]

        seed42 = [_is_train_capture(k, 0.7, 42) for k in keys]
        seed43 = [_is_train_capture(k, 0.7, 43) for k in keys]

        assert seed42 != seed43

    def test_prefix_and_face_do_not_change_capture_key(self):
        from utils.split_manager import _capture_key

        assert (_capture_key("OK_image_1_0.bmp") == _capture_key("NG_image_1_1.bmp")
                == _capture_key("image_1_0.bmp") == "image_1")


PINNED_KEYS = ("image_111412_118", "image_111412_314", "image_140037_003",
               "image_160651_131", "image_102332_793", "image_093532_400",
               "image_112225_152", "image_140321_082", "image_101503_207",
               "image_123344_129", "image_155901_456")
