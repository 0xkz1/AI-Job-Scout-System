---
title: JIS Strategic Expansion — assessment and proposal
type: proposal
created: 2026-08-29
status: P0 + P1 (6–9) implemented 2026-08-29 · items 10–14 measured and rejected · build complete
related: "[[career/career-strategy-2026-2027]]"
tags: [jis, architecture, proposal]
---

# JIS Strategic Expansion — Assessment & Proposal

Response to the Strategic Expansion Brief of 2026-08-29. Every number below is measured against the live corpus (`10_output/_analyzed.json`,
5202 postings) or read out of the code, and the measurement is named so it can be re-run.

The headline: **the brief's premise is roughly one release out of date.** Four of its
eighteen asks are already built, two are built and mis-tuned, and the two largest genuine
gaps (the YMS clock, and remote geography as a normalized field) are not in the brief's top
three. The keyword expansion it leads with is the one change the evidence argues against.

> **Status, 2026-08-29.** Sections A–I are the assessment as first written. **P0 (§H 1–5) and
> P1 items 6–9 are implemented and green** — see §K and §L. **Item 10 (Level Fit) was
> measured and rejected**, §L4. **All four P2 items were measured and dropped**, §M — the
> build is complete, and the remaining recommendation is a subtraction, not an addition.
>
> One P0 item was **withdrawn during implementation**: dropping `sponsorship: refused`
> postings before enrichment. It was wrong. A YMS holder has the right to work in the UK
> until 2027-10-09, so a posting that will not sponsor is still a job that can be taken
> today; the filter would have deleted 140 applicable postings to save LLM spend. The flag
> is recorded and never filters. §C5, §G, §H and §I below are corrected accordingly.

---

## A. Current-system assessment

### Pipeline

```
scrape (6 sites) → 00_saved/ staging → analyze (cheap pass) → filter → analyze (LLM top-up)
  → match (5 axes) → selection.select_top() → CV + cover letter → review → Obsidian
```

`run.py` orchestrates. `selection.py` is the single place any stage asks "which jobs?" —
`generation_top_percent: 30`, `review_top_percent: 40`, floor `match_score_threshold: 0.32`,
plus a `stretch_top_count: 15` tier for level-rejects. `config.yaml` is the control surface
and carries a measured justification for essentially every number in it.

### Normalized schema, as it stands

`job.analysis` — `experience_level`, `required_years`, `required_years_is_ceiling`,
`employment_types[]`, `work_style`, `salary{min,max,period}`, `skills[]`, `skill_coverage`.

`job.match` — `composite_score`, `tier`, `skills{}`, `experience{}`, `location{}`,
`salary{}`, `context_score` + seven `context_*` provenance fields, `title_relevance`,
`weights`, `role_affinity{}`, `detected_role`.

### Scoring, as it stands

Five axes, weights `skills .45 / context .40 / location .10 / experience .05 / salary .00`,
multiplied by `title_relevance` (a 0.0/0.1/1.0 gate), then tiered. `context` is the LLM read
of "could this candidate do the work"; `ethos` ("would they want it") is recorded beside it
rather than blended, because every blend predicted the review outcome worse.

### Cost model

Searches are the rationed resource. 42 of a hard 44 `(keyword, location)` pairs are in use
(`invariants.check_scrape_fits_its_timeout`); reed runs ~34s per search at depth 3 against a
1500s per-site cron timeout. **Two pairs of headroom exist.** Downstream, each surviving job
costs 2–5 LLM calls.

### Documentation drift found on the way

`career/AGENTS.md` §4 states "4軸スコアリング — skills 45% / experience 20% / location 20% /
salary 15%". There are five axes and the weights are `.45/.05/.10/.00/.40`. Fix this before
any agent reads it as spec.

---

## B. What the brief asks for that already exists

| Brief item | Status | Evidence |
|---|---|---|
| §3 Broaden beyond Graphic Designer | **Already done** | "Graphic Designer" is *not* a search keyword. 233 graphic-design-titled postings are in the DB anyway, 201 passed the filter, median composite 0.57, 88 at ≥0.60 — they arrive as by-catch of the keyword `Designer`, because `filter_jobs_by_keywords` keeps a job when a term appears in title **or** description |
| §5 Europe | **Already done** | `remote_target_countries` (DE/NL/LU/FR/SE/NO/FI/CH/AT/ES), `adzuna_countries: [gb, de, nl, fr, at, es]`, and `matcher._classify_international_location` scoring target-country remote 0.85, EU/EMEA 0.80, worldwide 0.72, on-site abroad 0.20 |
| §6 Remote as a first-class category | **~70% done** | Work style is classified (remote/hybrid/onsite/unknown, English **and** Japanese patterns) and remote is *scored* by geography — UK / target country / EU-EMEA / worldwide / Americas / Japan are all distinct verdicts. `exclude_timezone_keywords` hard-drops Americas-locked postings before scoring |
| §7 Employment-type expansion | **Already done** | `employment_types: [full_time, part_time, contract, freelance]`. The corpus holds 889 contract and 211 freelance postings and none are filtered on type. FTC/fixed-term/temporary all map to `contract` |
| §12 Portfolio-aware matching | **Already done** | `cv_generator` sends the full project registry to the LLM per job and gets back a ranked 3–5 project selection; `role_affinity` and `detected_role` are stored on every job |
| §17 Persistent professional identity | **Already true** | Nothing in the pipeline reads current employment. Identity comes from `cv/profile/*.md`, `skills.md`, `letter_facts_v1.md` |

