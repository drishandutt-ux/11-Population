# Britain's Choice (2020) seven segments: evidence file notes

Companion to `segments_2020_evidence.json`. Built 2026-10-08.

## Purpose and firewall

These profiles are for generating synthetic respondents that will later be scored against a **June 2023** More in Common poll broken down by the same seven segments. To keep that comparison clean:

- Only the 2020 segmentation research was used: the Britain's Choice report (Oct 2020, v2), its executive summary, and the britainschoice.uk segment and home pages.
- No June 2023 material was opened. The `xlsx/`, `deck/` and `deckpng/` scratch folders and `backend/kits/more_in_common/benchmarks` were not touched. The existing `render/full/` PNGs (origin unknown) were not used either. All renders for this file went to a new `render/p2020/` folder.
- No figure was estimated. Every number in the JSON comes from report text, a report table, or a value label printed on a chart, and carries a page reference.

## Sources

| File | Used for |
|---|---|
| `bc/report2020.txt` and `bc/report2020.pdf` | Main source, read in full (291 PDF pages) |
| `bc/exsum2020.txt` | Checked: same content as report pp. 6-27. Cited by its report pages. |
| `bc/seg_<slug>.txt` (7 files) | Website segment pages: shares, top priorities, preferred news sources. Mostly repeat report pp. 38-65; differences are noted below. |
| `bc/home.html`, `bc/segments.html` | Shares (13/13/12/12/17/18/15) and short segment snapshots |
| `bc/quiz2020.html` | Holds only navigation chrome. The questions load through JavaScript, so no quiz wording or scoring logic is in the file and nothing was captured. |

## Citation convention

- `page` is the **printed page label** in the report ("Page N"). The PDF page index is N+1; for example, the Loyal Nationals profile is printed p54, PDF p55.
- Several pages are comma-separated. "66-67" means the report's self-test quiz and its answer key.
- `figure` gives the report figure number when the value comes from a chart.
- `source: "web"` marks a britainschoice.uk segment page.
- Each numeric item has `value`, `uk_avg` (where the source gives one), `wording`, `page` and `date` (fieldwork wave: Feb 2020, May, June or Sept 2020).
- Qualitative items (`statement`) are paraphrases of the report prose. Quotes in `voice` are short participant excerpts, trimmed with ellipses.

## Method

1. Read the full report text and the website pages. Built a list of every by-segment chart and every segment-specific figure given in the prose.
2. **Charts:** the PDF text layer prints chart numbers in drawing order, not segment order. For example, Fig 4.3 reads "83 89 91 80 70 71 90 92" in the text layer, but the chart shows PA 89, CP 91, DB 90, EL 71, LN 92, DT 80, BC 70 with a UK average of 83. So **every by-segment chart used was rendered to PNG and read visually**. Text-layer order was never trusted.
3. Values went into `scratchpad/bc2020_charts.py`, a chart registry in PA, CP, DB, EL, LN, DT, BC order. Segment-specific prose went into `scratchpad/bc2020_build.py`, which writes the JSON. Rerun with `export DEVELOPER_DIR=/Library/Developer/CommandLineTools; cd $SP && python3 bc2020_build.py`. `count2020.py` produces the counts below.
4. Demographics come from Appendix 1.1, the full tables on printed pp. 275-277 (gender, generation, ethnicity, region, urban/rural, education, social grade, self-described class, income band, religion). Party ID comes from Appendix 1.1.8 on p277, cross-checked against Fig 4.8.

### Pages rendered (PDF page numbers; printed page = PDF minus 1)

Script `render/rp2020.swift` (a copy of `rp.swift` at 1800px), output in `render/p2020/`:

12, 13, 14, 18, 22, 23, 24, 25, 26, 27, 28, 71, 76, 80, 84, 88, 89, 90, 98, 100, 104, 105, 107, 108, 109, 113, 119, 120, 121, 123, 132, 135, 146, 147, 150, 159, 161, 167, 168, 178, 179, 180, 181, 182, 183, 186, 191, 192, 194, 199, 200, 202, 203, 207, 209, 211, 212, 213, 215, 217, 218, 225, 226, 229, 236, 237, 239, 240, 245, 253, 256, 257, 258, 262, 263, 267, 272 (77 pages).

