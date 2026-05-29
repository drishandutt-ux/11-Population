import asyncio
import json
from typing import Any

# In-process pub/sub — no Redis needed
_subscribers: dict[str, list[asyncio.Queue]] = {}


async def publish(channel: str, event: dict[str, Any]):
    payload = json.dumps(event)
    for q in list(_subscribers.get(channel, [])):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def subscribe(channel: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.setdefault(channel, []).append(q)
    return q


def unsubscribe(channel: str, q: asyncio.Queue):
    subs = _subscribers.get(channel, [])
    if q in subs:
        subs.remove(q)


def session_channel(session_id: str) -> str:
    return f"session:{session_id}"
