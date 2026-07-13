#!/usr/bin/env python3
"""依存ゼロ（stdlib のみ）の branch coverage + mutation testing ランナー。

test-validation スキルの Step2（カバレッジ）と Step3（mutation testing）で使う同梱ツール。
外部ツール（mutmut/Stryker）を入れずに、DB 非依存の◎/✅層（純粋ロジック・Validator・utils）へ
その場で mutation を掛け、テストが「落とせるか（killed）／落とせないか（survived）」を機械判定する。

なぜ自作か:
  - mutmut 3.x は Windows で不安定・要インストール。coverage は導入済みなので、それを所有し
    最小限の AST 変異を自前で回す方が、この環境で確実に完走する（Docker も不要）。
  - survived mutant のリストがそのまま「回帰を検出できない空洞」の具体的証拠になる。

対象は「テストが速く・DB 非依存で回るもの」に絞ること（Service の DB 依存部は不向き）。

使い方:
    # branch coverage（term-missing）。Windows の .coverage ロックを避けて計測。
    python mutation_runner.py cov --module src.services.metrics \\
        --tests tests/unit/test_metrics.py --project-dir /path/to/backend

    # mutation testing。1 ソースファイルへ変異を掛け、survived を列挙。
    python mutation_runner.py mutate --source src/services/metrics.py \\
        --tests tests/unit/test_metrics.py --project-dir /path/to/backend

判定:
    テストが失敗（returncode != 0）→ その変異は killed（良い）。
    テストが成功（returncode == 0）→ survived（テストが検出できない＝空洞の証拠）。
    タイムアウト → killed 扱い（無限ループ化した変異とみなす）。
"""

from __future__ import annotations

import argparse
import ast
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


# ---- mutation 定義（1 候補ノード = 1 変異。walk 順で index が安定する） ----

# Compare 演算子の主変異（片側 1 対 1）。
_CMP_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}

# 二項演算子の主変異。
_BIN_SWAP: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.Mod: ast.Mult,
    ast.FloorDiv: ast.Mult,
}

# 論理演算子の主変異。
_BOOL_SWAP: dict[type[ast.boolop], type[ast.boolop]] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}


@dataclass
class Mutation:
    """1 つの変異の記述（レポート用）。"""

    index: int
    lineno: int
    kind: str
    detail: str


def _iter_candidates(tree: ast.AST):
    """変異候補を walk 順に列挙する（(node, kind, detail) を yield）。

    列挙と適用で同一の走査順を使うため、木は必ず同一ソースから再パースすること。

    キーワード引数の定数（例 `@dataclass(frozen=True)` の `frozen=True`、`ConfigDict(extra="ignore")`）は
    変異させても挙動が変わらない等価変異になりやすくノイズになるため除外する（logic 側の分岐・演算・
    しきい値定数の変異に集中する）。
    """
    kw_const_ids = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                t = type(op)
                if t in _CMP_SWAP:
                    yield node, "compare", f"{t.__name__}->{_CMP_SWAP[t].__name__}"
        elif isinstance(node, ast.BinOp):
            t = type(node.op)
            if t in _BIN_SWAP:
                yield node, "binop", f"{t.__name__}->{_BIN_SWAP[t].__name__}"
        elif isinstance(node, ast.BoolOp):
            t = type(node.op)
            if t in _BOOL_SWAP:
                yield node, "boolop", f"{t.__name__}->{_BOOL_SWAP[t].__name__}"
        elif isinstance(node, ast.Constant):
            if id(node) in kw_const_ids:
                continue  # キーワード引数の定数（等価変異になりやすい）は除外
            v = node.value
            if isinstance(v, bool):
                yield node, "const-bool", f"{v}->{not v}"
            elif isinstance(v, int):
                yield node, "const-int", f"{v}->{v + 1}"
            elif isinstance(v, float):
                yield node, "const-float", f"{v}->{v + 1.0}"
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                yield node, "return-none", "return <expr>->return None"


