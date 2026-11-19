import pytest


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    # Findings say "shuts down on" or "was shut down on" depending on today's
    # date. Pin it so the tests give the same result on any day.
    monkeypatch.setenv("LUNA_CHECK_TODAY", "2026-11-19")
