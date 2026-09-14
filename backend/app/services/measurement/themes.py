"""Theme coding — free-text reasons into a shared, short list of themes.

The generic Ask instrument records each agent's "key factor" as a few free words rather than
an enum, so it can serve any question. One cheap model call afterwards reads every factor in
the population and codes them into at most `MAX_THEMES` themes; the theme is written back
onto each stored answer as `theme`, so everything that reads a driver (driver mix, coded
reasons among movers, CSV) works exactly as it does for an enum field.

An experiment codes all its arms in ONE pass so the theme vocabulary is shared between them.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.measurement import Probe, ProbeAnswer
from app.services.evidence.llm import analyze, arr, i, obj, s

MAX_THEMES = 7
MAX_UNIQUE = 400            # unique factors sent in one call; beyond this we sample
FACTOR_KEY = "key_factor"
THEME_KEY = "theme"

CODING_SCHEMA = obj({
    "themes": arr(obj({
        "label": s("2-4 word theme label, in the language of the answers, e.g. 'peak-time cost'"),
        "items": arr(i("indices of the factors that belong to this theme")),
    }), "At most 7 themes covering every factor; one theme per factor", max_items=MAX_THEMES),
})

SYSTEM = (
    "You code open-ended survey answers into themes. You are given numbered short phrases, each "
    "the single factor that decided one person's answer. Group them into at most 7 themes that a "
    "client could act on. Every index must appear in exactly one theme. Labels are short noun "
    "phrases, specific to this material (not 'other' or 'misc'). Use the record_answer tool."
)


def _norm(t: str) -> str:
    return " ".join(str(t or "").lower().split())[:120]


async def code_factors(factors: list[str], *, session_id: Optional[str], model: str) -> list[str]:
    """One theme label per input factor (aligned by position). Empty factors get ''."""
    uniq: dict[str, int] = {}
    order: list[str] = []
    for f in factors:
        n = _norm(f)
        if n and n not in uniq:
            uniq[n] = len(order)
            order.append(n)
    if not order:
        return ["" for _ in factors]
    sent = order[:MAX_UNIQUE]
    listing = "\n".join(f"{k}. {t}" for k, t in enumerate(sent))
    user = f"FACTORS ({len(sent)}):\n{listing}\n\nCode them into themes."
    result = await analyze(CODING_SCHEMA, SYSTEM, user, session_id=session_id, label="probe:themes",
                           model=model, max_tokens=1500)
    label_of: dict[int, str] = {}
    for theme in result.get("themes") or []:
        label = str(theme.get("label") or "").strip()
        for idx in theme.get("items") or []:
            try:
                k = int(idx)
            except (TypeError, ValueError):
                continue
            if 0 <= k < len(sent) and k not in label_of and label:
                label_of[k] = label
    # Anything the model missed (or beyond MAX_UNIQUE) keeps its own words as its theme.
    out = []
    for f in factors:
        n = _norm(f)
        if not n:
            out.append("")
            continue
        k = uniq.get(n)
        out.append(label_of.get(k, n) if k is not None else n)
    return out


async def apply_themes(probe_ids: list[str], *, model: Optional[str] = None) -> None:
    """Code the key factors of every answer in `probe_ids` together, write `theme` onto each
    answer, and refresh each probe's aggregates. Safe to call twice (recodes)."""
    from app.services.measurement import instruments

    if not probe_ids:
        return
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ProbeAnswer).where(ProbeAnswer.probe_id.in_(probe_ids)).order_by(ProbeAnswer.created_at)
        )).scalars().all()
        if not rows:
            return
        session_id = rows[0].session_id
        factors = [str((r.answer or {}).get(FACTOR_KEY) or "") for r in rows]
        try:
            themes = await code_factors(factors, session_id=session_id,
                                        model=model or get_settings().agent_model("fast"))
        except Exception as e:  # noqa: BLE001 — coding is a convenience; the run must not fail on it
            print(f"[themes] coding failed, keeping raw factors: {type(e).__name__}: {e}")
            themes = [_norm(f) for f in factors]
        for r, t in zip(rows, themes):
            ans = dict(r.answer or {})
            ans[THEME_KEY] = t
            r.answer = ans
        await db.commit()

        # Re-aggregate each probe now that every answer carries a theme.
        from app.services.measurement.probe import segments_for
        from app.models.agent import SpawnedAgent
        for pid in probe_ids:
            probe = await db.get(Probe, pid)
            if not probe:
                continue
            inst = instruments.get(probe.instrument)
            if not inst:
                continue
            pairs = (await db.execute(
                select(ProbeAnswer, SpawnedAgent)
                .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
                .where(ProbeAnswer.probe_id == pid)
            )).all()
            agg_rows = [{
                "agent_id": a.agent_id,
                "agent": {"name": getattr(ag, "name", ""), "role": getattr(ag, "role", ""),
                          "avatar_color": getattr(ag, "avatar_color", "")},
                "answer": a.answer or {},
                "segments": segments_for(ag) if ag else {},
            } for a, ag in pairs]
            agg_rows.sort(key=lambda r: r["agent_id"])
            probe.aggregates = inst.aggregate(agg_rows, dict(probe.spec or {}))
        await db.commit()