def _apply(node: ast.AST, kind: str) -> None:
    """候補ノードへ主変異を適用（in-place）。"""
    if kind == "compare":
        node.ops = [_CMP_SWAP.get(type(op), type(op))() for op in node.ops]  # type: ignore[attr-defined]
    elif kind == "binop":
        node.op = _BIN_SWAP[type(node.op)]()  # type: ignore[attr-defined]
    elif kind == "boolop":
        node.op = _BOOL_SWAP[type(node.op)]()  # type: ignore[attr-defined]
    elif kind == "const-bool":
        node.value = not node.value  # type: ignore[attr-defined]
    elif kind == "const-int":
        node.value = node.value + 1  # type: ignore[attr-defined]
    elif kind == "const-float":
        node.value = node.value + 1.0  # type: ignore[attr-defined]
    elif kind == "return-none":
        node.value = ast.Constant(value=None)  # type: ignore[attr-defined]


def _make_mutant(source: str, target: int) -> tuple[str, Mutation] | None:
    """target 番目の候補だけを変異させたソースを返す。"""
    tree = ast.parse(source)
    for i, (node, kind, detail) in enumerate(_iter_candidates(tree)):
        if i == target:
            _apply(node, kind)
            ast.fix_missing_locations(tree)
            mut = Mutation(index=i, lineno=getattr(node, "lineno", 0), kind=kind, detail=detail)
            return ast.unparse(tree), mut
    return None


def _count_candidates(source: str) -> int:
    return sum(1 for _ in _iter_candidates(ast.parse(source)))


