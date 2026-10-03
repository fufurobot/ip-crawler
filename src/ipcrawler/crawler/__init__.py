"""Layer 1 -- concrete crawler implementations.

``WgetMPXCrawler`` mirrors whole websites with ``wget``; see
:mod:`ipcrawler.crawler.wget`.
"""

from __future__ import annotations

from .wget import WgetMPXCrawler

__all__ = ["WgetMPXCrawler"]
