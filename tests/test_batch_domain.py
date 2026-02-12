"""
Unit tests for batch.py domain logic and environment parsers.

These tests cover pure functions — no GCP SDK calls.
"""

import json

import pytest

from services.batch import (
    calculate_disk_size,
    parse_allowed_zones,
    parse_float_env,
    parse_int_env,
    parse_machine_tiers,
    require_env,
    select_machine_tier,
)

# ---------------------------------------------------------------------------
# require_env
# ---------------------------------------------------------------------------


class TestRequireEnv:
    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert require_env("TEST_VAR") == "hello"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "  hello  ")
        assert require_env("TEST_VAR") == "hello"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ValueError, match="MISSING_VAR"):
            require_env("MISSING_VAR")

    def test_raises_when_empty(self, monkeypatch):
        monkeypatch.setenv("EMPTY_VAR", "   ")
        with pytest.raises(ValueError, match="EMPTY_VAR"):
            require_env("EMPTY_VAR")


# ---------------------------------------------------------------------------
# parse_int_env / parse_float_env
# ---------------------------------------------------------------------------


class TestParseIntEnv:
    def test_valid(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "42")
        assert parse_int_env("MY_INT") == 42

    def test_zero(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "0")
        assert parse_int_env("MY_INT") == 0

    def test_rejects_negative(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "-1")
        with pytest.raises(ValueError, match="must be >= 0"):
            parse_int_env("MY_INT")

    def test_rejects_non_numeric(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "abc")
        with pytest.raises(ValueError, match="must be an integer"):
            parse_int_env("MY_INT")


class TestParseFloatEnv:
    def test_valid(self, monkeypatch):
        monkeypatch.setenv("MY_FLOAT", "1.15")
        assert parse_float_env("MY_FLOAT") == pytest.approx(1.15)

    def test_rejects_non_numeric(self, monkeypatch):
        monkeypatch.setenv("MY_FLOAT", "abc")
        with pytest.raises(ValueError, match="must be a number"):
            parse_float_env("MY_FLOAT")


# ---------------------------------------------------------------------------
# parse_allowed_zones
# ---------------------------------------------------------------------------


class TestParseAllowedZones:
    def test_simple_zones(self):
        result = parse_allowed_zones("us-central1-a,us-central1-b")
        assert result == ["zones/us-central1-a", "zones/us-central1-b"]

    def test_already_prefixed(self):
        result = parse_allowed_zones("zones/us-central1-a")
        assert result == ["zones/us-central1-a"]

    def test_strips_whitespace(self):
        result = parse_allowed_zones("  us-east1-a , us-east1-b  ")
        assert result == ["zones/us-east1-a", "zones/us-east1-b"]

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="at least one zone"):
            parse_allowed_zones("")


# ---------------------------------------------------------------------------
# parse_machine_tiers
# ---------------------------------------------------------------------------


VALID_TIERS_JSON = json.dumps(
    [
        {"maxImages": 500, "machineType": "n2-standard-8", "cpuMilli": 8000, "memoryMib": 32768},
        {"maxImages": 200, "machineType": "n2-standard-4", "cpuMilli": 4000, "memoryMib": 16384},
    ]
)


class TestParseMachineTiers:
    def test_parses_and_sorts(self):
        tiers = parse_machine_tiers(VALID_TIERS_JSON)
        assert len(tiers) == 2
        # Should be sorted ascending by maxImages
        assert tiers[0]["maxImages"] == 200
        assert tiers[1]["maxImages"] == 500

    def test_rejects_invalid_json(self):
        with pytest.raises(ValueError, match="valid JSON"):
            parse_machine_tiers("not json")

    def test_rejects_empty_array(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_machine_tiers("[]")

    def test_rejects_missing_key(self):
        bad = json.dumps([{"maxImages": 100}])  # missing machineType, cpuMilli, memoryMib
        with pytest.raises(ValueError, match="missing required key"):
            parse_machine_tiers(bad)


# ---------------------------------------------------------------------------
# select_machine_tier
# ---------------------------------------------------------------------------


TIERS = [
    {"maxImages": 200, "machineType": "n2-standard-4", "cpuMilli": 4000, "memoryMib": 16384},
    {"maxImages": 500, "machineType": "n2-standard-8", "cpuMilli": 8000, "memoryMib": 32768},
    {"maxImages": 1000, "machineType": "n2-highmem-8", "cpuMilli": 8000, "memoryMib": 65536},
]


class TestSelectMachineTier:
    def test_small_count(self):
        machine, cpu, mem = select_machine_tier(50, TIERS)
        assert machine == "n2-standard-4"
        assert cpu == 4000
        assert mem == 16384

    def test_exact_boundary(self):
        machine, cpu, mem = select_machine_tier(200, TIERS)
        assert machine == "n2-standard-4"

    def test_just_above_boundary(self):
        machine, cpu, mem = select_machine_tier(201, TIERS)
        assert machine == "n2-standard-8"

    def test_exceeds_all_tiers(self):
        machine, cpu, mem = select_machine_tier(99999, TIERS)
        assert machine == "n2-highmem-8"  # Largest available


# ---------------------------------------------------------------------------
# calculate_disk_size
# ---------------------------------------------------------------------------


class TestCalculateDiskSize:
    def test_minimum_floor(self):
        # 10 images * 9 MB * 6 * 1.15 = 621 MB — below 51200 minimum
        result = calculate_disk_size(
            file_count=10, avg_image_size_mb=9, safety_margin=1.15, min_boot_disk_mb=51200
        )
        assert result == 51200

    def test_large_count_exceeds_minimum(self):
        # 2000 images * 9 MB * 6 * 1.15 ≈ 124200 MB (float precision may vary)
        result = calculate_disk_size(
            file_count=2000, avg_image_size_mb=9, safety_margin=1.15, min_boot_disk_mb=51200
        )
        assert 124199 <= result <= 124200
        assert result > 51200

    def test_formula_correctness(self):
        result = calculate_disk_size(
            file_count=100, avg_image_size_mb=10, safety_margin=1.0, min_boot_disk_mb=0
        )
        # 100 * 10 * 6 * 1.0 = 6000
        assert result == 6000
