"""現状の pipline.Evaluator.evaluate() の挙動を固定するテスト。

Seam2移行（evaluationパッケージへの切り出し）前の挙動を記録し、
Task2で実装する新実装 (evaluation.Evaluator) が同じ結果を出すことの比較対象とする。

実行: cd training && python -m pytest tests/evaluation/test_evaluator_characterization.py -v
"""
import os
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import pipline


def _make_cfg(tmp_path):
    return OmegaConf.create({
        "common": {
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
        }
    })


def _make_test_dirs(tmp_path, color="841", mode="color",
                     good_files=("g1.png",), defect_files=("d1.png",)):
    dataset_path = tmp_path / "4_dataset" / color / mode
    good_dir = dataset_path / "test" / "good" / "images"
    defect_dir = dataset_path / "test" / "defect" / "images"
    good_dir.mkdir(parents=True, exist_ok=True)
    defect_dir.mkdir(parents=True, exist_ok=True)
    for f in good_files:
        (good_dir / f).write_bytes(b"")
    for f in defect_files:
        (defect_dir / f).write_bytes(b"")


def _make_model_dir_with_para(tmp_path, color="841", mode="color"):
    model_dir = tmp_path / "6_model" / color / mode
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "para.json").write_text("{}")
    return str(model_dir)


def test_evaluate_computes_metrics_and_logs_when_test_data_present(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)

    mgr = MagicMock()
    ev = pipline.Evaluator(cfg, color="841", mode="color", mgr=mgr)

    fake_metrics = {"AUC": 0.9, "F1": 0.8, "miss_rate": 0.1, "false_alarm_rate": 0.05}
    with patch("utils.evaluation_pipeline.load_model", return_value={"model": "dummy"}) as mock_load, \
         patch("utils.evaluation_pipeline.score_images") as mock_score, \
         patch("utils.evaluation_pipeline.find_optimal_threshold", return_value=0.5) as mock_thresh, \
         patch("utils.evaluation_pipeline.compute_metrics", return_value=fake_metrics) as mock_metrics:
        mock_score.side_effect = [{"g1.png": 0.1}, {"d1.png": 0.9}]
        result = ev.evaluate()

    mock_load.assert_called_once_with(ev.model_dir)
    assert mock_score.call_count == 2
    mock_thresh.assert_called_once_with([0.1], [0.9])
    mock_metrics.assert_called_once_with([0.1], [0.9], 0.5)
    mgr.log_metrics.assert_called_once_with(fake_metrics)
    assert result == fake_metrics


def test_evaluate_returns_none_when_test_directories_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    # test/good, test/defect ディレクトリを作らない
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_file_lists_empty(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path, good_files=(), defect_files=())
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_para_json_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    # para.json を作らない
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_scoring_raises(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    with patch("utils.evaluation_pipeline.load_model", side_effect=RuntimeError("boom")):
        result = ev.evaluate()

    assert result is None
