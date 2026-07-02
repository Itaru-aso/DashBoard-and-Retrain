"""共有メトリクス `src.services.metrics`（A-R5）の unit テスト。

- 率: throughput=monochro, ng_rate=ng/monochro, false_alarm_rate=fp/monochro,
  miss_rate=miss/monochro。
- annotated_count==0 のとき虚報率・見逃し率は NULL(None)。
- monochro_count==0 の集計単位は除外（None を返す）。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_compute_rates_basic() -> None:
    """件数から各率を算出する。"""
    from src.services.metrics import MetricCounts, compute_rates

    rates = compute_rates(
        MetricCounts(monochro_count=10, ng_count=2, fp_num=1, miss_num=1, annotated_count=5)
    )
    assert rates is not None
    assert rates.throughput == 10
    assert rates.ng_rate == pytest.approx(0.2)
    assert rates.false_alarm_rate == pytest.approx(0.1)
    assert rates.miss_rate == pytest.approx(0.1)


@pytest.mark.unit
def test_rates_null_when_no_annotations() -> None:
    """annotated_count==0 なら虚報率・見逃し率は None（ng_rate/throughput は算出）。"""
    from src.services.metrics import MetricCounts, compute_rates

    rates = compute_rates(
        MetricCounts(monochro_count=8, ng_count=2, fp_num=0, miss_num=0, annotated_count=0)
    )
    assert rates is not None
    assert rates.throughput == 8
    assert rates.ng_rate == pytest.approx(0.25)
    assert rates.false_alarm_rate is None
    assert rates.miss_rate is None


@pytest.mark.unit
def test_excluded_when_monochro_zero() -> None:
    """monochro_count==0 の集計単位は除外（None）。"""
    from src.services.metrics import MetricCounts, compute_rates

    rates = compute_rates(
        MetricCounts(monochro_count=0, ng_count=0, fp_num=0, miss_num=0, annotated_count=0)
    )
    assert rates is None
