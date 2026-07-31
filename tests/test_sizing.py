"""Tester för conviction-sizing (paper trading)."""
from __future__ import annotations

import pytest

from insider_tracker.config import load_config
from insider_tracker.paper.sizing import conviction_multiplier, intended_position

CFG = load_config()


def test_conviction_scales_with_score():
    lo = conviction_multiplier(CFG, score=0.10, is_cluster=False, score_lo=0.10, score_hi=0.50)
    hi = conviction_multiplier(CFG, score=0.50, is_cluster=False, score_lo=0.10, score_hi=0.50)
    mid = conviction_multiplier(CFG, score=0.30, is_cluster=False, score_lo=0.10, score_hi=0.50)
    assert lo == pytest.approx(CFG["sizing"]["min_conviction_mult"])
    assert hi == pytest.approx(CFG["sizing"]["max_conviction_mult"])
    assert lo < mid < hi


def test_cluster_uses_cluster_mult():
    m = conviction_multiplier(CFG, score=None, is_cluster=True, score_lo=0.1, score_hi=0.5)
    assert m == pytest.approx(CFG["sizing"]["cluster_mult"])


def test_score_below_range_clamped_to_min():
    m = conviction_multiplier(CFG, score=0.05, is_cluster=False, score_lo=0.10, score_hi=0.50)
    assert m == pytest.approx(CFG["sizing"]["min_conviction_mult"])


def test_intended_position_pct_and_sek():
    # hög score, riklig likviditet -> position = base*max_mult av portföljen
    pos = intended_position(CFG, score=0.50, is_cluster=False, turnover=1e9,
                            score_lo=0.10, score_hi=0.50)
    exp_pct = min(CFG["sizing"]["base_position_pct"] * CFG["sizing"]["max_conviction_mult"],
                  CFG["sizing"]["max_position_pct"])
    assert pos.pct == pytest.approx(exp_pct)
    assert pos.sek == pytest.approx(CFG["sizing"]["portfolio_sek"] * exp_pct)


def test_liquidity_cap_binds_in_illiquid_name():
    # låg omsättning -> positionen kapas till max_pct_of_adv * turnover
    turnover = 20000.0
    pos = intended_position(CFG, score=0.50, is_cluster=False, turnover=turnover,
                            score_lo=0.10, score_hi=0.50)
    assert pos.sek == pytest.approx(CFG["sizing"]["max_pct_of_adv"] * turnover)
    assert pos.sek < CFG["sizing"]["portfolio_sek"] * CFG["sizing"]["base_position_pct"]