Four of these need **no work at all**. Acting on §3 and §7 as written would spend the two
remaining search pairs and add config for behaviour that already ships.

---

## C. Strategic gaps — the real ones, ranked

### C1. The YMS clock does not exist anywhere in the system

No date, no time-remaining, no notion that a 12-month contract starting 2027-04 ends after
the visa does. This is the single largest true gap and the cheapest to close: one config
date, one derived integer, zero LLM calls.

### C2. `director` in `exclude_title_keywords` deletes junior jobs

Measured — all four Art Director postings in the corpus are filtered:

```
title contains excluded keyword 'director' | Junior Art Director
title contains excluded keyword 'director' | Marketing Designer / Art Director (1 year FTC)
title contains excluded keyword 'senior'   | Senior Art Director - Web
title contains excluded keyword 'senior'   | Senior Art Director (Move to Dubai)
```

The first two are exactly the postings the brief asks for. 17 design-adjacent titles are
lost to `director` in total. The word is a seniority marker *and* half of a junior job title;
the exclusion list has no way to say that.

### C3. Remote geography is inferred from the location string, never extracted

`work_style: remote` is a boolean-ish label; the *scope* is guessed from whatever the board
wrote in the location field. Of 1341 remote postings:

```
103  london            66  united kingdom      64  remote
 58  uk                55  edinburgh, ...      50  españa
 31  remote - anywhere in the world            26  deutschland
 26  tokyo, tokyo, japan                       23  (empty)
```

There is no `remote_scope` field, so "Remote — UK only" and "Remote — Europe" are
indistinguishable downstream, and 23 postings state nothing at all. Direct extraction from
the description barely helps *by itself* — `remote (within|in|across) (the )?(eu|europe)`
matches 2 postings and the UK-restricted phrasings match 16 — so this must be a **derived
field with a declared confidence**, not a regex hunting for a phrase most postings never write.

### C4. Contract duration is extracted nowhere

203 postings (3.9%) state a duration in a matchable form (`\b(3|6|9|12|18|24)[\s-]*months?\b`
near contract/FTC/fixed-term). Nothing reads it. As the clock runs down this is the field
that decides whether a contract is useful or a trap.

### C5. Immigration evidence — thin, and a *score* would be fabrication

Measured across all 5202 postings:

| Signal | Postings | Share |
|---|---|---|
| mentions "sponsor" at all | 207 | 4.0% |
| sponsorship offered (explicit) | 86 | 1.7% |
| sponsorship refused (explicit) | 83 | 1.6% |
| "right to work" | 156 | 3.0% |
| "must already have" authorisation | 61 | 1.2% |
| relocation support | 37 | 0.7% |
| start date stated | 87 | 1.7% |

**96% of postings say nothing.** An "Immigration / Mobility Compatibility Score" over that
base would be a number computed from absence — and the brief itself forbids assuming
eligibility from salary or from a company being a licensed sponsor. So: extract a **three-state
flag with the verbatim quote as evidence**, and refuse to produce a score.

The table above counts loose phrase matches and **overstates both directions**. Measured again
after the extractor was built to be precise (§K): 140 refusals, 1 offer. Most of the 86
apparent "offers" were refusals containing the words *offer* and *sponsorship* inside the
negation — "we are unable to **offer sponsorship**" — and two were employer facts that say
nothing about this job ("whilst the University is a licensed sponsor, not all roles qualify";
"this vacancy does not meet the minimum salary threshold for Skilled Worker").

**The refusal flag must not filter anything.** A YMS holder can take a job that refuses
sponsorship — the right to work runs to 2027-10-09 regardless. The flag separates a role that
can outlive the visa from one that cannot, which is a ranking input, not an eligibility test.

### C6. Nothing represents trajectory

The composite answers "can I get this job." No field answers "does this move me toward
£43–45k" or "does the work produce portfolio evidence." The brief is right that this is
missing. It is wrong about the shape of the fix — see §E.

### C7. The level gate is binary, and `required_years` is deliberately dead

`analyzer.required_years` is extracted and stored, and `classify_experience_level` documents
at length why it is *not* consulted: wiring it in reclassifies 85 postings, 39 mid→senior, and
45 of them stop passing the filter — including "Creative Technologist (12 Month FTC)", already
applied to. The intended replacement is a **Level Fit** dimension (match / stretch / reach)
rather than a binary `include_levels`. The `stretch_top_count: 15` tier is the current stopgap.

### C8. Internship is allowed by level and rejected by type

`include_levels` contains `internship`; `employment_types` does not. 39 postings are rejected
with `employment type ['internship'] not in allowed [...]`. One of the two lists is wrong.

---

## D. Proposed taxonomy — and the case against most of it

### D1. Measured coverage of the brief's proposed titles

Occurrences in 5202 scraped titles:

