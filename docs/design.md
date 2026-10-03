# ip-crawler — three-layer OOP design

This document is the design the plan (`deepseek-harness-plan.md`) asks for: a
three-layer object model, drawn in Mermaid, with the concrete classes filled in.

---

## The three layers at a glance

```mermaid
flowchart TB
    subgraph L3["Layer 3 — concrete games (ipcrawler.games)"]
        SPEC["GameSpec<br/>12 franchises under ./data"]
        BUILD["build_ip(spec, pages)"]
    end

    subgraph L2["Layer 2 — wiki meta-structure (ipcrawler.analysis)"]
        MIRROR["WikiMirror"]
        SERVER["LocalWikiServer"]
        SCHEMA["analyse_page / extract_fields"]
        DRIVER["BrowserDriver / codegen_command"]
    end

    subgraph L1["Layer 1 — domain vocabulary (ipcrawler.domain)"]
        CRAWLER["Crawler (ABC)"]
        WGET["WgetMPXCrawler"]
        IPM["IP"]
        WORLD["World"]
        LOC["Location"]
        CHAR["Character"]
        SRC["Source"]
    end

    subgraph ST["Storage (ipcrawler.storage)"]
        DB["Database → one sqlite file"]
    end

    SPEC --> BUILD
    BUILD --> SCHEMA
    BUILD --> IPM
    MIRROR --> WGET
    MIRROR --> SRC
    DRIVER --> SERVER
    SERVER --> MIRROR
    IPM --> WORLD
    IPM --> CHAR
    IPM --> SRC
    WORLD --> LOC
    WGET -.implements.-> CRAWLER
    DB -.persists.-> IPM
    BUILD --> DB
```

**Why the dependency arrows only point downward:** layer 3 may use layers 1 and
2, layer 2 may use layer 1, but layer 1 uses nothing. That is what makes the
domain vocabulary reusable and the analysis machinery reusable across games.

---

## Layer 1 — the domain vocabulary

The nouns the whole project speaks in. Nothing here knows about HTTP, sqlite, or
any particular game.

```mermaid
classDiagram
    class Crawler {
        <<abstract>>
        +fetch(source: Source) str
        +fetch_all(sources) dict
    }

    class WgetMPXCrawler {
        -runner
        -workdir: Path
        -workers: int
        -timeout: float
        +build_command(source, dest) list
        +plan_workers(n) int
        +fetch(source) str
        +fetch_all(sources) dict
    }

    class Source {
        <<frozen>>
        +url: str
        +kind: str
        +title: str?
        +host: str
    }

    class IP {
        +name: str
        +add_world(world) World
        +add_character(c) Character
        +add_source(s) Source
        +worlds: tuple
        +characters: tuple
        +sources: tuple
    }

    class World {
        +name: str
        +add_location(loc) Location
        +locations: tuple
    }

    class Location {
        <<frozen>>
        +name: str
        +world_name: str?
    }

    class Character {
        <<frozen>>
        +name: str
        +aliases: tuple
        +world_name: str?
        +location_name: str?
        +attributes: tuple
        +attribute(key) str?
    }

    Crawler <|-- WgetMPXCrawler
    IP o-- World : owns
    IP o-- Character : owns
    IP o-- Source : learned from
    World o-- Location : contains
    Character ..> World : world_name
    Character ..> Location : location_name
    WgetMPXCrawler ..> Source : fetches
```

`Source`, `Location`, `Character` are **frozen dataclasses** — structural
equality, hashable, so they can join sets while the graph is assembled.
`IP` and `World` are **aggregate roots** — they own their members, hand out
read-only tuples, and expose `add_*` methods that are idempotent by name.

---

## Layer 2 — wiki meta-structure analysis

"Meta structure" means: *given this wiki, how do I get from a page to a
character's fields?* Layer 2 answers that from the HTML itself, so layer 3 never
hard-codes selectors.

```mermaid
classDiagram
    class WikiMirror {
        -crawler: Crawler
        -root: Path
        -concurrency: int
        +mirror(source, extra_paths) MirrorResult
    }

    class MirrorResult {
        <<frozen>>
        +host: str
        +directory: Path
        +files: tuple
        +failures: tuple
        +ok: bool
    }

    class LocalWikiServer {
        -root: Path
        -host: str
        +start() LocalWikiServer
        +stop() None
        +base_url: str
        +url_for(path) str
        +get(path) str
    }

    class PageSchema {
        <<frozen>>
        +fields: tuple~FieldSpec~
        +headings: tuple
        +merge(other) PageSchema
    }

    class FieldSpec {
        <<frozen>>
        +name: str
        +examples: tuple
        +with_example(v) FieldSpec
    }

    class BrowserDriver {
        -runner
        -gui
        -timeout: float
        +codegen(url, ...) CodegenResult
        +run(script) RunResult
        +click(x, y) None
        +move_to(x, y) None
    }

    WikiMirror ..> Crawler : uses
    WikiMirror --> MirrorResult : returns
    LocalWikiServer ..> WikiMirror : serves output of
    BrowserDriver ..> LocalWikiServer : drives
    PageSchema o-- FieldSpec : contains
    PageSchema ..> PageSchema : merge
```

### The mirror → serve → record loop

