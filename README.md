# ip-crawler

Crawl my favorite virtual characters by visiting their wiki.

Every franchise under [`data/`](data) is mirrored, analysed for the meta
structure of its wiki pages, and written into **one** sqlite database.

- Design: [docs/design.md](docs/design.md) — the three-layer OOP model in Mermaid.
- Tests: `python -m unittest discover -s tests -t .` (125 cases, no network needed).

## Install

```console
uv venv
uv pip install -e . --group dev
```

## Usage

```console
# what can be crawled?
ip-crawler games

# see what a mirror would do, without touching the network
ip-crawler mirror arknights --dry-run

# mirror a wiki (wget --mirror --no-parent --page-requisites)
ip-crawler mirror arknights

# what fields does this wiki's infoboxes carry?
ip-crawler analyse data/arknights/main

# host a mirror so playwright codegen can drive it
ip-crawler serve data/arknights/main
ip-crawler codegen http://127.0.0.1:8000/wiki/Amiya

# fill the single sqlite database from every mirror present
ip-crawler build-db
```

## The three layers

| Layer | Module | Responsibility |
|---|---|---|
| 1 | `ipcrawler.domain`, `ipcrawler.crawler` | `Crawler`, `IP`, `Character`, `World`, `Location`, `Source`; the concrete `WgetMPXCrawler` |
| 2 | `ipcrawler.analysis` | mirror a wiki, serve it locally, infer its meta structure, record browser sessions |
| 3 | `ipcrawler.games` | the 12 concrete franchises under `data/`, as declarative `GameSpec` records |

`ipcrawler.storage` turns any of the above into one sqlite file; `ipcrawler.cli`
wires all three behind the `ip-crawler` command.

## Python API

```python
from ipcrawler.cli import build_ip_from_directory
from ipcrawler.storage import Database

ip = build_ip_from_directory("arknights", "data/arknights/main")
with Database("ipcrawler.sqlite3") as db:
    db.save(ip)
    print(db.list_ips())
```

## Adding a game

Add a folder under `data/` and one `GameSpec` to `GAME_SPECS` in
`src/ipcrawler/games/__init__.py`. A test asserts the catalog and the `data/`
directory listing agree, so the two cannot drift apart.

## Development

This project is built test-first: each layer landed as a `[WIP]` commit
containing only failing tests, followed by the implementation commit that turned
them green. `git log --oneline` shows the sequence.

```console
python -m unittest discover -s tests -t . -v
```

## Database schema

| Table | Rows |
|---|---|
| `ip` | one row per franchise |
| `world` | fictional settings |
| `location` | places inside a world |
| `character` | personas |
| `alias` | alternative names |
| `attribute` | raw infobox key/value pairs |
| `source` | the wiki URLs an IP was learned from |

## License

See [LICENSE](LICENSE).
