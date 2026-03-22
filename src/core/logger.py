import logging
import sys
from version import __version__, APP_NAME

def setup_logger():
    from core.debug_logger import get_log_path
    log_file = get_log_path()

    # Reset handlers if re-initialized
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    handlers = [
        logging.FileHandler(log_file, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]

    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
        level=logging.DEBUG,
        handlers=handlers
    )

    logging.info(f"=== ChronoArchiver v{__version__} Started ===")
    logging.info(f"Log file: {log_file}")

    return logging.getLogger(APP_NAME)
