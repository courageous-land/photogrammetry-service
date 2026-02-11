"""
Unit tests for storage.py — sanitize_filename.

Pure function, no GCP dependencies.
"""

from services.storage import sanitize_filename


class TestSanitizeFilename:
    def test_normal_filename(self):
        assert sanitize_filename("image.jpg") == "image.jpg"

    def test_strips_path_traversal(self):
        assert ".." not in sanitize_filename("../../etc/passwd")

    def test_strips_absolute_path(self):
        result = sanitize_filename("/etc/passwd")
        assert result == "passwd"

    def test_strips_windows_path(self):
        result = sanitize_filename("C:\\Users\\hack\\evil.exe")
        assert result == "evil.exe"

    def test_removes_null_bytes(self):
        result = sanitize_filename("image\x00.jpg")
        assert "\x00" not in result

    def test_replaces_special_chars(self):
        result = sanitize_filename("file<>|name.jpg")
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_limits_length(self):
        long_name = "a" * 300 + ".tif"
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_empty_becomes_unnamed(self):
        assert sanitize_filename("") == "unnamed_file"

    def test_only_dots(self):
        assert sanitize_filename("...") == "unnamed_file"

    def test_spaces_preserved(self):
        result = sanitize_filename("my photo.jpg")
        assert result == "my photo.jpg"

    def test_unicode_replaced(self):
        result = sanitize_filename("café☕.png")
        # Non-word chars replaced with _
        assert "☕" not in result
