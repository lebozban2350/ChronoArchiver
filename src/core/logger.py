import logging
import os
import sys
import platformdirs
from version import __version__, APP_NAME

def setup_logger():
    # Reset handlers if re-initialized
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    # Standardize log location using platformdirs (Cross-platform)
    log_dir = platformdirs.user_log_dir(APP_NAME, "UnDadFeated")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'chronoarchiver.log')
    
    handlers = [
        logging.FileHandler(log_file, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]

    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        level=logging.INFO,
        handlers=handlers
    )
    
    logging.info(f"=== Application Started ({__version__}) ===")
    logging.info(f"Log file: {log_file}")
    
    return logging.getLogger(APP_NAME)
