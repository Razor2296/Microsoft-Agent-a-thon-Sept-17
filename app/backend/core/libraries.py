"""
Backend Libraries Module — Centralized logging setup and helper utilities.
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

from backend.core.runtime_paths import get_log_dir

# Writable log root (AppData when installed under Program Files; /data on ACA)
LOG_DIR = get_log_dir()


# Function to get logger for a specific module
def get_assistant_logger(name: str) -> logging.Logger:
    """Get logger for a specific module"""
    l = logging.getLogger(f"{name}_assistant")
    if not l.handlers:
        l.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # File handler
        name_lower = name.lower()
        if name_lower in ["gemini", "deepseek", "openai", "anthropic", "perplexity", "grok", "alibabacloud"]:
            prov_log_dir = os.path.join(LOG_DIR, name_lower, "Activity")
            os.makedirs(prov_log_dir, exist_ok=True)
            log_filepath = os.path.join(prov_log_dir, f"{name}.log")
        else:
            log_filepath = os.path.join(LOG_DIR, f"{name}.log")

        # Rotate so long-lived desktop/ACA processes never grow logs unbounded
        # (same 10MB x 3 policy as the crash log in launcher_webview).
        fh = RotatingFileHandler(
            log_filepath, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(formatter)
        l.addHandler(fh)

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        l.addHandler(ch)
    return l

# Default logger for base functionalities
logger = get_assistant_logger("base_processor")
get_logger = get_assistant_logger
