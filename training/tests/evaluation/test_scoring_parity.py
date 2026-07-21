"""evaluation.scoring.score_images() が model.py の EfficientADFullModel
(実際にデプロイされるスコア計算)と一致することを保証するパリティテスト。

Seam3(ADR-6)以前は evaluation.scoring.score_images() が
st_para=1.0/ae_para=0.0 を決め打ちし、pad+interpolateもcand1も
実装していなかったため、model.pyの実際のデプロイスコアと一致しなかった。

実行: cd training && python -m pytest tests/evaluation/test_scoring_parity.py -v
"""
import json

import numpy as np
import torch
from PIL import Image

from model import EfficientADFullModel


def _write_para_json(tmp_path, c, ae_para=0.0, cand1_enabled=False,
                      cand1_mu=None, cand1_sigma=None,
                      channel_weights=None, edge_mask_w=0):
    para = {
        'teacher_mean_1d': c['teacher_mean'].view(-1).tolist(),
        'teacher_std_1d': c['teacher_std'].view(-1).tolist(),
        'q_st_start': c['q_st_start'].item(),
        'q_st_end': c['q_st_end'].item(),
        'q_ae_start': c['q_ae_start'].item(),
        'q_ae_end': c['q_ae_end'].item(),
        'st_para': 1.0,
        'ae_para': ae_para,
        'edge_mask_w': edge_mask_w,
        'image_size_height': c['height'],
        'image_size_width': c['width'],
    }
    if channel_weights is not None:
        para['channel_weights'] = channel_weights.view(-1).tolist()
    if cand1_enabled:
        para['cand1_enabled'] = True
        para['cand1_mu'] = cand1_mu.tolist()
        para['cand1_sigma'] = cand1_sigma.tolist()
        para['cand1_A'] = 1.0
        para['cand1_Z'] = 3.0
        para['cand1_T'] = 1.0

    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    (model_dir / 'para.json').write_text(json.dumps(para), encoding='utf-8')
    torch.save(c['teacher'].state_dict(), model_dir / 'teacher_state_best.pth')
    torch.save(c['student'].state_dict(), model_dir / 'student_state_best.pth')
    torch.save(c['autoencoder'].state_dict(), model_dir / 'autoencoder_state_best.pth')
    return str(model_dir)


def _write_image(tmp_path, img_np, name='img.png'):
    image_dir = tmp_path / 'images'
    image_dir.mkdir(exist_ok=True)
    Image.fromarray(img_np).save(image_dir / name)
    return str(image_dir), name


def test_score_images_matches_model_forward_config_a(tmp_path, synthetic_scoring_components):
    """config A: ae_para=0, cand1無し (color相当・現状本番構成)。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    model_dir = _write_para_json(tmp_path, c, ae_para=0.0)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    full_model = EfficientADFullModel(
        'color', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4


def test_score_images_matches_model_forward_config_b_ae_enabled(
        tmp_path, synthetic_scoring_components):
    """config B: ae_para=0.7 (AE有効モデル)。旧実装はここで大きく不一致だった。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    model_dir = _write_para_json(tmp_path, c, ae_para=0.7)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    full_model = EfficientADFullModel(
        'color', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4


def test_score_images_matches_model_forward_config_c_cand1(
        tmp_path, synthetic_scoring_components):
    """config C: monochro相当、cand1有効 (現状本番の全monochroモデルの構成)。
    旧実装はcand1を一切実装していなかったため、ここは全く別スケールで不一致だった。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    torch.manual_seed(1)
    mu = (torch.rand(c['map_h'], c['map_w']) * 0.05).numpy().astype(np.float32)
    sigma = (torch.rand(c['map_h'], c['map_w']) * 0.04 + 0.01).numpy().astype(np.float32)

    model_dir = _write_para_json(tmp_path, c, ae_para=0.0, cand1_enabled=True,
                                  cand1_mu=mu, cand1_sigma=sigma)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0, 'T': 1.0}
    full_model = EfficientADFullModel(
        'monochro', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        cand1=cand1,
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4


def test_score_images_matches_model_forward_config_d_channel_weights_and_edge_mask(
        tmp_path, synthetic_scoring_components):
    """config D: channel_weights指定 + edge_mask_w>0 (color本番構成の実際の分岐)。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    torch.manual_seed(2)
    channel_weights = torch.rand(1, 384, 1, 1)

    model_dir = _write_para_json(tmp_path, c, ae_para=0.0,
                                  channel_weights=channel_weights, edge_mask_w=2)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    full_model = EfficientADFullModel(
        'color', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=channel_weights, edge_mask_w=2,
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4
