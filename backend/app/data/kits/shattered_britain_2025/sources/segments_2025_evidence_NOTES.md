# Shattered Britain (2025) segment evidence: notes

Companion to `segments_2025_evidence.json`. Built 2026-10-08.

## Sources

- **Primary:** More in Common, *Shattered Britain* (July 2025), the full 279-page report (`shattered-britain-17072025_compressed.pdf`).
- **Checked, but used only as duplicates:**
  - The executive summary.
  - The four chapter-4 extracts (media, economy, immigration, climate).
  - The two "in-depth segment reports" (`seg_progressive-activists`, `seg_dissenting-disruptors`). These turned out to be page extracts of chapter 3 of the full report. They contain nothing the full report does not.
- **Web pages saved alongside:** the segment pages, quiz and interactive. Their text adds no numbers.

## Page convention

Every `page` is the **PDF page index of the full report**, and the printed footer number is PDF page minus 1. This holds throughout the main report. The extracts carry different printed numbers, so cite the full report only.

## Method

1. **Index the figures.** I listed all captioned figures (Fig 1 to 160) from the text layer and rendered the 149 pages that hold them at 1400 px with PDFKit, using `render/rp.swift` in the session scratchpad.
2. **Transcribe the charts.** Six parallel transcription passes read every chart from the **images**: question wording, legend, and each printed label mapped to its row and option.
   - Small labels were re-rendered at 2400 to 2600 px. Re-rendered at high resolution: pp. 75, 77, 80, 85, 108, 119, 127-129, 135-138, 146, 147, 171, 179, 189, 193, 200-203, 209, 210, 219, 220, 225, 229, 231, 232, 235, 263, 266, 267, 271, 272.
   - I re-checked p. 59 (Fig 27) myself at 2400 px.
3. **Use no chart numbers from the text layer.** The text layer lists chart labels in scrambled order. **Every chart value in the JSON was read from a rendered page image**; nothing comes from the text layer. Values marked `source: "chart (read from rendered page image)"` were all verified visually in this way.
4. **Check prose figures.** Prose statements ("X per cent of Rooted Patriots ...") are tagged `source: "report prose"`. The build script checks each one's snippet against the text layer of the cited page and fails if it is not there. All focus-group quotes and distinctive findings are page-checked the same way.
5. **Leave unreadable values out.** Unlabelled or clipped values are `null` and were never estimated. Charts that print no values are excluded entirely:
   - radar charts: Fig 8 (institutional trust)
   - heatmaps: Fig 11 (stress), Fig 98 (issues)
   - dot plots: Figs 16, 69, 105, 106, 110
   - scatter plots: Figs 83-86
   - the moral-foundations line chart: Fig 57
   - word clouds
   - the vote-share-by-age chart: Fig 146
   - the 2020-to-2025 segment flow: Fig 160
6. **Exclude Fig 94.** Fig 94 (benefits winners/losers by segment) is excluded because its printed segment rows do not sum to 100, which points to an error in the source chart.
7. **Generate the JSON.** It comes from `build/figs.py` and `build/build.py` in the session scratchpad, which hold one record per figure. A segment section shows that segment's row (`values_pct`) beside the national row (`national_pct`).

## Quiz-item coverage (`core_beliefs`)

| Item | Evidence | Match |
|---|---|---|
| agency_1 | Fig 33, p70 | exact |
| chaos_1 | Fig 28, p64 | exact. Also Fig 67b, reform vs tear down, p119 |
| conspiracy_grid_2 | Fig 39, p75 | exact. Format is true/false, % true |
| engagement_6 | Fig 43, p78 | exact |
| nativism_2 | Fig 49, p84 | exact |
| freespeech_1 | Fig 51, p86 | assumed match |
| freespeech_2 | Fig 52, p86 (political correctness) | assumed. Fig 64 (offence) is also included |
| nativism_1 | Fig 46, p81 (identity disappearing vs strengthened by diversity) | closest. Also Fig 97 (immigration undermined vs enriched) |
| selfefficacy_2, authority_grid_1/2, care_grid_1, autonomy_grid_3/5/6, parenting_4, victimhood_immig, lr_grid_2..5 | not found | **no by-segment numbers printed**. Proxies and prose notes are given in the JSON |

The moral-foundations chart (Fig 57) would have covered the authority, care and autonomy items, but it has no data labels. The published data tables (moreincommon.org.uk/our-work/polling-tables/) are the obvious next source for these items.

## Confidence and gaps by segment

Every segment has around 400 to 450 cited numbers. Each has the same 60+ by-segment charts plus segment-specific prose.

| Segment | Confidence | Notes and gaps |
|---|---|---|
| Progressive Activists | High | Rich prose: ethnicity, religion, renting, student debt, Green/SNP/Plaid voting. Gaps: Conservative and Reform party-ID bars unlabelled; share of Conservative 2024 voters unlabelled. |
| Incrementalist Left | High | Thinner segment-specific prose: no exact volunteering %. Daily-poster sliver unlabelled. |
| Established Liberals | High | Has the only by-segment institutional-trust chart (Fig 66: judges, police, scientists, etc.). Some "ashamed" and housing slivers are clipped. Reform/Green party-ID bars unlabelled. |
| Sceptical Scrollers | Medium-high | Age bars for 65+ unlabelled. The prose says 46% are under 35, but the chart labels sum to 49% (both cited). The prose gives 22% non-white, the chart 75% white (both cited). The NHS-distrust claim is qualitative only. |
| Rooted Patriots | High | 18-24 age bar unlabelled. Has current voting intention (Fig 129) and the Reform-swing charts. Several thin slivers unlabelled. |
| Traditional Conservatives | High | Small segment, so many small bars are unlabelled: young age bands, young-children rows, several party-ID bars, share of Labour 2024 voters. |
| Dissenting Disruptors | High | Rich prose on vote history, Reform, debt and riots. Several small party-ID bars unlabelled. |

## Gaps across all segments

- **Institutional trust:** no by-segment numbers for judges, police, journalists, business, faith leaders or scientists, except Established Liberals vs All. The NHS has only qualitative segment statements: a majority of every segment trusts it, and Sceptical Scrollers and Dissenting Disruptors trust it less.
- **Health:** nothing beyond pandemic isolation compliance (Fig 7), Covid conspiracy (Fig 39) and the NHS prose. No mental health or vaccine data.
- **Charity and giving:** no donation or volunteering percentages by segment, only prose. Memberships (Fig 156) and local voting (Fig 73) are the only numbers.
- **Aid:** no international-aid questions. The international section covers Ukraine, world stage, global responsibility and voting priorities.
- **Not shown in figures:** income bands, social grade, region within England and housing tenure percentages. Tenure appears only in prose: PA over a quarter renting privately, and qualitative statements for the others.
- **Media:** no by-segment numbers for outlets (BBC, GB News and so on), because Fig 110 is unlabelled. Only prose is available, e.g. half of GB News viewers are Dissenting Disruptors.
- **Discrepancies kept as printed:**
  - Fig 7 vs Fig 71: All row 42/30/16/12 vs 43/29/15/12.
  - Fig 62 vs Fig 96: All "significantly reduce" 46 vs 47.
  - PA radical change: prose says 46, chart sums to 45.
- **Fig 137:** printed as "EU Referendum vote by segment", but it is the 2014 Scottish independence vote (Scotland subsample).
- **Fig 157 (party supporters by segment):** not used. The page does not state its base.
