"""evaluation / deploy(model.py) 共有のスコア計算ロジック。

teacher-student diff -> quantile正規化 -> channel_weights -> edge_mask
-> (cand1 分岐 または pad+interpolate) -> max、という anomaly score
計算をここに集約する。model.py の EfficientADFullModel.forward() と
evaluation/scoring.py の score_images() の両方がこの関数を呼ぶことで、
evaluationとdeployのスコアリング実装重複(ADR-6)を解消する。

compute_anomaly_maps は compute_anomaly_score が内部で計算する2Dマップを
スカラーに還元する前の状態で返す下位関数 (black_dot 最終判定層PoCの
特徴抽出用、決定17参照)。compute_anomaly_score はこれを呼んでスカラーに
還元するだけの薄いラッパーにリファクタし、外部から見た入出力は変更しない。
"""
import torch
import torch.nn.functional as F

from utils.edge_mask import apply_edge_mask_zero


def compute_anomaly_maps(
    x,
    teacher,
    student,
    autoencoder,
    teacher_mean,
    teacher_std,
    st_para,
    ae_para,
    q_st_start=None,
    q_st_end=None,
    q_ae_start=None,
    q_ae_end=None,
    channel_weights=None,
    edge_mask_w=0,
    cand1=None,
    height=None,
    width=None,
):
    """正規化済み画像テンソル x から、スカラーに還元する前の異常マップ群を計算する。

    height/width は cand1 の有無に関わらず常に必須 (map_resized は cand1 有無に関わらず
    計算されるため)。cand1 指定時、map_resized の計算により以前の早期return実装より
    計算コストが増える (出力される anomaly score 自体への影響はない)。

    Returns:
        dict:
            'map_native': edge_mask後・pad/interpolate前のmap_combined (B,1,map_h,map_w)。
            'map_resized': pad+interpolateで(height,width)に拡大したmap_combined (B,1,height,width)。
            'zscore_map_resized': cand1が指定されている場合のみ、cand1のmu/sigmaを
                同じpad+interpolateで(height,width)に拡大し
                (map_resized - mu_resized) / (sigma_resized + 1e-6) で計算したマップ。
                cand1がNoneならNone。
    """
    teacher_output = teacher(x)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(x)
    out_channels = teacher_output.shape[1]

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    if ae_para > 0:
        autoencoder_output = autoencoder(x)
        map_ae = torch.mean(
            (autoencoder_output - student_output[:, out_channels:]) ** 2,
            dim=1, keepdim=True)
    else:
        map_ae = torch.zeros_like(map_st)

    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None and ae_para > 0:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)

    map_combined = st_para * map_st + ae_para * map_ae

    edge_w = int(edge_mask_w)
    if edge_w > 0:
        map_combined = apply_edge_mask_zero(map_combined, edge_w)

    map_native = map_combined

    map_resized = F.pad(map_combined, (4, 4, 4, 4))
    map_resized = F.interpolate(map_resized, (height, width), mode='bilinear')

    zscore_map_resized = None
    if cand1 is not None:
        mu_resized = F.pad(cand1['mu'], (4, 4, 4, 4))
        mu_resized = F.interpolate(mu_resized, (height, width), mode='bilinear')
        sigma_resized = F.pad(cand1['sigma'], (4, 4, 4, 4))
        sigma_resized = F.interpolate(sigma_resized, (height, width), mode='bilinear')
        zscore_map_resized = (map_resized - mu_resized) / (sigma_resized + 1e-6)

    return {
        'map_native': map_native,
        'map_resized': map_resized,
        'zscore_map_resized': zscore_map_resized,
    }


def compute_anomaly_score(
    x,
    teacher,
    student,
    autoencoder,
    teacher_mean,
    teacher_std,
    st_para,
    ae_para,
    q_st_start=None,
    q_st_end=None,
    q_ae_start=None,
    q_ae_end=None,
    channel_weights=None,
    edge_mask_w=0,
    cand1=None,
    height=None,
    width=None,
):
    """正規化済み画像テンソル x から anomaly score を計算する。

    Args:
        x: 正規化済み画像テンソル (B, 3, H, W)。
        teacher_mean/teacher_std: (1, C, 1, 1) にreshape済みのテンソル。
        cand1: None、または {'mu', 'sigma', 'A', 'Z'} を含む dict。
            Noneでない場合、統合スコア max(raw/A, z/Z) を
            元のグリッド(pad/interpolate前)上で計算して返す。
        height/width: 常に必須 (pad+interpolateの出力サイズ。cand1指定時も
            compute_anomaly_maps内部でmap_resizedを計算するため必要)。

    Returns:
        Tensor shape (B, 1): 画像ごとの anomaly score。
    """
    maps = compute_anomaly_maps(
        x, teacher, student, autoencoder, teacher_mean, teacher_std,
        st_para, ae_para, q_st_start, q_st_end, q_ae_start, q_ae_end,
        channel_weights, edge_mask_w, cand1, height, width)

    if cand1 is not None:
        map_native = maps['map_native']
        raw = torch.max(torch.max(map_native, dim=3)[0], dim=2)[0]
        zmap = (map_native - cand1['mu']) / (cand1['sigma'] + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / cand1['A'], zval / cand1['Z'])

    return torch.max(torch.max(maps['map_resized'], dim=3)[0], dim=2)[0]