| Present and productive | n | Absent from the market |
|---|---|---|
| design engineer 300, web developer 233, graphic designer 228, ux designer 137, digital designer 128, ui designer 77, web designer 60, ux/ui 56, technical artist 48, brand designer 32, visual designer 31, technical designer 25, experience designer 21, creative technologist 20, junior graphic 20, motion designer 17 | | communication designer **0**, visual communication **0**, creative engineer **0**, creative coder **0**, creative coding **0**, interactive designer **0**, generative designer **0**, generative artist **0**, front-end designer **0**, prototyping engineer **0** |

Ten of the brief's titles do not appear once in 5202 UK/EU postings. They are portfolio
vocabulary, not hiring vocabulary. Spending search pairs on them buys searches against words
employers do not write.

### D2. The distinction the brief conflates

**What to search** and **how to label** are different problems with different budgets.

- Searching is capped at 44 pairs, 42 used. A new keyword costs ~34s of a 1500s window and
  competes with an existing one.
- Labelling is free. It runs post-scrape over text already in hand.

The brief's taxonomy is a *labelling* taxonomy. Implement it there and it costs nothing.

### D3. Recommended: a role-family map, not new keywords

`cv_generator.ROLE_KEYWORDS` already holds 17 families with title×10 / body×1 weighting and
corroboration guards (`MIN_BODY_KEYWORDS`, `MIN_BODY_MARGIN`) built from real misroutes. Add
a thin layer *above* it in config:

```yaml
role_families:
  core_design:        [graphic_designer, product_designer]
  creative_technology:[creative_technologist, technical_artist]
  hybrid_design_dev:  [product_designer, web_developer]
  bridge:             [implementation_specialist, technical_support, qa_engineer,
                       product_ops, research_engineer, content_analyst]
ladder:
  core_design:         {step: 1, toward: creative_technology}
  hybrid_design_dev:   {step: 2, toward: creative_technology}
  creative_technology: {step: 3, toward: null}
```

Aliases and synonyms belong in `ROLE_KEYWORDS` where they already are — adding a parallel
alias table would give the router two sources of truth.

### D4. Search keywords: change nothing yet, then measure one swap

Two pairs of headroom exist. Do not spend them on a guess. If one is spent, the candidate
with evidence behind it is **"Graphic Designer"** — 228 titles arriving as by-catch says the
density is real. But run it as a one-off depth-1 probe first (the pattern used for the Japan
searches on 2026-08-19), compare yield against the weakest current pair, and only then make
it permanent. Bare single words stay banned: `filter_jobs_by_keywords` would match nearly
every posting and silently disable the relevance filter for the whole run.

---

## E. Proposed schema changes

Small, normalized, deterministic. Every one of these is regex-and-rules over text already
scraped — **zero new LLM calls**.

### Added to `job.analysis`

| Field | Type | Source |
|---|---|---|
| `remote_scope` | `onsite \| hybrid \| remote_uk \| remote_country \| remote_eu \| remote_emea \| remote_worldwide \| remote_unscoped` | location text + country code + description phrases |
| `remote_scope_confidence` | `stated \| inferred \| unknown` | `stated` only when the description says it |
| `contract_kind` | `permanent \| ftc \| freelance \| temp \| unknown` | refines `employment_types` |
| `contract_months` | `int \| null` | the 203-posting pattern in §C4 |
| `sponsorship` | `offered \| refused \| silent` | explicit phrases only, never inferred |
| `sponsorship_evidence` | `str \| null` | verbatim quote, so a claim can be checked |
| `start_date_text` | `str \| null` | not parsed to a date — postings lie about this |
| `relocation_support` | `bool \| null` | explicit phrases only |

### Added to `job.match`

| Field | Type | Source |
|---|---|---|
| `role_family` | enum from §D3 | `detected_role` → family map |
| `ladder_step` | `1 \| 2 \| 3 \| null` | family → ladder |
| `runway_fit` | `fits \| ends_after_expiry \| unknown` | `contract_months` vs YMS expiry |
| `action_tier` | `1..5` | rule table, §F |

### Explicitly **not** added

- An Immigration/Mobility Compatibility **Score** — see §C5. Flag and evidence only.
- Eight new scoring dimensions (brief §10 A–H). See §F for why.
- A parallel keyword/alias table. `ROLE_KEYWORDS` is the router.

---

## F. Proposed scoring model

### The evidence against adding dimensions

`config.yaml` records three separate attempts to improve the composite by re-weighting, and
all three lost:

> "The refit LOST on all five seeds (-0.003 to -0.028) ... Capping context by skills lost at
> every margin too. Both failed for the same reason — every dimension is a weak predictor, so
> no linear recombination of them has anywhere to go."

> "What did work was fixing the input rather than the arithmetic."

Adding eight weak dimensions (Current Fit, Skill Development, Salary Trajectory, Portfolio
Value, Creative Tech Relevance, Mobility, Sponsorship, Optionality) to five weak ones produces
thirteen weak ones and an opaque number. Several would also have to be *invented* by an LLM
per job — recurring cost, no ground truth to validate against, and the review score is already
the only human-checked signal here.

