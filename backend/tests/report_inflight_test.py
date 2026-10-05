"""One report proper at a time per session (2026-10-05): the browser's generate call can be cut
off by a timeout and retried while the first write is still running — the retry must join the
write in flight, not start a second report."""
import asyncio


def test_second_generate_joins_the_write_in_flight(monkeypatch):
    from app.api.v1 import reports

    calls = {"n": 0}

    async def slow_write(session_id, query, mode, question):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"id": f"r{calls['n']}", "question": "report", "answer": "done", "sources": None, "records": [], "structure": {}}

    monkeypatch.setattr(reports, "_write_report", slow_write)
    reports._inflight.clear()

    async def go():
        a, b = await asyncio.gather(reports.run_report("s1", "q"), reports.run_report("s1", "q"))
        other = await reports.run_report("s2", "q")           # another session is its own write
        again = await reports.run_report("s1", "q")           # once finished, a new call writes anew
        return a, b, other, again

    a, b, other, again = asyncio.new_event_loop().run_until_complete(go())
    assert a == b and a["id"] == "r1"
    assert other["id"] == "r2"
    assert again["id"] == "r3" and calls["n"] == 3
    assert not reports._inflight                              # nothing left registered
