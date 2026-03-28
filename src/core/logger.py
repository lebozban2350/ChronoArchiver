import logging
import sys
import threading
import warnings

from version import __version__, APP_NAME


def setup_logger():
    from core.debug_logger import get_log_path, init_log, install_global_exception_hooks

    init_log()
    log_file = get_log_path()

    def _log_network():
        try:
            from core.network_status import log_network_status_to_debug

            log_network_status_to_debug()
        except Exception:
            pass

    threading.Thread(target=_log_network, daemon=True).start()

    # Reset handlers if re-initialized
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    fmt = "%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
    handlers = [
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]

    logging.basicConfig(
        format=fmt,
        level=logging.DEBUG,
        handlers=handlers,
        force=True,
    )

    logging.captureWarnings(True)
    warnings.simplefilter("default")
    wlog = logging.getLogger("py.warnings")
    wlog.setLevel(logging.WARNING)

    install_global_exception_hooks()

    logging.info(f"=== ChronoArchiver v{__version__} Started ===")
    logging.info(f"Log file: {log_file}")

    return logging.getLogger(APP_NAME)
