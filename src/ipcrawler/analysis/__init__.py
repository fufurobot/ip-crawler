"""Layer 2 -- analyse mirrored wikis for their meta structure.

Modules
-------
``mirror``
    Download a wiki into a local, host-namespaced file tree.
``server``
    Serve a mirrored tree over loopback HTTP so a real browser can drive it.
``driver``
    Record and replay playwright/pyautogui sessions against that server.

Nothing here knows about any specific game; see :mod:`ipcrawler.games`.
"""

from __future__ import annotations

__all__: list[str] = []
