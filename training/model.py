import torch
import json
import os
import numpy as np
import torch.nn as nn
from torchvision import transforms

from utils.common import get_autoencoder, get_pdn_small
from utils.edge_mask import apply_edge_mask_zero
from utils.scoring_transform import compute_anomaly_score


class EfficientADFullModel(torch.nn.Module):
    """EfficientAD 統合推論モデル（ONNX エクスポート対応）

    Teacher-Student + AutoEncoder を統合し、anomaly score を出力する。
    - チャネル重み (channel_weights) 対応
    - AE 無効時 (ae_para=0) の安全処理（AE出力サイズ不一致回避）
    - threshold による OK/NG 判定
    """

    def __init__(self, mode, height, width, teacher, student, autoencoder,
                 teacher_mean, teacher_std,
                 st_para, ae_para,
                 q_st_start=None, q_st_end=None,
                 q_ae_start=None, q_ae_end=None,
                 channel_weights=None, threshold=None,
                 edge_mask_w=0, cand1=None):
        super().__init__()

        self.mode = mode
        self.height = height
        self.width = width
        self.out_channels = 384

        self.register_buffer(
            "edge_mask_w", torch.tensor(int(edge_mask_w), dtype=torch.int64))

        self.teacher = teacher
        self.student = student
        self.autoencoder = autoencoder

        if self.mode == "monochro":
            self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        elif self.mode == "color":
            self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        else:
            raise ValueError("Invalid mode. Choose monochro or color")

        self.register_buffer("teacher_mean", teacher_mean.view(1, -1, 1, 1))
        self.register_buffer("teacher_std", teacher_std.view(1, -1, 1, 1))
        self.register_buffer("st_para", torch.tensor(st_para))
        self.register_buffer("ae_para", torch.tensor(ae_para))

        if q_st_start is not None:
            self.register_buffer("q_st_start", q_st_start)
            self.register_buffer("q_st_end", q_st_end)
        else:
            self.q_st_start = self.q_st_end = None

        if q_ae_start is not None:
            self.register_buffer("q_ae_start", q_ae_start)
            self.register_buffer("q_ae_end", q_ae_end)
        else:
            self.q_ae_start = self.q_ae_end = None

        # チャネル重み: [1, 384, 1, 1] or None
        if channel_weights is not None:
            self.register_buffer("channel_weights", channel_weights.view(1, -1, 1, 1))
        else:
            self.channel_weights = None

        # 閾値: score >= threshold → NG
        if threshold is not None:
            self.register_buffer("threshold_val", torch.tensor(threshold))
        else:
            self.threshold_val = None

        # 候補1 (raw + z-score OR, monochro 専用): cand1=dict(mu,sigma,A,Z,T) or None。
        # 有効時 forward は統合スコア max(raw/A, z/Z) を出力 (NG if >= T は C#/外部で判定)。
        # mode!=monochro or cand1=None なら従来 raw 出力 (後方互換)。
        self.cand1_enabled = False
        if self.mode == "monochro" and cand1 is not None:
            mu = torch.as_tensor(cand1["mu"], dtype=torch.float32)
            sigma = torch.as_tensor(cand1["sigma"], dtype=torch.float32)
            self.register_buffer("cand1_mu", mu.view(1, 1, *mu.shape))
            self.register_buffer("cand1_sigma", sigma.view(1, 1, *sigma.shape))
            self.register_buffer("cand1_A", torch.tensor(float(cand1["A"])))
            self.register_buffer("cand1_Z", torch.tensor(float(cand1["Z"])))
            self.register_buffer("cand1_T", torch.tensor(float(cand1.get("T", 1.0))))
            self.cand1_enabled = True

    def forward(self, x):
        x = x / 255.0
        x = (x - self.mean) / self.std

        cand1 = None
        if self.cand1_enabled:
            cand1 = {
                'mu': self.cand1_mu,
                'sigma': self.cand1_sigma,
                'A': self.cand1_A,
                'Z': self.cand1_Z,
            }

        return compute_anomaly_score(
            x, self.teacher, self.student, self.autoencoder,
            self.teacher_mean, self.teacher_std,
            self.st_para, self.ae_para,
            q_st_start=self.q_st_start, q_st_end=self.q_st_end,
            q_ae_start=self.q_ae_start, q_ae_end=self.q_ae_end,
            channel_weights=self.channel_weights,
            edge_mask_w=int(self.edge_mask_w),
            cand1=cand1,
            height=self.height, width=self.width,
        )


