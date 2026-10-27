# The Open Data Store — starting brief

*Drafted 2026-10-27 by Claude with Drishan, from the Doorda analysis
(`docs/doorda-sources-analysis.md` in the 11 Minds Population repo) and the brainstorm that
followed. This file is the seed for a new project. It should read on its own.*

---

## 1. The idea in one line

A portal of our own that pulls the UK's published statistics straight from the publishers,
notices when they update, keeps every version, and serves the figures to any of our tools
through a REST API and an MCP server, with the publisher, dataset, year and retrieval date
attached to every number.

## 2. Why

- Every tool we run (Populations, Brand Buddy, Pulse, SuperMind, the n8n flows) gathers
  the same official figures again and again by searching the web and reading bulletin
  prose. The numbers that matter most sit in xlsx, ODS and CSV files and behind APIs that
  the readers skip. Doorda's entire business is opening those files.
- Doorda (doorda.com) proves the model: watch about 1,500 official publishers, download
  their files monthly, parse them, link them, sell access. But Doorda sells address-level
  data on licensed Ordnance Survey and Royal Mail foundations, prices on request, and
  forbids redistribution. We need none of that. We need published figures at nation,
  region, local authority and sometimes ward or LSOA, with provenance.
- Provenance is the product. A figure served by the store must be the publisher's figure,
  traceable to the release it came from. That is stronger evidence than a re-publisher's
  copy and the reason to build rather than buy.

## 3. What Doorda is, in four parts (and which we copy)

| Part | Doorda | Us |
|---|---|---|
| Source catalogue with metadata (lineage, cadence, format) | 1,500 publishers, human-curated | Start from the 30-publisher, ~70-dataset registry already written for Populations; grow to perhaps 150 datasets |
| Watcher that notices updates | Downloads ~2,000 files a month | Release calendars, Atom feeds, CKAN modified dates, conditional HTTP; perhaps 100 files a month |
| Parsers that turn each spreadsheet into rows | Analysts and maintained metadata | Model-written parser per dataset, stored, re-run on each release, repaired by the model when the layout drifts |
| Linking | Patented address matching to 34M addresses (UPRN, UDPRN) | ONS geography codes only; nothing below LSOA; no addresses, no people, no companies |
| Query layer | Presto SQL (DoordaHost), REST, CSV, Datarade | REST on FastAPI plus an MCP server; keys per tool |
| Versioning | Snapshot and ledger tables per product | Dataset versions with valid-from / valid-to on every fact |

What we deliberately do not copy: address-level property data, directors and owners,
planning applications, Doorda's own modelled propensities (output-area smoking, obesity,
biological age, vulnerability ranks, small-area spend). Those are models, not published
figures, and the store must never present a model as a publication.

## 4. Scope

**In.** Official and quasi-official UK statistics at nation → region → local authority →
ward / MSOA / LSOA, from publishers whose data is Open Government Licence or equivalent:
ONS, Nomis, gov.uk statistics (MHCLG, DWP, DfT, DfE, DESNZ, DCMS, DSIT), Scotland's Census
and Scottish Government, NISRA, Welsh Government, NHS England / NHS Digital, OHID Fingertips,
NHS BSA (prescribing), Sport England, Ofcom, FCA, data.police.uk, Valuation Office Agency,
HM Land Registry (price paid aggregates, house price index), MHCLG EPC open data
(aggregated), Companies House counts, FSA food hygiene ratings (aggregated), CQC
(aggregated), HMRC (personal incomes by area, PAYE), Charity Commission (counts), London
Datastore. Later: pollster tables (More in Common, Ipsos, YouGov, Opinium, Savanta,
Focaldata) as extracted figures with citations, not documents.

**Out.** Anything address-level or personal (OS AddressBase, Royal Mail PAF, Land Registry
ownership, directors, planning applicants). Anything we would have to model ourselves to
make small-area. Any source whose licence forbids storage or onward use. Maps and
polygons (link to the ONS Open Geography Portal instead).

## 5. Architecture

