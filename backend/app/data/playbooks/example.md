---
playbook: 1
title: Migraine HCPs in London
population: Healthcare professionals in Greater London who diagnose, treat or prescribe for migraine
geography: Greater London
size_hint: 120
author: Drishan Dutt
---

# Migraine HCPs in London — segmentation playbook

<!--
A segmentation playbook tells the Population Studio HOW YOU want this population cut,
and WHAT ELSE you believe shapes these people that a generic persona would miss.
Every section is optional except "Approach". Write in plain English; the Studio reads it,
shows you what it understood, and you confirm before anything is built.
Anything you state without a source is labelled "analyst hypothesis" in the report.
-->

## Approach

- **Primary axis:** behavioural — how they actually manage migraine (who escalates to
  preventives, who refers, who prescribes CGRP drugs).
- **Secondary axis:** demographic — role and care setting.
- **Why:** the question is about adopting a new preventive; what a clinician *does today*
  predicts uptake better than their age or title alone.
- **Match exactly on:** role, care setting. **Weight only:** borough group.

## Segments

<!-- Name the segments you expect. Give a share if you know it, or write "find" to let the
Studio look for the figure, or leave it blank for the planner to propose. -->

| Segment | Share | Who they are | Source for share |
|---|---|---|---|
| Headache specialists (tertiary) | 5% | Consultant neurologists in headache clinics (Queen Square, King's, Barts) | find |
| General neurologists | 15% | Hospital neurologists who see migraine among everything else | find |
| GPs with an extended role in headache | 10% | GPwER / GPs running a community headache service | find |
| Generalist GPs | 50% | First contact for most migraine patients | find |
| Headache specialist nurses | 5% | Run follow-up and injection clinics | find |
| Community pharmacists | 15% | Triptan and OTC advice, first stop for many patients | find |

## Variables

<!-- The extra forces you believe matter. For each: what it is, what low and high mean,
how it differs by segment, and anything you know about it. The Studio decides where each
one lives (a 0–10 dial, a category, or a rule of character) and which of the standard
112 dials it pushes; you can override both. -->

### Commute burden
- **Kind:** dial
- **What it is:** how much time and energy getting to work takes out of the day.
- **Low (0):** walks or a short direct trip. **High (10):** 90+ minutes each way, multiple changes, unreliable.
- **By segment:** Headache specialists (tertiary) 6–9; General neurologists 6–9;
  Headache specialist nurses 5–8; Generalist GPs 3–6; GPs with an extended role in headache 3–6;
  Community pharmacists 3–6 (hospital staff are priced out of inner London).
- **Shows up as:** less patience for anything that adds time; shorter clinics run late.
- **Evidence:** analyst hypothesis — check London travel-to-work data for NHS staff.

### Burnout
- **Kind:** dial
- **What it is:** emotional exhaustion and cynicism from workload.
- **Low (0):** energised, has slack. **High (10):** running on empty, counting the days.
- **By segment:** Generalist GPs 7–9; GPs with an extended role in headache 6–8;
  Headache specialists (tertiary) 5–8; General neurologists 5–8; Headache specialist nurses 5–8;
  Community pharmacists 5–7.
- **Shows up as:** resists new initiatives unless they save time; short, tired answers;
  defaults to what they already do.
- **Pushes:** frustration up, cognitive load up, time cost up, novelty down, hope down
- **Evidence:** find — NHS Staff Survey burnout question by London trust; GP Worklife Survey.

### Formulary pressure
- **Kind:** dial
- **What it is:** how hard the local ICB rules make it to prescribe newer migraine preventives.
- **Low (0):** prescribes freely. **High (10):** blocked in practice without specialist sign-off.
- **By segment:** Generalist GPs 8–10; GPs with an extended role in headache 5–8;
  Community pharmacists 6–9; General neurologists 3–6; Headache specialists (tertiary) 1–3;
  Headache specialist nurses 2–5.
- **Evidence:** find — NICE TA guidance for CGRP antibodies; London ICB formularies.

### Care setting
- **Kind:** category
- **Values:** tertiary headache centre · district general hospital · GP practice · community pharmacy
- **By segment:** Headache specialists (tertiary) tertiary headache centre; General neurologists
  district general hospital · tertiary headache centre; Headache specialist nurses tertiary headache centre;
  Generalist GPs GP practice; GPs with an extended role in headache GP practice;
  Community pharmacists community pharmacy
- **Evidence:** follows from the segment.

## Rules of character

<!-- Anything you want every twin, or one segment, to obey. Written as you'd brief an actor. -->

- Generalist GPs: think in 10-minute appointments; "will this cut my workload or add to it?"
- Headache specialists: evidence-led, cite trials, frustrated by the GP waiting list into them.
- Pharmacists: see medication-overuse headache weekly and worry about it.

## Things I'm not sure about

- Whether nurse specialists exist in meaningful numbers outside the tertiary centres.
- Whether burnout differs inner vs outer London.
