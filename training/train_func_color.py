#!/usr/bin/python
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import seaborn as sns
import tifffile
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import transforms
from sklearn.metrics import confusion_matrix
import argparse
import itertools
import os
import shutil
import random
import json
from tqdm import tqdm
from torch.amp import GradScaler, autocast
from utils.common import get_autoencoder_256_512, get_autoencoder, get_pdn_small, get_pdn_medium, \
    ImageFolderWithoutTarget, ImageFolderWithPath, InfiniteDataloader, OpenCVResize
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, precision_recall_fscore_support, precision_recall_curve
from omegaconf import DictConfig
from utils.channel_weights import compute_channel_weights
from utils.edge_mask import slice_edge_excluded
import glob
# numpyをjson形式に対応させるための関数
def numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)

# constants
seed = 42
random.seed(0)
on_gpu = torch.cuda.is_available()
out_channels = 384

def focal_feature_loss(distance, gamma=2.0):
    """Focal Feature Loss: 困難な特徴ほど重みが大きくなる連続的な損失関数。

    Hard Feature Lossがquantile閾値で離散的に上位0.1%だけ選択するのに対し、
    全特徴に連続的な重み付けを行うことで学習を安定させる。

    Args:
        distance: Teacher-Student間の二乗距離テンソル
        gamma: 集中度パラメータ (大きいほど困難な特徴に集中)
    """
    d_norm = distance / (distance.max().detach() + 1e-8)
    weights = d_norm ** gamma
    return torch.mean(weights * distance)

if os.name != 'nt':
    # expandable_segments は Linux 限定 (Windows では非対応で警告が出るため抑制)
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