def _run_pytest(tests: str, project_dir: Path, timeout: int) -> str:
    """テストを実行し 'pass' / 'fail' / 'timeout' を返す（cwd=project_dir）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            # `-o addopts=` で ini の addopts（--cov ... --cov-fail-under=80）を無効化する。
            # これをしないとカバレッジゲートで常に非0終了し、mutation の kill/survive 判定が壊れる。
            [sys.executable, "-m", "pytest", tests, "-q", "-o", "addopts=", "-p", "no:cacheprovider"],
            cwd=str(project_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    return "pass" if proc.returncode == 0 else "fail"


def cmd_mutate(args: argparse.Namespace) -> int:
    """mutation testing を実行し survived を列挙する。"""
    project_dir = Path(args.project_dir).resolve()
    source_path = (project_dir / args.source).resolve()
    if not source_path.is_file():
        print(f"エラー: ソースが見つかりません: {source_path}", file=sys.stderr)
        return 2

    original = source_path.read_text(encoding="utf-8")
    src_lines = original.splitlines()

    # 変異前にベースラインが緑であることを確認（赤ならテスト環境が壊れている）。
    baseline = _run_pytest(args.tests, project_dir, args.timeout)
    if baseline != "pass":
        print(f"エラー: ベースラインのテストが緑ではありません（{baseline}）。先に環境を直すこと。", file=sys.stderr)
        return 2

    total = _count_candidates(original)
    if total == 0:
        print("変異候補が 0 件（分岐・演算・定数を持たないファイル）。mutation 対象外。")
        return 0
    limit = min(total, args.max_mutants)

    killed = 0
    survived: list[Mutation] = []
    dropped = total - limit

    print(f"対象: {source_path.name} / テスト: {args.tests}")
    print(f"変異候補: {total} 件（実行 {limit} 件{'・' + str(dropped) + ' 件は上限で省略' if dropped else ''}）\n")

    # SIGTERM/SIGINT で kill されても必ず元へ戻す（finally は SIGTERM では走らないため）。
    def _restore_and_exit(signum: int, _frame: object) -> None:
        source_path.write_text(original, encoding="utf-8")
        print(f"\n[中断] シグナル {signum} を受信。ソースを復元して終了。", file=sys.stderr)
        raise SystemExit(130)

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _restore_and_exit)
        except (ValueError, OSError):
            pass  # 非メインスレッド等では設定できないが finally で担保

    try:
        for i in range(limit):
            made = _make_mutant(original, i)
            if made is None:
                continue
            mutant_src, mut = made
            source_path.write_text(mutant_src, encoding="utf-8")
            verdict = _run_pytest(args.tests, project_dir, args.timeout)
            if verdict == "pass":
                survived.append(mut)
                flag = "SURVIVED"
            else:
                killed += 1
                flag = "killed" if verdict == "fail" else "killed(timeout)"
            print(f"  [{i + 1}/{limit}] L{mut.lineno} {mut.kind} {mut.detail} … {flag}")
    finally:
        # どんな経路でも必ずソースを復元する（変異を残さない）。
        source_path.write_text(original, encoding="utf-8")

    score = killed / limit if limit else 0.0
    print("\n==== mutation score ====")
    print(f"  killed={killed} / survived={len(survived)} / 実行={limit}  score={score:.0%}")
    if survived:
        print("\n---- survived mutants（回帰を検出できない＝空洞の証拠） ----")
        for m in survived:
            code = src_lines[m.lineno - 1].strip() if 0 < m.lineno <= len(src_lines) else ""
            print(f"  L{m.lineno} [{m.kind}] {m.detail}\n      | {code}")
        print("\nこれらを潰すテストを追加すること（該当変異を検出できる境界/異常系）。")
    else:
        print("\nsurvived なし。この対象のテストは変異を全て検出できている。")
    return 0


def cmd_cov(args: argparse.Namespace) -> int:
    """branch coverage を term-missing で計測する（Windows の .coverage ロック回避）。"""
    project_dir = Path(args.project_dir).resolve()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # .coverage をスクラッチへ退避（Windows の WinError 5 ロックを避ける）。
    cov_file = Path(tempfile.gettempdir()) / f"tv_{os.getpid()}.coverage"
    env["COVERAGE_FILE"] = str(cov_file)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        args.tests,
        "-o",
        "addopts=",  # ini の addopts（--cov=src ... --cov-fail-under=80）を無効化し、自前の cov 設定だけ効かせる
        f"--cov={args.module}",
        "--cov-branch",
        "--cov-report=term-missing",
        "-p",
        "no:cacheprovider",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(project_dir), env=env)
    finally:
        if cov_file.exists():
            try:
                cov_file.unlink()
            except OSError:
                pass
    # pytest-cov の閾値ゲート等で非0でも、計測自体は出力済み。
    return proc.returncode


def main() -> int:
    # コンソールが cp932 等でも日本語出力を文字化けさせない。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="branch coverage + mutation testing ランナー（stdlib のみ）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cov = sub.add_parser("cov", help="branch coverage を term-missing で計測")
    p_cov.add_argument("--module", required=True, help="計測対象モジュール（例 src.services.metrics）")
    p_cov.add_argument("--tests", required=True, help="テストパス/式（例 tests/unit/test_metrics.py）")
    p_cov.add_argument("--project-dir", default=".", help="pytest を回す作業ディレクトリ（既定: カレント）")
    p_cov.set_defaults(func=cmd_cov)

    p_mut = sub.add_parser("mutate", help="1 ソースへ mutation testing")
    p_mut.add_argument("--source", required=True, help="変異対象ソース（project-dir 相対。例 src/services/metrics.py）")
    p_mut.add_argument("--tests", required=True, help="対象テスト（速く・DB 非依存で回るもの）")
    p_mut.add_argument("--project-dir", default=".", help="pytest を回す作業ディレクトリ（既定: カレント）")
    p_mut.add_argument("--max-mutants", type=int, default=200, help="実行する変異の上限（既定 200）")
    p_mut.add_argument("--timeout", type=int, default=60, help="変異 1 件あたりのテスト実行タイムアウト秒（既定 60）")
    p_mut.set_defaults(func=cmd_mutate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
