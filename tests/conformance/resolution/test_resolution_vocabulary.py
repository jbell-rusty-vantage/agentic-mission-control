"""The frozen resolution vocabulary (R0): closed refusal codes, valid fixtures, vendor coverage.

R1 adds the resolver conformance proper (every code reachable and pointed, pairing, digest
stability across registration order) against these fixtures.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from mission_control.domain.resolution.configuration import VENDORS, Vendor
from mission_control.domain.resolution.resolved import (
    REFUSAL_CODES,
    RefusalCode,
    ResolutionRefused,
)
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS


def test_refusal_codes_are_one_closed_vocabulary() -> None:
    assert set(get_args(RefusalCode)) == set(REFUSAL_CODES)
    assert len(REFUSAL_CODES) == len(set(REFUSAL_CODES))


@pytest.mark.parametrize("code", REFUSAL_CODES)
def test_every_refusal_is_pointed_and_actionable(code: RefusalCode) -> None:
    refusal = ResolutionRefused(
        code=code, pointer="/stages/0/model/profile", reason="r", remedy="m", lane_profile=None
    )
    assert refusal.pointer.startswith("/")
    with pytest.raises(ValidationError):
        ResolutionRefused(code=code, pointer="stages/0", reason="r", remedy="m")
    with pytest.raises(ValidationError):
        ResolutionRefused(code=code, pointer="", reason="r", remedy="")


def test_vendor_literal_matches_the_tuple() -> None:
    assert set(get_args(Vendor)) == set(VENDORS)


def test_fixture_registrations_are_distinct_and_cover_both_vendors() -> None:
    assert len({app.application_id for app in APPLICATIONS}) == len(APPLICATIONS)
    assert len({model.profile for model in MODELS}) == len(MODELS)
    assert {model.vendor for model in MODELS} == set(VENDORS)


def test_judge_and_producer_differ_by_vendor() -> None:
    by_profile = {model.profile: model for model in MODELS}
    assert by_profile["judge.default"].vendor != by_profile["producer.default"].vendor
