"""Peers, sharing and the shared chat (2026-10-20).

Everyone signed in on the same email domain is a peer. A session's owner shares it with one or
more peers; for them it appears under *Shared with you* on the landing page and opens as a chat
page where the owner and the people it is shared with talk to each other and, with `@report`,
to the report agent — the same Ask-Report that answers from the session's records, evidence and
transcript. Sharing (since the follow-up the same day) grants the whole session — every tab, every tool and
the chat — through `get_owned_session`; only deleting it and deciding who it is shared with stay
the owner's (`strict=True`).
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, email_domain, ensure_profile, get_accessible_session, get_current_user, get_owned_session, owns
from app.core.database import get_db
from app.core.redis_client import publish, session_channel
from app.models.profile import Profile
from app.models.session import AnalysisSession
from app.models.share import SessionShare, SharedMessage

router = APIRouter(tags=["sharing"])

REPORT_MENTION = re.compile(r"@report\b", re.I)
REPORT_AUTHOR = "Report"
MAX_MESSAGES = 300


def _uid(v) -> str:
    return str(v or "").replace("-", "").lower()


def _name(p: Optional[Profile], fallback: str = "") -> str:
    if p is None:
        return fallback
    return (p.display_name or "").strip() or (p.email or "").split("@")[0] or fallback


def _peer(p: Profile) -> dict:
    return {"id": p.id, "email": p.email, "name": _name(p)}


def _msg(m: SharedMessage) -> dict:
    return {"id": m.id, "session_id": m.session_id, "user_id": m.user_id, "author_name": m.author_name, "kind": m.kind,
            "content": m.content, "reply_to": m.reply_to, "created_at": m.created_at.isoformat() if m.created_at else None}


async def _domain_profiles(user: AuthUser, db: AsyncSession) -> list[Profile]:
    """Everyone on the caller's email domain (everyone, in dev mode)."""
    rows = (await db.execute(select(Profile).order_by(Profile.created_at.asc()))).scalars().all()
    dom = email_domain(user.email)
    if user.is_dev or not dom:
        return list(rows)
    return [p for p in rows if email_domain(p.email) == dom]


# ── peers ──────────────────────────────────────────────────────────────────────

