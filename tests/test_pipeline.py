import httpx

from cite_check import check_report
from cite_check.judge import HeuristicJudge, OllamaJudge
from cite_check.report import render_html
from cite_check.sources import Fetcher, chunk_text, html_to_text

PAGE = ("<html><body><nav>menu</nav><p>The Calder Bridge opened in 1967 after four years of construction. "
        "It has a main span of 503 metres. About 98,000 vehicles cross it each weekday. "
        "Tolls were removed in 2008 after nineteen years of collection.</p><script>var x=1</script></body></html>")


def fetcher(tmp_path, routes):
    def handler(req):
        r = routes.get(str(req.url))
        return r if r is not None else httpx.Response(404)
    return Fetcher(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_html_text_extraction_drops_scripts_and_nav():
    t = html_to_text(PAGE)
    assert "Calder Bridge" in t and "var x" not in t and "menu" not in t


def test_chunks_overlap():
    assert len(chunk_text("One two three. Four five six. Seven eight nine. Ten eleven twelve.")) == 2


def test_end_to_end_verdicts_and_unreachable(tmp_path):
    routes = {"https://ex.test/bridge": httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}),
              "https://ex.test/paywall": httpx.Response(403)}
    report = (
        "The Calder Bridge opened in 1967 [a](https://ex.test/bridge).\n\n"
        "About 150,000 vehicles cross the Calder Bridge each weekday [a](https://ex.test/bridge).\n\n"
        "The bridge was designed by a Danish architect famous for opera houses [a](https://ex.test/bridge).\n\n"
        "Maintenance costs rose forty percent [b](https://ex.test/paywall).\n"
    )
    results = check_report(report, fetcher(tmp_path, routes), HeuristicJudge())
    labels = [r.verdict.label for r in results]
    assert labels == ["supported", "partial", "unsupported", "unreachable"]
    assert "98,000" in results[1].verdict.passage  # the passage shown is the one that contradicts the number
    assert "paywall" in results[3].verdict.reason or "403" in results[3].verdict.reason


def test_multiple_sources_take_the_best_verdict(tmp_path):
    routes = {"https://ex.test/bridge": httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}),
              "https://ex.test/other": httpx.Response(200, text="<p>" + "Unrelated gardening advice about tomatoes and soil. " * 10 + "</p>")}
    report = "The Calder Bridge opened in 1967 [a](https://ex.test/other) [b](https://ex.test/bridge).\n"
    (r,) = check_report(report, fetcher(tmp_path, routes), HeuristicJudge())
    assert r.verdict.label == "supported" and r.url == "https://ex.test/bridge"


def test_html_report_is_self_contained_and_escaped(tmp_path):
    routes = {"https://ex.test/bridge": httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})}
    results = check_report("The <b>Calder</b> Bridge opened in 1967 [a](https://ex.test/bridge).\n", fetcher(tmp_path, routes))
    out = render_html(results)
    assert "<script" not in out and "Supported" in out and "&lt;" not in out.split("<article")[0]


def test_llm_judge_parses_json_and_falls_back_on_error():
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"response": '{"verdict":"partial","reason":"number differs"}'})))
    v = OllamaJudge(http=ok).judge("claim text here now", [(0.9, "passage")])
    assert v.label == "partial" and v.reason == "number differs" and v.judge.startswith("ollama:")
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    v2 = OllamaJudge(http=bad).judge("claim text here now", [(0.9, "passage")])
    assert "heuristic" in v2.reason


def test_unresolved_reference_is_reported_not_dropped(tmp_path):
    results = check_report("Output grew forty percent last year [7].\n", fetcher(tmp_path, {}), HeuristicJudge())
    assert len(results) == 1 and results[0].verdict.label == "unreachable" and "no matching reference" in results[0].verdict.reason


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    from cite_check import cli

    rep = tmp_path / "r.md"
    rep.write_text("No citations at all in this report.\n")
    assert cli.main([str(rep)]) == 2  # nothing parsed is an error, not a pass
    rep.write_text("Output grew forty percent last year [7].\n")
    assert cli.main([str(rep)]) == 3  # could not be checked is not a pass


def test_llm_judge_survives_odd_json_shapes():
    for body in ('["verdict"]', "null", '{"verdict": 5}'):
        c = httpx.Client(transport=httpx.MockTransport(lambda r, b=body: httpx.Response(200, json={"response": b})))
        v = OllamaJudge(http=c).judge("claim text here now", [(0.9, "passage")])
        assert v.label in {"supported", "partial", "unsupported"} and "heuristic" in v.reason


def test_unwritable_cache_does_not_abort(tmp_path):
    f = Fetcher(cache_dir=tmp_path / "x", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}))))
    f.cache_dir = tmp_path / "does" / "not" / "exist"  # writes will fail
    assert f.get("https://ex.test/a").ok


def test_llm_supported_verdict_is_downgraded_when_the_claim_adds_a_number():
    body = '{"verdict":"supported","reason":"matches"}'
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"response": body})))
    j = OllamaJudge(http=c)
    ok = j.judge("Uluru is a World Heritage Site", [(0.9, "Uluru is listed as a UNESCO World Heritage Site.")])
    added = j.judge("Uluru has been a World Heritage Site since 1987", [(0.9, "Uluru is listed as a UNESCO World Heritage Site.")])
    assert ok.label == "supported" and added.label == "partial" and "1987" in added.reason
