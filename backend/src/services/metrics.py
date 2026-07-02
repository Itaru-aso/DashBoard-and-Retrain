"""共有メトリクス算出（A-R5）。

件数（monochro/ng/fp/miss/annotated）から率を算出する。ダッシュボード・保守タスク
（逸脱判定）・色ライフサイクル（昇格）で共有する。

- throughput = monochro_count
- ng_rate = ng_count / monochro_count
- false_alarm_rate = annotated_count==0 ? None : fp_num / monochro_count
- miss_rate = annotated_count==0 ? None : miss_num / monochro_count
- monochro_count==0 の集計単位は除外（None を返す。呼び出し側で単位ごとに適用）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricCounts:
    """集計単位（JST日×フルタプル×号機、または号機合算）の件数。"""

    monochro_count: int
    ng_count: int
    fp_num: int
    miss_num: int
    annotated_count: int


@dataclass(frozen=True)
class MetricRates:
    """件数から算出した率（分母は monochro_count）。"""

    throughput: int
    ng_rate: float
    false_alarm_rate: float | None
    miss_rate: float | None


def compute_rates(counts: MetricCounts) -> MetricRates | None:
    """件数から率を算出する。

    Args:
        counts: 集計単位の件数。

    Returns:
        算出した率。`monochro_count==0` の単位は除外対象として None を返す。
        `annotated_count==0` のときは虚報率・見逃し率を None（NULL）とする。
    """
    monochro = counts.monochro_count
    if monochro == 0:
        return None

    ng_rate = counts.ng_count / monochro
    if counts.annotated_count == 0:
        false_alarm_rate: float | None = None
        miss_rate: float | None = None
    else:
        false_alarm_rate = counts.fp_num / monochro
        miss_rate = counts.miss_num / monochro

    return MetricRates(
        throughput=monochro,
        ng_rate=ng_rate,
        false_alarm_rate=false_alarm_rate,
        miss_rate=miss_rate,
    )
