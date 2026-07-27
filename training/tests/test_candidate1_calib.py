"""utils.candidate1_calib.compute_mu_sigma のsigma平滑化・floor拡張を検証する。

既存のmonochro.py呼び出し（デフォルト引数）との後方互換性、および
sigma_smooth/sigma_floor_pctが仕様通りに効くことを純関数レベルで確認する。

実行: cd training && python -m pytest tests/test_candidate1_calib.py -v
"""
import numpy as np
from scipy.ndimage import uniform_filter

from utils.candidate1_calib import compute_mu_sigma


def _make_maps(rng, n=30, shape=(8, 10)):
    return [rng.normal(loc=0.0, scale=1.0, size=shape) for _ in range(n)]


def test_compute_mu_sigma_default_matches_plain_mean_std():
    """デフォルト引数 (sigma_smooth=1, sigma_floor_pct=None) は既存monochro呼び出しと同じ結果。"""
    rng = np.random.default_rng(0)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    expected_mu, expected_sigma = arr.mean(axis=0), arr.std(axis=0)

    mu, sigma = compute_mu_sigma(maps)

    np.testing.assert_allclose(mu, expected_mu)
    np.testing.assert_allclose(sigma, expected_sigma)


def test_compute_mu_sigma_sigma_smooth_applies_uniform_filter():
    """sigma_smooth>1 は sigma マップに uniform_filter を適用する。muは平滑化されない。"""
    rng = np.random.default_rng(1)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    raw_mu, raw_sigma = arr.mean(axis=0), arr.std(axis=0)

    mu, sigma = compute_mu_sigma(maps, sigma_smooth=5)

    np.testing.assert_allclose(mu, raw_mu)
    np.testing.assert_allclose(sigma, uniform_filter(raw_sigma, size=5))
    assert not np.allclose(sigma, raw_sigma)


def test_compute_mu_sigma_sigma_smooth_one_is_noop():
    """sigma_smooth=1 は平滑化なし (raw sigmaのまま)。"""
    rng = np.random.default_rng(2)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    raw_sigma = arr.std(axis=0)

    _, sigma = compute_mu_sigma(maps, sigma_smooth=1)

    np.testing.assert_allclose(sigma, raw_sigma)


def test_compute_mu_sigma_sigma_floor_pct_clamps_lower_values():
    """sigma_floor_pct はσの下限をパーセンタイルでフロアする。"""
    rng = np.random.default_rng(3)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    raw_sigma = arr.std(axis=0)
    expected_floor = np.percentile(raw_sigma, 50)

    _, sigma = compute_mu_sigma(maps, sigma_floor_pct=50)

    assert sigma.min() >= expected_floor - 1e-12
    np.testing.assert_allclose(sigma, np.maximum(raw_sigma, expected_floor))


def test_compute_mu_sigma_sigma_floor_pct_none_is_noop():
    """sigma_floor_pct=None (デフォルト) はフロアなし。"""
    rng = np.random.default_rng(4)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    raw_sigma = arr.std(axis=0)

    _, sigma = compute_mu_sigma(maps, sigma_floor_pct=None)

    np.testing.assert_allclose(sigma, raw_sigma)


def test_compute_mu_sigma_smooth_and_floor_combine():
    """smoothとfloorを同時指定した場合、平滑化後にフロアが適用される。"""
    rng = np.random.default_rng(5)
    maps = _make_maps(rng)
    arr = np.stack(maps, axis=0)
    raw_sigma = arr.std(axis=0)
    smoothed = uniform_filter(raw_sigma, size=3)
    expected = np.maximum(smoothed, np.percentile(smoothed, 25))

    _, sigma = compute_mu_sigma(maps, sigma_smooth=3, sigma_floor_pct=25)

    np.testing.assert_allclose(sigma, expected)