```
publishers ──▶ watcher ──▶ fetch jobs ──▶ parser (per dataset) ──▶ facts (+ ledger)
                 ▲                              │                       │
                 │                              ▼                       ▼
           catalogue table              drift check ──▶ model repair   query layer
                                                                        ├─ REST API (FastAPI)
                                                                        └─ MCP server
                                                                             │
                                             Populations · Brand Buddy · Pulse · SuperMind · n8n · Claude Code
```

### 5.1 Catalogue (sources as data)

One row per dataset, not per publisher: publisher, dataset name as the publisher titles it,
what it gives (attributes and crossbreaks), geographies reached, cadence, licence, the
landing page, the file or API URL pattern, format (xlsx / ods / csv / json / html / pdf),
the parser id, last checked, last changed, last checksum, status. Seed it from the
`_HOLDINGS` dictionary in `backend/app/services/population/sources.py` of the Populations
repo, which already has name / gives / geo / how / cannot for every entry in prose.

### 5.2 Watcher

A scheduled worker (hourly or daily per source) that asks the cheapest question first:

- ONS release calendar and dataset "last updated" fields; ONS beta API versions.
- gov.uk statistics collections publish Atom feeds; the publication page's "updated" line.
- data.gov.uk CKAN API `metadata_modified` for anything catalogued there.
- Nomis dataset metadata, Fingertips indicator metadata, Stat-Xplore table metadata.
- Conditional HTTP (ETag, Last-Modified) and a content checksum for plain files.

A change writes a fetch job. Jobs are idempotent, resumable after a redeploy, and visible
on an admin page (what changed, what failed, what was repaired). A watcher that stops
silently is worse than none.

### 5.3 Fetch and parse

- Fetch the file to object storage, keep the original bytes forever (small; most releases
  are under 10 MB; the big ones such as Land Registry price paid or EPC are aggregated on
  the way in and the raw file dropped).
- Open xlsx / xls / ods / csv with pandas, openpyxl, odfpy. For PDFs, the existing reader.
- **First time:** the model is shown the sheet names, the first forty rows of each sheet
  and the catalogue entry, and writes a parser (a small Python function) that emits the
  tidy shape below. A human glances at the output once. The parser is stored with the
  dataset version it was written against.
- **Each release:** re-run the stored parser. Compare the output shape (columns, category
  labels, geography count, value ranges) with the last run. Within tolerance, publish.
  Outside it, flag drift: the model is shown the old parser, the new sheet and the
  differences, proposes a repair, and the result waits for a human tick. This is the one
  trick that replaces Doorda's analysts.

### 5.4 The tidy shape

Every fact is one row:

| column | meaning |
|---|---|
| dataset_id | catalogue row |
| dataset_version | which release (date or edition) |
| geography_code | ONS code (E06000009, S12000033, N09000003…) or nation / region code |
| geography_name | as published |
| geography_level | nation · region · local_authority · ward · msoa · lsoa |
| period | the reference period as published (2021, 2023-24, 2024-Q3, 2025-03) |
| measure | what is counted (e.g. "residents", "households", "share of adults") |
| category | the breakdown value ("16–24", "Owned outright", "Level 4+") |
| crossbreak | a second breakdown when present (sex, age band) or null |
| value, unit | the number and its unit (count, %, £, rate per 1,000) |
| flags | suppressed, provisional, revised, rounded |
| source_url, retrieved_at | the release page and the fetch time |
| valid_from, valid_to | ledger: when this version was current |

