"""テスト全体で共有するfixture。"""
import numpy as np
import pytest
import torch

from utils.common import get_autoencoder, get_pdn_small

OUT_CHANNELS = 384
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


@pytest.fixture
def synthetic_scoring_components():
    """teacher/student/autoencoder(乱数初期化・seed固定)と、
    quantile境界・合成画像を含む辞書を返すbuilder関数を提供する。

    Seam3のスコアリング計算パリティテスト(model.py と
    utils.scoring_transform / evaluation.scoring の一致検証)で、
    実際の学習済み重み無しに再現可能な入力を用意するために使う。
    """
    def _build(image_h=256, image_w=512, seed=0):
        torch.manual_seed(seed)
        np.random.seed(seed)

        teacher = get_pdn_small(OUT_CHANNELS)
        student = get_pdn_small(2 * OUT_CHANNELS)
        autoencoder = get_autoencoder(
            OUT_CHANNELS, image_size_height=image_h, image_size_width=image_w)
        teacher.eval()
        student.eval()
        autoencoder.eval()

        img_np = np.random.randint(0, 256, (image_h, image_w, 3), dtype=np.uint8)

        teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
        teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

        with torch.no_grad():
            image_norm = torch.from_numpy(
                img_np.transpose(2, 0, 1)[None]).float() / 255.0
            image_norm = (image_norm - IMAGENET_MEAN) / IMAGENET_STD

            teacher_out = teacher(image_norm)
            teacher_out_n = (teacher_out - teacher_mean) / teacher_std
            student_out = student(image_norm)
            diff_st = (teacher_out_n - student_out[:, :OUT_CHANNELS]) ** 2
            map_st = torch.mean(diff_st, dim=1, keepdim=True)

            autoencoder_out = autoencoder(image_norm)
            map_ae = torch.mean(
                (autoencoder_out - student_out[:, OUT_CHANNELS:]) ** 2,
                dim=1, keepdim=True)

        return {
            'teacher': teacher,
            'student': student,
            'autoencoder': autoencoder,
            'teacher_mean': teacher_mean,
            'teacher_std': teacher_std,
            'image_np': img_np,
            'image_norm': image_norm,
            'q_st_start': map_st.min(),
            'q_st_end': map_st.max(),
            'q_ae_start': map_ae.min(),
            'q_ae_end': map_ae.max(),
            'map_h': map_st.shape[2],
            'map_w': map_st.shape[3],
            'height': image_h,
            'width': image_w,
        }

    return _build
