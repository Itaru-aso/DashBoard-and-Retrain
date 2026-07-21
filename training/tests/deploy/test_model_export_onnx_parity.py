"""model_exporter.ModelExporter がエクスポートするONNXの推論結果が、
model.py の EfficientADFullModel のeager実行結果と一致することを保証する
characterization test。

Seam4でこのファイル(および対象クラス)がdeploy/model_export.pyへ移動した後も、
import行のみ変更してこのテストが変わらず通ることを確認する(挙動保存の証拠)。

実行: cd training && python -m pytest tests/test_model_exporter_onnx_parity.py -v
"""
import json
import os

import numpy as np
import onnxruntime
import torch
from omegaconf import OmegaConf

from model import EfficientADFullModel
from deploy.model_export import ModelExporter
from utils.common import get_autoencoder, get_pdn_small

OUT_CHANNELS = 384


def _build_synthetic_model_dir(tmp_path, mode, cand1_enabled, seed=0):
    """teacher/student/autoencoderの.pthファイルとpara.jsonをtmp_pathに書き出し、
    ModelExporterがそのまま読み込める構造を用意する。
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    height, width = 256, 512
    color = "841"

    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=height, image_size_width=width)
    teacher.eval()
    student.eval()
    autoencoder.eval()

    input_dir = tmp_path / color / mode
    input_dir.mkdir(parents=True, exist_ok=True)
    torch.save(teacher.state_dict(), input_dir / "teacher_state_best.pth")
    torch.save(student.state_dict(), input_dir / "student_state_best.pth")
    torch.save(autoencoder.state_dict(), input_dir / "autoencoder_state_best.pth")

    img_np = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)

    teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
    teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

    image_norm = torch.from_numpy(img_np.transpose(2, 0, 1)[None]).float() / 255.0
    imagenet_mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    imagenet_std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    image_norm = (image_norm - imagenet_mean) / imagenet_std

    with torch.no_grad():
        t_out = teacher(image_norm)
        t_out_n = (t_out - teacher_mean) / teacher_std
        s_out = student(image_norm)
        map_st = torch.mean((t_out_n - s_out[:, :OUT_CHANNELS]) ** 2, dim=1, keepdim=True)
        ae_out = autoencoder(image_norm)
        map_ae = torch.mean((ae_out - s_out[:, OUT_CHANNELS:]) ** 2, dim=1, keepdim=True)

    para = {
        "teacher_mean_1d": teacher_mean.view(-1).tolist(),
        "teacher_std_1d": teacher_std.view(-1).tolist(),
        "q_st_start": map_st.min().item(),
        "q_st_end": map_st.max().item(),
        "q_ae_start": map_ae.min().item(),
        "q_ae_end": map_ae.max().item(),
        "st_para": 1.0,
        "ae_para": 0.0,
        "threshold": 0.5,
        "edge_mask_w": 0,
        "image_size_height": height,
        "image_size_width": width,
    }
    if cand1_enabled:
        torch.manual_seed(seed + 1)
        map_h, map_w = map_st.shape[2], map_st.shape[3]
        mu = (torch.rand(map_h, map_w) * 0.05).numpy().astype(np.float32)
        sigma = (torch.rand(map_h, map_w) * 0.04 + 0.01).numpy().astype(np.float32)
        para["cand1_enabled"] = True
        para["cand1_mu"] = mu.tolist()
        para["cand1_sigma"] = sigma.tolist()
        para["cand1_A"] = 1.0
        para["cand1_Z"] = 3.0
        para["cand1_T"] = 1.0

    with open(input_dir / "para.json", "w", encoding="utf-8") as f:
        json.dump(para, f)

    cfg = OmegaConf.create({
        "model_dir": str(tmp_path),
        "target_color": color,
        "mode": mode,
        "image_size_height": height,
        "image_size_width": width,
        "out_channels": OUT_CHANNELS,
        "gpu_id": 0,
    })

    return {"cfg": cfg, "para": para, "image_np": img_np, "height": height, "width": width}


def _run_onnx(onnx_path, image_np):
    """ONNXモデルに raw pixel (0-255) の画像テンソルを与えて推論する。"""
    session = onnxruntime.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    image_t = image_np.transpose(2, 0, 1)[None].astype(np.float32)
    outputs = session.run(None, {"input": image_t})
    return outputs[0], session


def _run_eager(built, mode):
    """model.py の EfficientADFullModel を直接構築してeager実行する。"""
    cfg, para, image_np = built["cfg"], built["para"], built["image_np"]
    color, height, width = cfg.target_color, built["height"], built["width"]
    input_dir = os.path.join(cfg.model_dir, color, mode)

    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=height, image_size_width=width)
    teacher.load_state_dict(torch.load(os.path.join(input_dir, "teacher_state_best.pth")))
    student.load_state_dict(torch.load(os.path.join(input_dir, "student_state_best.pth")))
    autoencoder.load_state_dict(torch.load(os.path.join(input_dir, "autoencoder_state_best.pth")))
    teacher.eval()
    student.eval()
    autoencoder.eval()

    cand1 = None
    if para.get("cand1_enabled", False):
        cand1 = {
            "mu": np.array(para["cand1_mu"], dtype=np.float32),
            "sigma": np.array(para["cand1_sigma"], dtype=np.float32),
            "A": float(para["cand1_A"]),
            "Z": float(para["cand1_Z"]),
            "T": float(para["cand1_T"]),
        }

    model = EfficientADFullModel(
        mode, height, width, teacher, student, autoencoder,
        torch.tensor(para["teacher_mean_1d"]), torch.tensor(para["teacher_std_1d"]),
        st_para=para["st_para"], ae_para=para["ae_para"],
        q_st_start=torch.tensor(para["q_st_start"]), q_st_end=torch.tensor(para["q_st_end"]),
        q_ae_start=torch.tensor(para["q_ae_start"]), q_ae_end=torch.tensor(para["q_ae_end"]),
        threshold=para["threshold"], edge_mask_w=para.get("edge_mask_w", 0), cand1=cand1,
    ).eval()

    image_t = torch.from_numpy(image_np.transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        return model(image_t).numpy()


def test_export_onnx_matches_eager_model_color(tmp_path):
    """color構成(cand1無し)でONNX出力とeager実行が一致することを確認する。"""
    built = _build_synthetic_model_dir(tmp_path, mode="color", cand1_enabled=False)
    onnx_path = ModelExporter(built["cfg"]).export_onnx()

    onnx_output, session = _run_onnx(onnx_path, built["image_np"])
    eager_output = _run_eager(built, mode="color")

    np.testing.assert_allclose(onnx_output, eager_output, rtol=1e-3, atol=1e-3)

    # onnxruntimeはメタデータをget_modelmeta().custom_metadata_mapで公開する
    meta = dict(session.get_modelmeta().custom_metadata_map)
    assert meta["threshold"] == str(built["para"]["threshold"])
    assert meta["edge_mask_w"] == "0"
    assert meta["cand1_enabled"] == "false"
    assert meta["score_type"] == "raw"


def test_export_onnx_matches_eager_model_monochro_cand1(tmp_path):
    """monochro+cand1有効構成でONNX出力とeager実行が一致することを確認する。"""
    built = _build_synthetic_model_dir(tmp_path, mode="monochro", cand1_enabled=True)
    onnx_path = ModelExporter(built["cfg"]).export_onnx()

    onnx_output, session = _run_onnx(onnx_path, built["image_np"])
    eager_output = _run_eager(built, mode="monochro")

    np.testing.assert_allclose(onnx_output, eager_output, rtol=1e-3, atol=1e-3)

    meta = dict(session.get_modelmeta().custom_metadata_map)
    assert meta["threshold"] == str(built["para"]["threshold"])
    assert meta["cand1_enabled"] == "true"
    assert meta["cand1_T"] == str(built["para"]["cand1_T"])
    assert meta["score_type"] == "unified"
