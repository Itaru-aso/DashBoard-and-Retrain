"""train.color._calibrate_cand1 のcolor candidate1較正パイロットを検証する。

train_color() 全体（学習ループ）を実行する統合テストは行わない（既存方針を維持、
学習ループ自体は高コストで未テスト対象のまま）。合成データによる純関数レベルの検証のみ。

実行: cd training && python -m pytest tests/train/test_color_cand1_calibration.py -v
"""
import numpy as np

from train.color import _calibrate_cand1
from utils.candidate1_calib import (
    compute_mu_sigma, raw_map_max, zscore_map_max, calib_AZ)


def _make_maps(rng, n=40, shape=(6, 8)):
    return [rng.normal(loc=0.0, scale=1.0, size=shape) for _ in range(n)]


def test_calibrate_cand1_returns_expected_keys():
    rng = np.random.default_rng(0)
    maps = _make_maps(rng)

    result = _calibrate_cand1(
        maps, sigma_smooth=1, sigma_floor_pct=None, fpr=0.5
    )

    assert result['cand1_enabled'] is True
    assert set(result.keys()) >= {
        'cand1_enabled', 'cand1_mu', 'cand1_sigma', 'cand1_A', 'cand1_Z',
        'cand1_T', 'cand1_fpr', 'cand1_sigma_smooth', 'cand1_sigma_floor_pct',
    }
    assert result['cand1_T'] == 1.0
    assert result['cand1_fpr'] == 0.5
    assert result['cand1_sigma_smooth'] == 1
    assert result['cand1_sigma_floor_pct'] is None


def test_calibrate_cand1_matches_manual_computation():
    """utils.candidate1_calibの各関数を素朴に呼んだ結果と一致することを確認する。"""
    rng = np.random.default_rng(1)
    maps = _make_maps(rng)
    sigma_smooth, sigma_floor_pct, fpr = 3, 25, 0.5

    expected_mu, expected_sigma = compute_mu_sigma(
        maps, sigma_smooth=sigma_smooth, sigma_floor_pct=sigma_floor_pct)
    expected_raws = [raw_map_max(m) for m in maps]
    expected_zs = [
        zscore_map_max(m, expected_mu, expected_sigma) for m in maps
    ]
    expected_A, expected_Z = calib_AZ(expected_raws, expected_zs, fpr_pct=fpr)

    result = _calibrate_cand1(
        maps, sigma_smooth=sigma_smooth,
        sigma_floor_pct=sigma_floor_pct, fpr=fpr,
    )

    np.testing.assert_allclose(np.array(result['cand1_mu']), expected_mu)
    np.testing.assert_allclose(np.array(result['cand1_sigma']), expected_sigma)
    assert result['cand1_A'] == expected_A
    assert result['cand1_Z'] == expected_Z


def test_calibrate_cand1_mu_sigma_shape_matches_input_map_shape():
    rng = np.random.default_rng(2)
    maps = _make_maps(rng, shape=(6, 8))

    result = _calibrate_cand1(maps)

    assert np.array(result['cand1_mu']).shape == (6, 8)
    assert np.array(result['cand1_sigma']).shape == (6, 8)