### Recommendation: one composite, one orthogonal number, one rule table

**1. Composite — unchanged.** It answers "can I realistically get this job now." It is
fitted, measured, and it works as well as anything measured against it.

**2. `strategic_value` — a new, separate 0–1 number, computed deterministically.** Never
blended into the composite; shown as a second column. Fully interpretable because it is a sum
of named, testable parts:

```
strategic_value =
    0.30 · ladder_gain      # role_family vs current step: 0 lateral, 1 toward creative tech
  + 0.25 · salary_gain      # salary.max vs the £43–45k target band, clipped
  + 0.25 · runway_fit       # contract_months against months-to-expiry
  + 0.20 · mobility         # remote_scope survives leaving the UK: worldwide/EU 1, UK 0.3, onsite 0
```

Every term reads a normalized field from §E. No LLM. Each independently unit-testable, which
is the property the brief asked for and the composite does not have.

**3. `action_tier` — the brief's §13, as a rule table, not a fitted score.**

| Tier | Rule | Meaning |
|---|---|---|
| 1 | `composite ≥ 0.60` and `review_score ≥ 75` and `strategic_value ≥ 0.5` | Apply immediately |
| 2 | `composite ≥ 0.50` and `review_score ≥ 60` | Apply |
| 3 | `composite < 0.50` and `strategic_value ≥ 0.7` | Opportunistic — weak fit, strong trajectory |
| 4 | `strategic_value ≥ 0.6` and `filter_status = level` | Monitor — the stretch tier's proper home |
| 5 | otherwise | Ignore |

`review_score` is the trusted signal and is already computed for the top 40%. Tiers 1–2 lean
on it; tiers 3–5 must work without it, because a job outside the review set has none.

### On `title_relevance` and the level gate

Two soft-gate changes are worth measuring, both currently hard:

- `title_relevance` returns 0.1 for an unrecognised title and zeroes the composite. It already
  has an LLM-rescue path (`context_source == "llm" and context_score ≥ 0.6 → 1.0`). The
  target-word whitelist should gain the *labelling* taxonomy's vocabulary — free, and it fixes
  titles the whitelist cannot currently name.
- The `director` / `senior` exclusions should become **phrase-aware**, not word-aware:
  `junior art director` and `art director` are not senior; `senior art director` is.

---

## G. Proposed pipeline changes, stage by stage

| Stage | Change | Cost |
|---|---|---|
| **Scrape** | None. Budget is full at 42/44 pairs. A probe run for one candidate keyword, measured before it becomes permanent | 0 |
| **Dedup** | None. `run.dedupe_by_company_title` + `selection._dedupe` are correct as documented, and `(company, title)` is already known not to be a unique key — the URL/jk join stays | 0 |
| **Analyze** | Add the eight §E fields. All regex/rules, computed in the *cheap* pass so filtering can read them before LLM spend | 0 LLM calls |
| **Filter** | (a) phrase-aware title exclusions; (b) reconcile the internship inconsistency. **No sponsorship filtering** — see §C5 | 0 |
| **Match** | Compute `role_family`, `ladder_step`, `runway_fit`, `strategic_value`, `action_tier`. Composite untouched | 0 LLM calls |
| **Selection** | Add one stage key so a small `opportunistic_top_count` can pull tier-3 jobs into generation the way `stretch_top_count` does for level-rejects | small |
| **Generation** | None to the generator. `letter_facts_v1.md` and the CV profiles are the identity and must not vary by job | 0 |
| **Reporting** | Frontmatter gains `remote_scope`, `contract_months`, `sponsorship`, `strategic_value`, `action_tier`, `role_family` — all Dataview-sliceable, which is where the UK-vs-Europe-vs-Remote separation the brief asks for actually belongs | 0 |
| **Invariants** | One new check: every `sponsorship: offered/refused` carries a non-empty `sponsorship_evidence` quote. Enforces "surface evidence, never conclude" in code | 0 |

The UK / Europe / Remote separation (brief §14) is a **view**, not a pipeline split. One
corpus, one schema, sliced by `remote_scope` + country. Splitting the pipeline would double
the scrape budget for no new postings.

---

## H. Priority roadmap

### P0 — essential, cheap, unambiguous

1. **YMS expiry in config** — `yms_expiry: 2027-10-09`, plus a derived `months_remaining`. Every
   time-aware feature depends on it and nothing else does.
2. **Phrase-aware title exclusions** — recovers "Junior Art Director" and "Marketing Designer /
   Art Director (1 year FTC)". 17 design-adjacent titles currently lost to `director` alone.
3. **`contract_kind` + `contract_months`** — 203 postings have the data; nothing reads it.
4. **`sponsorship` flag + verbatim evidence** — recorded only, never filtered.
5. **Fix the internship contradiction** (39 postings) and **fix `career/AGENTS.md` §4** (wrong
   axis count, wrong weights).

### P1 — high value, needs a design decision

6. **`remote_scope` + confidence** — the largest schema gap. Derived, with `stated` reserved for
   postings that actually say it.
