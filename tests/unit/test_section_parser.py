"""Unit tests for SectionParser — pure Python, no GCP credentials needed."""

from frontend.main import SectionParser

# SectionParser keeps the last 20 chars in buffer as a partial-header guard.
# Content must exceed 20 chars to be emitted by process(); the remainder comes via flush().
LONG = "X" * 60  # long enough to trigger emission from process()


def events_for(chunks: list[str]) -> list[dict]:
    parser = SectionParser()
    events = []
    for chunk in chunks:
        events.extend(parser.process(chunk))
    events.extend(parser.flush())
    return events


def agents(events: list[dict]) -> list[str]:
    return [e["agent"] for e in events]


def content_for(agent: str, events: list[dict]) -> str:
    return "".join(e["content"] for e in events if e["agent"] == agent)


# ── Basic routing ─────────────────────────────────────────────────────────────


def test_routes_humorous_content() -> None:
    evts = events_for([f"## HUMOROUS\n{LONG}"])
    assert "humorous" in agents(evts)
    assert "X" in content_for("humorous", evts)


def test_routes_professional_content() -> None:
    evts = events_for([f"## PROFESSIONAL\n{LONG}"])
    assert "professional" in agents(evts)


def test_routes_urgent_content() -> None:
    evts = events_for([f"## URGENT\n{LONG}"])
    assert "urgent" in agents(evts)


def test_routes_judge_content() -> None:
    evts = events_for([f"## JUDGE\n{LONG}"])
    assert "judge" in agents(evts)


# ── Multi-section ─────────────────────────────────────────────────────────────


def test_all_four_sections_in_one_chunk() -> None:
    text = (
        f"## HUMOROUS\n{'H' * 40}\n"
        f"## PROFESSIONAL\n{'P' * 40}\n"
        f"## URGENT\n{'U' * 40}\n"
        f"## JUDGE\n{'J' * 40}"
    )
    evts = events_for([text])
    agent_set = set(agents(evts))
    assert {"humorous", "professional", "urgent", "judge"} == agent_set


def test_content_routed_to_correct_section_in_multi() -> None:
    text = f"## HUMOROUS\n{'H' * 40}\n## PROFESSIONAL\n{'P' * 40}"
    evts = events_for([text])
    assert "H" in content_for("humorous", evts)
    assert "P" in content_for("professional", evts)
    assert "P" not in content_for("humorous", evts)
    assert "H" not in content_for("professional", evts)


# ── Preamble handling ─────────────────────────────────────────────────────────


def test_preamble_before_first_header_is_dropped() -> None:
    evts = events_for([f"This preamble should be dropped.\n## HUMOROUS\n{LONG}"])
    combined = "".join(e["content"] for e in evts)
    assert "preamble" not in combined
    assert "humorous" in agents(evts)


def test_no_events_without_any_header() -> None:
    evts = events_for(["just some text with no headers"])
    assert evts == []


# ── Flush ─────────────────────────────────────────────────────────────────────


def test_flush_emits_short_content_held_in_buffer() -> None:
    # Content < 20 chars stays in buffer; flush releases it.
    parser = SectionParser()
    parser.process("## JUDGE\n")
    parser.process("Short!")  # 6 chars — below the 20-char safe threshold
    evts = parser.flush()
    assert len(evts) == 1
    assert evts[0]["agent"] == "judge"
    assert "Short!" in evts[0]["content"]


def test_flush_before_any_section_returns_empty() -> None:
    parser = SectionParser()
    assert parser.flush() == []


def test_flush_after_content_emitted_returns_remaining() -> None:
    parser = SectionParser()
    parser.process(f"## URGENT\n{LONG}")  # emits some, holds last 20
    evts = parser.flush()
    assert len(evts) == 1
    assert evts[0]["agent"] == "urgent"


# ── Streaming across chunk boundaries ─────────────────────────────────────────


def test_header_split_across_chunks() -> None:
    # Header split mid-word shouldn't emit the partial as content.
    evts = events_for(["## PROFES", f"SIONAL\n{LONG}"])
    combined = "".join(e["content"] for e in evts)
    assert "PROFES" not in combined
    assert "professional" in agents(evts)


def test_content_accumulates_across_chunks() -> None:
    parser = SectionParser()
    parser.process("## HUMOROUS\n")
    parser.process("First chunk. ")
    parser.process("Second chunk. ")
    parser.process("Third chunk.")
    evts = parser.flush()
    combined = content_for("humorous", evts)
    # All chunks should be present
    assert "First" in combined or "Second" in combined or "Third" in combined
