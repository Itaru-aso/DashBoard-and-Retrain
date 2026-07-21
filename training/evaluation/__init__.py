# training/evaluation/__init__.py
"""evaluationステージの公開API。

evaluationパッケージ外からは `evaluation.Evaluator` のみを使用すること。
`evaluation.scoring` / `evaluation.predict` 内の関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_evaluation_boundary.pyで検証）。
"""
from evaluation.evaluator import Evaluator

__all__ = ["Evaluator"]