7. **`role_family` / `ladder_step`** taxonomy layer over `ROLE_KEYWORDS`.
8. **`strategic_value`** — deterministic, four named terms, separate column.
9. **`action_tier`** rule table replacing ad-hoc reading of composite + review.
10. **Level Fit** as a soft dimension using the already-extracted `required_years`, retiring the
    binary `include_levels`. Note the documented cost: 45 postings change side. Measure first.

### P2 — optional / later

11. Keyword probe for "Graphic Designer", measured against the weakest current pair.
12. Portfolio recommendation surfaced as structured fields (primary/secondary project, missing
    evidence) rather than only inside generated prose.
13. Germany-specific config block (employment / freelance / artist paths as *evidence
    categories*, not eligibility conclusions).
14. A `casual_work_mode` flag that lowers nightly volume without stopping the pipeline.

### P3 — explicitly rejected

- An Immigration/Mobility Compatibility **Score** (§C5).
- Eight new scoring dimensions blended into one number (§F).
- Adding the ten zero-occurrence titles as search keywords (§D1).
- A separate European pipeline (§G).

---

## I. Risks

| Risk | Assessment |
|---|---|
| **Recall bought with precision** | The brief's central worry. Largely already handled: broad search terms are paired with `title_relevance`, `filter_jobs_by_keywords`, and a filter-before-LLM ordering that keeps a wider net from becoming a wider bill |
| **Scrape budget** | 42/44 pairs. Any new keyword is a swap, not an addition. `check_scrape_fits_its_timeout` fails the run if this is ignored — trust the invariant over any estimate |
| **LLM cost** | The proposal adds none — every new field is regex over text already scraped, computed in the cheap pass. Anything that would add per-job LLM cost was deliberately designed out |
| **Immigration misinformation** | The real hazard. Mitigations: three-state flag not a score; verbatim evidence required by invariant; no inference from salary or sponsor-licence status; no legal conclusion anywhere in the system |
| **False confidence in `remote_scope`** | Only 18 postings state a geographic restriction in matchable prose. This is why the field carries `stated \| inferred \| unknown` and why nothing gates on `inferred` |
| **Complexity** | Eight `analysis` fields and four `match` fields, all deterministic and unit-testable. That is the whole surface. The brief's own §19 is the right constraint and it is what ruled out most of §10 |
| **Losing what works** | `letter_facts_v1.md`, the CV profile routing, the review rubric, and the composite are untouched. Nothing here changes what a document says |

---

## J. Recommended implementation sequence

Each step is independently landable, testable, and reversible. No step depends on a later one.

| # | Step | Test |
|---|---|---|
| 1 | `yms_expiry` + `months_remaining` in config, exposed via `selection` | unit: date arithmetic; invariant: date is in the future |
| 2 | Phrase-aware title exclusions | corpus sweep: the 4 Art Director postings land on the right side; no currently-passing posting starts failing |
| 3 | `contract_kind` + `contract_months` in `analyze_job` | fixture postings for 3/6/12-month FTC wording; corpus count matches the 203 measured |
| 4 | `sponsorship` + evidence, recorded only | corpus sweep; new invariant on evidence presence |
| 5 | Internship contradiction + `career/AGENTS.md` correction | existing filter tests |
| 6 | `remote_scope` + confidence | corpus sweep over the 1341 remote postings; no posting reaches `stated` without a quote |
| 7 | `role_families` + `ladder` config, `role_family` on match | routing tests extended; no existing route changes |
| 8 | `strategic_value`, four terms, each tested alone | unit per term; corpus distribution sanity |
| 9 | `action_tier` rule table + frontmatter | regenerate reports; check tier 1 is small and tier 5 is most of the corpus |
| 10 | Level Fit (soft) — **measure before landing** | replay the documented 85-posting reclassification; confirm "Creative Technologist (12 Month FTC)" still passes |

Steps 1–5 are P0 and touch no scoring. Steps 6–9 add the strategy layer. Step 10 is the one
with a known price and should not be bundled with anything else.

---

## K. What shipped — P0, 2026-08-29

All five P0 items are implemented and the full suite is green (**1008 passed**). No LLM call
was added anywhere; every new field is regex over text already scraped, computed in
`analyze_job`'s cheap pass so the filter can read it before any model spend.

### K1. Files changed

| File | Change |
|---|---|
| `config.yaml` | `yms_expiry: 2027-10-09`; `exclude_title_exceptions`; `employment_types` gains `internship` |
| `analyzer.py` | `contract_duration_months`, `classify_contract_kind`, `classify_sponsorship`, `_sentence_around`; four new keys on `analysis` |
| `filter.py` | `_exception_spans` / `_within_any`; title exclusions are span-aware |
| `selection.py` | `yms_expiry()`, `months_until_expiry()` |
| `matcher.py` | `_runway_fit`; `runway_fit` on every match |
| `invariants.py` | `check_sponsorship_claims_carry_evidence` (17th check) |
| `backfill_contract_and_sponsorship.py` | new — writes only the four new keys onto the existing DB |
| `career/AGENTS.md` | §4 corrected (was "4軸 45/20/20/15"); new §4.5 on the visa clock |
| `tests/` | `test_title_exclusion_exceptions.py` (16), `test_contract_shape.py` (32), `test_sponsorship_evidence.py` (18) |