val_default_transform = transforms.Compose([
    #OpenCVResize(width=512, height=256),
    #transforms.Resize((304, 416)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

default_transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

class GaussianNoise:
    """ガウシアンノイズを付加する変換（pickle可能）"""
    def __init__(self, std=0.02):
        self.std = std

    def __call__(self, image):
        import torchvision.transforms.functional as TF
        tensor = TF.to_tensor(image)
        noise = torch.randn_like(tensor) * self.std
        tensor = torch.clamp(tensor + noise, 0.0, 1.0)
        return TF.to_pil_image(tensor)

def get_pre_transform(cfg):
    aug = cfg.augmentation.color
    # 原論文準拠: RandomChoiceで1つ選択（AE入力専用）
    choices = [
        transforms.ColorJitter(brightness=aug.get('ae_color_jitter_brightness', 0.2)),
        transforms.ColorJitter(contrast=aug.get('ae_color_jitter_contrast', 0.2)),
        transforms.ColorJitter(saturation=aug.get('ae_color_jitter_saturation', 0.2)),
    ]
    # 追加Augmentation（configで0以外の場合のみ有効化）
    blur_kernel = aug.get('ae_gaussian_blur_kernel', 0)
    if blur_kernel > 0:
        choices.append(transforms.GaussianBlur(
            kernel_size=blur_kernel,
            sigma=(aug.get('ae_gaussian_blur_sigma_min', 0.1),
                   aug.get('ae_gaussian_blur_sigma_max', 1.0))))
    noise_std = aug.get('ae_gaussian_noise_std', 0.0)
    if noise_std > 0:
        choices.append(GaussianNoise(std=noise_std))
    affine_degrees = aug.get('ae_random_affine_degrees', 0)
    if affine_degrees > 0:
        translate = tuple(aug.get('ae_random_affine_translate', [0.03, 0.03]))
        choices.append(transforms.RandomAffine(degrees=affine_degrees, translate=translate))
    return transforms.RandomChoice(choices)

def get_st_transform(cfg):
    """ST入力用の軽微なAugmentationを構築する（configで無効化可能）"""
    st_cfg = cfg.get('st_augmentation', None)
    if st_cfg is None or not st_cfg.get('enabled', False):
        return None
    tf_list = []
    if st_cfg.get('horizontal_flip', False):
        tf_list.append(transforms.RandomHorizontalFlip())
    brightness = st_cfg.get('color_jitter_brightness', 0)
    contrast = st_cfg.get('color_jitter_contrast', 0)
    saturation = st_cfg.get('color_jitter_saturation', 0)
    if brightness > 0 or contrast > 0 or saturation > 0:
        tf_list.append(transforms.ColorJitter(
            brightness=brightness, contrast=contrast, saturation=saturation))
    if not tf_list:
        return None
    return transforms.Compose(tf_list)

class TrainTransform:
    """pickle可能なtrain transform（Windows multiprocessing対応）"""
    def __init__(self, pre_tf, default_tf, st_tf=None):
        self.pre_tf = pre_tf
        self.default_tf = default_tf
        self.st_tf = st_tf

    def __call__(self, image):
        # ST入力: 軽微なaugmentation（configで制御、Noneなら原論文準拠）
        if self.st_tf is not None:
            st_image = self.default_tf(self.st_tf(image))
        else:
            st_image = self.default_tf(image)
        # AE入力: augmentationあり
        ae_image = self.default_tf(self.pre_tf(image))
        return st_image, ae_image


def _resolve_teacher_weights_path(cfg) -> str:
    """Teacher 重みファイルの絶対パスを解決する (monochro と対称)。

    cfg.teacher_weights が指定されていればそれを使い、
    なければ cfg.pretraining_dir 配下の命名規約から自動推定する。

    retrain_app_CW での想定配置 (常に {h}_{w}_ prefix を付ける):
        0_pretraining/384_512_teacher_small_color_wide_resnet101_final_state.pth
        0_pretraining/256_512_teacher_small_color_wide_resnet101_final_state.pth
    """
    override = cfg.get('teacher_weights', None)
    if override:
        return override
    pretraining_dir = cfg.get('pretraining_dir', './0_pretraining')
    model_size = cfg.get('model_size', 'small')
    backbone = cfg.get('backbone', 'wide_resnet101')
    h = int(cfg.image_size_height)
    w = int(cfg.image_size_width)
    fname = f'{h}_{w}_teacher_{model_size}_color_{backbone}_final_state.pth'
    return os.path.join(pretraining_dir, fname)


def train_color(cfg: DictConfig, mgr=None):

    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    image_size_height = cfg.image_size_height
    image_size_width = cfg.image_size_width

    # 両端 padding artifact を loss / quantile / threshold 計算から除外する幅 (W 列単位)
    # cfg.color.edge_mask_w で設定、デフォルト 0 (= 無効、後方互換)
    edge_mask_w = int(cfg.get('edge_mask_w', 0))
    if edge_mask_w > 0:
        print(f'[edge_mask_w={edge_mask_w}] 両端マスクを loss / quantile / threshold 計算から除外')

    output_dir = cfg.model_dir

    scaler = GradScaler(device='cuda')

    # color 専用: {model_dir}/{target_color}/{color_subdir}/ に保存
    # color_subdir は config で上書き可 (環境別学習時は color_<env> 等、monochro 側と対称)
    color_subdir = cfg.get('color_subdir', 'color')
    train_output_dir = os.path.join(output_dir, str(cfg.target_color), color_subdir)

    # 使用したいGPUの番号を指定
    gpu_id = 0
    # デバイスを作成
    device = torch.device(f'cuda:{gpu_id}' if torch.cuda.is_available() else 'cpu')

    if os.path.isdir(train_output_dir):
        pass
    else:
        os.makedirs(train_output_dir)

    dataset_dir_path = cfg.dataset_path
    color_num = str(cfg.target_color)
    # color 専用: {dataset_path}/{target_color}/{color_subdir}/ を参照 (monochro 側と対称)
    dataset_path = os.path.join(dataset_dir_path, color_num, color_subdir)

    pretrain_penalty = True
    # load data
    pre_tf = get_pre_transform(cfg)
    st_tf = get_st_transform(cfg)
    train_tf = TrainTransform(pre_tf, default_transform, st_tf=st_tf)
    full_train_set = ImageFolderWithoutTarget(
        os.path.join(dataset_path, 'train'),
        transform=train_tf)

    # 訓練、検証、テストに分割
    train_size = int(0.8 * len(full_train_set))
    validation_size = len(full_train_set) - train_size
    rng = torch.Generator().manual_seed(seed)
    train_set, validation_set = torch.utils.data.random_split(full_train_set,
                                                        [train_size,
                                                        validation_size],
                                                        rng)

    _nw = int(cfg.get('num_workers', 4))
    _pw = bool(cfg.get('persistent_workers', False)) and _nw > 0
    train_loader = DataLoader(train_set, batch_size=cfg.batch_size, shuffle=True,
                            num_workers=_nw, pin_memory=True, persistent_workers=_pw)
    validation_loader = DataLoader(validation_set, batch_size=cfg.batch_size)

    train_loader_infinite = InfiniteDataloader(train_loader)

    imagenet_train_path = cfg.get('imagenet_train_path', 'none')
    if imagenet_train_path == 'none' or not imagenet_train_path:
        pretrain_penalty = False

    if pretrain_penalty:
        # load pretraining data for penalty
        pen_aug = cfg.get('penalty_augmentation', {})
        penalty_transform_list = [
            transforms.Resize((2 * image_size_height, 2 * image_size_width)),
            transforms.RandomGrayscale(pen_aug.get('grayscale_p', 0.3)),
            transforms.RandomCrop((image_size_height, image_size_width)),
        ]
        if pen_aug.get('horizontal_flip', True):
            penalty_transform_list.append(transforms.RandomHorizontalFlip())
        if pen_aug.get('color_jitter_brightness', 0.2) > 0:
            penalty_transform_list.append(transforms.ColorJitter(
                brightness=pen_aug.get('color_jitter_brightness', 0.2),
                contrast=pen_aug.get('color_jitter_contrast', 0.2),
                saturation=pen_aug.get('color_jitter_saturation', 0.2)))
        penalty_transform_list.extend([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224,
                                                                0.225]),
        ])
        if pen_aug.get('random_erasing_p', 0.1) > 0:
            penalty_transform_list.append(transforms.RandomErasing(
                p=pen_aug.get('random_erasing_p', 0.1),
                scale=(0.02, 0.15)))
        penalty_transform = transforms.Compose(penalty_transform_list)
        penalty_set = ImageFolderWithoutTarget(imagenet_train_path,
                                            transform=penalty_transform)
        penalty_loader = DataLoader(penalty_set, batch_size=cfg.batch_size, shuffle=True,
                                    num_workers=_nw, pin_memory=True, persistent_workers=_pw)
        penalty_loader_infinite = InfiniteDataloader(penalty_loader)
        penalty_set_size = len(penalty_set)

        print("The size of training_set is {}.".format(len(full_train_set)))
        print(f"The size of penalty_set is {penalty_set_size}.")
    else:
        penalty_loader_infinite = itertools.repeat(None)

    pdn_dropout = cfg.get('pdn_dropout', 0.0)  # 論文準拠デフォルト: 0.0
    if cfg.model_size == "small":
        teacher = get_pdn_small(out_channels, dropout_rate=pdn_dropout)
        student = get_pdn_small(2 * out_channels, dropout_rate=pdn_dropout)
    elif cfg.model_size == "medium":
        teacher = get_pdn_medium(out_channels, dropout_rate=pdn_dropout)
        student = get_pdn_medium(2 * out_channels, dropout_rate=pdn_dropout)

    weights_path = _resolve_teacher_weights_path(cfg)
    print(f'Teacher 重み: {weights_path}')
    state_dict = torch.load(weights_path, map_location='cpu', weights_only=True)
    # 旧 PDN (Dropout なし、最終 Conv が index 8) → 現行 PDN (Dropout 追加、最終 Conv が index 9) へのキー読み替え
    if '8.weight' in state_dict and '9.weight' not in state_dict:
        state_dict = {(('9' + k[1:]) if k.startswith('8.') else k): v for k, v in state_dict.items()}
    teacher.load_state_dict(state_dict) #TeacherモデルにPretrainingで作成した
    autoencoder = get_autoencoder(out_channels,
                                  image_size_height=image_size_height,
                                  image_size_width=image_size_width)

    # teacher frozen
    teacher.eval()
    student.train()
    autoencoder.train()

    if on_gpu:
        teacher.to(device)
        student.to(device)
        autoencoder.to(device)

    best_val_loss = float('inf')
    val_patience_counter = 0

    train_dataset_size = len(full_train_set)
    iterations_per_epoch = train_dataset_size // cfg.batch_size
    target_step = iterations_per_epoch * cfg.epochs
    # max_train_step キャップ: データ増加時の学習時間増をキャップで抑える
    max_train_step = cfg.get('max_train_step', None)
    if max_train_step is not None and max_train_step > 0:
        cfg.train_step = min(target_step, int(max_train_step))
        print(f"  train_step: {cfg.train_step} (target={target_step}, cap={max_train_step})")
    else:
        cfg.train_step = target_step
        print(f"  train_step: {cfg.train_step} (target={target_step}, cap=none)")

    # val_interval: cfg.val_interval があればそれを使い、無ければ len(train_loader) (1 epoch 毎)
    cfg_val_interval = cfg.get('val_interval', None)
    val_interval = int(cfg_val_interval) if cfg_val_interval else len(train_loader)
    print(f'[val_interval={val_interval}] {val_interval} step ごとに validation 実行')

    teacher_mean, teacher_std = teacher_normalization(teacher, train_loader)

    optimizer = torch.optim.AdamW(itertools.chain(student.parameters(),
                                                autoencoder.parameters()),
                                lr=cfg.model.lr, weight_decay=cfg.model.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=cfg.train_step)

    # MLflow step ログ間隔
    mlflow_log_interval = cfg.get('mlflow', {}).get('log', {}).get('train_step_interval', 500)

    tqdm_obj = tqdm(range(cfg.train_step))
    for iteration, (image_st, image_ae), image_penalty in zip(
            tqdm_obj, train_loader_infinite, penalty_loader_infinite):
        optimizer.zero_grad()
        with autocast("cuda"):
            if on_gpu:
                image_st = image_st.to(device)
                image_ae = image_ae.to(device)
                if image_penalty is not None:
                    image_penalty = image_penalty.to(device)

            with torch.no_grad():
                teacher_output_st = teacher(image_st)
                teacher_output_st = (teacher_output_st - teacher_mean) / teacher_std
            student_output_st = student(image_st)[:, :out_channels]

            distance_st = (teacher_output_st - student_output_st) ** 2
            distance_st_masked = slice_edge_excluded(distance_st, edge_mask_w)

            loss_type = cfg.get('st_loss_type', 'hard')  # 'hard' or 'focal'
            if loss_type == 'focal':
                focal_gamma = cfg.get('focal_gamma', 2.0)
                loss_hard = focal_feature_loss(distance_st_masked, gamma=focal_gamma)
            else:
                flat = distance_st_masked.flatten()
                max_elements = 100_000
                if flat.numel() > max_elements:
                    indices = torch.randperm(flat.numel(), device=flat.device)[:max_elements]
                    flat = flat[indices]
                d_hard = torch.quantile(flat, q=cfg.get('hard_mining_quantile', 0.999))
                loss_hard = torch.mean(distance_st_masked[distance_st_masked >= d_hard])

            # --- メモリ節約：不要なテンソルを削除 ---
            del teacher_output_st, student_output_st, distance_st

            if image_penalty is not None:
                student_output_penalty = student(image_penalty)[:, :out_channels]
                loss_penalty = torch.mean(student_output_penalty**2)
                penalty_weight = cfg.get('penalty_weight', 1.0)
                loss_st = loss_hard + penalty_weight * loss_penalty
            else:
                loss_st = loss_hard

            with torch.no_grad():
                teacher_output_ae = teacher(image_ae)
                teacher_output_ae = (teacher_output_ae - teacher_mean) / teacher_std
            target_size = teacher_output_ae.shape[2:]  # (height, width)

            ae_output = autoencoder(image_ae)
            student_output_ae = student(image_ae)[:, out_channels:]

            distance_ae = (teacher_output_ae - ae_output)**2
            distance_stae = (ae_output - student_output_ae)**2
            loss_ae = torch.mean(slice_edge_excluded(distance_ae, edge_mask_w))  # autoencoderの出力とteacherの出力の距離
            loss_stae = torch.mean(slice_edge_excluded(distance_stae, edge_mask_w))  # autoencoderの出力とstudentの出力の距離
            loss_total = cfg.loss_st * loss_st + cfg.loss_ae * loss_ae + cfg.loss_stae * loss_stae

        scaler.scale(loss_total).backward()
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        if iteration % 10 == 0:
            tqdm_obj.set_description(
                "Current loss: {:.4f}  ".format(loss_total.item()))

        # MLflow step メトリクスのログ
        if mgr is not None and mlflow_log_interval > 0 and iteration % mlflow_log_interval == 0:
            step_metrics = {'train_loss_total': loss_total.item(),
                            'train_loss_st': loss_st.item(),
                            'train_loss_ae': loss_ae.item()}
            if image_penalty is not None:
                step_metrics['train_loss_penalty'] = loss_penalty.item()
            mgr.log_metrics(step_metrics, step=iteration)

        if iteration % val_interval == 0:
            val_loss = evaluate_validation_loss(validation_loader, teacher, student, autoencoder, teacher_mean, teacher_std, device, cfg)
            print(f"Validation Loss: {val_loss:.4f}")
            if mgr is not None:
                mgr.log_metrics({'val_loss': val_loss}, step=iteration)

            # NOTE: temp .pth (teacher/student/autoencoder_state_temp.pth) は学習時間短縮のため削除済み
            # best 更新時のみ *_state_best.pth を保存する (下記 if val_loss < best_val_loss ブロック参照)

            q_st_start, q_st_end, q_ae_start, q_ae_end = map_normalization(
                validation_loader=validation_loader, teacher=teacher,
                student=student, autoencoder=autoencoder,
                teacher_mean=teacher_mean, teacher_std=teacher_std, st_para=cfg.map_st, ae_para=cfg.map_ae,
                desc='Intermediate map normalization',
                edge_mask_w=edge_mask_w)


            # best モデル保存も patience リセットも「min_delta 以上の真の改善」で統一
            min_delta = float(cfg.get('early_stop_min_delta', 0.0))
            meaningful_improved = val_loss < (best_val_loss - min_delta)

            if meaningful_improved:
                best_val_loss = val_loss
                val_patience_counter = 0
                torch.save(teacher.state_dict(), os.path.join(train_output_dir, 'teacher_state_best.pth'))
                torch.save(student.state_dict(), os.path.join(train_output_dir, 'student_state_best.pth'))
                torch.save(autoencoder.state_dict(), os.path.join(train_output_dir, 'autoencoder_state_best.pth'))

                q_st_start_l = [q_st_start.to('cpu').detach().numpy().copy()]
                q_st_end_l = [q_st_end.to('cpu').detach().numpy().copy()]
                q_ae_start_l = [q_ae_start.to('cpu').detach().numpy().copy()]
                q_ae_end_l = [q_ae_end.to('cpu').detach().numpy().copy()]
                teacher_mean_l = [teacher_mean.to('cpu').detach().numpy().copy()]
                teacher_std_l = [teacher_std.to('cpu').detach().numpy().copy()]

                para_json = {
                    'q_st_start':q_st_start_l, 'q_st_end':q_st_end_l, 'q_ae_start':q_ae_start_l, 'q_ae_end':q_ae_end_l,
                    'teacher_mean':teacher_mean_l, 'teacher_std':teacher_std_l,
                    'image_size_height': int(image_size_height),
                    'image_size_width': int(image_size_width),
                    'edge_mask_w': edge_mask_w,
                            }

                with open(os.path.join(train_output_dir, 'para.json'), 'w', encoding='utf-8') as para_file:
                    json.dump(para_json, para_file, indent=4, default=numpy_encoder, ensure_ascii=False)

            else:
                val_patience_counter += 1
                if val_patience_counter >= cfg.early_stop_patience:
                    print(f"Early stopping triggered (val_loss stagnated for {cfg.early_stop_patience} intervals, min_delta={min_delta}).")
                    if mgr is not None:
                        mgr.log_metrics({'early_stop_step': iteration}, step=iteration)
                    break

            # teacher frozen
            teacher.eval()
            student.train()
            autoencoder.train()

            # --- メモリ解放 ---
            del image_st, image_ae, image_penalty
            del teacher_output_ae, student_output_ae, ae_output
            del distance_ae, distance_stae, loss_ae, loss_stae, loss_total
            torch.cuda.empty_cache()

    teacher.eval()
    student.eval()
    autoencoder.eval()

    # bestモデルのパラメータ読み込み
    teacher.load_state_dict(torch.load(os.path.join(train_output_dir, 'teacher_state_best.pth'), weights_only=True))
    student.load_state_dict(torch.load(os.path.join(train_output_dir, 'student_state_best.pth'), weights_only=True))
    autoencoder.load_state_dict(torch.load(os.path.join(train_output_dir, 'autoencoder_state_best.pth'), weights_only=True))

    # チャネル重み計算
    channel_weights_tensor = None
    channel_weights_info = {}
    cw_cfg = cfg.get('channel_weights', None)
    if cw_cfg is not None and cw_cfg.get('enabled', False):
        train_path = os.path.join(dataset_path, 'train')
        weights_np, cw_method, ch_aucs, w_sup = compute_channel_weights(
            teacher, student, teacher_mean, teacher_std,
            train_path, device,
            supervised_power=cw_cfg.get('supervised_power', 5),
            unsupervised_power=cw_cfg.get('unsupervised_power', 3),
            blend_n_mid=cw_cfg.get('blend_n_mid', 30),
            blend_scale=cw_cfg.get('blend_scale', 10.0),
            max_fpr=cw_cfg.get('max_fpr', 0.05))
        channel_weights_tensor = torch.from_numpy(weights_np).float().to(device)
        channel_weights_tensor = channel_weights_tensor[None, :, None, None]  # [1, 384, 1, 1]
        channel_weights_info['channel_weights'] = weights_np.tolist()
        channel_weights_info['channel_weights_method'] = cw_method
        channel_weights_info['blend_w_sup'] = float(w_sup)
        if ch_aucs is not None:
            channel_weights_info['channel_aucs'] = ch_aucs.tolist()
        print(f'チャネル重み計算完了 (方式: {cw_method}, w_sup={w_sup:.4f})')

    q_st_start, q_st_end, q_ae_start, q_ae_end = map_normalization(
        validation_loader=validation_loader, teacher=teacher, student=student,
        autoencoder=autoencoder, teacher_mean=teacher_mean, st_para=cfg.map_st, ae_para=cfg.map_ae,
        teacher_std=teacher_std, desc='Final map normalization',
        channel_weights=channel_weights_tensor,
        edge_mask_w=edge_mask_w)

    q_st_start_l = [q_st_start.to('cpu').detach().numpy().copy()]
    q_st_end_l = [q_st_end.to('cpu').detach().numpy().copy()]
    q_ae_start_l = [q_ae_start.to('cpu').detach().numpy().copy()]
    q_ae_end_l = [q_ae_end.to('cpu').detach().numpy().copy()]
    teacher_mean_l = [teacher_mean.to('cpu').detach().numpy().copy()]
    teacher_std_l = [teacher_std.to('cpu').detach().numpy().copy()]

    # AE 無効 (map_ae=0) で運用しているため map 重みは config の値をそのまま使う
    best_st, best_ae = cfg.map_st, cfg.map_ae

    # teacher_mean/std を4次元で保存（ロード時の reshape 不要にする）
    teacher_mean_4d = teacher_mean.squeeze().cpu().detach().numpy()  # [384]
    teacher_std_4d = teacher_std.squeeze().cpu().detach().numpy()    # [384]

    para_json = {
        'q_st_start':q_st_start_l, 'q_st_end':q_st_end_l, 'q_ae_start':q_ae_start_l, 'q_ae_end':q_ae_end_l,
        'teacher_mean':teacher_mean_l, 'teacher_std':teacher_std_l,
        'teacher_mean_1d': teacher_mean_4d.tolist(),
        'teacher_std_1d': teacher_std_4d.tolist(),
        'edge_mask_w': edge_mask_w,
        'st_para': best_st, 'ae_para': best_ae,
        'image_size_height': int(image_size_height),
        'image_size_width': int(image_size_width),
                }
    para_json.update(channel_weights_info)

    # F1最大化閾値の計算（validation setから）
    print('閾値計算中...')
    scores_val = []
    for image, _ in tqdm(validation_loader, desc='Computing threshold scores'):
        if on_gpu:
            image = image.to(device)
        teacher_output = teacher(image)
        teacher_output = (teacher_output - teacher_mean) / teacher_std
        student_output = student(image)
        diff_st = (teacher_output - student_output[:, :out_channels])**2
        if channel_weights_tensor is not None:
            map_st = torch.sum(diff_st * channel_weights_tensor, dim=1, keepdim=True)
        else:
            map_st = torch.mean(diff_st, dim=1, keepdim=True)
        if q_st_start is not None:
            map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
        scored_map = best_st * map_st
        scored_map = slice_edge_excluded(scored_map, edge_mask_w)
        score = scored_map.max().item()
        scores_val.append(score)

    # 正常画像のスコア分布から閾値設定（99.5パーセンタイル）
    scores_np = np.array(scores_val)
    threshold_val = float(np.quantile(scores_np, 0.995))
    para_json['threshold'] = threshold_val
    print(f'閾値: {threshold_val:.6f} (validation 99.5パーセンタイル)')

    with open(os.path.join(train_output_dir, 'para.json'), 'w', encoding='utf-8') as para_file:
        json.dump(para_json, para_file, indent=4, default=numpy_encoder, ensure_ascii=False)