A **concept** table above it maps a question our tools ask ("adult obesity", "median
household income", "households in fuel poverty") to the dataset that answers it for each
nation, with a note where the four nations are not comparable. The caller asks for a
concept and a place; the store chooses the dataset and says which it chose.

A **geography** table holds the ONS code lists with their vintages, parents and names, so
a 2019 council and its 2023 successor are both resolvable and a figure is stamped with
the vintage it was published on.

### 5.5 Storage

Postgres (Supabase, the project already used in production) for catalogue, geography,
concepts, facts and the ledger. At local-authority level the facts table is millions of
rows at most, which is small. Object storage (a Railway bucket or Supabase storage) for
the raw files and the stored parsers. No address-level data, so no multi-gigabyte tables.

### 5.6 Query layer

**REST (FastAPI, same stack as Populations).**

- `GET /datasets?q=` search the catalogue
- `GET /figure?concept=&place=&period=latest` one number with its citation
- `GET /distribution?concept=&place=` the full breakdown for a dimension (what a
  sampling frame needs)
- `GET /compare?concept=&places=` side by side
- `GET /changes?since=` what updated
- `GET /cite?fact_id=` the attribution line and the release URL

**MCP server** exposing the same six as tools (`find_dataset`, `get_figure`,
`get_distribution`, `compare_places`, `list_changes`, `cite`), served over streamable HTTP
next to the API so Claude Desktop, Claude Code, Brand Buddy's engine, Pulse, SuperMind
and n8n can all call it. Keys per consuming tool; usage logged per key (the Populations
token-and-cost ledger is the pattern).

Every response carries the attribution line the licence asks for ("Source: Office for
National Statistics licensed under the Open Government Licence v3.0", "Contains HM Land
Registry data © Crown copyright…").

### 5.7 First consumer: Populations

The frame matcher asks the store before it searches the web. A hit is a new standing,
**published figure on file**, with publisher, year and retrieval date, matched and
weighted like a found distribution. The work-it-out step takes its component figures from
the store. The *worked out* and *assumed* chips appear less often, which is the point of
them.

## 6. What to reuse from the Populations repo

- `backend/app/services/population/sources.py`: `QUANT_SOURCES` (publishers) and
  `_HOLDINGS` (datasets in prose) are the catalogue seed; `gather_targets` is the web
  fallback when the store has no answer.
- `backend/app/services/population/workout.py`: the decompose → gather → compute pattern
  becomes "ask the store, then fall back".
- `backend/app/services/recovery.py`: stuck-job recovery after a redeploy; copy the
  discipline for watcher and fetch jobs.
- The admin tab and the `llm_usage` ledger: the shape for a "what changed / what failed"
  page and per-key usage.
- The SuperMind evidence-gathering stack (`/Users/drishan/SuperMind`): page watchers that
  track what changed on a site, reusable for publishers without feeds.

## 7. Licences and conduct

- Official statistics: Open Government Licence v3.0. Store, transform, serve, attribute.
- HM Land Registry price paid: OGL with a required attribution statement; third-party
  rights excluded.
- EPC open data: OGL with stated exceptions; aggregate only, no certificates.
- Nomis, Fingertips, data.police.uk, FHRS, CQC, OpenPrescribing, Companies House: open,
  free API; some need a free key (Stat-Xplore, EPC, Companies House, CQC); keys in env.
- Pollsters, Ofcom and trade-body reports: copyright. Store extracted figures with
  citation; never the documents; internal use until each is reviewed for outward use.
- No personal data. If a source has it, aggregate before storing or leave it out.
- The store is internal to 11 London's tools until a licence review says otherwise.

## 8. Build order

1. **Catalogue and reader (week 1).** Catalogue table seeded from the registry; the
   spreadsheet reader; the facts, geography and concept tables; twenty frame-critical
   datasets parsed by hand-checked model parsers at local-authority level (list below).
   Populations reads from the store first.
2. **Watcher, ledger, drift repair (3–4 days).** Scheduled checks, fetch jobs, versioned
   facts, drift detection and model repair with a human tick; the admin page.
3. **REST and MCP (2–3 days).** The six calls, keys, usage log, attribution lines; one
   other tool wired in as the proof.
4. **Widen (ongoing).** Police, VOA, EPC aggregates, Land Registry HPI, Companies House
   counts, Stat-Xplore, HMRC incomes, devolved deprivation indices, pollster tables.

### The first twenty datasets

| # | Dataset | Publisher | Level | Format today |
|---|---|---|---|---|
| 1 | Mid-year population estimates by single year of age and sex | ONS / Nomis | LA | xlsx / Nomis API |
| 2 | Census 2021 TS007A age bands | ONS / Nomis | LSOA | Nomis API csv |
| 3 | Census 2021 TS054 tenure | ONS / Nomis | LSOA | Nomis API csv |
| 4 | Census 2021 TS062 NS-SeC | ONS / Nomis | LSOA | Nomis API csv |
| 5 | Census 2021 TS067 highest qualification | ONS / Nomis | LSOA | Nomis API csv |
| 6 | Census 2021 TS021 ethnic group | ONS / Nomis | LSOA | Nomis API csv |
| 7 | Census 2021 TS003 household composition | ONS / Nomis | LSOA | Nomis API csv |
| 8 | Census 2021 TS037 general health; TS038 disability | ONS / Nomis | LSOA | Nomis API csv |
| 9 | Census 2021 TS066 economic activity; TS063 occupation | ONS / Nomis | LSOA | Nomis API csv |
| 10 | English Indices of Deprivation 2019, local-authority summary (File 10) and LSOA ranks (File 7) | MHCLG | LA / LSOA | xlsx |
| 11 | Scottish IMD 2020; WIMD 2019; NI MDM 2017 | Scottish Gov / Welsh Gov / NISRA | data zone / LSOA / SOA | xlsx / csv |
| 12 | Small area income estimates | ONS | MSOA | xlsx |
| 13 | Households below average income, regional tables | DWP | region | ODS |
| 14 | Children in low income families, local area statistics | DWP | LA / ward | xlsx |
| 15 | Annual Survey of Hours and Earnings, place of residence | ONS / Nomis | LA | Nomis API |
| 16 | Universal Credit, PIP, Housing Benefit claimants | DWP Stat-Xplore | LA / ward | API (key) |
| 17 | Sub-regional fuel poverty | DESNZ | LA / LSOA | xlsx |
| 18 | Public Health Profiles (obesity, smoking, diabetes, life expectancy, deprivation score) | OHID Fingertips | LA | API json |
| 19 | Active Lives, local authority tables | Sport England | LA | xlsx |
| 20 | Personal well-being by local authority | ONS | LA | xlsx |

Then: street-level crime by LSOA (data.police.uk), council tax stock of properties (VOA),
EPC bands by LA (MHCLG), UK House Price Index by LA (Land Registry), UK Business Counts
(Nomis), Adults' Media Use and Attitudes data tables (Ofcom), Financial Lives tables (FCA),
Community Life Survey (DCMS), National Travel Survey (DfT), GP Patient Survey (NHS England).

## 9. Costs and limits to design around

- **Spreadsheets are the job.** Multi-sheet workbooks, two-row headers, totals mixed with
  rows, suppression marks, footnotes. Expect a week of iteration on the first thirty
  before parser generation feels routine.
- **Geography drift.** Council mergers (2019, 2021, 2023, 2025), census vs mid-year areas,
  Scottish and Welsh code sets. The geography table with vintages is not optional.
- **Four nations.** Most concepts need a harmonising rule and some are not comparable
  across borders; the store says so rather than blends.
- **Revisions.** ONS revises; the ledger keeps both and the API serves "latest" by
  default with "as published on" available.
- **Model cost.** Parser generation and repair are one-off calls per dataset per drift,
  a few pence to a pound each. Running cost is a worker, Postgres and storage.
- **It is a product.** Someone has to look at the admin page when something turns red.

## 10. Open questions for the new project

1. Name. Working title: the Open Data Store.
2. One repo or a service inside the Populations backend first, then split? Proposal: a
   new repo from the start, with Populations as the first client, so the API boundary is
   real from day one.
3. Where it runs: Railway (same account as Populations) with the Supabase Postgres, or
   its own Supabase project.
4. Which tool is the second consumer for the MCP proof: Brand Buddy, Pulse or SuperMind.
5. Whether pollster tables belong in phase 4 or a separate "evidence" store with
   different licence handling.
6. How much human review the drift repair gets: every repair, or only when the value
   ranges move.

## 11. Success looks like

- A Populations frame for any UK local authority matches every demographic dimension to
  a published figure on file, with a clickable release behind each, and runs faster
  because the gather step has less to search.
- The same figure fetched from two tools is the same figure with the same citation.
- When ONS publishes new mid-year estimates, the store has them within a day, every
  consumer sees the new version, and the old one is still there for anyone who asks.