def load_para(para_path, device='cpu'):
    """para.json を読み込み、テンソル化して返す。

    新形式 (teacher_mean_1d) と旧形式 (teacher_mean) の両方に対応。
    """
    with open(para_path, 'r', encoding='utf-8') as f:
        para = json.load(f)

    # teacher_mean/std: 新形式があれば使用、なければ旧形式から reshape
    if 'teacher_mean_1d' in para:
        teacher_mean = torch.tensor(para['teacher_mean_1d'], dtype=torch.float32)
    else:
        teacher_mean = torch.tensor(para['teacher_mean']).reshape(-1).float()

    if 'teacher_std_1d' in para:
        teacher_std = torch.tensor(para['teacher_std_1d'], dtype=torch.float32)
    else:
        teacher_std = torch.tensor(para['teacher_std']).reshape(-1).float()

    q_st_start = torch.tensor(para['q_st_start']).squeeze().float()
    q_st_end = torch.tensor(para['q_st_end']).squeeze().float()
    q_ae_start = torch.tensor(para['q_ae_start']).squeeze().float()
    q_ae_end = torch.tensor(para['q_ae_end']).squeeze().float()

    # チャネル重み (あれば)
    channel_weights = None
    if 'channel_weights' in para:
        channel_weights = torch.tensor(para['channel_weights'], dtype=torch.float32)

    # 閾値 (あれば)
    threshold = para.get('threshold', None)

    # st_para/ae_para
    st_para = para.get('st_para', 1.0)
    ae_para = para.get('ae_para', 0.0)

    # edge_mask_w (Phase H): anomaly map の両端 N 列を推論時に除外 (旧 para.json は 0)
    edge_mask_w = int(para.get('edge_mask_w', 0))

    # 候補1 (z-score OR, monochro 専用): cand1_enabled があれば μ,σ,A,Z,T を読む。無ければ None=従来 raw。
    cand1 = None
    if para.get('cand1_enabled', False):
        cand1 = {
            'mu': np.array(para['cand1_mu'], dtype=np.float32),
            'sigma': np.array(para['cand1_sigma'], dtype=np.float32),
            'A': float(para['cand1_A']),
            'Z': float(para['cand1_Z']),
            'T': float(para.get('cand1_T', 1.0)),
        }

    return {
        'teacher_mean': teacher_mean.to(device),
        'teacher_std': teacher_std.to(device),
        'q_st_start': q_st_start.to(device),
        'q_st_end': q_st_end.to(device),
        'q_ae_start': q_ae_start.to(device),
        'q_ae_end': q_ae_end.to(device),
        'channel_weights': channel_weights.to(device) if channel_weights is not None else None,
        'threshold': threshold,
        'st_para': st_para if st_para is not None else 1.0,
        'ae_para': ae_para if ae_para is not None else 0.0,
        'edge_mask_w': edge_mask_w,
        'cand1': cand1,
    }


def build_full_model(mode, color_num, model_dir, device='cpu'):
    """学習済みモデルとパラメータから EfficientADFullModel を構築する。

    Args:
        mode: "monochro" or "color"
        color_num: 色番号 (str)
        model_dir: モデルディレクトリのルート
        device: 推論デバイス

    Returns:
        EfficientADFullModel (eval モード)
    """
    out_channels = 384
    input_dir = os.path.join(model_dir, color_num, mode)

    teacher = get_pdn_small(out_channels)
    student = get_pdn_small(2 * out_channels)
    # para.json に image_size が保存されていれば AE をその解像度に合わせて構築
    _para_path = os.path.join(input_dir, 'para.json')
    _img_h, _img_w = 256, 512
    if os.path.exists(_para_path):
        with open(_para_path, 'r') as _pf:
            _p = json.load(_pf)
        _img_h = int(_p.get('image_size_height', 256))
        _img_w = int(_p.get('image_size_width', 512))
    autoencoder = get_autoencoder(out_channels,
                                  image_size_height=_img_h,
                                  image_size_width=_img_w)

    teacher.load_state_dict(torch.load(
        os.path.join(input_dir, 'teacher_state_best.pth'), map_location=device))
    student.load_state_dict(torch.load(
        os.path.join(input_dir, 'student_state_best.pth'), map_location=device))
    autoencoder.load_state_dict(torch.load(
        os.path.join(input_dir, 'autoencoder_state_best.pth'), map_location=device))

    para = load_para(os.path.join(input_dir, 'para.json'), device=device)

    from omegaconf import OmegaConf
    cfg = OmegaConf.load('./conf/config.yaml')
    height = cfg.image_size_height if hasattr(cfg, 'image_size_height') else _img_h
    width = cfg.image_size_width if hasattr(cfg, 'image_size_width') else _img_w

    model = EfficientADFullModel(
        mode, height, width, teacher, student, autoencoder,
        para['teacher_mean'], para['teacher_std'],
        st_para=para['st_para'], ae_para=para['ae_para'],
        q_st_start=para['q_st_start'], q_st_end=para['q_st_end'],
        q_ae_start=para['q_ae_start'], q_ae_end=para['q_ae_end'],
        channel_weights=para['channel_weights'],
        threshold=para['threshold'],
        edge_mask_w=para.get('edge_mask_w', 0),
        cand1=para.get('cand1'),  # monochro+cand1 で z-OR 統合スコア (Python 評価も本番と一致)
    ).to(device)
    model.eval()
    return model


def test_efficientad_full_model(color_num, mode, image_path, model_dir='./model'):
    """テスト用: 1枚の画像に対して推論を実行する"""
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

    model = build_full_model(mode, color_num, model_dir, device=device)

    from PIL import Image
    image = Image.open(image_path).convert('RGB')
    image_np = np.array(image, dtype=np.float32).transpose(2, 0, 1)[np.newaxis, ...]
    image_tensor = torch.from_numpy(image_np).to(torch.float32).to(device)

    with torch.no_grad():
        score = model(image_tensor)

    threshold = model.threshold_val
    if threshold is not None:
        result = "NG" if score.item() >= threshold.item() else "OK"
        print(f"Score: {score.item():.4f}, Threshold: {threshold.item():.4f}, Result: {result}")
    else:
        print(f"Score: {score.item():.4f} (threshold not set)")

    return score.item()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--color', default='841', help='色番号')
    parser.add_argument('--mode', default='color', help='monochro or color')
    parser.add_argument('--image', required=True, help='テスト画像パス')
    parser.add_argument('--model_dir', default='./model', help='モデルディレクトリ')
    args = parser.parse_args()
    test_efficientad_full_model(args.color, args.mode, args.image, args.model_dir)