### K2. What the corpus looks like now

Backfilled across 5133 postings (15 have no `analysis` block and were left alone):

```
contract_kind    unknown 4087   permanent 628   freelance 212   ftc 193   temp 13
contract_months  stated 244     unstated 4889
sponsorship      silent 4992    refused 140     offered 1
```

`unknown` dominating `contract_kind` is correct, not a gap: UK postings use the bare word
"contract" for both a fixed-term employee and a day-rate contractor, and guessing which would
be inventing a fact. `employment_types` already records that the word appeared.

### K3. Four things the measurement changed

Each was a plausible-looking pattern that fired mostly on unrelated prose. All four are now
pinned by a negative test.

| Removed | Fired on |
|---|---|
| `contractor` → freelance | "engineering **contractor**" (a company), "Maintenance **Contractor**" (a persona in a UX brief), "**contractor** design elements" (a scope of works) |
| `seasonal` → temp | "**seasonal** campaigns", "**seasonal** direction" — marketing copy, in every sampled hit |
| bare `temporary` → temp | "supply of **temporary** workers" (recruiter boilerplate in every posting from some agencies), "**temporary** works design" (a civil-engineering discipline) |
| `licensed sponsor` → offered | "whilst the University is a **licensed sponsor**, under UKVI not all roles qualify" — a refusal |

A fifth was a plain bug with a real consequence: postings arrive from Word with curly
apostrophes, so `can't` and `can’t` are different strings to a regex, and **"we can’t offer
visa sponsorship" was being read as an offer**. Text is punctuation-folded before matching,
refusal is tested first, and an offer match is dropped when the run-up to it negates.

### K4. The title exceptions, measured

`exclude_title_exceptions` is span-based, not a title allowlist, so a hit lying inside the
phrase is exempt and a hit anywhere else still fires:

```
PASS  Junior Art Director                              PASS  Art Director
PASS  Marketing Designer / Art Director (1 year FTC)   PASS  Lead Generation Specialist
DROP  Senior Art Director - Web        (senior)        DROP  Creative Director   (director)
DROP  Associate Creative Director, Design (director)   DROP  Lead UX Designer    (lead)
```

Both entries were chosen by sweeping the corpus, not guessed: `director` blocks 17
design-adjacent titles of which exactly two are the mid-level craft title, and `lead` blocks
148 of which exactly one ("Lead Generation Specialist") is not a lead role. A test fails if an
entry ever stops rescuing something, and a second test sweeps every corpus title to assert
nothing is admitted without matching an exception phrase.

### K5. Note on the database

The backfill wrote only the four new keys and backed the DB up first
(`10_output/_analyzed.bak_20260829_100651.json`). Row count moved 5202 → 5148 during the
session for an unrelated reason: a concurrent `dropped_sources` purge at 09:46 removed
remoteok (15) and weworkremotely (39), which is the documented behaviour of that mechanism.

### K6. Still open

`invariants.py --warn` reports 5 violations, all pre-existing and none from this work: 285
truncated-description postings inside the top 40%, 9 title-excluded jobs inside a selection
(stored composites predate `title_relevance`), 15 unscoreable reviews holding a score, and 2
shared document paths. Each has a named remedy script in the violation text.

P1 (§H 6–10) is unbuilt. The highest-value next step is `remote_scope`, and it needs the
design decision flagged in §C3: it must be a derived field with a declared confidence, because
only 18 postings state a geographic restriction in matchable prose.

---

## L. What shipped — P1 items 6–9, 2026-08-29

Suite **1048 passed** (40 new). No LLM call added; every value is arithmetic over fields the
cheap pass already produced. Backfilled across all 5148 postings with the DB backed up first
(`_analyzed.bak_20260829_110625.json`).

### L1. Shape

New module **`strategy.py`** rather than more weight in `matcher.py` (152KB already). It takes
primitives and config, calls nothing, and every function is testable alone.

| Field | Where | Values |
|---|---|---|
| `remote_scope` | `match` | onsite · hybrid · remote_uk · remote_country · remote_eu · remote_worldwide · remote_americas · remote_unscoped · unknown |
| `remote_scope_confidence` | `match` | stated · inferred · unknown |
| `role_family` / `ladder_step` | `match` | core_design 1 · hybrid_design_dev 2 · creative_technology 3 · bridge — · other — |
| `strategic_value` / `strategic_terms` / `strategic_coverage` | `match` | 0–1, four named terms, and how much of the weight had data |
| `action_tier` | `match` | 1 apply now · 2 apply · 3 opportunistic · 4 monitor · 5 ignore |

`remote_scope` lives on `match`, not `analysis` as §E proposed. It needs the Adzuna country
code, which only `matcher._infer_country` derives; duplicating the country/region alias tables
into `analyzer.py` would guarantee they drift apart.

### L2. The corpus, after backfill

```
action_tier      1: 141    2: 524    3: 423    4: 279    5: 3781
role_family      hybrid_design_dev 1507  other 1455  bridge 1293  core_design 716  creative_technology 177
remote_scope     onsite 1506  hybrid 1290  unknown 1033  remote_uk 803  remote_country 263
                 remote_unscoped 192  remote_worldwide 41  remote_eu 14  remote_americas 6
runway_fit       unknown 4904  fits 223  ends_after_expiry 21
strategic_value  median 0.44  p90 0.84
```

