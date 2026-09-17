import os
import sys
import time
import logging
import ctypes
import pathlib
import subprocess
import traceback
import shutil
import threading
import sysconfig

# Force UTF-8 stdout/stderr streams on Windows to prevent cp1252 charmap encoding crashes
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# NumPy 2.0+ compatibility shim for openpyxl / dependencies expecting NumPy 1.x types
try:
    import numpy as _np
    _type_mapping = {
        'short': getattr(_np, 'int16', int),
        'ushort': getattr(_np, 'uint16', int),
        'intc': getattr(_np, 'int32', int),
        'uintc': getattr(_np, 'uint32', int),
        'int_': getattr(_np, 'int64', int),
        'uint': getattr(_np, 'uint64', int),
        'longlong': getattr(_np, 'int64', int),
        'ulonglong': getattr(_np, 'uint64', int),
        'half': getattr(_np, 'float16', float),
        'single': getattr(_np, 'float32', float),
        'double': getattr(_np, 'float64', float),
        'longdouble': getattr(_np, 'longdouble', getattr(_np, 'float64', float)),
        'bool_': getattr(_np, 'bool_', bool),
    }
    for _name, _typ in _type_mapping.items():
        if not hasattr(_np, _name):
            setattr(_np, _name, _typ)
except ImportError:
    pass

# Native ARM64 Python only: pythonnet cannot load netfx (no arm64 ClrLoader). Use CoreCLR.
# Must be set before importing clr / pywebview winforms. Skip for x64 Python under emulation.
if sys.platform == 'win32' and 'arm64' in sysconfig.get_platform().lower():
    os.environ.setdefault('PYTHONNET_RUNTIME', 'coreclr')
    _launcher_root = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    _cfg_candidates = [
        os.path.join(_launcher_root, 'pythonnet.runtimeconfig.json'),
        os.path.join(_launcher_root, 'Ignite Chat.runtimeconfig.json'),
        os.path.join(_launcher_root, '_internal', 'pythonnet.runtimeconfig.json'),
    ]
    if hasattr(sys, '_MEIPASS'):
        _cfg_candidates.append(os.path.join(sys._MEIPASS, 'pythonnet.runtimeconfig.json'))
    for _c in _cfg_candidates:
        if os.path.isfile(_c):
            os.environ.setdefault('PYTHONNET_CORECLR_RUNTIME_CONFIG', _c)
            break

from main.libraries import (
    webview,
    clr,
    System,
    WindowInteropHelper,
)
from logging.handlers import RotatingFileHandler

# Add current directory to Python path to resolve imports correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Crash log must be user-writable (Program Files installs cannot write next to the exe).
try:
    from backend.core.runtime_paths import get_writable_data_dir

    _data_root = get_writable_data_dir(
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else current_dir
    )
    crash_log_dir = os.path.join(_data_root, "crash_log")
except Exception:
    _fallback = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    crash_log_dir = os.path.join(_fallback, "Ignite Chat", "crash_log")
os.makedirs(crash_log_dir, exist_ok=True)
crash_log_path = os.path.join(crash_log_dir, "crash_log.txt")

# Configure WebView2 cache folder in %LOCALAPPDATA% to prevent OneDrive sync file locks and hangs
local_appdata = os.environ.get("LOCALAPPDATA")
if not local_appdata:
    local_appdata = os.environ.get("TEMP", os.path.expanduser("~"))
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = os.path.join(local_appdata, "IgniteChatWebView2")
os.environ["PYWEBVIEW_USER_DATA_FOLDER"] = os.path.join(local_appdata, "IgniteChatWebView2")

# Force WebView2 to bypass autoplay user gesture requirements and silently grant mic permissions
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required "
    "--use-fake-ui-for-media-stream "
    "--enable-features=WebPermission "
    "--allow-file-access-from-files"
)
if sys.platform == 'win32':
    local_app_data = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
    webview_data_dir = os.path.join(local_app_data, "IgniteChat", "WebView2Data")
    os.makedirs(webview_data_dir, exist_ok=True)
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = webview_data_dir


# Enable robust error logging with rotation (max 10MB, max 3 backups)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler = RotatingFileHandler(crash_log_path, maxBytes=10*1024*1024, backupCount=3, encoding='utf-8')
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.DEBUG)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
if not root_logger.handlers:
    root_logger.addHandler(log_handler)

