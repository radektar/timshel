"""Logging configuration for Timshel."""

import logging
import logging.handlers
import sys

# Import config from config package
# Using normal import now that config is properly structured
from src.config import config


_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_LOG_BACKUP_COUNT = 5  # keep up to 5 rotated files (~25 MB total ceiling)


def setup_logger(
    name: str = "timshel",
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """Setup centralized logging with file and console handlers.
    
    Args:
        name: Logger name
        level: Logging level (default: INFO)
        log_to_file: Enable file logging
        log_to_console: Enable console logging
        
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    config.ensure_directories()
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Capture all, handlers will filter
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler (rotating to cap disk usage at ~25 MB)
    if log_to_file:
        try:
            # encoding='utf-8' jest KRYTYCZNE: w py2app domyślny preferred
            # encoding to często ASCII, co powodowało, że logi zawierające
            # emoji (🎙️/🔄/✓/⚠️) rzucały UnicodeEncodeError i były ciche
            # gubione. Bez tego whole transcription path był niewidoczny
            # w pliku timshel.log mimo prawidłowego wykonania.
            file_handler = logging.handlers.RotatingFileHandler(
                config.LOG_FILE,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)
    
    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


# Global logger instance
logger = setup_logger()






