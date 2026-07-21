"""EfficientADFullModel.forward() の Seam3抽出前後の一致を保証する回帰テスト。

_reference_forward は Seam3抽出直前の model.py forward() 本体を
字句通り複製した参照実装。抽出後もこの出力と一致することを保証する。

実行: cd training && python -m pytest tests/model/test_efficientad_full_model_regression.py -v
"""
import torch

from model import EfficientADFullModel


def _reference_forward(model, x):
    x = x / 255.0
    x = (x - model.mean) / model.std

    teacher_output = model.teacher(x)
    teacher_output = (teacher_output - model.teacher_mean) / model.teacher_std
    student_output = model.student(x)

    diff_st = (teacher_output - student_output[:, :model.out_channels]) ** 2
    if model.channel_weights is not None:
        map_st = torch.sum(diff_st * model.channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    if model.ae_para > 0:
        autoencoder_output = model.autoencoder(x)
        map_ae = torch.mean(
            (autoencoder_output - student_output[:, model.out_channels:]) ** 2,
            dim=1, keepdim=True)
    else:
        map_ae = torch.zeros_like(map_st)

    if model.q_st_start is not None:
        map_st = 0.1 * (map_st - model.q_st_start) / (model.q_st_end - model.q_st_start)
    if model.q_ae_start is not None and model.ae_para > 0:
        map_ae = 0.1 * (map_ae - model.q_ae_start) / (model.q_ae_end - model.q_ae_start)

    map_combined = model.st_para * map_st + model.ae_para * map_ae

    edge_w = int(model.edge_mask_w)
    if edge_w > 0:
        from utils.edge_mask import apply_edge_mask_zero
        map_combined = apply_edge_mask_zero(map_combined, edge_w)

    if model.cand1_enabled:
        raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        zmap = (map_combined - model.cand1_mu) / (model.cand1_sigma + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / model.cand1_A, zval / model.cand1_Z)

    map_combined = torch.nn.functional.pad(map_combined, (4, 4, 4, 4))
    map_combined = torch.nn.functional.interpolate(
        map_combined, (model.height, model.width), mode='bilinear')
    return torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]


def _build_model(c, mode='color', cand1=None):
    return EfficientADFullModel(
        mode, c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0 if cand1 is not None else 0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, threshold=None, edge_mask_w=0, cand1=cand1,
    ).eval()


def test_forward_matches_reference_no_cand1_branch(synthetic_scoring_components):
    """pad+interpolate分岐(cand1無し)。AE分岐(ae_para>0)も併せて被覆する。

    Task1のパリティテストのconfig A/B(ae_para=0 / ae_para=0.7)とは別軸の
    検証観点(model.py自身のforward委譲が正しいか)のためのテストであり、
    名称の対応関係は意図的に持たせていない。
    """
    c = synthetic_scoring_components()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    model = _build_model(c, mode='color', cand1=None)

    with torch.no_grad():
        actual = model(image_raw)
        expected = _reference_forward(model, image_raw)

    assert torch.allclose(actual, expected)


def test_forward_matches_reference_cand1_branch(synthetic_scoring_components):
    """cand1統合スコア分岐(monochro相当)。"""
    c = synthetic_scoring_components()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    torch.manual_seed(1)
    mu = torch.rand(c['map_h'], c['map_w']).numpy() * 0.05
    sigma = torch.rand(c['map_h'], c['map_w']).numpy() * 0.04 + 0.01
    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0, 'T': 1.0}
    model = _build_model(c, mode='monochro', cand1=cand1)

    with torch.no_grad():
        actual = model(image_raw)
        expected = _reference_forward(model, image_raw)

    assert torch.allclose(actual, expected)