Four rendered pages are dot plots without value labels: Figs 8.5 and 8.6 (feelings toward the haves and have-nots), 9.12 (feelings by ethnic group) and 10.9 (who is to blame for environmental damage). No numbers were read from these. Only the values the prose states are used, for example Established Liberals 48 and Disengaged Battlers 26 toward the wealthy, and Disengaged Traditionalists 33 toward people on benefits and 56 toward the working class.

## Cited-figure counts

The counts below cover items that carry a page and a numeric value. A demographic table counts as one item, even though each table holds many values.

| Segment | share | demog | politics | core beliefs | trust | health/NHS | charity/civic | intl/aid | immigration | climate | polarisation | media | wellbeing | ideal UK | **Total numeric** | qualitative | moral foundations |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Progressive Activists | 1 | 11 | 26 | 33 | 6 | 4 | 9 | 1 | 16 | 15 | 16 | 6 | 8 | 1 | **153** | 53 | 6 |
| Civic Pragmatists | 1 | 11 | 22 | 24 | 6 | 5 | 9 | 1 | 16 | 9 | 14 | 5 | 4 | 1 | **128** | 47 | 6 |
| Disengaged Battlers | 1 | 12 | 22 | 23 | 9 | 4 | 8 | 1 | 17 | 9 | 11 | 1 | 12 | 1 | **131** | 50 | 6 |
| Established Liberals | 1 | 11 | 21 | 21 | 8 | 4 | 8 | 1 | 17 | 9 | 14 | 1 | 6 | 1 | **123** | 50 | 6 |
| Loyal Nationals | 1 | 12 | 21 | 31 | 9 | 6 | 11 | 1 | 17 | 14 | 16 | 1 | 5 | 1 | **146** | 49 | 6 |
| Disengaged Traditionalists | 1 | 11 | 21 | 23 | 7 | 5 | 9 | 1 | 20 | 16 | 14 | 1 | 5 | 1 | **135** | 51 | 6 |
| Backbone Conservatives | 1 | 12 | 23 | 29 | 7 | 5 | 11 | 1 | 17 | 13 | 14 | 1 | 4 | 1 | **139** | 48 | 6 |

The qualitative column includes the eight `voice` quotes per segment.

## Confidence

- **High:** the segment shares (four sources agree), the Appendix demographic and party tables, and every chart value (read from rendered pages, with segment labels visible). Where a value appears on more than one chart (for example gender-equality pride on pp. 21, 134 and 167; racism on pp. 24 and 198; Green New Deal on pp. 191 and 237), the copies agree.
- **Medium (source ambiguities, flagged in `note` fields):**
  - **Fig 0.9 / 11.13, "citizens can change society":** the pole labels look swapped relative to the bars. The values were assigned using the text on p263: two-thirds agree, Backbone Conservatives and Established Liberals are most confident, and the Disengaged segments and Loyal Nationals are least confident.
  - **Fig 3.3, authoritarian index:** the PA, CP, DB and EL bars sit on the "low" side, but the printed labels have no minus sign. Values are recorded as printed, with the side noted.
  - **Fig 4.3:** the axis says "% Satisfied", but the measure is "politicians don't care".
  - **PA "least confident ... 68 v 46" (p40) and DT "less likely to act on climate 12 v 6" (p60):** the wording and the numbers do not fit together. Both are recorded as printed, with a note.
  - **LN "stronger environmental rules ... 63 v 48" (p56)** against Fig 10.10, which gives 91 v 83 for the same theme. Both are recorded.
  - **C2DE share:** the text gives DB 54% (p47) and LN 52% "highest" (p186), which conflict with each other and with Appendix 1.1.4.
  - **Coldest feeling toward the wealthy:** p181 says DB (26); p186 says LN.
  - **LN anxiety:** p260 says both that they are and are not above average.
  - **Climate item pole:** the Fig 0.16/10.1 chart says "left-wing people", while Appendix 2.1.18 says "rich, white, middle class people".