logger = logging.getLogger(__name__)

def kill_orphan_launcher_processes():
    """Kill any ghost/orphan launcher processes running in background on Windows."""
    if sys.platform != 'win32':
        return
    current_pid = os.getpid()
    try:
        # Terminate any python process executing launcher_webview.py other than current PID
        cmd = (
            f"powershell -NoProfile -NonInteractive -Command \""
            f"Get-CimInstance Win32_Process | Where-Object {{ ($_.ProcessId -ne {current_pid}) -and "
            f"($_.CommandLine -like '*launcher_webview.py*' -or $_.Name -like '*IgniteChat*') }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}\""
        )
        subprocess.run(cmd, shell=True, timeout=5)
    except Exception as ex:
        logger.warning(f"Could not kill orphan processes: {ex}")

# Ensure single instance & terminate orphan ghost processes on startup
def ensure_single_instance():
    """Ensure only one instance of IgniteChat runs at a time on Windows using a Named Mutex."""
    if sys.platform == 'win32':
        try:
            kernel32 = ctypes.windll.kernel32
            mutex_name = "Global\\IgniteChat_SingleInstance_Mutex_v1"
            mutex = kernel32.CreateMutexW(None, False, mutex_name)
            last_error = kernel32.GetLastError()
            ERROR_ALREADY_EXISTS = 183
            if last_error == ERROR_ALREADY_EXISTS:
                try:
                    user32 = ctypes.windll.user32
                    hwnd = user32.FindWindowW(None, "Ignite Chat")
                    if not hwnd:
                        hwnd = user32.FindWindowW(None, "Ignite Gemini Assistant")
                    if hwnd and user32.IsWindowVisible(hwnd):
                        logger.warning("⚠️ Another instance of IgniteChat is already running. Bringing window to focus...")
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE / SW_SHOWNORMAL
                        user32.SetForegroundWindow(hwnd)
                        sys.exit(0)
                except Exception:
                    pass
                logger.warning("Mutex key detected from an invisible orphan process. Cleaning up orphan processes...")
                kill_orphan_launcher_processes()
        except Exception as e:
            logger.warning(f"Could not check single instance mutex: {e}")

ensure_single_instance()

# Initialize variables to None for safe fallback/checks
webview = None
PyWebViewApi = None
import_error = None

# Safely import webview
logger.debug("Loading pywebview...")
try:
    import webview
    logger.debug("Pywebview loaded successfully!")
except Exception as e:
    logger.critical(f"webview import failed: {e}", exc_info=True)

# Load helper libraries
logger.debug("Loading main libraries...")
try:
    logger.debug("Main libraries verified!")
except Exception as e:
    logger.critical(f"main.libraries import failed: {e}", exc_info=True)

# Run log folder reorganization migration on startup
logger.debug("Running log folder migration...")
try:
    from main.migration import migrate_logs
    migrate_logs()
except Exception as e:
    logger.error(f"Failed to run log folder migration on startup: {e}", exc_info=True)

# Load runtime mode before choosing local vs remote API backend
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(current_dir, ".env"))
except Exception:
    pass

runtime_mode = (os.getenv("IGNITE_RUNTIME_MODE") or "local").strip().lower()
logger.info("IGNITE_RUNTIME_MODE=%s", runtime_mode)

# Safely import API backend (local processors or remote ACA proxy)
logger.debug("Trying to import desktop API backend...")
try:
    if runtime_mode == "remote":
        from main.remote_api_proxy import RemotePyWebViewApi as PyWebViewApi

        logger.debug("RemotePyWebViewApi imported successfully (remote mode).")
    else:
        from main.api import PyWebViewApi

        logger.debug("PyWebViewApi imported successfully (local mode).")
