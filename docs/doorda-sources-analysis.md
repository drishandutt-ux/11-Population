# Doorda: what it collects, where from, and what we should take

*Analysis by Claude for Drishan, 2026-10-27. Question asked: analyse all the data points
Doorda publishes, where it collects them from, and whether we can use some or most of them,
since they are proven, accurately published data points.*

**Short answer.** Doorda publishes nothing of its own. It is an aggregator: it watches about
1,500 official UK publishers, downloads their files every month, opens the spreadsheets, and
links every row to a postcode, an address or a company number. The accuracy Drishan is
pointing at belongs to the publishers underneath it (ONS, Land Registry, Companies House,
DWP, NHS, the police, councils), and all of those publish under the Open Government Licence,
free, to anyone. So we can use **most of what Doorda uses** without Doorda. What we cannot
easily copy is the one thing Doorda actually sells: address-level linking across 34 million
addresses, which our tool does not need. The useful lesson is narrower and cheaper: Doorda's
whole business is *opening the xlsx, ODS and CSV files our reader currently cannot open*, and
calling the APIs our registry currently marks "not readable". Fixing that would unlock most
of Doorda's catalogue at the geographies we frame on (nation, region, local authority, ward).

---

## 1. What Doorda is

- A UK company (founded 2011, London) selling "trusted data on demand": open and public-sector
  data consolidated into one queryable platform. Customers named: PwC Deals & Analytics,
  South Central Ambulance Service, Sagacity, Capital on Tap, CARTO, Konsileo, 118 / Market
  Location.
- Its own description of the method: *we actively monitor 1,524 sources, download over 2,000
  files each month, and meticulously maintain all associated metadata*; elsewhere *over 1,500
  official sources* and *over 4,000 datasets refreshed each month*. It also harvests some data
  itself through Freedom of Information requests (planning applications are the obvious case).
- Linking keys: postcode, address (Royal Mail UDPRN, Ordnance Survey UPRN, Doorda's own
  building id "DAR") and Companies House company number. The address matching is patented and
  is the real intellectual property.
- Delivery: DoordaHost (a Presto SQL warehouse, one schema per product, snapshot and ledger
  tables with a `urn` key, an `_evaluation` schema for trials), a REST API, bulk CSV, Python
  and R SDKs, Tableau and Qlik connectors, and listings on Datarade with free sample previews.
- Pricing: never published. "Pricing available upon request"; one-off, monthly, yearly and
  usage-based licences all offered. Enterprise sales motion (book a demo). Website content is
  CC BY-NC 4.0; the data licence is in the contract, not on the site, and redistribution is
  forbidden without written consent.

## 2. The catalogue, product by product, with the publishers underneath

Doorda names only a handful of sources in text (HMRC, Ordnance Survey, Land Registry, Local
Authorities, Companies House, Royal Mail). The rest is read from its glossary, its product
pages' logo strips, its Datarade data dictionaries and its DoordaHost schema names. Where a
publisher is inferred rather than named, it says so.

### 2.1 Population / geodemographics ("DoordaStats", 173 sources, 2.2M postcodes → 230k output areas)

| Doorda data point | Publisher underneath | Geography Doorda gives | Open? | Already in our registry? |
|---|---|---|---|---|
| Census: age, sex, households, tenure, ethnicity, qualifications, NS-SeC, economic activity, health, car access | ONS Census 2021, Scotland's Census 2022, NISRA Census 2021 | output area | OGL, free | **Yes** (ONS, Nomis, Scotland, NISRA) — but read from bulletin prose and Nomis HTML; the OA tables are csv/API |
| Index of Multiple Deprivation (rank, decile, 7 domains) | MHCLG IoD 2019; SIMD 2020; WIMD 2019; NI MDM 2017 | LSOA → postcode | OGL, free | **England only**, and only the prose ("File 10 is xlsx the reader cannot open") |
| Income (net annual household income; income by postcode area) | ONS small-area income estimates (MSOA, xlsx); HMRC personal incomes by postcode area / PAYE | MSOA, postcode district | OGL, free | **ONS yes** (xlsx not opened); **HMRC no** |
| Household spend by product category | ONS Living Costs and Food Survey, modelled down to small areas by Doorda | postcode | the survey is OGL; the small-area model is Doorda's | Survey yes (region); model no, and it is not a published figure |
| DWP benefits: Universal Credit, Housing Benefit, claimant counts | DWP Stat-Xplore; Nomis | LSOA / ward | OGL, free API with a key | Registry says *detail behind Stat-Xplore (not readable)* — it has an API |
| Crime | data.police.uk street-level crime (England, Wales, NI) | LSOA / postcode | OGL, free API, no key | **No** |
| Council tax bands and stock of properties | Valuation Office Agency (England, Wales), Scottish Assessors, LPS Northern Ireland | LSOA | OGL, free | **No** |
| Rural/urban classification; Output Area Classification (geodemographic classification) | ONS | OA | OGL, free | **No** |
| Output area sizes, LSOA lookups, postcode centroids and polygons | ONS Open Geography Portal, OSNI, Royal Mail | OA / postcode | OGL (postcode polygons partly OS/Royal Mail licensed) | n/a — we do not map |
| Schools | DfE | LA | OGL | Yes |

