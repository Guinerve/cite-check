from cite_check.parse import parse_report

REPORT = """# Energy report

Solar capacity grew by 24 percent in 2023 [see IEA](https://example.org/iea.html). Wind did not grow as fast.

Prices fell sharply in the second half of the year.[1] Storage deployments doubled.[^2]

The grid operator said demand was flat (https://example.org/aemo).

## References

[1]: https://example.org/prices
[^2]: https://example.org/storage "Storage report"
"""


def test_extracts_claims_with_inline_numeric_and_bare_citations():
    claims = parse_report(REPORT)
    by_text = {c.text: c for c in claims}
    assert by_text["Solar capacity grew by 24 percent in 2023."].urls == [
        "https://example.org/iea.html"
    ]
    assert any(
        c.urls == ["https://example.org/prices"] and c.text.startswith("Prices fell")
        for c in claims
    )
    assert any(c.urls == ["https://example.org/storage"] and "doubled" in c.text for c in claims)
    assert any(c.urls == ["https://example.org/aemo"] for c in claims)


def test_sentences_without_citations_are_not_claims():
    assert not any("Wind did not grow" in c.text for c in parse_report(REPORT))


def test_reference_definitions_and_headings_are_not_claims():
    claims = parse_report(REPORT)
    assert not any(
        c.text.startswith("References") or "example.org/prices" in c.text for c in claims
    )


def test_numbered_reference_list():
    text = "Output rose 5 percent last quarter [1].\n\n## References\n\n1. ABS. Quarterly output. https://example.org/abs\n"
    (c,) = parse_report(text)
    assert c.urls == ["https://example.org/abs"]


def test_html_input():
    html = '<p>The bridge opened in 1967 <a href="https://example.org/b">source</a>.</p>'
    (c,) = parse_report(html, is_html=True)
    assert "bridge opened in 1967" in c.text and c.urls == ["https://example.org/b"]


def test_line_numbers_survive_multiple_blank_lines():
    text = "# T\n\n\n\nFirst claim here is cited [a](https://example.org/a).\n\n\n\n\nSecond claim here is cited [b](https://example.org/b).\n"
    assert [c.line for c in parse_report(text)] == [5, 10]


def test_trailing_citation_anchor_is_not_part_of_the_claim_but_inline_links_keep_their_words():
    (a,) = parse_report("The bridge opened in 1932 [Wikipedia](https://example.org/b).\n")
    assert a.text == "The bridge opened in 1932." and a.urls == ["https://example.org/b"]
    (b,) = parse_report(
        "The [IEA](https://example.org/iea) reported that solar grew 24 percent in 2023.\n"
    )
    assert "IEA reported" in b.text


def test_missing_reference_is_kept_when_another_reference_resolves():
    (c,) = parse_report(
        "Output rose 5 percent last quarter [1][9].\n\n[1]: https://example.org/abs\n"
    )
    assert c.urls == ["https://example.org/abs"] and c.unresolved == ["9"]


def test_numbered_references_followed_by_another_section():
    text = (
        "Output rose 5 percent last quarter [1].\n\n## References\n\n"
        "1. ABS. Quarterly output. https://example.org/abs\n\n## Appendix\n\nMethod notes here.\n"
    )
    (c,) = parse_report(text)
    assert c.urls == ["https://example.org/abs"]


def test_numbered_references_in_html_report():
    html = (
        "<p>Output rose 5 percent last quarter [1].</p><h2>References</h2>"
        "<ol><li>1. ABS. Quarterly output. https://example.org/abs</li></ol><h2>Appendix</h2><p>1. Not a ref.</p>"
    )
    (c,) = parse_report(html, is_html=True)
    assert c.urls == ["https://example.org/abs"]
