"""Application-wide logging setup."""

import logging
import sys


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logging with a single, clean stream handler.

    Called once from the app factory in main.py. Uses a plain, readable format
    suitable for local development (no external log shipping in this phase).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Avoid duplicate handlers if configure_logging() is called more than once
    # (e.g. under the --reload dev server, which re-imports the app module).
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
