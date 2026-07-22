"""trainステージの公開API。

trainパッケージ外からは `train.train_color` / `train.train_monochro`
のみを使用すること。`train.common` / `train.color` / `train.monochro`
内の関数を外部から直接importしてはならない
（境界はtests/ci_gates/test_training_boundary.pyで検証）。
"""
