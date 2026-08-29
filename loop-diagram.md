# Loop Diagram — Job Intelligence System

The pictures for [LOOP.md](LOOP.md), kept separate so the diagrams can be
redrawn without touching the configuration they describe, and so a reader who
wants the shape does not have to scroll past it to reach the numbers.

Rendered with `mermaid-cli` before committing rather than eyeballed:

```bash
npx -y @mermaid-js/mermaid-cli@11 -i loop-diagram.md -o /tmp/loop-diagram.svg
```

## The whole night

Three scheduled things run against this repo. Only one of them writes code, and
none of them finishes a decision — every path ends at a human or at a file a
human reads. Times are JST; the machine is `Asia/Tokyo`.

```mermaid
flowchart TB
    classDef clock fill:#1f2937,stroke:#4b5563,color:#f9fafb
    classDef store fill:#0f2a1d,stroke:#2f6f4f,color:#eafff3
    classDef gate fill:#3b1d1d,stroke:#a14141,color:#ffecec
    classDef human fill:#2a2416,stroke:#8a7320,color:#fff8e1

    subgraph L1["L1 — nightly scout · archivist profile · no agent"]
        direction TB
        E["02:00 early<br/>linkedin · adzuna · indeed"]:::clock
        LATE["04:30 late<br/>reed · remote_apis · guardian"]:::clock
        SAVED[("00_saved/<br/>staged postings")]:::store
        PIPE["analyse · context score · rescore<br/>render reports · NOTIFY<br/>review sweep · re-render · stamp"]
        DOCS[("00_matches · 10_cvs<br/>10_cover-letters · 15_reviews")]:::store
        E -->|"scrape only, then exits"| SAVED
        LATE -->|"scrape only"| SAVED
        SAVED --> PIPE
        PIPE --> DOCS
    end

    subgraph L2["L2 — scraper repair · builder profile · one agent"]
        direction TB
        R7["07:00 loop-repair"]:::clock
        DRY{"any site dry?<br/>ran clean, returned nothing"}:::gate
        WT["git worktree<br/>agent: Read Edit Grep Glob<br/>no Bash, no Write"]
        GATE{"verify: distinct URLs >= floor<br/>distinct titles<br/>no new test failures"}:::gate
        BR["branch loop/repair-site-date"]:::store
        R7 --> DRY
        DRY -->|no| SILENT["silent, spends nothing"]
        DRY -->|yes, one site| WT
        WT --> GATE
        GATE -->|fail| DISCARD["worktree and branch deleted"]
        GATE -->|pass| BR
    end

    subgraph L3["L3 — readiness · archivist profile"]
        direction TB
        R9["09:00 loop-readiness-daily"]:::clock
        SCORE["scores that loop FILES exist<br/>does not check that any loop ran"]
    end

    STATS[("_llm_stats.tsv<br/>_nightly_site_yield.tsv<br/>_nightly_run_summary.tsv")]:::store
    TG["Telegram — one channel<br/>site outcomes · stale_sites · dry_sites<br/>coverage warnings · what loop_repair did"]
    HUMAN["YOU<br/>read the diff, merge or not<br/>send the application or not"]:::human
    PAUSE[".loop-pause<br/>kill switch"]:::gate

    PIPE --> STATS
    PIPE --> TG
    DOCS --> HUMAN
    BR --> HUMAN
    R7 --> TG
    R9 --> SCORE --> TG
    PAUSE -.->|"present = L2 does nothing"| R7
    STATS -.->|"read by hand with llm_stats.py"| HUMAN
    DRY -.->|"trigger comes from the night's yield"| STATS
```

Read the picture for two things.

**Every arrow into `YOU` is a stop, not a handoff.** L1 ends at generated
documents; nothing sends them. L2 ends at a branch; nothing merges it. The
system has no path to the outside world that does not pass through a person.

**L2 is one narrow arrow.** It fires only when a scraper ran clean and returned
nothing, touches one scraper file, and is discarded unread if the diff reaches
anything else. It has never fired in production — `git branch --list "loop/*"`
is empty — because nothing has broken. Dormant is the expected state.

The loop that has actually changed this system is not on the diagram, because it
runs on human attention rather than on cron: something gets measured into
`_llm_stats.tsv` or into `STATE.md`, a person reads it, and a change follows.
Every weight, gate and provider decision in the git log arrived that way. The
scheduled loops feed it; they do not replace it.

## L2 in detail

The gate is the whole design, so it is worth seeing on its own. `count > 0` was
the first version, and an agent passes that by fabricating one record.

```mermaid
flowchart LR
    classDef gate fill:#3b1d1d,stroke:#a14141,color:#ffecec
    classDef human fill:#2a2416,stroke:#8a7320,color:#fff8e1

    A["dry site selected<br/>one per night"] --> B["worktree off HEAD"]
    B --> C["agent edits the scraper<br/>round 1 of max 3"]
    C --> D{"diff touches only<br/>that one scraper?"}:::gate
    D -->|no| X["discarded unread"]
    D -->|yes| V["run.py --site X --scrape-only"]
    V --> F{"distinct URLs >= max of<br/>3 and a quarter of the<br/>site's best night?"}:::gate
    F -->|no| G{"rounds left?"}
    G -->|yes| C
    G -->|no| X2["attempt spent<br/>2 per site, then stop"]
    F -->|yes| T{"suite still green<br/>vs a baseline taken<br/>BEFORE the agent ran?"}:::gate
    T -->|no| X
    T -->|yes| BR["branch, and a message<br/>saying how many rounds built it"]
    BR --> H["YOU read the diff"]:::human
```

The round count is on the branch message deliberately: the worktree is not reset
between rounds, so a branch built in two rounds can carry round one's wrong edit
beside round two's fix, and nothing rejects a leftover that merely looks
harmless. No production branch has been built in two rounds yet. The first one
is worth reading closely.