@router.get("/peers")
async def list_peers(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The people on the caller's email domain, without the caller."""
    await ensure_profile(user, db)
    rows = [p for p in await _domain_profiles(user, db) if _uid(p.id) != _uid(user.id)]
    return sorted((_peer(p) for p in rows), key=lambda x: (x["name"] or "").lower())


# ── shares on a session (owner's side) ──────────────────────────────────────────

class SharesBody(BaseModel):
    user_ids: list[str]


async def _members(session: AnalysisSession, db: AsyncSession) -> list[dict]:
    shares = (await db.execute(select(SessionShare).where(SessionShare.session_id == session.id).order_by(SessionShare.created_at))).scalars().all()
    ids = [s.user_id for s in shares] + ([session.user_id] if session.user_id else [])
    profiles = {_uid(p.id): p for p in (await db.execute(select(Profile).where(Profile.id.in_(ids)))).scalars().all()} if ids else {}
    out = []
    if session.user_id:
        p = profiles.get(_uid(session.user_id))
        out.append({"user_id": session.user_id, "email": p.email if p else None, "name": _name(p, "owner"), "is_owner": True, "created_at": None})
    for s in shares:
        p = profiles.get(_uid(s.user_id))
        out.append({"user_id": s.user_id, "email": p.email if p else None, "name": _name(p, "colleague"), "is_owner": False,
                    "created_at": s.created_at.isoformat() if s.created_at else None})
    return out


@router.get("/sessions/{session_id}/shares")
async def get_shares(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db, strict=True)
    return {"members": await _members(session, db)}


@router.put("/sessions/{session_id}/shares")
async def set_shares(session_id: str, body: SharesBody, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Replace the set of colleagues this session is shared with. Only peers on the owner's
    domain can be named (400 otherwise); the owner is never a share."""
    session = await get_owned_session(session_id, user, db, strict=True)
    await ensure_profile(user, db)
    peers = {_uid(p.id): p for p in await _domain_profiles(user, db)}
    wanted: list[str] = []
    for raw in body.user_ids:
        k = _uid(raw)
        if not k or k == _uid(user.id) or (session.user_id and k == _uid(session.user_id)):
            continue
        p = peers.get(k)
        if p is None:
            raise HTTPException(status_code=400, detail="You can only share with people on your own email domain")
        if p.id not in wanted:
            wanted.append(p.id)
    existing = (await db.execute(select(SessionShare).where(SessionShare.session_id == session_id))).scalars().all()
    have = {_uid(s.user_id): s for s in existing}
    for k, s in have.items():
        if k not in {_uid(w) for w in wanted}:
            await db.delete(s)
    for uid in wanted:
        if _uid(uid) not in have:
            db.add(SessionShare(id=str(uuid.uuid4()), session_id=session_id, user_id=uid, shared_by=user.id if not user.is_dev else None, created_at=datetime.utcnow()))
    await db.commit()
    await db.refresh(session)
    members = await _members(session, db)
    await publish(session_channel(session_id), {"type": "shares_changed", "members": members})
    return {"members": members}


@router.delete("/sessions/{session_id}/shares/{user_id}")
async def remove_share(session_id: str, user_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The owner removes a colleague, or a colleague leaves."""
    session = (await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not (owns(session, user) or _uid(user_id) == _uid(user.id)):
        raise HTTPException(status_code=404, detail="Session not found")
    rows = (await db.execute(select(SessionShare).where(SessionShare.session_id == session_id))).scalars().all()
    hit = [s for s in rows if _uid(s.user_id) == _uid(user_id)]
    for s in hit:
        await db.delete(s)
    await db.commit()
    return {"removed": len(hit)}


# ── shared with me ─────────────────────────────────────────────────────────────

@router.get("/shared-sessions")
async def shared_sessions(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every session with sharing on it that involves the caller, newest share first: the ones
    colleagues shared with them (`direction: with_you`) and the ones they shared out
    (`direction: by_you`), each with the owner, who is in the chat and when it last moved."""
    mine = (await db.execute(select(SessionShare).where(SessionShare.user_id == user.id))).scalars().all()
    own_sessions = [] if user.is_dev else (await db.execute(select(AnalysisSession.id).where(AnalysisSession.user_id == user.id))).scalars().all()
    out_shares = (await db.execute(select(SessionShare).where(SessionShare.session_id.in_(own_sessions)))).scalars().all() if own_sessions else []
    if not mine and not out_shares:
        return []
    ids = list({s.session_id for s in mine} | {s.session_id for s in out_shares})
    sessions = {s.id: s for s in (await db.execute(select(AnalysisSession).where(AnalysisSession.id.in_(ids), AnalysisSession.deleted_at.is_(None)))).scalars().all()}
    all_shares = (await db.execute(select(SessionShare).where(SessionShare.session_id.in_(ids)).order_by(SessionShare.created_at))).scalars().all()
    people_ids = list({s.user_id for s in all_shares} | {s.user_id for s in sessions.values() if s.user_id})
    people = {_uid(p.id): p for p in (await db.execute(select(Profile).where(Profile.id.in_(people_ids)))).scalars().all()} if people_ids else {}
    stats = {sid: (n, last) for sid, n, last in (await db.execute(
        select(SharedMessage.session_id, func.count(SharedMessage.id), func.max(SharedMessage.created_at)).where(SharedMessage.session_id.in_(ids)).group_by(SharedMessage.session_id))).all()}
    by_session: dict[str, list[SessionShare]] = {}
    for sh in all_shares:
        by_session.setdefault(sh.session_id, []).append(sh)
    mine_by_session = {sh.session_id: sh for sh in mine}
    out = []
    for sid, s in sessions.items():
        shares = by_session.get(sid, [])
        if not shares:
            continue
        owner = people.get(_uid(s.user_id)) if s.user_id else None
        is_owner = bool(s.user_id) and _uid(s.user_id) == _uid(user.id)
        colleagues = [people.get(_uid(sh.user_id)) for sh in shares]
        names = [_name(p, "colleague") for p in colleagues]
        n, last = stats.get(sid, (0, None))
        shared_at = mine_by_session[sid].created_at if sid in mine_by_session else max(sh.created_at for sh in shares)
        out.append({
            "id": s.id, "title": s.title, "query": s.query, "status": getattr(s.status, "value", s.status), "agent_count": s.agent_count,
            "created_at": s.created_at, "updated_at": s.updated_at,
            "direction": "by_you" if is_owner else "with_you",
            "owner": {"id": s.user_id, "email": owner.email if owner else None, "name": _name(owner, "owner")},
            "with": names,
            "shared_at": shared_at, "members": len(shares) + (1 if s.user_id else 0),
            "messages": int(n or 0), "last_message_at": last.isoformat() if isinstance(last, datetime) else last,
        })
    out.sort(key=lambda x: str(x["shared_at"] or ""), reverse=True)
    return out


# ── the shared chat ────────────────────────────────────────────────────────────

async def _latest_report(session_id: str, db: AsyncSession) -> Optional[dict]:
    from app.models.report import ReportQuery
    rows = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id).order_by(ReportQuery.created_at.desc()).limit(40))).scalars().all()
    if not rows:
        return None
    proper = [r for r in rows if getattr(r, "structure", None)]
    r = proper[0] if proper else rows[0]
    return {"id": r.id, "question": r.question, "answer": r.answer, "is_report": bool(getattr(r, "structure", None)),
            "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None}


@router.get("/sessions/{session_id}/shared-chat")
async def get_shared_chat(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_accessible_session(session_id, user, db)
    await ensure_profile(user, db)
    members = await _members(session, db)
    msgs = (await db.execute(select(SharedMessage).where(SharedMessage.session_id == session_id).order_by(SharedMessage.created_at.desc()).limit(MAX_MESSAGES))).scalars().all()
    owner = next((m for m in members if m.get("is_owner")), None)
    return {
        "session": {"id": session.id, "title": session.title, "query": session.query, "status": getattr(session.status, "value", session.status),
                    "agent_count": session.agent_count, "created_at": session.created_at, "updated_at": session.updated_at},
        "owner": {"id": session.user_id, "email": owner["email"] if owner else None, "name": owner["name"] if owner else "owner"},
        "you": {"id": user.id, "is_owner": owns(session, user) and (user.is_dev or _uid(session.user_id) == _uid(user.id)), "can_open": True},
        "members": members,
        "messages": [_msg(m) for m in reversed(msgs)],
        "report": await _latest_report(session_id, db),
    }


class MessageBody(BaseModel):
    content: str


async def _display_name(user: AuthUser, db: AsyncSession) -> str:
    if user.is_dev:
        return "you (dev)"
    p = (await db.execute(select(Profile).where(Profile.id == user.id))).scalar_one_or_none()
    return _name(p, (user.email or "").split("@")[0] or "someone")


async def _answer_as_report(session_id: str, original_query: str, asked: str, reply_to: str) -> None:
    """The report agent's turn, in the background: the question with the last few lines of the
    chat for continuity, answered by Ask-Report and posted as a message of its own."""
    from app.core.database import AsyncSessionLocal
    from app.services.simulation.report_generator import answer_report_query
    async with AsyncSessionLocal() as db:
        recent = (await db.execute(select(SharedMessage).where(SharedMessage.session_id == session_id, SharedMessage.id != reply_to)
                                   .order_by(SharedMessage.created_at.desc()).limit(8))).scalars().all()
        lines = [f"- {m.author_name}: {m.content[:300]}" for m in reversed(recent) if (m.content or "").strip()]
        question = asked
        if lines:
            question = "This question was asked in a conversation between colleagues about the session. The last few lines, for context:\n" + "\n".join(lines) + f"\n\nTHE QUESTION: {asked}"
        try:
            answer, _ = await answer_report_query(session_id, original_query, question, db)
        except Exception as e:  # noqa: BLE001 — the chat shows the error as the agent's reply, never a dropped turn
            from app.core.llm_errors import friendly_llm_error
            print(f"[sharing] report reply failed for {session_id}: {type(e).__name__}: {e}")
            answer = friendly_llm_error(e)
        m = SharedMessage(id=str(uuid.uuid4()), session_id=session_id, user_id=None, author_name=REPORT_AUTHOR, kind="report",
                          content=answer, reply_to=reply_to, created_at=datetime.utcnow())
        db.add(m)
        await db.commit()
        await db.refresh(m)
    await publish(session_channel(session_id), {"type": "shared_message", "message": _msg(m)})


_report_tasks: dict[str, asyncio.Task] = {}


@router.post("/sessions/{session_id}/shared-chat")
async def post_shared_message(session_id: str, body: MessageBody, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A message from one of the people in the chat. `@report` anywhere in it asks the report
    agent, which answers in a message of its own (over the websocket, and on the next load)."""
    session = await get_accessible_session(session_id, user, db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Say something")
    m = SharedMessage(id=str(uuid.uuid4()), session_id=session_id, user_id=None if user.is_dev else user.id, author_name=await _display_name(user, db),
                      kind="user", content=content[:6000], reply_to=None, created_at=datetime.utcnow())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    out = _msg(m)
    await publish(session_channel(session_id), {"type": "shared_message", "message": out})
    asks_report = bool(REPORT_MENTION.search(content))
    if asks_report:
        asked = REPORT_MENTION.sub("", content).strip(" ,:;-—") or "Summarise what the report found, for the group."
        t = asyncio.create_task(_answer_as_report(session_id, session.query, asked, m.id))
        _report_tasks[m.id] = t
        t.add_done_callback(lambda _t, k=m.id: _report_tasks.pop(k, None))
    return {"message": out, "report_pending": asks_report}
