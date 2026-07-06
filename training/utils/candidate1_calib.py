#!/usr/bin/python
# -*- coding: utf-8 -*-
"""候補1 (raw + z-score OR, monochro 専用) の較正純関数。

統合スコア: unified = max(raw/A, z/Z), NG if unified >= T (既定 1.0)。
  raw = max(map_st)            … 絶対異常 (構造部の不良に強い)
  z   = max((map_st - μ)/σ)    … per-pixel 良品標準化 (平坦地の低コントラスト痕に強い)
μ,σ は良品 ST マップの per-pixel 統計。A,Z は良品の raw/z の分位点。
本モジュールは学習(train_func_monochro)・推論(model.py)・検証で共用するコア。
"""
from __future__ import annotations

import numpy as np

EPS = 1e-6


def compute_mu_sigma(maps):
    """良品 ST マップ列 (各 2D, N 枚) → per-pixel (μ, σ)。"""
    arr = np.stack([np.asarray(m, dtype=np.float64) for m in maps], axis=0)
    return arr.mean(axis=0), arr.std(axis=0)


def raw_map_max(m) -> float:
    """ST マップ → raw スコア (最大値)。"""
    return float(np.asarray(m).max())


def zscore_map_max(m, mu, sigma) -> float:
    """ST マップ → z スコア = max((m - μ)/σ)。"""
    z = (np.asarray(m, dtype=np.float64) - mu) / (np.asarray(sigma, dtype=np.float64) + EPS)
    return float(z.max())


def calib_AZ(raws, zs, fpr_pct: float = 1.0):
    """良品の raw / z 列 → (A, Z) = P(100 - fpr_pct)。FPR=fpr_pct%% を狙う分位点較正。"""
    p = 100.0 - float(fpr_pct)
    return float(np.percentile(raws, p)), float(np.percentile(zs, p))


def unified_score(raw: float, z: float, A: float, Z: float) -> float:
    """統合スコア = max(raw/A, z/Z)。"""
    return max(raw / A, z / Z)


def is_ng(raw: float, z: float, A: float, Z: float, T: float = 1.0) -> bool:
    """OR 判定 (= unified >= T)。raw>=A or z>=Z と等価。"""
    return unified_score(raw, z, A, Z) >= T
