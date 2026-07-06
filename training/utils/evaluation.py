#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Shared evaluation utilities for color anomaly detection."""

from typing import Dict, List, Optional, Tuple

import torch
from torch import nn, Tensor

from utils.edge_mask import apply_edge_mask_zero

out_channels = 384


@torch.no_grad()
def predict(
    image: Tensor,
    teacher: nn.Module,
    student: nn.Module,
    autoencoder: nn.Module,
    teacher_mean: Tensor,
    teacher_std: Tensor,
    st_para: float,
    ae_para: float,
    q_st_start: Optional[Tensor] = None,
    q_st_end: Optional[Tensor] = None,
    q_ae_start: Optional[Tensor] = None,
    q_ae_end: Optional[Tensor] = None,
    channel_weights: Optional[Tensor] = None,
) -> Tuple[Tensor, Tensor, Tensor]:
    """Shared predict function for color evaluation.

    Runs teacher, student, and autoencoder on the input image, then computes
    anomaly maps (map_st, map_ae) and a combined map.

    Args:
        image: Input image tensor.
        teacher: Teacher network.
        student: Student network.
        autoencoder: Autoencoder network.
        teacher_mean: Channel-wise mean used to normalise teacher output.
        teacher_std: Channel-wise std used to normalise teacher output.
        st_para: Weight for the student-teacher map in the combined map.
        ae_para: Weight for the autoencoder map in the combined map.
        q_st_start: Optional quantile start for map_st normalisation.
        q_st_end: Optional quantile end for map_st normalisation.
        q_ae_start: Optional quantile start for map_ae normalisation.
        q_ae_end: Optional quantile end for map_ae normalisation.
        channel_weights: Optional [1, C, 1, 1] tensor of per-channel weights.
            When provided, map_st is computed as a weighted sum instead of
            a simple mean across channels.

    Returns:
        Tuple of (map_combined, map_st, map_ae).
    """
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2

    if channel_weights is not None:
        # チャネル重み付きスコア: 有効チャネルに集中
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean(
        (autoencoder_output - student_output[:, out_channels:]) ** 2,
        dim=1,
        keepdim=True,
    )

    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)

    map_combined = st_para * map_st + ae_para * map_ae

    return map_combined, map_st, map_ae


def compute_image_score(anomaly_map: Tensor, edge_mask_w: int = 0) -> float:
    """Return the maximum value of the anomaly map as a float score.

    Args:
        anomaly_map: Anomaly map tensor (any shape; last dim is W).
        edge_mask_w: 両端 N 列を 0 化してから max を取る (PDN padding artifact 抑制)。
            既存挙動互換のため既定 0 (= no-op)。

    Returns:
        Maximum anomaly value as a Python float.
    """
    if edge_mask_w > 0:
        anomaly_map = apply_edge_mask_zero(anomaly_map, edge_mask_w)
    return anomaly_map.max().item()


def compute_miss_and_false_alarm_rates(
    scores_good: List[float],
    scores_defect: List[float],
    threshold: float,
) -> Dict[str, object]:
    """Compute miss rate and false alarm rate for a given threshold.

    Args:
        scores_good: Anomaly scores for good (normal) images.
        scores_defect: Anomaly scores for defect (anomalous) images.
        threshold: Decision threshold. Scores >= threshold are predicted as defect.

    Returns:
        Dict with keys: miss_rate, false_alarm_rate, TP, FP, FN, TN, threshold.
    """
    total_defect = len(scores_defect)
    total_good = len(scores_good)

    # FN: defect images incorrectly classified as good (score < threshold)
    FN = sum(1 for s in scores_defect if s < threshold)
    # TP: defect images correctly classified as defect (score >= threshold)
    TP = total_defect - FN

    # FP: good images incorrectly classified as defect (score >= threshold)
    FP = sum(1 for s in scores_good if s >= threshold)
    # TN: good images correctly classified as good (score < threshold)
    TN = total_good - FP

    miss_rate = FN / total_defect if total_defect > 0 else 0.0
    false_alarm_rate = FP / total_good if total_good > 0 else 0.0

    return {
        "miss_rate": miss_rate,
        "false_alarm_rate": false_alarm_rate,
        "TP": TP,
        "FP": FP,
        "FN": FN,
        "TN": TN,
        "threshold": threshold,
    }
