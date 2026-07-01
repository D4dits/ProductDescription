import logging
from logging.handlers import RotatingFileHandler
from app.config import LOGS_DIR

# Set up logging configuration
log_file = LOGS_DIR / "app.log"

logger = logging.getLogger("graszki_generator")
logger.setLevel(logging.INFO)

# Avoid adding multiple handlers if logger is already configured
if not logger.handlers:
    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler (rotating, max 5MB per file, keeping 3 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
