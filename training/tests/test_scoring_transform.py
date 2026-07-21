"""utils.scoring_transform.compute_anomaly_score の正当性を検証する。

model.py の EfficientADFullModel.forward() (Seam3抽出前) を字句通り
複製した参照実装 (_reference_compute) との数値一致を保証する。

実行: cd training && python -m pytest tests/test_scoring_transform.py -v
"""
import torch

from utils.edge_mask import apply_edge_mask_zero


def _reference_compute(x, teacher, student, autoencoder, teacher_mean, teacher_std,
                        st_para, ae_para, q_st_start, q_st_end, q_ae_start, q_ae_end,
                        channel_weights, edge_mask_w, cand1, height, width):
    """Seam3抽出前の model.py EfficientADFullModel.forward() 本体の字句通りの複製。

    teacher_mean/teacher_std は呼び出し側で (1, C, 1, 1) 形状に整えて渡すこと
    (model.py の register_buffer 済みバッファと同じ契約)。
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

    if cand1 is not None:
        raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        zmap = (map_combined - cand1['mu']) / (cand1['sigma'] + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / cand1['A'], zval / cand1['Z'])

    map_combined = torch.nn.functional.pad(map_combined, (4, 4, 4, 4))
    map_combined = torch.nn.functional.interpolate(
        map_combined, (height, width), mode='bilinear')
    return torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]


def test_compute_anomaly_score_matches_reference_config_a(synthetic_scoring_components):
    """config A: ae_para=0, cand1無し (color相当・現状本番構成)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=None,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)


def test_compute_anomaly_score_matches_reference_config_b(synthetic_scoring_components):
    """config B: ae_para=0.7 (AE有効。config.yamlのmap_aeが将来0以外になった場合の回帰防止)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=None,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)


def test_compute_anomaly_score_matches_reference_config_d_channel_weights_and_edge_mask(
        synthetic_scoring_components):
    """config D: channel_weights指定 + edge_mask_w>0 (color本番構成の実際の分岐)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    torch.manual_seed(2)
    channel_weights = torch.rand(1, 384, 1, 1)

    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=channel_weights, edge_mask_w=2, cand1=None,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)


def test_compute_anomaly_score_matches_reference_config_c(synthetic_scoring_components):
    """config C: monochro相当、cand1有効 (現状本番の全monochroモデルの構成)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    torch.manual_seed(1)
    mu = torch.rand(1, 1, c['map_h'], c['map_w']) * 0.05
    sigma = torch.rand(1, 1, c['map_h'], c['map_w']) * 0.04 + 0.01
    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0}

    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=cand1,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)
