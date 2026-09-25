"""Isolated pydantic contract probe; no application imports."""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError


@pytest.mark.probe("pydantic")
def test_P_PYD_001_strict_extra_errors_and_frozen_assignment() -> None:
    class StrictValue(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

        count: int

    for payload in ({"count": 1, "extra": 2}, {"count": "1"}):
        with pytest.raises(ValidationError) as caught:
            StrictValue.model_validate(payload)
        errors = caught.value.errors(include_input=False)
        assert errors
        assert all("loc" in entry and "input" not in entry for entry in errors)
        assert errors[0]["loc"] == (("extra",) if "extra" in payload else ("count",))

    value = StrictValue(count=1)
    with pytest.raises(ValidationError):
        value.count = 2
    assert value.count == 1