### 2.2 Health (20 sources, 1.8M postcodes → output areas)

Doorda's health tables are **modelled small-area propensities**: smoking propensity, obesity
propensity, biological age and the gap to real age, standardised mortality ratio and life
expectancy, each by sex and age band from 18–24 to 85+, at output area. These numbers are not
published by anyone; they are Doorda's own estimates from the published inputs:

| Input underneath | Publisher | Open? | In our registry? |
|---|---|---|---|
| Smoking and obesity prevalence by local authority | OHID Fingertips; Active Lives; Health Survey for England; Annual Population Survey | OGL, free API | **Yes** (fingertips, sportengland, nhs) |
| Deaths and life expectancy | ONS; OHID | OGL | Yes |
| GP Patient Survey | NHS England / Ipsos | OGL | Partly (nhs holds patient experience) |
| Prescribing | NHS BSA English Prescribing Dataset; OpenPrescribing API (free, no key) | OGL | No |
| QOF disease registers by practice | NHS Digital | OGL | Yes (nhs) |
| Hospital episodes, A&E | NHS Digital | OGL (aggregate) | Partly |

### 2.3 Vulnerability (30 sources, 1.8M postcodes)

Four ranks per postcode, 1–100: `vuln_income_rank`, `vuln_education_rank`,
`vuln_health_rank`, `vuln_debt_rank` (a fifth area is advertised but unnamed). Again a Doorda
composite built from IMD domains, benefits, HBAI, FCA Financial Lives, insolvency and county
court judgment counts. Not a published figure; a proprietary index.

### 2.4 Property ("DoordaProperty", 357–398 sources, 34.5M addresses, 3.2M commercial locations)