@torch.no_grad()
def evaluate_validation_loss(validation_loader, teacher, student, autoencoder, teacher_mean, teacher_std, device, cfg):
    teacher.eval()
    student.eval()
    autoencoder.eval()

    total_loss = 0
    count = 0
    for image, _ in validation_loader:
        image = image.to(device)
        teacher_output = teacher(image)
        teacher_output = (teacher_output - teacher_mean) / teacher_std
        student_output = student(image)
        ae_output = autoencoder(image)

        loss_st = torch.mean((teacher_output - student_output[:, :384]) ** 2)
        loss_ae = torch.mean((teacher_output - ae_output) ** 2)
        loss_stae = torch.mean((ae_output - student_output[:, 384:]) ** 2)

        loss_total = cfg.loss_st * loss_st + cfg.loss_ae * loss_ae + cfg.loss_stae * loss_stae
        total_loss += loss_total.item()
        count += 1

    student.train()
    autoencoder.train()
    return total_loss / count


@torch.no_grad()
def predict(image, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para,
            q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None,
            channel_weights=None):
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :out_channels])**2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean((autoencoder_output -
                        student_output[:, out_channels:])**2,
                        dim=1, keepdim=True)
    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)
    map_combined = st_para * map_st + ae_para * map_ae

    return map_combined, map_st, map_ae

