"""03CZT8専用train_color.pyの特性化テスト。

colorはDataLoader構築に`RawShiftImageFolder`系を使わないため
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定5）、
`items/item_03czt8/train_color.py` はコピー元(`train/color.py`)と内容の差分が無い。
importが正常に通ること・主要関数が期待通りのシグネチャで存在することのみを確認する。

実行: cd training && python -m pytest tests/items/test_item_03czt8_train_color.py -v
"""
import inspect

import train.color as original_train_color
import train.item_03czt8.train_color as copied_train_color


def test_module_imports_without_error():
    assert hasattr(copied_train_color, "train_color")
    assert hasattr(copied_train_color, "evaluate_validation_loss")


def test_train_color_signature_matches_copy_source():
    original_sig = inspect.signature(original_train_color.train_color)
    copied_sig = inspect.signature(copied_train_color.train_color)
    assert original_sig == copied_sig


def test_does_not_reference_item_03czt8_crop_params():
    """colorはcrop_x0/crop_width/overlapのいずれも参照しない(決定5の確認)。

    モジュールdocstring中の説明文言は対象外とし、実行コード本体(train_color/
    evaluate_validation_lossの関数ソース)のみを検査する。
    """
    train_color_source = inspect.getsource(copied_train_color.train_color)
    eval_source = inspect.getsource(copied_train_color.evaluate_validation_loss)
    for source in (train_color_source, eval_source):
        assert "crop_x0" not in source
        assert "crop_width" not in source
        assert "RawShiftImageFolder" not in source
