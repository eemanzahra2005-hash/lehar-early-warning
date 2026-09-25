"""Process memory measurement (LEHAR Phase 1).

The deployed API has a hard 512MB ceiling (Render free tier — CLAUDE.md
rule 11), and the first LEHAR deploy was OOM-killed on `/api/v1/meta` and
`/api/v1/predict`. Knowing what the process actually costs is the only way
to keep that ceiling honest, so this module exposes one real measurement:
the process's resident set size (RSS) in MB.

Two rules shape everything here:

  - CLAUDE.md rule 4 — never fabricate a number. If psutil isn't installed
    or the platform refuses the reading, these return None. A caller that
    gets None reports `null`, never an estimate.
  - CLAUDE.md rule 11 — every eager import is weighed against 512MB. psutil
    is imported lazily inside the functions rather than at module level, so
    importing this module (which app/main.py does at startup) costs nothing
    until something actually asks for a measurement.

RSS is the right metric for a container memory limit: it is the physical
RAM the process is currently occupying, which is what the OOM killer and
`docker run --memory` both look at. It deliberately does NOT count the
memory-mapped model file's untouched pages (see ModelService's
`mmap_mode="r"` load under LOW_MEMORY_MODE) — that is the point of mmap.
"""

import logging

logger = logging.getLogger("app.memory")

BYTES_PER_MB = 1024 * 1024


def current_rss_mb() -> float | None:
    """This process's resident set size in MB, rounded to 1 decimal place.

    Returns None — never a guess — when psutil is unavailable or the
    reading fails. Never raises: a memory *diagnostic* must not be able to
    break the endpoint or the startup path it is reporting on.
    """
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / BYTES_PER_MB, 1)
    except Exception:
        logger.debug("RSS measurement unavailable on this platform/install.", exc_info=True)
        return None


def log_startup_memory() -> float | None:
    """Log the boot-time RSS once, at startup (called from app/main.py's
    lifespan when LOG_MEMORY=true). Returns the same value it logged, or
    None if it couldn't be measured — in which case it says so explicitly
    rather than logging a placeholder number.

    On a 512MB host this line is the single most useful thing in the deploy
    log: it is the floor every request then builds on top of. See
    docs/MEMORY.md for the measured numbers this project runs against.
    """
    rss_mb = current_rss_mb()
    if rss_mb is None:
        logger.warning("LOG_MEMORY is enabled but RSS could not be measured (is psutil installed?).")
        return None
    logger.info("Startup memory: RSS %.1f MB.", rss_mb)
    return rss_mb
