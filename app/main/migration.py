import os
import sys
import shutil
import glob
import logging
import time
import hashlib
logger = logging.getLogger("IgniteChat_LogMigration")

def migrate_logs():
    """
    Automatically reorganizes log folders into the new structure on application startup:
    - Moves root-level provider logs: log/{provider}.log -> log/{provider}/Activity/{provider}.log
    - Moves provider session JSON files: log/{provider}/*.json -> log/{provider}/Sessions/*.json
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        _exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(_exe_dir, '.env')):
            app_dir = _exe_dir
        elif os.path.exists(os.path.join(os.path.dirname(_exe_dir), '.env')):
            app_dir = os.path.dirname(_exe_dir)
        else:
            app_dir = _exe_dir
    else:
        app_dir = os.path.dirname(current_dir)
    log_dir = os.path.join(app_dir, "log")
    
    if not os.path.exists(log_dir):
        logger.info("No log directory found. Skipping migration.")
        return
    else:
        logger.info(f"Log directory found at: {log_dir}. Starting migration.")

    providers = ["gemini", "deepseek", "openai", "anthropic", "perplexity", "grok", "alibabacloud"]
    
    # 1. Reorganize provider .log files into Activity/ subfolders
    for prov in providers:
        prov_log_file = os.path.join(log_dir, f"{prov}.log")
        if os.path.exists(prov_log_file):
            target_dir = os.path.join(log_dir, prov, "Activity")
            os.makedirs(target_dir, exist_ok=True)
            target_file = os.path.join(target_dir, f"{prov}.log")
            
            try:
                if os.path.exists(target_file):
                    # Append source to target if target already exists
                    with open(prov_log_file, "r", encoding="utf-8") as f_src:
                        src_content = f_src.read()
                    with open(target_file, "a", encoding="utf-8") as f_dest:
                        f_dest.write(src_content)
                    os.remove(prov_log_file)
                else:
                    shutil.move(prov_log_file, target_file)
                logger.info(f"Migrated provider log: {prov_log_file} -> {target_file}")
            except Exception as e:
                logger.error(f"Failed to migrate log file {prov_log_file}: {e}")
        else:
            logger.info(f"Log file not found for provider: {prov}")

    # 2. Reorganize session JSON files into Sessions/ subfolders
    for prov in providers:
        prov_dir = os.path.join(log_dir, prov)
        if os.path.exists(prov_dir):
            json_pattern = os.path.join(prov_dir, "*.json")
            json_files = glob.glob(json_pattern)
            
            if json_files:
                sessions_dir = os.path.join(prov_dir, "Sessions")
                os.makedirs(sessions_dir, exist_ok=True)
                
                for json_file in json_files:
                    target_file = os.path.join(sessions_dir, os.path.basename(json_file))
                    try:
                        if os.path.exists(target_file):
                            with open(json_file, "rb") as f_src:
                                src_data = f_src.read()
                            with open(target_file, "rb") as f_dest:
                                dest_data = f_dest.read()
                            if src_data == dest_data:
                                os.remove(json_file)
                            else:
                                content_hash = hashlib.md5(src_data).hexdigest()[:8]
                                base, ext = os.path.splitext(os.path.basename(json_file))
                                unique_target = os.path.join(sessions_dir, f"{base}_{content_hash}{ext}")
                                shutil.move(json_file, unique_target)
                                logger.info(f"Resolved session name collision: moved {json_file} -> {unique_target}")
                        else:
                            shutil.move(json_file, target_file)
                        logger.info(f"Migrated session file: {json_file} -> {target_file}")
                    except Exception as e:
                        logger.error(f"Failed to migrate session file {json_file}: {e}")

    # 3. Clean up generated files older than 30 days
    generated_dir = os.path.join(log_dir, "generated_files")
    if os.path.exists(generated_dir):
        logger.info(f"Checking for old generated files to clean up in: {generated_dir}")
        now = time.time()
        cutoff = now - (30 * 24 * 60 * 60)  # 30 days in seconds
        try:
            for filename in os.listdir(generated_dir):
                file_path = os.path.join(generated_dir, filename)
                if os.path.isfile(file_path):
                    file_mtime = os.path.getmtime(file_path)
                    if file_mtime < cutoff:
                        os.remove(file_path)
                        logger.info(f"Deleted old generated file: {filename}")
        except Exception as e:
            logger.error(f"Failed to clean up old generated files: {e}")
