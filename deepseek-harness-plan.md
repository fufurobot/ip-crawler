first generate a three layered oop design by mermaid:

first layer: Crawler,IP,Character,World,Location,Source. implement a concrete WgetMPXCrawler to mirror websites.

second layer: analyse wikis for meta structures for each game (listed under ./data). use WgetMPXCrawler to mirror these wikis. use simple python http server to host them and `playwright codegen -o output.py --user-data-dir (some dir under .data)` to analysis. use pyautogui to control playwright instances.

third layer: the concrete things to the second layer.

then fill in the database with a single sqlite.
