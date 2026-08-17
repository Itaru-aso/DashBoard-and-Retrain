# 実測スニペット（輝度・シャープネス・ONNXスコア）

Step 1-2（統計比較→実測）で使う最小構成の例。学習データ・実機画像のフォルダを渡し、輝度統計・シャープネス・ONNXスコアをまとめて出す。

```python
import glob
import cv2
import numpy as np
import onnxruntime as ort

def image_stats(path: str) -> dict:
    """輝度(mean/p1/p99)とシャープネス(Laplacian分散)を計算する。"""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
    return {
        "mean": float(img.mean()),
        "p1": float(np.percentile(img, 1)),
        "p99": float(np.percentile(img, 99)),
        "sharpness": float(laplacian_var),
    }

def onnx_score(session: ort.InferenceSession, path: str, input_name: str) -> float:
    """学習済みONNXモデルへ通した異常スコアを返す(前処理はmodel.py/推論コードと同一にすること)。"""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
    x = img[np.newaxis, np.newaxis, :, :]  # (1, 1, H, W) — モデルの入力形状に合わせる
    (score,) = session.run(None, {input_name: x})
    return float(score)

def compare_domains(train_glob: str, field_glob: str, onnx_path: str) -> None:
    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name

    for label, pattern in [("train", train_glob), ("field", field_glob)]:
        stats = [image_stats(p) for p in glob.glob(pattern)]
        scores = [onnx_score(session, p, input_name) for p in glob.glob(pattern)]
        print(label, {
            "mean_brightness": np.mean([s["mean"] for s in stats]),
            "mean_sharpness": np.mean([s["sharpness"] for s in stats]),
            "mean_score": np.mean(scores),
            "max_score": np.max(scores),  # 外れ値(撮像失敗)の当たりをつける
        })
```

## 使い方の要点

- `onnx_score`の前処理（正規化・リサイズ・crop）は、実際の学習・推論コード（`training/model.py` や配信先のC#推論プログラム）と**完全に一致させる**こと。ズレると測定自体が無効になる（567番の実例: `export_root`の画像が既にcrop済みだったのに気づかず二重cropして誤ったベースラインを出した）。
- `max_score`が他サンプルより極端に高い場合、まずその画像を目視確認する（白飛び等の撮像失敗の可能性）。
- 統計（`mean_brightness`/`mean_sharpness`）が近くても`mean_score`/NG率が悪化するケースがあるので、**最終判断は`mean_score`/NG率側**を使う。
