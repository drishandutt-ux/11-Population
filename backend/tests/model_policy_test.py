"""Model tier policy (2026-10-23): Fast = Haiku everywhere, Pro = Sonnet, Opus never."""
import asyncio

from app.core import model_policy as mp
from app.core.monitoring import tracked_messages_create


def test_tier_overrides_requested_model():
    assert mp.enforce("claude-sonnet-4-6", "fast") == mp.HAIKU
    assert mp.enforce("claude-opus-4-5", "fast") == mp.HAIKU
    assert mp.enforce("claude-haiku-4-5-20251001", "pro") == mp.SONNET
    assert mp.enforce("claude-opus-4-5-20251101", "pro") == mp.SONNET


def test_no_session_clamps_opus_but_keeps_haiku_and_sonnet():
    assert mp.enforce("claude-opus-4-5-20251101", None) == mp.SONNET
    assert mp.enforce("claude-fable-5-1", None) == mp.SONNET
    assert mp.enforce("claude-haiku-4-5-20251001", None) == "claude-haiku-4-5-20251001"
    assert mp.enforce("claude-sonnet-4-6", None) == "claude-sonnet-4-6"
    assert mp.enforce(None, None) == mp.SONNET


def test_settings_ignore_env_model_overrides(monkeypatch):
    from app.core.config import Settings
    s = Settings(model_pro_orchestration="claude-opus-4-5", model_orchestration="claude-opus-4-5")
    assert s.orchestration_model("pro") == mp.SONNET
    assert s.orchestration_model("fast") == mp.HAIKU


class _Msgs:
    def __init__(self):
        self.seen = []

    async def create(self, **kw):
        self.seen.append(kw["model"])
        return None


class _Client:
    def __init__(self):
        self.messages = _Msgs()


def test_tracked_create_sends_the_session_tier_model():
    c = _Client()
    mp.remember("sess-fast", "fast")
    mp.remember("sess-pro", "pro")

    async def go():
        await tracked_messages_create(c, session_id="sess-fast", model="claude-opus-4-5", max_tokens=1, messages=[])
        await tracked_messages_create(c, session_id="sess-pro", model="claude-haiku-4-5-20251001", max_tokens=1, messages=[])
        await tracked_messages_create(c, model="claude-opus-4-5-20251101", max_tokens=1, messages=[])

    asyncio.run(go())
    assert c.messages.seen == [mp.HAIKU, mp.SONNET, mp.SONNET]
