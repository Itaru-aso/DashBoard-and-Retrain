from __future__ import annotations

import json
import os
import re

import torch
import torch.nn as nn
from omegaconf import DictConfig, OmegaConf

from model import EfficientADFullModel, load_para
from utils.common import get_autoencoder, get_pdn_small


class ModelExporter:
    """EfficientAD 学習済みモデルを ONNX 形式にエクスポートするクラス。

    Teacher-Student ネットワークと AutoEncoder を統合した
    EfficientADFullModel を構築し、ONNX ファイルとして保存する。
    monochro（凹凸検査）/ color（色検査）の両モードに対応。

    対応機能:
    - チャネル重み (channel_weights) の組み込み
    - AE 無効時 (ae_para=0) の安全処理
    - threshold の組み込み
    - teacher_mean_1d (新形式) / teacher_mean (旧形式) の両対応
    - ONNX ファイル名: {color}_{mode}_model.onnx (検査PC FTP 互換)
    - ONNX メタデータ: threshold / channel_weights_enabled を追記
    """

    def __init__(self, cfg: DictConfig) -> None:
        self.cfg: DictConfig = cfg
        self.input_dir: str = os.path.join(
            self.cfg.model_dir, str(self.cfg.target_color), self.cfg.mode)

        self.height: int = self.cfg.image_size_height
        self.width: int = self.cfg.image_size_width
        self.out_channels: int = self.cfg.get('out_channels', 384)

        self.gpu_id: int = self.cfg.gpu_id
        self.device: torch.device = torch.device(
            f'cuda:{self.gpu_id}' if torch.cuda.is_available() else 'cpu')
        self.mode: str = self.cfg.mode

    def load_models(self) -> tuple[nn.Module, nn.Module, nn.Module]:
        """学習済みの Teacher, Student, AutoEncoder モデルを読み込む。"""
        teacher_model: nn.Module = get_pdn_small(self.out_channels)
        student_model: nn.Module = get_pdn_small(2 * self.out_channels)
        autoencoder_model: nn.Module = get_autoencoder(
            self.out_channels, image_size_height=self.height, image_size_width=self.width)

        teacher_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'teacher_state_best.pth'),
            map_location=self.device))
        student_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'student_state_best.pth'),
            map_location=self.device))
        autoencoder_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'autoencoder_state_best.pth'),
            map_location=self.device))

        teacher_model.eval()
        student_model.eval()
        autoencoder_model.eval()

        return teacher_model, student_model, autoencoder_model

    def load_parameters(self) -> dict:
        """学習時に保存された正規化パラメータを para.json から読み込む。

        新形式 (teacher_mean_1d) と旧形式 (teacher_mean) の両方に対応。
        JSON が壊れている場合（ブラケット不整合）は自動修復を試みる。

        Returns:
            load_para() の返り値 (dict)
        """
        para_path: str = os.path.join(self.input_dir, 'para.json')

        # JSON 破損チェック・修復
        with open(para_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        try:
            json.loads(raw)
        except json.JSONDecodeError:
            fixed = raw
            opens_brace = fixed.count('{')
            closes_brace = fixed.count('}')
            to_trim = max(0, closes_brace - opens_brace)
            if to_trim:
                fixed = re.sub(r"\s*}\s*$", "", fixed, count=to_trim)

            opens_bracket = fixed.count('[')
            closes_bracket = fixed.count(']')
            to_trim = max(0, closes_bracket - opens_bracket)
            if to_trim:
                fixed = re.sub(r"\s*]\s*$", "", fixed, count=to_trim)

            try:
                json.loads(fixed)
                with open(para_path, 'w', encoding='utf-8') as f:
                    f.write(fixed)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"JSON修正後も読み込み失敗: {e}")

        return load_para(para_path, device=self.device)

    def export_onnx(self) -> str:
        """EfficientADFullModel を ONNX 形式でエクスポートする。

        ファイル名: {color}_{mode}_model.onnx (検査PC FTP アップロード処理との互換維持)
        ONNX メタデータ: threshold / channel_weights_enabled を追記

        Returns:
            エクスポートした ONNX ファイルのパス
        """
        import onnx

        teacher_model, student_model, autoencoder_model = self.load_models()
        para = self.load_parameters()

        model = EfficientADFullModel(
            self.mode, self.height, self.width,
            teacher_model, student_model, autoencoder_model,
            para['teacher_mean'], para['teacher_std'],
            st_para=para['st_para'], ae_para=para['ae_para'],
            q_st_start=para['q_st_start'], q_st_end=para['q_st_end'],
            q_ae_start=para['q_ae_start'], q_ae_end=para['q_ae_end'],
            channel_weights=para['channel_weights'],
            threshold=para['threshold'],
            edge_mask_w=para.get('edge_mask_w', 0),
            cand1=para.get('cand1'),  # monochro+cand1 のとき z-OR 統合スコアを出力
        ).to(self.device)
        model.eval()

        dummy_input: torch.Tensor = torch.randn(
            1, 3, self.height, self.width).to(self.device) * 255

        # 検査PCのFTPアップロード処理との互換のため {color}_{mode}_model.onnx を維持
        onnx_path: str = os.path.join(
            self.input_dir, f"{self.cfg.target_color}_{self.cfg.mode}_model.onnx")

        torch.onnx.export(
            model, dummy_input, onnx_path,
            input_names=["input"],
            output_names=["output"],
            opset_version=11,
            dynamic_axes={
                "input": {0: "batch_size"},
                "output": {0: "batch_size"},
            }
        )

        # ONNX メタデータに threshold / channel_weights_enabled / edge_mask_w を追記
        onnx_model = onnx.load(onnx_path)
        if para.get('threshold') is not None:
            meta = onnx_model.metadata_props.add()
            meta.key = 'threshold'
            meta.value = str(para['threshold'])
        if para.get('channel_weights') is not None:
            meta = onnx_model.metadata_props.add()
            meta.key = 'channel_weights_enabled'
            meta.value = 'true'
        # edge_mask_w (Phase H): C# 側でのトレース用にメタデータに記録 (推論挙動自体は ONNX に内包済)
        edge_mask_w = int(para.get('edge_mask_w', 0))
        meta = onnx_model.metadata_props.add()
        meta.key = 'edge_mask_w'
        meta.value = str(edge_mask_w)
        # 候補1 (z-score OR): C# 側で出力の意味・閾値を判別するためメタに記録。
        # score_type=unified のとき output は統合スコア (NG if >= cand1_T)。raw のとき従来通り。
        cand1 = para.get('cand1')
        c1_enabled = (self.mode == 'monochro' and cand1 is not None)
        for k, v in (('cand1_enabled', 'true' if c1_enabled else 'false'),
                     ('cand1_T', str(cand1['T']) if c1_enabled else ''),
                     ('score_type', 'unified' if c1_enabled else 'raw')):
            m = onnx_model.metadata_props.add(); m.key = k; m.value = v
        onnx.save(onnx_model, onnx_path)

        print(f"Exported ONNX: {onnx_path}")
        print(f"  st_para={para['st_para']}, ae_para={para['ae_para']}")
        print(f"  channel_weights: {'あり' if para['channel_weights'] is not None else 'なし'}")
        print(f"  threshold: {para['threshold']}")
        print(f"  edge_mask_w: {edge_mask_w}")

        return onnx_path


if __name__ == '__main__':
    cfg: DictConfig = OmegaConf.load("./conf/config.yaml")
    exporter: ModelExporter = ModelExporter(cfg)
    exporter.export_onnx()
