"""Import LinkedIn scrapers from the sibling hexawealth_outreach package."""

from __future__ import annotations

import sys
from pathlib import Path

_OUTREACH_SRC = (
    Path(__file__).resolve().parents[2] / "hexawealth_outreach" / "src"
)
if _OUTREACH_SRC.is_dir() and str(_OUTREACH_SRC) not in sys.path:
    sys.path.insert(0, str(_OUTREACH_SRC))

from hexawealth_outreach.person_scraper import PersonScraper  # noqa: E402

__all__ = ["PersonScraper"]
