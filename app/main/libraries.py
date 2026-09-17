"""
Main Libraries Module — Logging configuration and shared main utilities.
"""
import os
import sys
import sysconfig
import logging

from typing import Any, Optional

# Document generation optional imports
docx: Any = None
openpyxl: Any = None
pptx: Any = None
PptRGBColor: Any = None
PptInches: Any = None
PptPt: Any = None
PP_ALIGN: Any = None

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

try:
    import docx
except ImportError:
    pass

try:
    import openpyxl
except ImportError:
    pass

try:
    import pptx
    from pptx.util import Inches as PptInches, Pt as PptPt
    from pptx.dml.color import RGBColor as PptRGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    pass

# Resolve app root early (needed for CoreCLR runtimeconfig on ARM64)
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(_exe_dir, '.env')):
        app_dir = _exe_dir
    elif os.path.exists(os.path.join(os.path.dirname(_exe_dir), '.env')):
        app_dir = os.path.dirname(_exe_dir)
    else:
        app_dir = _exe_dir
else:
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_windows_arm64_python() -> bool:
    """True only for a native ARM64 Python process (not x64 Python under emulation)."""
    if sys.platform != 'win32':
        return False
    try:
        return 'arm64' in sysconfig.get_platform().lower()
    except Exception:
        return False


# Try loading CLR / pythonnet for .NET interop (WPF/WinForms) in Windows webview
# Native ARM64 Python cannot use netfx (ClrLoader has no arm64 DLL) — use CoreCLR + Desktop.
clr: Any = None
System: Any = None
WindowInteropHelper: Any = None
try:
    if _is_windows_arm64_python():
        os.environ.setdefault('PYTHONNET_RUNTIME', 'coreclr')
        candidate_configs = [
            os.path.join(app_dir, 'pythonnet.runtimeconfig.json'),
            os.path.join(app_dir, 'Ignite Chat.runtimeconfig.json'),
            os.path.join(app_dir, '_internal', 'pythonnet.runtimeconfig.json'),
        ]
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            candidate_configs.extend([
                os.path.join(exe_dir, 'pythonnet.runtimeconfig.json'),
                os.path.join(exe_dir, 'Ignite Chat.runtimeconfig.json'),
                os.path.join(exe_dir, '_internal', 'pythonnet.runtimeconfig.json'),
            ])
            if hasattr(sys, '_MEIPASS'):
                candidate_configs.append(os.path.join(sys._MEIPASS, 'pythonnet.runtimeconfig.json'))

        _runtime_config = next((p for p in candidate_configs if os.path.isfile(p)), None)
        if _runtime_config:
            os.environ.setdefault('PYTHONNET_CORECLR_RUNTIME_CONFIG', _runtime_config)
        try:
            import pythonnet  # type: ignore
            _load_fn = getattr(pythonnet, 'load', None)
            if callable(_load_fn):
                _load_fn(
                    'coreclr',
                    runtime_config=_runtime_config if _runtime_config and os.path.isfile(_runtime_config) else None,
                )
        except Exception:
            pass
    import clr  # type: ignore
    # CoreCLR does not auto-load this assembly (unlike netfx); pywebview needs it.
    if os.environ.get('PYTHONNET_RUNTIME') == 'coreclr' and clr is not None:
        try:
            _add_ref = getattr(clr, 'AddReference', None)
            if callable(_add_ref):
                _add_ref('Microsoft.Win32.SystemEvents')
        except Exception:
            pass
    import System  # type: ignore
    from System.Windows.Interop import WindowInteropHelper  # type: ignore
except Exception:
    clr = None
    System = None
    WindowInteropHelper = None

try:
    import webview  # type: ignore
except ImportError:
    webview = None

LOG_DIR = None  # set below after writable-path resolution

try:
    from backend.core.runtime_paths import get_log_dir

    LOG_DIR = get_log_dir(app_dir)
except Exception:
    # Last-resort: never crash import on logging path (Program Files installs).
    _fallback = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    LOG_DIR = os.path.join(_fallback, "Ignite Chat", "log")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        LOG_DIR = os.environ.get("TEMP") or os.environ.get("TMP") or os.path.expanduser("~")

logger = logging.getLogger("Ignite Chat")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    try:
        fh = logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except OSError:
        pass

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)