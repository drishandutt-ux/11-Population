---
playbook: 1
title: Women overdue for cervical screening and the home kit
population: Women aged 30 to 65 in England overdue for cervical screening, plus the professionals who see them
geography: England
size_hint: 60
author: Test analyst
---

# Overdue for screening and the home kit — segmentation playbook (TEST DATA)

## Approach

- **Primary axis:** attitudinal — why she has not been screened (the barrier, not the person).
- **Secondary axis:** situational — deprivation, ethnicity, digital confidence.
- **Why:** a home kit removes some barriers (the examination, the appointment) and leaves others
  (trust, privacy at home, language, the follow-up). The reason predicts uptake better than age.
- **Match exactly on:** role (woman or professional). **Weight only:** region.

## Segments

| Segment | Share | Who they are | Source for share |
|---|---|---|---|
| Busy and meaning to | 25% | Working, often shifts or childcare; not against it, never finds the slot | analyst hypothesis |
| Examination avoiders | 20% | Embarrassment, pain, body image, past trauma; the speculum is the barrier | find |
| Never seen the invitation | 12% | Letters unopened, App messages unread; not a refusal | analyst hypothesis |
| Private at home | 10% | No privacy for post or a kit; partner or family reads letters | |
| Self-test doubters | 10% | Trust the nurse, not themselves; worry about a false all-clear | find |
| Needs support to take part | 8% | Language, literacy, learning disability; needs pictures or a helper | |
| Professionals | 15% | Practice nurses, GPs, community pharmacists, sexual health nurses | analyst hypothesis |

## Variables

### Exam aversion
- **Kind:** dial
- **What it is:** how strongly the in-person examination itself keeps her away.
- **Low (0):** does not mind it. **High (10):** will never lie on that bed.
- **By segment:** Examination avoiders 8–10; Busy and meaning to 2–4; Self-test doubters 1–3;
  Never seen the invitation 3–5.
- **Pushes:** emotional resistance up, risk aversion down for a home kit.
- **Evidence:** find — reasons women delay screening, embarrassment and pain.

### Self-test trust
- **Kind:** dial
- **What it is:** how much she believes a sample she took herself.
- **Low (0):** a self-test is worthless. **High (10):** as good as the nurse's.
- **By segment:** Self-test doubters 1–3; Examination avoiders 6–8; Busy and meaning to 6–8.
- **Evidence:** analyst hypothesis.

### How the invitation reaches her
- **Kind:** category
- **Labels:** NHS App, text, letter, never reaches her
- **By segment:** Never seen the invitation letter, never reaches her; Busy and meaning to text, NHS App.

## Rules of character

- Professionals answer for the women they see, never as patients themselves.
- Private at home: anything that arrives by post is a risk before it is a help.
- Everyone: speak about real places, real surgeries and real days, not about "screening" in general.

## Things I'm not sure about

- Whether "never seen the invitation" is really a separate group or busy women by another name.
- Whether self-test doubters would order a kit just to be told to come in anyway.
