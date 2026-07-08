"""Main entry point for Timshel daemon."""

import sys

from src.bootstrap import ensure_ready

# Run bootstrap before importing config-dependent runtime modules.
ensure_ready()

from src.config.config import get_config

# Initialize global config instance after migration
# This ensures config is deterministic and doesn't depend on import order
get_config()

from src.logger import logger
from src.app_core import TimshelTranscriber


def main():
    """Main entry point."""
    try:
        app = TimshelTranscriber()
        app.start()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()


