"""
Windows User Module - Handles Windows user interactions.

On Linux (ACA), Windows-only APIs are skipped with safe fallbacks so the HTTP
backend can boot without winreg / Win32 DLLs.
"""
import os
import sys
import ctypes
import locale
import subprocess
import glob
import datetime
import time

try:
    import winreg
except ImportError:
    winreg = None

# Constants for GetGeoInfo
GEO_ISO2 = 0x0004          # Country code in 2 letters (e.g., "PE")
GEOCLASS_NATION = 16       # Geolocalization constant
_IS_WINDOWS = sys.platform == "win32"


def get_user_display_name() -> str:
    """
    Retrieve the Windows user's full display name using ctypes.
    Falls back to environment variables or getlogin() on failure.
    """
    if _IS_WINDOWS:
        try:
            # EXTENDED_NAME_FORMAT enum: NameDisplay = 3
            GetUserNameEx = ctypes.windll.secur32.GetUserNameExW
            size = ctypes.pointer(ctypes.c_ulong(0))
            GetUserNameEx(3, None, size)

            # Prevent zero-length buffer segfault
            req_size = size.contents.value
            if req_size > 0:
                name_buffer = ctypes.create_unicode_buffer(req_size)
                if GetUserNameEx(3, name_buffer, size):
                    return name_buffer.value
            return os.getlogin()
        except Exception:
            try:
                return os.getlogin()
            except Exception:
                pass

    return os.getenv("USERNAME", os.getenv("USER", "User")).title().replace('.', ' ')


def get_special_folder(folder_name: str) -> str:
    """ Helper to get a Windows special folder from the registry. """
    if not _IS_WINDOWS or winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            path, _ = winreg.QueryValueEx(key, folder_name)
            return os.path.expandvars(path)
    except Exception:
        return ""


def get_desktop_path() -> str:
    """Helper to get the path to the user's desktop folder from the registry."""
    return get_special_folder("Desktop") or os.path.join(os.path.expanduser("~"), "Desktop")


def get_downloads_path() -> str:
    """Helper to get the path to the user's downloads folder from the registry."""
    return get_special_folder("{374DE290-123F-4565-9164-39C4925E467B}") or os.path.join(os.path.expanduser("~"), "Downloads")


def get_documents_path() -> str:
    """Helper to get the path to the user's documents folder from the registry."""
    return get_special_folder("Personal") or os.path.join(os.path.expanduser("~"), "Documents")


def get_pictures_path() -> str:
    """Helper to get the path to the user's pictures folder from the registry."""
    return get_special_folder("My Pictures") or os.path.join(os.path.expanduser("~"), "Pictures")


def is_system_dark_mode() -> bool:
    """Check if Windows is using Dark Mode."""
    if not _IS_WINDOWS or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except Exception:
        return False


def get_system_language() -> str:
    """Get the Windows default UI language (e.g., 'en-US')."""
    if _IS_WINDOWS:
        try:
            windll = ctypes.windll.kernel32
            windll.GetUserDefaultLocaleName.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
            windll.GetUserDefaultLocaleName.restype = ctypes.c_int

            buffer = ctypes.create_unicode_buffer(85)
            if windll.GetUserDefaultLocaleName(buffer, 85):
                return buffer.value
        except Exception:
            pass
    try:
        loc = locale.getdefaultlocale()[0]
        # Linux CI / containers often report bare "C" or "POSIX" — not a UI locale.
        if not loc or loc in {"C", "POSIX"} or len(loc) < 2:
            return "en-US"
        return loc
    except Exception:
        return "en-US"


def get_system_timezone() -> str:
    """Get the system timezone with numeric UTC offset."""
    try:
        now = datetime.datetime.now()
        local_tz = now.astimezone()
        tz_name = local_tz.tzname() or time.tzname[time.daylight]
        tz_offset = local_tz.strftime('%z')
        if tz_offset:
            return f"{tz_name} (UTC{tz_offset[:3]}:{tz_offset[3:]})"
        return f"{tz_name}"
    except Exception:
        try:
            return time.tzname[time.daylight]
        except Exception:
            return "UTC"


def get_user_profile_picture() -> str:
    """Get the path to the user's profile picture if it exists, with asset fallback."""
    if _IS_WINDOWS:
        try:
            # 1. Search Windows Public AccountPictures by SID
            kwargs = {}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            output = subprocess.check_output(['whoami', '/user'], **kwargs).decode('cp1252', errors='ignore')
            sid = output.strip().split()[-1]
            if sid.startswith('S-1-'):
                pic_dir = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "AccountPictures", sid)
                if os.path.exists(pic_dir):
                    images = glob.glob(os.path.join(pic_dir, "*.jpg")) + glob.glob(os.path.join(pic_dir, "*.png"))
                    if images:
                        images.sort(key=os.path.getsize, reverse=True)
                        return images[0]

            # 2. Search Windows Roaming AccountPictures
            appdata_pics = os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\AccountPictures")
            if os.path.exists(appdata_pics):
                images = glob.glob(os.path.join(appdata_pics, "*.jpg")) + glob.glob(os.path.join(appdata_pics, "*.png"))
                if images:
                    images.sort(key=os.path.getsize, reverse=True)
                    return images[0]
        except Exception:
            pass

    # 3. Fallback: Search application assets directory for user profile picture
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assets_dir = os.path.join(base_dir, "assets")
        for fname in ["user_profile.png", "user_profile.jpg", "user.png", "user.jpg", "profile.png", "profile.jpg"]:
            fpath = os.path.join(assets_dir, fname)
            if os.path.exists(fpath):
                return fpath
    except Exception:
        pass

    return ""


def get_user_country_code() -> str:
    """
    Gets the country/region configured in Windows (Settings > Time & Language > Region).
    Returns the 2-letter ISO 3166-1 code (e.g., 'PE', 'CO', 'US') or an empty string if it fails.
    Not affected by VPNs.
    """
    if not _IS_WINDOWS or winreg is None:
        return ""
    try:
        key_path = r"Control Panel\International"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            country_name, _ = winreg.QueryValueEx(key, "sCountry")
            return country_name.strip()
    except Exception:
        return ""


def get_clipboard_text() -> str:
    """Get current text from the Windows clipboard using ctypes safely."""
    if not _IS_WINDOWS:
        return ""
    try:
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(0):
            return ""

        text = ""
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            data = user32.GetClipboardData(CF_UNICODETEXT)
            if data:
                locked = kernel32.GlobalLock(data)
                if locked:
                    size = kernel32.GlobalSize(data)
                    if size > 0:
                        raw_bytes = ctypes.string_at(locked, size)
                        text = raw_bytes.decode('utf-16-le', errors='ignore').rstrip('\x00')
                    kernel32.GlobalUnlock(data)
        user32.CloseClipboard()
        return text
    except Exception:
        return ""