except BaseException as e:
    import_error = traceback.format_exc()
    logger.error(f"[ERROR] Failed to import desktop API backend (Caught BaseException):\n{import_error}")
    try:
        traceback.print_exc(file=sys.stdout)
        with open(crash_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- Desktop API Import Failure ---\n{import_error}\n")
    except Exception:
        pass
    PyWebViewApi = None

"""
Class to handle API initialization errors and display them in the UI.
"""
class PyAPI:
    def __init__(self, error_message):
        self.error_message = error_message
    
    # Initialize the API state
    def get_initial_state(self):
        return {
            "user_name": "User",
            "providers": ["System"],
            "current_provider": "System",
            "models": {"System": ["Error"]},
            "current_model": {"System": "Error"},
            "avatars": {},
            "history": [{"role": "assistant", "content": f"**API Initialization Error:**\n\n```text\n{self.error_message}\n```\n\nPlease check your configuration, API keys, or missing modules.", "token_info": None, "timestamp": None}],
            "token_totals": {"System": 0}
        }
    
    # Set the provider
    def set_provider(self, provider):
        return {"status": "success", "history": self.get_initial_state()["history"]}
    
    # Set the theme window size
    def set_theme_window_size(self, theme):
        return {"status": "success"}
    
    # Send a message to the API
    def send_message_async(self, text, files=None, language=None, from_mic=False, temperature=None, top_p=None, max_tokens=None, provider=None):
        return {"request_id": "error_1"}
    
    # Get the generation status
    def get_generation_status(self, request_id, since_reply_index=0):
        return {
            "status": "done",
            "result": {
                "status": "error",
                "message": "The API failed to initialize. See the first message for details."
            }
        }

# Start the webview
def start_webview():
    if webview is None:
        logger.critical("Cannot start webview because the webview module is not loaded. Check 'crash_log/crash_log.txt' for details.")
        return

    # Ensure mp3 assets are copied to frontend/assets/ for local file WebView2 access
    try:
        frontend_assets_dir = os.path.join(current_dir, 'frontend', 'assets')
        os.makedirs(frontend_assets_dir, exist_ok=True)
        src_dir = os.path.join(current_dir, 'assets')
        if os.path.exists(src_dir):
            # Copy/Sync light mode image.png with WhatsApp_light_mode_2.jpg if needed
            src_jpg = os.path.join(src_dir, 'WhatsApp_light_mode_2.jpg')
            dest_png_src = os.path.join(src_dir, 'light mode image.png')
            dest_png_fe = os.path.join(frontend_assets_dir, 'light mode image.png')
            if os.path.exists(src_jpg):
                if not os.path.exists(dest_png_src) or os.path.getmtime(src_jpg) > os.path.getmtime(dest_png_src):
                    shutil.copy2(src_jpg, dest_png_src)
                    shutil.copy2(src_jpg, dest_png_fe)
                    logger.info("Synced light mode image.png with WhatsApp_light_mode_2.jpg")
            for file_name in os.listdir(src_dir):
                if file_name.endswith(('.mp3', '.svg', '.png', '.jpg', '.jpeg')):
                    src_file = os.path.join(src_dir, file_name)
                    dest_file = os.path.join(frontend_assets_dir, file_name)
                    if not os.path.exists(dest_file):
                        shutil.copy2(src_file, dest_file)
                        logger.info(f"Copied {file_name} to frontend/assets/")
    except Exception as e:
        logger.error(f"Failed to copy mp3 assets: {e}")

    logger.debug("Creating window...")
    api = None
    if PyWebViewApi is None:
        api = PyAPI(import_error or "Unknown import error.")
    else:
        try:
            api = PyWebViewApi()
        except Exception as e:
            err_msg = traceback.format_exc()
            logger.error(f"[ERROR] API initialization failed:\n{err_msg}", exc_info=True)
            api = PyAPI(err_msg)

    html_path = os.path.abspath(os.path.join(current_dir, 'frontend', 'index.html'))
    html_url = pathlib.Path(html_path).as_uri()
    
    logger.debug(f"Loading URL: {html_url}")
    try:
        window = webview.create_window(
            'IgniteChat', 
            url=html_url, 
            js_api=api,
            width=800, 
            height=600,
            min_size=(300, 500),
            background_color='#161717',
            resizable=False          
        )
        
        if window is None:
            logger.error("Failed to create webview window: create_window returned None.")
            return

        def on_window_closed():
            logger.info("Window closed event fired. Forcing exit of the python process to prevent ghost instances.")
            os._exit(0)
            
        window.events.closed += on_window_closed

        if hasattr(api, "set_window"):
            api.set_window(window)

        # Override set_theme_window_size to dynamically change title bar colors
        if api is not None and hasattr(api, "set_theme_window_size"):
            original_set_theme = api.set_theme_window_size
            def custom_set_theme(theme):
                res = original_set_theme(theme)
                try:
                    hwnd = None
                    native_obj = getattr(window, 'native', None) if window is not None else None
                    if native_obj is not None:
                        try:
                            helper = WindowInteropHelper(native_obj)
                            hwnd = int(helper.EnsureHandle().ToInt64())
                        except BaseException:
                            pass
                        if hwnd is None:
                            try:
                                if hasattr(native_obj, 'Handle') and native_obj.Handle is not None:
                                    hwnd = int(native_obj.Handle.ToInt64())
                            except BaseException:
                                pass
                    
                    if hwnd is not None:
                        dwmapi = ctypes.WinDLL("dwmapi")
                        DWMWA_CAPTION_COLOR = 35
                        DWMWA_TEXT_COLOR = 36
                        
                        if theme == "dark":
                            caption_color = 0x001F1F1D  # #1D1F1F -> BGR: 1F, 1F, 1D -> 0x001F1F1D
                            text_color = 0x00FFFFFF  # white text
                        else:
                            caption_color = 0x00F3F5F7  # #F7F5F3 -> BGR: F3, F5, F7 -> 0x00F3F5F7
                            text_color = 0x000A0A0A  # #0A0A0A -> BGR: 0A, 0A, 0A -> 0x000A0A0A
                            
                        dwmapi.DwmSetWindowAttribute(
                            hwnd, 
                            DWMWA_CAPTION_COLOR, 
                            ctypes.byref(ctypes.c_int(caption_color)), 
                            ctypes.sizeof(ctypes.c_int)
                        )
                        dwmapi.DwmSetWindowAttribute(
                            hwnd, 
                            DWMWA_TEXT_COLOR, 
                            ctypes.byref(ctypes.c_int(text_color)), 
                            ctypes.sizeof(ctypes.c_int)
                        )
                        logger.info(f"Dynamically updated DWM window title bar color to: {theme}")
                except Exception as dwm_ex:
                    logger.error(f"Failed to dynamically update title bar color: {dwm_ex}")
                return res
            setattr(api, "set_theme_window_size", custom_set_theme)
        
        # Create the window
        def on_webview_created(win):
            try:
                # Wait for win.native to be initialized
                for _ in range(50):
                    if win.native is not None:
                        break
                    time.sleep(0.1)
                
                if win.native is None:
                    logger.error("win.native was not initialized.")
                    return

                ico_path = os.path.join(current_dir, 'icon.ico')
                if not os.path.exists(ico_path):
                    logger.error(f"Icon path does not exist: {ico_path}")
                    return

                hwnd = None
                
                # 1. Try to set WPF Window.Icon property and get WPF hwnd (if using WPF/pythonnet)
                try:
                    if clr is not None:
                        clr.AddReference('PresentationFramework')
                        clr.AddReference('PresentationCore')
                        clr.AddReference('WindowsBase')
                                                            
                    # Get handle using WPF WindowInteropHelper
                    if WindowInteropHelper is not None:
                        helper = WindowInteropHelper(win.native)
                        hwnd = int(helper.EnsureHandle().ToInt64())
                        logger.info(f"Got WPF HWND: {hwnd}")
                    
                    from System import Uri  # type: ignore
                    from System.Windows.Media.Imaging import BitmapFrame  # type: ignore

                    # Set the WPF Icon property
                    abs_ico_path = os.path.abspath(ico_path)
                    uri = Uri(abs_ico_path)
                    bitmap_frame = BitmapFrame.Create(uri)
                    
                    Action = getattr(System, 'Action', None) if System is not None else None
                    if hasattr(win.native, 'Dispatcher') and win.native.Dispatcher is not None:
                        def set_wpf_icon():
                            win.native.Icon = bitmap_frame
                            logger.info("WPF Window.Icon property set via Dispatcher.")
                        if Action is not None:
                            win.native.Dispatcher.Invoke(Action(set_wpf_icon))
                        else:
                            win.native.Dispatcher.Invoke(set_wpf_icon)
                    else:
                        win.native.Icon = bitmap_frame
                        logger.info("WPF Window.Icon property set directly.")
                except BaseException as wpf_ex:
                    logger.debug(f"Not a WPF window or failed to set WPF icon: {wpf_ex}")

                # 2. Try to set WinForms Form.Icon property and get WinForms hwnd (if using WinForms)
                if hwnd is None:
                    try:
                        if clr is not None:
                            try:
                                clr.AddReference('System.Drawing')
                            except Exception:
                                pass
                        
                        if hasattr(win.native, 'Handle') and win.native.Handle is not None:
                            hwnd = int(win.native.Handle.ToInt64())
                            logger.info(f"Got WinForms HWND: {hwnd}")
                            
                            if System is not None and hasattr(System, 'Drawing'):
                                form_icon = System.Drawing.Icon(ico_path)
                                Action = getattr(System, 'Action', None)
                                if hasattr(win.native, 'InvokeRequired') and win.native.InvokeRequired:
                                    def set_wf_icon():
                                        win.native.Icon = form_icon
                                        logger.info("WinForms Form.Icon property set via Invoke.")
                                    if Action is not None:
                                        win.native.Invoke(Action(set_wf_icon))
                                    else:
                                        win.native.Invoke(set_wf_icon)
                                else:
                                    win.native.Icon = form_icon
                                    logger.info("WinForms Form.Icon property set directly.")
                    except BaseException as wf_ex:
                        logger.debug(f"Not a WinForms window or failed to set WinForms icon: {wf_ex}")

                # 3. Fallback/Standard Win32 API icon set via ctypes (uses hwnd if found)
                if hwnd is not None:
                    WM_SETICON = 0x0080
                    ICON_SMALL = 0
                    ICON_BIG = 1
                    LR_LOADFROMFILE = 0x00000010
                    IMAGE_ICON = 1
                    
                    hicon = ctypes.windll.user32.LoadImageW(
                        None, 
                        ico_path, 
                        IMAGE_ICON, 
                        0, 0, 
                        LR_LOADFROMFILE
                    )
                    if hicon:
                        ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                        ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                        logger.info("Window icon updated successfully via ctypes SendMessageW.")
                    # DWM Title Bar Color support (Win11+)
                    try:
                        dwmapi = ctypes.WinDLL("dwmapi")
                        DWMWA_CAPTION_COLOR = 35
                        DWMWA_TEXT_COLOR = 36
                        # Set initial dark theme caption color (#1D1F1F -> BGR: 1F, 1F, 1D -> 0x001F1F1D)
                        caption_color = 0x001F1F1D
                        text_color = 0x00FFFFFF
                        dwmapi.DwmSetWindowAttribute(
                            hwnd, 
                            DWMWA_CAPTION_COLOR, 
                            ctypes.byref(ctypes.c_int(caption_color)), 
                            ctypes.sizeof(ctypes.c_int)
                        )
                        dwmapi.DwmSetWindowAttribute(
                            hwnd, 
                            DWMWA_TEXT_COLOR, 
                            ctypes.byref(ctypes.c_int(text_color)), 
                            ctypes.sizeof(ctypes.c_int)
                        )
                        logger.info("Window title bar style updated to dark mode via dwmapi.")
                    except Exception as dwm_ex:
                        logger.debug(f"Failed to set initial dwmapi title bar color: {dwm_ex}")
                else:
                    logger.warning("Could not retrieve HWND; ctypes SendMessageW skipped.")
            except Exception as icon_ex:
                logger.error(f"Failed to set window icon: {icon_ex}")

        logger.info("[4] Starting webview event loop...")
        debug_mode = os.getenv("IGNITE_DEBUG", "False").lower() in ("true", "1")
        try:
            webview.start(on_webview_created, (window,), debug=debug_mode)
        except Exception as start_ex:
            err_str = str(start_ex)
            if "0x800700AA" in err_str or "resource is in use" in err_str.lower():
                logger.warning("WebView2 resource in use (0x800700AA) detected. Cleaning up orphan processes and retrying...")
                kill_orphan_launcher_processes()
                time.sleep(1)
                webview.start(on_webview_created, (window,), debug=debug_mode)
            else:
                raise start_ex
        logger.info("[5] Webview event loop closed normally.")
    except Exception as e:
        logger.error(f"[ERROR] webview start failed: {e}", exc_info=True)
        with open(crash_log_path, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)

if __name__ == '__main__':
    start_webview()
