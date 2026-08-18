"""evaluation.Evaluator の公開APIテスト。

早期return条件はTask1のcharacterization testと同じ期待値を維持する
（旧実装 pipline.Evaluator との挙動一致）。

ただし**閾値の出どころ**は S2（評価リーク修正）で意図的に変更した:
旧挙動は `find_optimal_threshold` で評価対象そのものにフィットした閾値を
主指標に使っていた（楽観バイアス）。現在は `para.json` の `threshold`
（＝実機へ配信される閾値）を主指標に使い、F1最大化閾値は `ref_f1_optimal_*`
として参考値のみ併記する。

実行: cd training && python -m pytest tests/evaluation/test_evaluator.py -v
"""
import json
import os
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import evaluation


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


def _make_model_dir_with_para(tmp_path, color="841", mode="color", threshold=0.42):
    """para.json を作る。`threshold=None` なら threshold キーを持たない para.json にする。"""
    model_dir = tmp_path / "6_model" / color / mode
    model_dir.mkdir(parents=True, exist_ok=True)
    para = {} if threshold is None else {"threshold": threshold}
    (model_dir / "para.json").write_text(json.dumps(para), encoding="utf-8")
    return str(model_dir)


MAIN_METRICS = {"AUC": 0.9, "F1": 0.8, "miss_rate": 0.1, "false_alarm_rate": 0.05}
REF_METRICS = {"AUC": 0.9, "F1": 0.95, "miss_rate": 0.02, "false_alarm_rate": 0.20}


def test_evaluate_uses_deployed_threshold_from_para_json(tmp_path):
    """S2: 主指標は para.json の配信閾値で算出し、F1最大化値は参考値に留める。"""
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path, threshold=0.42)

    mgr = MagicMock()
    ev = evaluation.Evaluator(cfg, color="841", mode="color", mgr=mgr)

    with patch("evaluation.scoring.load_model", return_value={"model": "dummy"}) as mock_load, \
         patch("evaluation.scoring.score_images") as mock_score, \
         patch("evaluation.scoring.find_optimal_threshold", return_value=0.77) as mock_thresh, \
         patch("evaluation.scoring.compute_metrics") as mock_metrics:
        mock_score.side_effect = [{"g1.png": 0.1}, {"d1.png": 0.9}]
        mock_metrics.side_effect = [dict(MAIN_METRICS), dict(REF_METRICS)]
        result = ev.evaluate()

    mock_load.assert_called_once_with(ev.model_dir)
    assert mock_score.call_count == 2
    # 主指標は配信閾値(0.42)。後付けフィット値(0.77)ではない。
    assert mock_metrics.call_args_list[0].args == ([0.1], [0.9], 0.42)
    assert result["threshold_from_para"] == 1.0
    assert result["AUC"] == MAIN_METRICS["AUC"]
    assert result["F1"] == MAIN_METRICS["F1"]
    # F1最大化閾値は参考値としてのみ併記される。
    mock_thresh.assert_called_once_with([0.1], [0.9])
    assert result["ref_f1_optimal_threshold"] == 0.77
    assert result["ref_f1_optimal_F1"] == REF_METRICS["F1"]
    mgr.log_metrics.assert_called_once_with(result)


def test_evaluate_falls_back_to_f1_optimal_when_para_threshold_missing(tmp_path):
    """S2: para.json に threshold が無い場合は代替するが、その事実を metrics に残す。"""
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path, threshold=None)

    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    with patch("evaluation.scoring.load_model", return_value={"model": "dummy"}), \
         patch("evaluation.scoring.score_images") as mock_score, \
         patch("evaluation.scoring.find_optimal_threshold", return_value=0.77), \
         patch("evaluation.scoring.compute_metrics") as mock_metrics:
        mock_score.side_effect = [{"g1.png": 0.1}, {"d1.png": 0.9}]
        mock_metrics.side_effect = [dict(MAIN_METRICS), dict(REF_METRICS)]
        result = ev.evaluate()

    assert mock_metrics.call_args_list[0].args == ([0.1], [0.9], 0.77)
    assert result["threshold_from_para"] == 0.0


def test_evaluate_returns_none_when_test_directories_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_file_lists_empty(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path, good_files=(), defect_files=())
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_para_json_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_scoring_raises(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    with patch("evaluation.scoring.load_model", side_effect=RuntimeError("boom")):
        result = ev.evaluate()

    assert result is None