| Doorda data point | Publisher underneath | Open? | Of use to us? |
|---|---|---|---|
| Price paid transactions, 20+ years | HM Land Registry Price Paid Data (monthly CSV, 5 GB; yearly files); UK House Price Index | OGL (attribution statement required) | Yes, at local-authority level (median price, sales volume, price-to-income) — a frame dimension we do not have |
| Ownership (commercial and overseas owners) | Land Registry CCOD and OCOD datasets | free with registration | No — row-level, personal/company data |
| Rateable values, occupancy, property type and internal details | VOA non-domestic rating lists | OGL | Only aggregates (shops per town, by category) |
| Council tax band per address | VOA | OGL (stock by LSOA only; per-address is VOA's own lookup) | Aggregates only |
| Energy performance, heating fuel, floor area, construction age | MHCLG EPC open data register (free API key; bulk by local authority) | OGL with exceptions | Yes, aggregated: share of homes in band D or worse, heating fuel, property age by LA — useful for energy, net-zero and cost-of-living questions |
| Planning applications (7.5M; "Local Planning Intelligence" chatbot) | ~340 council planning portals, scraped / FOI'd by Doorda | not open as one file | Not for us |
| Building height, floors, footprint | OS, Environment Agency LiDAR, Doorda derivation | OS licensed | No |
| Addresses, UPRN, UDPRN, lat/long | OS AddressBase Premium (licensed; Doorda is an OS partner), Royal Mail PAF (licensed) | **not open** — this is what Doorda pays for | No |
| Regulatory inspections at a location | CQC (API, OGL), FSA food hygiene ratings (free API, no key), Gambling Commission licence register | OGL | Aggregates only (care homes and their ratings per LA; food businesses per town) |
| Local crime, education, income beside a property | as in 2.1 | | as in 2.1 |

### 2.5 Business ("DoordaBiz", 1,024 sources, 16.5M company numbers, 40 courts and regulators)

| Doorda data point | Publisher underneath | Open? |
|---|---|---|
| Company profiles, officers, PSC register, filings, name history, charges, dissolutions | Companies House (bulk products and free REST API with a key; some tables Doorda reconstructs from one-record-at-a-time pages) | free |
| Filed accounts as structured fields (turnover, profit, employees, wages) | Companies House iXBRL accounts bulk feed | free |
| Liquidations, insolvency notices | The Gazette; Insolvency Service | free |
| Regulatory breaches: fines, prosecutions | HSE convictions and notices; HSENI; Environment Agency; SEPA; ICO register and enforcement; Gangmasters and Labour Abuse Authority; Advertising Standards Authority rulings | free |
| Court judgements and tribunals | National Archives Find Case Law; employment tribunal decisions on gov.uk | free |
| Public tenders and contracts (230k+) | Contracts Finder; Find a Tender | free API |
| Government spend over £500 (100M invoices, 1,500 bodies) | every council's and department's transparency CSVs | free, but 1,500 files |
| Trade: company activity, tariffs, volumes | HMRC overseas trade statistics; HMRC importer/exporter lists | OGL |
| Charities | Charity Commission register | free |
| Science Based Targets | SBTi | free |

For a public-opinion simulator almost none of this is a frame dimension. The one business
figure we do want — businesses by size and industry for a place — is already on Nomis
(Business Register and Employment Survey, UK Business Counts).

### 2.6 Spatial

Postcode polygons (2.2M), output areas (230k), LSOAs (37k), from ONS, OSNI and Royal Mail.
We do not draw maps; nothing to take.

## 3. Can we use them?

### Use the publishers, not Doorda — four reasons

1. **Provenance is our product.** Every figure in a frame is labelled with the publisher, the
   dataset and the year, and "matched to published figures" is the promise. A number read from
   Doorda would be cited as "Doorda, 2026", one step removed from the ONS table it was copied
   from, and the reader cannot click through to the release. That is weaker evidence than
   what the gather step produces now, not stronger.
2. **The geography we frame on is the geography the publishers already give.** Doorda's
   value is pushing everything down to postcode and address. Our populations are framed on
   nation, region, local authority and occasionally ward. Every table in §2 is published at
   local authority or LSOA by the publisher itself, free.
3. **Doorda's genuinely novel numbers are models, not publications.** The health propensities,
   biological age, vulnerability ranks and small-area spend are Doorda's estimates. We already
   produce an *educated assumption* when a figure is not published and we label it as one
   everywhere. Swapping a labelled assumption for an unlabelled third-party model would
   undermine the labelling.
4. **Licence and cost.** No public price, enterprise sales, no redistribution, and the
   address layer sits on OS and Royal Mail licences we have no use for. A Datarade "free
   sample" preview exists and a DoordaHost `_evaluation` schema exists, but both need an
   account and a conversation with their sales team.

### Where Doorda would be worth paying for

- If the tool ever has to frame on **postcode sectors or output areas** (a local campaign, a
  single constituency's wards, a store catchment), Doorda has done the small-area modelling
  and the lookups already.
- If a client question needs **commercial location data** (which brands trade on a high
  street, rateable values, occupants) — not something the twins need today.
- If we wanted **one SQL endpoint** instead of thirty readers. That is convenience, and the
  convenience is what we would be paying for.

## 4. What to take from Doorda: the open-data layer

The honest finding is that the gap is not sources, it is **file formats and APIs**. Our
publisher registry already names most of the datasets Doorda holds at the geography we need,
and then says, over and over, *the local-authority numbers are in an xlsx the reader cannot
open*, *the regional tables are ODS*, *detail behind Stat-Xplore (not readable)*. Doorda's
business is reading exactly those files. Three steps, in order:

**Step 1 — Open the spreadsheets (biggest win, smallest build).** Teach the reader to open
xlsx, xls, ods and csv links found on a release page (openpyxl, pandas, odfpy; sheet names
and the first rows go to the model, the named table is extracted as rows). That alone turns
these registry entries from *prose only* into *table read*: IMD local-authority summary
(File 10), HBAI regional ODS, children in low income by LA and ward, ASHE place medians,
ONS small-area income (MSOA), fuel poverty by LA and LSOA, well-being by LA, VOA council
tax stock, ONS internet access tables. Every one is a figure Doorda sells back.

**Step 2 — Call the APIs the registry already knows exist.** Each becomes a `how` route in
the registry and a direct fetch in the gather step, keys in env vars:

| API | Gives us | Key |
|---|---|---|
| Nomis `api/v01/dataset/<id>.data.csv` | any census TS table and labour-market series for a named geography code | none |
| ONS API (`api.beta.ons.gov.uk`) | census 2021 custom tables by area | none |
| DWP Stat-Xplore | UC, PIP, Housing Benefit, pension credit by LA, ward, age | free key |
| data.police.uk | crimes by category per LSOA/postcode per month | none |
| EPC open data (`epc.opendatacommunities.org`) | energy band, heating, age, floor area per LA | free key |
| Companies House REST | business counts by SIC and place (where Nomis is stale) | free key |
| FSA FHRS | food businesses and ratings by authority | none |
| CQC | care providers and ratings by LA | free key (post-migration) |
| OpenPrescribing | prescribing per practice / ICB | none |
| OHID Fingertips API | every indicator by LA (already in the registry, as JS tool) | none |
| HM Land Registry linked data / UK HPI | median price and volumes by LA | none |

**Step 3 — Add the missing publishers to the registry.** New entries with `holds`, `cannot`,
`geographies` and `how`, matching the pattern in `population/sources.py`: data.police.uk;
VOA (council tax stock, rateable values); MHCLG EPC; HM Land Registry (price paid, HPI);
HMRC (personal incomes by postcode area, PAYE); Companies House; FSA; CQC; the devolved
deprivation indices (SIMD, WIMD, NI MDM); ONS Output Area Classification and rural/urban
classification. Each is OGL: attribution is the publisher name and year, which the frame
already prints.

**Effort.** Step 1 is a day or two (reader plus the extraction prompt plus tests on three
known files). Step 2 is a day per two or three APIs, and can be done one at a time as a
frame dimension needs it. Step 3 is registry text and the compact-registry prompt budget.
No new money, no new licence, no personal data.

**What it does to a run.** A Blackpool or Oxford frame that today matches four of five
dimensions and works out the fifth would match deprivation from the real IMD summary,
income from the MSOA table, benefits from Stat-Xplore and, when the brief asks, crime and
housing from police and Land Registry, with every figure linked to its release. The *worked
out* and *assumed* chips would appear less often, which is the whole point of them.

## 5. Caveats on "proven accuracy"

- Doorda does not verify figures; it verifies **linking** (its address matching). The
  figures are only as good as the publisher's, which is the same bar our gather step applies.
- The public listings are not tidy: 1.8M postcodes in one line and 18M in the next; 3M
  addresses in a title and 34M in the description; sample data dictionaries with malformed
  column names (`male_85_plus_bio_age_diff55055`). None of this says the data is wrong, but it
  says the catalogue is sales material, not documentation. The real catalogue is behind the
  demo.
- Several of its headline tables contain personal data (27M directors' correspondence
  addresses, owners, planning applicants). We should not want those in the tool at all.

## Sources read

doorda.com (home, products: property, business, spatial; our story; glossary of data
sources; terms and conditions); data.doorda.com product listings (Health, Vulnerability,
Company Data, Population, Geospatial, Rental, Building Characteristics, Commercial Real
Estate, Director Data); datarade.ai provider profile; github.com/Doorda/Getting-Started
(README and terms: DoordaBiz, Public Procurement, DoordaStats, DoordaProperty, Commercial
Location schemas); carto.com Doorda partner post; differentia.consulting and builtin.com
profiles; PwC press release (2023); publisher pages for data.police.uk, EPC open data, HM
Land Registry Price Paid Data, Companies House API, FSA FHRS API, CQC API, OpenPrescribing
and VOA council tax stock of properties.
