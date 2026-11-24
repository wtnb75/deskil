"""timeline.py: view model and the self-contained HTML page."""

import json
import re

import timeline


def visit(state, start, end, *, gate=False, tok=100, agents=(), n=1):
    base = {
        "state": state,
        "visit": n,
        "start": f"2026-11-24T10:00:{start:02d}.000+00:00",
        "end": f"2026-11-24T10:00:{end:02d}.000+00:00",
        "gate": gate,
        "open": False,
        "turns": 1,
        "tool_calls": 0,
        "sub_total": 0,
        "agents": list(agents),
    }
    if tok is None:
        base.update(input=None, cache_create=None, cache_read=None, output=None)
    else:
        base.update(input=tok, cache_create=0, cache_read=0, output=0)
    return base


def agent(name, start, end, tok):
    return {
        "name": name,
        "start": f"2026-11-24T10:00:{start:02d}.000+00:00",
        "end": f"2026-11-24T10:00:{end:02d}.000+00:00",
        "input": tok,
        "cache_create": 0,
        "cache_read": 0,
        "output": 0,
        "turns": 1,
        "tool_calls": 0,
    }


def build(tl, definition="a/b/c/flow.toml"):
    return timeline.build_view(run_id="r1", definition=definition, timeline=tl)


def test_build_view_labels_repeated_states_with_visit_number():
    view = build(
        [
            visit("write", 0, 10, n=1),
            visit("test", 10, 20),
            visit("write", 20, 30, n=2),
        ]
    )
    assert [v["label"] for v in view["visits"]] == ["write #1", "test", "write #2"]
    assert view["note"] == "c/flow.toml"
    assert view["total_sec"] == 30


def test_build_view_totals_include_subagents():
    view = build(
        [
            visit("review", 0, 30, tok=10, agents=[agent("a", 0, 10, 5)]),
            visit("gate", 30, 50, gate=True, tok=0),
        ]
    )
    assert view["tokens"] == 15
    assert view["wait_sec"] == 20
    assert view["visits"][0]["tok"] == 10
    assert view["visits"][0]["subs"] == [["a", 0.0, 10.0, 5]]


def test_build_view_none_tokens_are_unknown_not_zero():
    view = build([visit("x", 0, 10, tok=None)])
    v = view["visits"][0]
    assert (v["known"], v["tok"]) == (False, 0)


def test_build_view_clamps_subagent_offsets_into_the_visit():
    view = build(
        [visit("r", 10, 20, agents=[agent("a", 5, 8, 1), agent("b", 18, 40, 1)])]
    )
    subs = view["visits"][0]["subs"]
    assert subs[0][1] == 0
    for _, off, dur, _ in subs:
        assert off >= 0 and off + dur <= 10


def test_build_view_zero_length_visit_has_no_subs():
    view = build([visit("r", 10, 10, agents=[agent("a", 10, 11, 1)])])
    assert view["visits"][0]["sec"] == 0
    assert view["visits"][0]["subs"] == []


def test_build_view_empty_timeline():
    view = build([])
    assert view["total_sec"] == 0
    assert view["visits"] == []
    assert view["tokens"] == 0


def _extract(html):
    m = re.search(
        r'<script type="application/json" id="data">(.*?)</script>', html, re.DOTALL
    )
    assert m
    return json.loads(m.group(1))


def test_render_html_embeds_data_that_roundtrips():
    views = [
        build([visit('a</script><!--"&日本語', 0, 5)]),
        build([]),
    ]
    views[0]["id"] = "x</script> "
    html = timeline.render_html(views)
    assert _extract(html)["runs"] == views
    assert html.count("</script>") == 2


def test_render_html_has_no_external_references():
    html = timeline.render_html([build([visit("a", 0, 5)])])
    assert "http://" not in html and "https://" not in html


def test_render_html_is_a_complete_document():
    html = timeline.render_html([])
    assert html.startswith("<!doctype html>")
    assert "<title>Flow Timeline</title>" in html
    assert "prefers-color-scheme" in html
    assert "__DATA__" not in html


def test_render_html_handles_no_runs():
    html = timeline.render_html([])
    assert _extract(html) == {"runs": []}