@torch.no_grad()
def map_normalization(validation_loader, teacher, student, autoencoder,
                    teacher_mean, teacher_std, st_para, ae_para, desc='Map normalization',
                    channel_weights=None, edge_mask_w=0):
    maps_st = []
    maps_ae = []
    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device
    # ignore augmented ae image
    for image, _ in tqdm(validation_loader, desc=desc):
        if on_gpu:
            image = image.to(device)
        map_combined, map_st, map_ae = predict(
            image=image, teacher=teacher, student=student,
            autoencoder=autoencoder, teacher_mean=teacher_mean,
            teacher_std=teacher_std, st_para=st_para, ae_para=ae_para,
            channel_weights=channel_weights)
        maps_st.append(slice_edge_excluded(map_st, edge_mask_w))
        maps_ae.append(slice_edge_excluded(map_ae, edge_mask_w))
    maps_st = torch.cat(maps_st).cpu().numpy().flatten()
    maps_ae = torch.cat(maps_ae).cpu().numpy().flatten()
    q_st_start = torch.tensor(np.quantile(maps_st, 0.9))
    q_st_end = torch.tensor(np.quantile(maps_st, 0.995))
    q_ae_start = torch.tensor(np.quantile(maps_ae, 0.9))
    q_ae_end = torch.tensor(np.quantile(maps_ae, 0.995))

    return q_st_start, q_st_end, q_ae_start, q_ae_end

