from modules.utils import latex_escape, latex_escape_url


def test_latex_escape_basic_chars():
    s = r"A&B%_$#"
    out = latex_escape(s)
    # Spot-check key escapes
    assert r"\&" in out
    assert r"\%" in out
    assert r"\_" in out
    assert r"\#" in out


def test_latex_escape_url():
    url = "https://example.com/a&b?x=1#frag"
    out = latex_escape_url(url)
    assert r"\&" in out
    assert r"\#" in out

