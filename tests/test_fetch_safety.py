"""The fetcher reads URLs from untrusted reports. It must not reach private hosts or read unbounded bodies."""

import httpx
import pytest

from cite_check.sources import BlockedHostError, Fetcher, PublicOnlyTransport

TEXT = (
    "<p>" + "The Calder Bridge opened in 1967 after four years of construction work. " * 5 + "</p>"
)
PUBLIC = {"public.test": "93.184.215.14", "rebind.test": "93.184.215.15"}


def resolver(host: str, port: int) -> list[str]:
    if host in PUBLIC:
        return [PUBLIC[host]]
    if host == "mixed.test":
        return ["93.184.215.16", "10.0.0.5"]
    return [host]  # IP literals resolve to themselves


def guarded_fetcher(tmp_path, handler) -> tuple[Fetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    transport = PublicOnlyTransport(inner=httpx.MockTransport(record), resolver=resolver)
    client = httpx.Client(transport=transport, follow_redirects=True)
    return Fetcher(cache_dir=tmp_path, http=client), seen


def ok(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=TEXT, headers={"content-type": "text/html"})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://192.168.1.1/",
        "http://100.100.100.100/",  # carrier grade NAT range, used by Tailscale
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://mixed.test/",
    ],
)
def test_private_and_local_hosts_are_blocked(tmp_path, url):
    def localhost_resolver(host, port):
        return ["127.0.0.1"] if host == "localhost" else resolver(host, port)

    seen: list[httpx.Request] = []
    transport = PublicOnlyTransport(
        inner=httpx.MockTransport(lambda r: seen.append(r) or ok(r)), resolver=localhost_resolver
    )
    f = Fetcher(cache_dir=tmp_path, http=httpx.Client(transport=transport))
    src = f.get(url)
    assert not src.ok and src.error.startswith("blocked")
    assert seen == []  # no request left the machine


def test_redirect_to_a_private_host_is_blocked(tmp_path):
    def handler(req):
        if req.url.host == PUBLIC["public.test"]:
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return ok(req)

    f, seen = guarded_fetcher(tmp_path, handler)
    src = f.get("http://public.test/start")
    assert not src.ok and src.error.startswith("blocked")
    assert [r.url.host for r in seen] == [PUBLIC["public.test"]]


def test_public_host_is_pinned_to_the_checked_address(tmp_path):
    f, seen = guarded_fetcher(tmp_path, ok)
    assert f.get("https://public.test/page").ok
    (req,) = seen
    assert req.url.host == PUBLIC["public.test"]  # connects to the address that passed the check
    assert req.headers["host"] == "public.test"
    assert req.extensions["sni_hostname"] == "public.test"  # TLS still verifies the real name


def test_non_http_schemes_are_blocked():
    t = PublicOnlyTransport(inner=httpx.MockTransport(ok), resolver=resolver)
    with pytest.raises(BlockedHostError):
        t.handle_request(httpx.Request("GET", "ftp://public.test/file"))


def test_allow_private_lets_local_hosts_through(tmp_path):
    t = PublicOnlyTransport(inner=httpx.MockTransport(ok), resolver=resolver, allow_private=True)
    f = Fetcher(cache_dir=tmp_path, http=httpx.Client(transport=t))
    assert f.get("http://127.0.0.1/doc").ok


def test_default_fetcher_blocks_private_hosts(tmp_path):
    assert Fetcher(cache_dir=tmp_path).get("http://127.0.0.1:9/").error.startswith("blocked")


def test_body_over_the_limit_is_refused_without_reading_it_all(tmp_path):
    sent = []

    def stream():
        for _ in range(1000):
            sent.append(1)
            yield b"x" * 1024

    f = Fetcher(
        cache_dir=tmp_path,
        max_bytes=10_000,
        http=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=stream()))
        ),
    )
    src = f.get("https://ex.test/huge")
    assert src.error == "too large (over 10000 bytes)"
    assert len(sent) < 20  # stopped early


def test_declared_length_over_the_limit_is_refused(tmp_path):
    big = httpx.Response(200, headers={"content-length": "999999999"}, content=b"")
    f = Fetcher(
        cache_dir=tmp_path,
        max_bytes=1000,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: big)),
    )
    assert f.get("https://ex.test/big").error.startswith("too large")


def test_binary_content_types_are_not_parsed_as_text(tmp_path):
    img = httpx.Response(
        200, content=b"\x89PNG" + b"\x00" * 500, headers={"content-type": "image/png"}
    )
    f = Fetcher(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: img)))
    assert f.get("https://ex.test/a.png").error == "unsupported content type: image/png"


def test_html_page_at_a_pdf_url_is_read_as_html(tmp_path):
    page = httpx.Response(200, text=TEXT, headers={"content-type": "text/html; charset=utf-8"})
    f = Fetcher(
        cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: page))
    )
    assert f.get("https://ex.test/paper.pdf").ok


def test_unknown_charset_falls_back_to_utf8(tmp_path):
    page = httpx.Response(
        200, content=TEXT.encode(), headers={"content-type": "text/html; charset=klingon"}
    )
    f = Fetcher(
        cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: page))
    )
    assert f.get("https://ex.test/odd").ok