```mermaid
sequenceDiagram
    participant L3 as Layer 3 (GameSpec)
    participant MP as WikiMirror
    participant CR as WgetMPXCrawler
    participant SV as LocalWikiServer
    participant DR as BrowserDriver
    participant PW as playwright codegen

    L3->>MP: mirror(spec.source)
    MP->>CR: fetch_all(pages)
    CR-->>MP: HTML bodies
    MP-->>L3: data/<game>/main/**/*.html
    L3->>SV: serve(data/<game>/main)
    SV-->>L3: http://127.0.0.1:<port>/
    L3->>DR: codegen(url)
    DR->>PW: playwright codegen -o output.py --user-data-dir ...
    PW-->>DR: recorded script
    DR-->>L3: output.py (replayable)
    Note over DR,PW: pyautogui clicks the live window<br/>for interactions codegen cannot express
```

Serving over loopback rather than opening `file://` matters: a file URL changes
CORS, `fetch`, and relative-URL resolution, so a page that works offline can
behave differently from the same page online.

Three infobox dialects are recognised, which between them cover the target
wikis:

| Dialect | Markup | Seen in |
|---|---|---|
| Table rows | `<tr><th>K</th><td>V</td></tr>` | classic MediaWiki / Fandom |
| Portable infobox | `<div class="pi-item"><h3 class="pi-data-label">…` | modern Fandom |
| Description list | `<dt>K</dt><dd>V</dd>` | hand-rolled wikis |

---

## Layer 3 — the concrete games

Layer 3 is **data, not subclasses**: each franchise is a `GameSpec` record.

```mermaid
classDiagram
    class GameSpec {
        <<frozen>>
        +slug: str
        +name: str
        +wiki_url: str
        +character_prefix: str
        +world: str?
        +data_dir: str
        +source: Source
        +matches_character_path(p) bool
        +character_name_from_path(p) str
        +mirror_dir(root) Path
    }

    class GameCatalog {
        <<module>>
        GAME_SPECS: tuple
        +get_spec(slug) GameSpec
        +spec_for_slug(dirname) GameSpec
        +discover_local_games(root) tuple
        +build_ip(spec, pages) IP
    }

    GameCatalog o-- GameSpec : GAME_SPECS
    GameCatalog ..> IP : build_ip produces
    GameSpec ..> Source : source
```

The 12 franchises under `./data`, all catalogued in `GAME_SPECS`:

| Slug | Game | Wiki |
|---|---|---|
| `arknights` | Arknights | arknights.fandom.com |
| `bang-dream` | BanG Dream! | bang-dream.fandom.com |
| `blue-archive` | Blue Archive | bluearchive.fandom.com |
| `genshin-impact` | Genshin Impact | genshin-impact.fandom.com |
| `harry-potter-magic-awakened` | Harry Potter: Magic Awakened | harrypotter.fandom.com |
| `kantai-collection` | Kantai Collection | kancolle.fandom.com |
| `lovelive` | Love Live! | love-live.fandom.com |
| `naruto-mobile` | Naruto Mobile | naruto.fandom.com |
| `personality-database-mbti` | Personality Database (MBTI) | personality-database.com |
| `project-seikai` | Project SEKAI | project-sekai.fandom.com |
| `the-fifth-persionality` | The Fifth Personality | id5.fandom.com |
| `touhou-project` | Touhou Project | touhou.fandom.com |

A unit test asserts this catalog and the actual `./data` directory listing agree,
so adding a folder without a spec fails CI.

---

## Storage — one sqlite file

```mermaid
erDiagram
    IP ||--o{ WORLD : "has"
    IP ||--o{ CHARACTER : "has"
    IP ||--o{ SOURCE : "learned from"
    WORLD ||--o{ LOCATION : "contains"
    CHARACTER ||--o{ ALIAS : "also known as"
    CHARACTER ||--o{ ATTRIBUTE : "infobox fields"

    IP {
        int id PK
        text name UK
    }
    WORLD {
        int id PK
        int ip_id FK
        text name
    }
    LOCATION {
        int id PK
        int world_id FK
        text name
    }
    CHARACTER {
        int id PK
        int ip_id FK
        text name
        text world_name
        text location_name
    }
    ALIAS {
        int id PK
        int character_id FK
        text value
    }
    ATTRIBUTE {
        int id PK
        int character_id FK
        text key
        text value
    }
    SOURCE {
        int id PK
        int ip_id FK
        text url
        text kind
        text title
    }
```

`character.world_name` / `location_name` are stored as **text, not FKs**: wiki
data is messy and a character routinely references a world or faction that was
never enumerated as its own page. Making them hard FKs would reject real data;
keeping them as text and additionally materialising `location` rows when they
are known gives both recall and structure.

Every write uses `INSERT ... ON CONFLICT DO UPDATE` against `UNIQUE`
constraints, so re-crawling the same wiki **converges instead of duplicating**.

---

## TDD history

Each layer was built test-first. `git log` shows the pattern — a `[WIP]` commit
containing only failing tests, then the implementation commit that turns them
green:

```mermaid
gitGraph
    commit id: "chore: scaffold"
    commit id: "[WIP] layer1 tests"
    commit id: "feat: domain models"
    commit id: "[WIP] layer2 mirror tests"
    commit id: "feat: WikiMirror"
    commit id: "[WIP] layer1 wget tests"
    commit id: "feat: WgetMPXCrawler"
    commit id: "[WIP] layer2 server tests"
    commit id: "feat: LocalWikiServer"
    commit id: "[WIP] layer2 driver tests"
    commit id: "feat: BrowserDriver"
    commit id: "[WIP] layer2 schema tests"
    commit id: "feat: schema inference"
    commit id: "[WIP] layer3 tests"
    commit id: "feat: game catalog"
    commit id: "[WIP] storage tests"
    commit id: "feat: sqlite storage"
    commit id: "[WIP] cli tests"
    commit id: "feat: CLI"
```
