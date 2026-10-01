"""
Unit tests for the closure-gap vector.
"""

import pytest
import numpy as np
from src.compiler.gap_vector import ClosureGapVector, ClosureStatus


def test_default_vector_is_fully_open():
    cv = ClosureGapVector()
    assert cv.c_sem == 1.0
    assert cv.c_evid == 1.0
    assert cv.c_proc == 1.0
    assert cv.c_inst == 1.0


def test_l2_norm_fully_open():
    cv = ClosureGapVector()
    assert abs(cv.l2_norm() - 2.0) < 1e-6  # sqrt(4) = 2.0


def test_l2_norm_partially_closed():
    cv = ClosureGapVector(c_sem=0.0, c_evid=0.0, c_proc=0.0, c_inst=0.5)
    assert abs(cv.l2_norm() - 0.5) < 1e-6


def test_is_closed_true_when_all_below_threshold():
    cv = ClosureGapVector(c_sem=0.05, c_evid=0.08, c_proc=0.09, c_inst=0.01)
    assert cv.is_closed(threshold=0.1) is True


def test_is_closed_false_when_any_above_threshold():
    cv = ClosureGapVector(c_sem=0.05, c_evid=0.8, c_proc=0.09, c_inst=0.01)
    assert cv.is_closed(threshold=0.1) is False


def test_dominant_gap_returns_largest_component():
    cv = ClosureGapVector(c_sem=0.1, c_evid=0.9, c_proc=0.3, c_inst=0.2)
    assert cv.dominant_gap() == "evidentiary"


def test_closure_status_all_closed():
    cv = ClosureGapVector(c_sem=0.05, c_evid=0.05, c_proc=0.05, c_inst=0.05)
    statuses = cv.closure_statuses(threshold=0.1)
    assert all(v == ClosureStatus.CLOSED for v in statuses.values())


def test_closure_status_mixed():
    cv = ClosureGapVector(c_sem=0.05, c_evid=0.5, c_proc=0.3, c_inst=0.95)
    statuses = cv.closure_statuses(threshold=0.1)
    assert statuses["semantic"] == ClosureStatus.CLOSED
    assert statuses["institutional"] == ClosureStatus.OPEN


def test_invalid_gap_value_raises():
    with pytest.raises(ValueError, match="c_sem"):
        ClosureGapVector(c_sem=1.5)


def test_weighted_norm():
    cv = ClosureGapVector(c_sem=1.0, c_evid=0.0, c_proc=0.0, c_inst=0.0)
    # With weight [2,1,1,1]: sqrt(2^2 * 1.0^2) = 2.0
    assert abs(cv.weighted_norm(weights=(2.0, 1.0, 1.0, 1.0)) - 2.0) < 1e-6


def test_to_dict_includes_all_fields():
    cv = ClosureGapVector(c_sem=0.5, c_evid=0.3, c_proc=0.2, c_inst=0.1)
    d = cv.to_dict()
    assert "c_sem" in d and "c_evid" in d and "c_proc" in d and "c_inst" in d
    assert "l2_norm" in d
    assert "dominant_gap" in d
    assert "statuses" in d