Only **51 postings** carry `remote_scope_confidence: stated`. Everything else is `inferred`,
and nothing gates on `inferred` — that is the whole reason the confidence field exists.

### L3. The renormalisation trap, found by measuring

A term with no data drops and the rest renormalise — the idiom the composite already uses for
an unscored context. It does not survive contact with four terms where three can be missing:
**"Product Design Engineer — AI-Native Product" scored `strategic_value: 1.00` off `ladder`
alone**, no salary, no length, no work style, and read as the strongest posting in the corpus.

Fix: `strategic_coverage` records the share of weight that had data, and `action_tier` treats
the value as unmeasured below `coverage_min: 0.50` — so the role family *and* how far the
arrangement travels both have to be known before a tier moves. That reclassified ~90 postings
out of acting tiers (tier 1 162 → 141). Both halves are pinned by tests and by a new invariant,
`check_action_tier_respects_its_gates`.

A separate gap surfaced the same way: `remote_americas` had no mobility weight, so a US-remote
posting had its mobility term *drop* — scored as though its work style were unknown rather
than known and unwanted. Caught by a test asserting every scope has a weight.

### L4. Item 10 (Level Fit) — measured, and **rejected**

`analyzer.required_years` has been extracted-but-unused since it was written, with a comment
explaining that wiring it into the level gate costs more than it returns. Re-measured today on
the current corpus, the cost has grown:

- **847** postings state years. Wiring them in **reclassifies 237**, of which 82 go mid→senior.
- **90** stop passing `include_levels`; **72** of those are currently passing the filter.
- **30** of those 72 hold a CV review. The casualties include **three that reviewed at 93** —
  "Creative Technologist (12 Month FTC)" (composite 0.81, already applied to), "Corporate
  Solutions Engineer, UK", "Ralph Lauren UI Visual Designer" — plus "Designer — Bids and
  Branding" at composite 0.88.

That is the case against the *binary* wiring, and it was already known. The new measurement is
against the **soft** replacement, which was the reason to keep the field at all. Over the 278
reviewed postings that state years:

```
required_years    n    mean review   >=75
0-1              31        68.8       35%
2                68        65.8       28%
3               118        66.5       32%
4-5              58        64.6       26%
6+                3        67.3        0%
not stated      867        65.8       29%

correlation(required_years, review_score)  r = -0.068   n=278
```

**Flat.** A posting asking for five years reviews the same as one asking for one, and both
review the same as the 867 that ask for nothing. r = -0.068 is noise.

So a Level Fit dimension built on `required_years` would predict the trusted signal no better
than chance, while costing 72 currently-passing postings. It is moved from P1 to **P3 —
rejected**, on the same grounds as the re-weighting attempts recorded in `config.yaml`: the
arithmetic was never the problem.

Two honest caveats. The review score exists only for postings that got documents, so this is a
restricted range — but it is the same population the composite weights were fitted on, and it
is the population any level gate would act on. And this rejects *this* use of `required_years`,
not the field: it stays recorded as evidence, and it is what made this measurement possible.

Corroborating, from the same run: `experience_level` itself barely separates the review score
(entry_level 68.5, mid 64.4, unknown 69.1 over 1145 reviewed postings), which is why the
composite already holds `experience` at 0.05.

### L5. What a human now sees

Match report frontmatter gains 11 Dataview-sliceable fields (`action_tier`, `strategic_value`,
`strategic_coverage`, `role_family`, `ladder_step`, `remote_scope`,
`remote_scope_confidence`, `runway_fit`, `contract_kind`, `contract_months`, `sponsorship`),
so "every tier-2 job whose contract finishes inside the visa and that is remote outside the
UK" is one query.

The sponsorship quote goes in the **body** as a callout, never the frontmatter — it is a
sentence, and it is the entire justification for the flag. The callout says in both languages
that it is evidence rather than an eligibility verdict, and that a YMS holder can take a role
that refuses sponsorship.

### L6. Still open

P2 (§H 11–14) untouched. The tier thresholds in `config.yaml: action_tiers` are a starting
rule table, not a measurement — there is no ground truth for "should I have applied".
`record_outcome.py` is accumulating the outcomes that could eventually calibrate them; until
then a tier is a reading aid, not a verdict.

---

## M. P2 — measured, and none of it built

The instruction that shaped this section: *a system that misses some irregular cases but
stays simple may beat one that handles everything and breaks in strange ways.* Applied
honestly, that argues against all four P2 items, and against some of what P0/P1 shipped.

### M1. Two kinds of number, and only one belongs in config

`config.yaml` is the right home for **facts that change** and **data that grows by
observation** — the visa date, the salary band, the family map, the title exceptions. It is
the wrong home for a **knob with no measurement behind it**: exposing one advertises a
tunability that does not exist, and every knob is another way to be quietly wrong.

