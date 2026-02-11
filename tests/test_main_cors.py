"""
Unit tests for main.py — CORS origin loading and validation.

Pure function, no GCP dependencies.
"""
import pytest

from main import load_allowed_origins


class TestLoadAllowedOrigins:
    def test_wildcard(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "*")
        assert load_allowed_origins() == ["*"]

    def test_single_origin(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com")
        assert load_allowed_origins() == ["https://example.com"]

    def test_multiple_origins(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com, https://b.com")
        result = load_allowed_origins()
        assert result == ["https://a.com", "https://b.com"]

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "  https://a.com  ,  https://b.com  ")
        result = load_allowed_origins()
        assert result == ["https://a.com", "https://b.com"]

    def test_rejects_missing(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        with pytest.raises(ValueError, match="required"):
            load_allowed_origins()

    def test_rejects_empty_string(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "")
        with pytest.raises(ValueError, match="required"):
            load_allowed_origins()

    def test_rejects_only_commas(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", " , , ")
        with pytest.raises(ValueError, match="at least one origin"):
            load_allowed_origins()

    def test_rejects_wildcard_with_specific(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "*, https://a.com")
        with pytest.raises(ValueError, match="cannot mix"):
            load_allowed_origins()