@torch.no_grad()
def teacher_normalization(teacher, train_loader):

    mean_outputs = []

    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device

    for train_image, _ in tqdm(train_loader, desc='Computing mean of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        mean_output = torch.mean(teacher_output, dim=[0, 2, 3])
        mean_outputs.append(mean_output)
    channel_mean = torch.mean(torch.stack(mean_outputs), dim=0)
    channel_mean = channel_mean[None, :, None, None]

    mean_distances = []
    for train_image, _ in tqdm(train_loader, desc='Computing std of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        distance = (teacher_output - channel_mean) ** 2
        mean_distance = torch.mean(distance, dim=[0, 2, 3])
        mean_distances.append(mean_distance)
    channel_var = torch.mean(torch.stack(mean_distances), dim=0)
    channel_var = channel_var[None, :, None, None]
    channel_std = torch.sqrt(channel_var)

    return channel_mean, channel_std

if __name__ == '__main__':
    import sys
    from omegaconf import OmegaConf
    cfg = OmegaConf.load("./conf/config.yaml")
    # CLI引数のオーバーライド（key=value形式）をマージ
    cli_overrides = [arg for arg in sys.argv[1:] if '=' in arg]
    if cli_overrides:
        cli_cfg = OmegaConf.from_dotlist(cli_overrides)
        cfg = OmegaConf.merge(cfg, cli_cfg)
    train_color(cfg)
