---
playbook: 1
title: London commuters and PedalPass
population: Adults commuting into Zones 1-3 of London on weekdays
geography: Greater London
size_hint: 40
author: Test analyst
---

# London commuters and PedalPass — segmentation playbook (TEST DATA)

## Approach

- **Primary axis:** behavioural — how they get to work today and whether they already cycle.
- **Secondary axis:** demographic — job type (office, shift, student, parent).
- **Why:** what someone does on their commute today predicts uptake better than age or income.
- **Match exactly on:** commute mode. **Weight only:** borough.

## Segments

| Segment | Share | Who they are | Source for share |
|---|---|---|---|
| Short-hop tube and bus commuters | 35% | Under 8 km, Zone 2-3 to Zone 1, office jobs | analyst hypothesis |
| Shift workers | 20% | Nurses, retail, transport; early or late starts | find |
| Students | 10% | Short trips, very price-sensitive | |
| Parents on the school run | 15% | Trip chains via nursery or school | analyst hypothesis |
| Existing cyclists | 10% | Already own a bike and ride weekly | find |
| Car and long-distance commuters | 10% | Over 10 km or drive in | |

## Variables

### Traffic fear
- **Kind:** dial
- **What it is:** how unsafe London roads feel to them on a bike.
- **Low (0):** rides anywhere without thinking. **High (10):** would not ride on a main road at all.
- **By segment:** Existing cyclists 1–3; Short-hop tube and bus commuters 5–7; Shift workers 6–8;
  Students 3–5; Parents on the school run 7–9; Car and long-distance commuters 7–9.
- **Pushes:** risk aversion up, emotional resistance up.
- **Evidence:** find — London attitudes to cycling safety by age.

### Dock luck
- **Kind:** dial
- **What it is:** how often a dock is near and has a bike when they need one.
- **Low (0):** never a bike at the dock. **High (10):** always one waiting.
- **Shows up as:** frustration at empty docks; trust in the service.
- **Evidence:** analyst hypothesis.

### Workplace facilities
- **Kind:** category
- **Labels:** shower and storage, storage only, nothing
- **By segment:** Short-hop tube and bus commuters shower and storage, nothing; Shift workers nothing, storage only.

## Rules of character

- Parents on the school run: any plan has to fit the nursery drop-off first.
- Existing cyclists: compare everything to owning a bike outright.
- Everyone: talk about real London places and roads, not cycling in general.

## Things I'm not sure about

- Whether shift workers are put off more by safety at night or by the price.
- Whether a free first month brings in people who never pay.
