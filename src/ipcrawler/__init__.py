"""ip-crawler: crawl virtual characters from their wikis into a single sqlite db.

The package is organised in three layers:

* layer 1 (:mod:`ipcrawler.domain`, :mod:`ipcrawler.crawler`) -- the abstract
  vocabulary of the problem: ``Crawler``, ``IP``, ``Character``, ``World``,
  ``Location`` and ``Source``, plus the concrete ``WgetMPXCrawler``.
* layer 2 (:mod:`ipcrawler.analysis`) -- mirror wiki sites, serve them locally
  and analyse their meta structure (playwright/pyautogui driven).
* layer 3 (:mod:`ipcrawler.games`) -- concrete per-game adapters that bind the
  generic layer 2 machinery to the wikis listed under ``./data``.

:mod:`ipcrawler.storage` fills a single sqlite database from any of the above.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
