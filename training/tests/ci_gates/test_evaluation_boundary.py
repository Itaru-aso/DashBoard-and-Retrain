"""training/evaluationステージの境界を守るCI gate。

evaluation.scoring / evaluation.predict（評価ロジックの低レベルモジュール）を
直接importできるのは training/evaluation パッケージ内のみであることを保証する。
他のモジュールは evaluation.Evaluator の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "evaluation", "__pycache__"}
INTERNAL_MODULES = {"evaluation.scoring", "evaluation.predict"}


def _imported_module_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_pipline_does_not_import_evaluation_internals_directly():
    """pipline.py は evaluation.scoring / evaluation.predict を直接importしてはいけない。
    評価処理は evaluation.Evaluator の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_evaluation_module_imports_scoring_internals():
    """evaluation.scoring / evaluation.predict を直接importしているのは
    training/evaluation パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"evaluation外からのevaluation.scoring/predict直接importを検出: {offenders}"