- **Moral foundations:** Fig 3.1 is an **unlabelled** line chart. Only the report's text labels (for example "lowest care", "joint highest authority") and relative positions on the chart are recorded. No scores were read off it. **Liberty was not measured** in the 2020 model.
- **Website v report differences** (both recorded, with notes):
  - DB "politicians don't care": website 87 v 76; report 90 v 83.
  - DB "fairer society": website 30 v 45; report 30 v 44.
  - DB "UK remain united very important": website 25 v 35; report 25 v 34.
  - CP "immigration positive": website 60; report text 59, chart 60.
  - BC "gradual climate change": report p64 gives 47 v 32 average; p231 gives 47 gradual v 37 radical within BC.

## Gaps (topics the June 2023 survey covers but the 2020 research does not, by segment)

- **Health priorities for government, NHS performance and trust in the NHS:** there is no by-segment measure. The report says only that the NHS was every segment's top source of pride (p163), that healthcare was a near-universal priority and so was left out of segment profiles (p37), and that 94% overall say Covid showed the importance of the NHS and public services (p163). Everything else is qualitative, for example a Loyal Nationals participant who would limit the NHS to people who paid in (p57).
- **Trust in vaccines, pharma, charities, health apps, Google and social media platforms:** not measured by segment. The closest material:
  - The two Disengaged segments are about three times as likely to refuse a Covid vaccine (pp. 139, 258).
  - Social-media benefits outweigh harms (Fig 11.14).
  - Regulating social media, by segment for LN, CP and BC only (p266).
  - Trust in climate scientists (DB only, p48; Leave v Remain, p242).
- **Mental health:** no by-segment data beyond loneliness (Fig 11.11), the DB anxiety figure (p48) and a qualitative ordering of which segments are above average for anxiety (p260).
- **Obesity, addiction and personal responsibility for free NHS treatment:** not measured. Closest proxies are the personal agency items (Figs 3.8 and 8.7), feelings toward people on benefits (DT p60/182, PA p182), and one Backbone Conservative quote (p81).
- **Clinical trials and medication adherence:** not covered.
- **Government v charity responsibility (poverty, refugees, homelessness, foodbanks, climate, aid) and charity giving:** there is no government-v-charity item. On giving, the report has only "almost all Civic Pragmatists give regularly v about half the public" (p43) and volunteering for EL, DB and the average (pp. 48, 52). The proxies used are business obligations (Fig 8.9), spending cuts (BC, LN), stopping borrowing (BC), "government should play a bigger role" (LN), redistribution (overall only, p188), and climate leadership must come from government (p239, qualitative).
- **International aid and developing countries:** no survey item. The material is qualitative only (CP global outlook p8/p44; LN p187; DT Jake p61; EL pride in positive influence p51 and refugee reception p67), plus the "Global" ideal-UK quality (Fig 0.12).
- **Compromise v fighting for beliefs:** figures exist only for PA ("stick to beliefs and fight" 35 v 22), CP (compromise 60 v 50) and EL (compromise 62 v 50). Overall, more than two to one prefer compromise (pp. 128, 135). The other four segments have no compromise figure. Proxies: "disagree without giving up on each other" (Fig 0.21) and leader/government-power items.
- **Polarisation, respect and media divisiveness:** good coverage (Figs 0.5, 5.2-5.6, 0.20, 6.3). By-segment "causes of division" figures are partial: LN, BC, DT immigration; PA and CP economic system; LN class.
- **Demographics:** no housing tenure or employment-status tables by segment, only qualitative cues. Nothing on disability, children in household or health conditions. The "victimhood" cluster items (Appendix 1.3) are not printed.
- **Politics:** no full 2019 or 2017 vote tables by segment. The figures are DB non-voters 29%, LN Conservative 46% (2017) to 56% (2019), DT voters about 4:1 Conservative to Labour, and EL voters 2:1 Conservative to Labour. Party ID (Appendix 1.1.8) and EU referendum vote are complete.
- **Northern Ireland** is excluded; the data are GB only.
- **Timing:** fieldwork was Feb to Sept 2020, during Covid, which inflates community and solidarity measures. The report argues core beliefs are stable over time (p8), but issue attitudes may have moved by 2023.