Removed from `config.yaml` and moved into `strategy.py` as documented constants:
`strategic_weights` (4 numbers) and `action_tiers` (5, including `coverage_min`). **32 lines
of config gone**, one function parameter gone, and roughly ten `float(cfg.get(...))`
defensive reads gone with them. Tier counts are byte-identical before and after — these were
never tuned, only tunable.

What stayed in config, and why it earns the place:

| Key | Why it is a fact, not a knob |
|---|---|
| `yms_expiry` | A date on a visa. It will change. |
| `exclude_title_exceptions` | Grows by observation; a test fails if an entry stops matching |
| `role_families` / `ladder` / `candidate_ladder_step` | A taxonomy and a position on it, both of which move |
| `salary_target_band` | A career target |

The measured guards added in P0 — `_NOT_A_DURATION`, the dropped `contractor` / `seasonal`
patterns, the punctuation fold — are **not** in this category and were kept. Removing a guard
that a measurement put there is not simplification; it is reintroducing a known bug. The
distinction that matters is *unmeasured knob* versus *measured guard*, not "less code".

### M2. Item 11 (a "Graphic Designer" keyword) — settled without a probe

The plan was a live depth-1 probe. The corpus answers it for free. Per keyword, over 5148
postings, counting only what reaches a CV review — the trusted signal:

| keyword | titles | pass | reviewed | mean review | ≥75 | pairs |
|---|---|---|---|---|---|---|
| Web Designer | 58 | 52 | 30 | **81.8** | 22 | 3 |
| Creative Technologist | 20 | 15 | 13 | **79.0** | 7 | 5 |
| Web Developer | 227 | 183 | 46 | 70.6 | 22 | 4 |
| Digital Designer | 127 | 98 | 54 | 70.3 | 15 | 5 |
| Designer | 1845 | 1301 | 611 | 67.7 | 194 | 3 |
| Technical Artist | 48 | 22 | 6 | 66.7 | 1 | 4 |
| Research Software Engineer | 16 | 10 | 5 | 66.4 | 2 | 3 |
| Solutions Engineer | 299 | 181 | 42 | 63.4 | 4 | 3 |
| Technical Support | 356 | 326 | 25 | 61.6 | 6 | 3 |
| Digital Producer | 18 | 14 | 1 | 72.0 | **0** | 3 |
| QA Analyst | 30 | 24 | 3 | 53.3 | **0** | 3 |
| Implementation Consultant | 150 | 128 | 8 | **48.4** | **0** | 3 |
| **(Graphic Designer — never searched)** | **225** | **193** | **125** | 67.9 | **33** | **0** |

Graphic Designer produces **33 submission-ready documents, more than any searched keyword**,
on **zero** pairs of a 42-of-44 budget. It arrives as by-catch of `Designer`. Adding it as a
keyword would spend budget to collect what is already arriving. **Not added, no probe needed.**

### M3. The finding that matters is a subtraction

Three keywords have produced **zero** documents scoring ≥75 across the entire corpus, for
**9 of the 42 pairs**:

- **Implementation Consultant** — 128 postings past the filter, 8 reviewed, mean **48.4**, best 72
- **QA Analyst** — 24 past the filter, 3 reviewed, mean 53.3, best 58
- **Digital Producer** — 14 past the filter, 1 reviewed

Dropping all three takes the budget from 42 to **33 pairs**, shortens the nightly, and costs
nothing measurable. It also reverses part of a deliberate decision (the six bridge terms added
2026-08-07 as a parallel track), so it is **recorded as a recommendation and not executed** —
the measurement is mine to make, the strategy is not. The other three bridge terms stay
regardless: Solutions Engineer, Technical Support and Research Software Engineer have each
produced documents at 75+.

### M4. Items 12, 13, 14 — dropped

**12 · Portfolio recommendation as structured fields.** `cv_generator` ranks the project
registry per job and writes the result straight into the CV. Storing the ranking as fields
would duplicate a value that is already visible in the document it exists to produce, and no
decision downstream would read it. Dropped for want of a consumer.

**13 · A Germany-specific config block.** Measured: 176 German postings, 91 remote (the only
reachable kind), 51 past the filter, 35 at tier ≤3, and 36 carrying a German-language
requirement that `exclude_description_keywords` already removes. Every one of those flows
through machinery that exists — `remote_target_countries`, `adzuna_countries: de`,
`_classify_international_location`, `remote_scope`. A dedicated block would add a special case
for one country and change no outcome. Dropped.

**14 · `casual_work_mode`.** A flag to lower nightly volume without stopping the pipeline. The
pipeline already runs unattended and its bottleneck is the per-site cron timeout, which this
would not touch. A switch nobody would turn. Dropped.

### M5. Where this leaves the system

Built: the visa clock, contract shape, sponsorship evidence, span-aware title exclusions,
remote scope, the role-family ladder, `strategic_value`, `action_tier`. **Eighteen invariant
checks, 1048 tests, no added model spend.**

Rejected after measurement, with the numbers recorded so none of it is re-proposed: an
immigration score (§C5), eight blended dimensions (§F), ten zero-occurrence keywords (§D1), a
separate European pipeline (§G), Level Fit on `required_years` (§L4), and all four P2 items
(§M4).

That ratio is the point. Most of the value here came from measuring an idea and not building
it.
