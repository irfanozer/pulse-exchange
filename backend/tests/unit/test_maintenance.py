from __future__ import annotations

import pytest

from pulseexchange import maintenance


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_reseed_enabled_accepts_true_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PULSEEXCHANGE_MAINTENANCE_RESEED", value)
    assert maintenance._reseed_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_reseed_enabled_accepts_false_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PULSEEXCHANGE_MAINTENANCE_RESEED", value)
    assert maintenance._reseed_enabled() is False


def test_reseed_enabled_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSEEXCHANGE_MAINTENANCE_RESEED", "sometimes")
    with pytest.raises(ValueError, match="must be true or false"):
        maintenance._reseed_enabled()
