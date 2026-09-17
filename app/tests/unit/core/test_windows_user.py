"""
app/tests/unit/test_windows_user.py
Unit tests for backend/user/windows_user.py (Host OS context extraction).
"""
import os
import pytest
from backend.user.windows_user import (
    get_user_display_name,
    get_system_language,
    get_system_timezone,
    is_system_dark_mode,
    get_desktop_path,
    get_downloads_path,
    get_documents_path,
    get_pictures_path,
)


class TestWindowsUserContext:
    def test_get_user_display_name_returns_non_empty_string(self):
        name = get_user_display_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_get_system_language_returns_valid_locale_string(self):
        lang = get_system_language()
        assert isinstance(lang, str)
        assert len(lang) >= 2

    def test_get_system_timezone_returns_non_empty_string(self):
        tz = get_system_timezone()
        assert isinstance(tz, str)
        assert len(tz) > 0

    def test_is_system_dark_mode_returns_boolean(self):
        is_dark = is_system_dark_mode()
        assert isinstance(is_dark, bool)

    def test_desktop_path_exists_or_is_string(self):
        path = get_desktop_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_downloads_path_exists_or_is_string(self):
        path = get_downloads_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_documents_path_exists_or_is_string(self):
        path = get_documents_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_pictures_path_exists_or_is_string(self):
        path = get_pictures_path()
        assert isinstance(path, str)
        assert len(path) > 0
