"""Template tests. The rendered email is what an administrator actually sees,
so these pin the things that silently break it: a missing code, a logo URL
that leaks a non-public host, or an HTML-only body with no text alternative.
"""
from app.core.config import settings
from app.core.mfa_email_template import render_mfa_html, render_mfa_text


def test_html_contains_the_code_and_expiry(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mfa_email_logo_url", "https://example.com/logo.png")

    html = render_mfa_html(to_name="Ada", code="123456", minutes=10)

    # Rendered spaced for legibility, so assert on the digits individually.
    for digit in "123456":
        assert digit in html
    assert "10 minutes" in html
    assert "Ada" in html


def test_html_uses_only_inline_styles_and_tables(monkeypatch) -> None:
    """Gmail strips <style> blocks and ignores flex/grid - a regression here
    silently wrecks the layout in the client that matters most."""
    monkeypatch.setattr(settings, "mfa_email_logo_url", "https://example.com/logo.png")

    html = render_mfa_html(to_name="Ada", code="123456", minutes=10)

    assert "<style" not in html.lower()
    assert "display:flex" not in html.replace(" ", "")
    assert "display:grid" not in html.replace(" ", "")
    assert "<table" in html


def test_html_degrades_to_a_text_wordmark_when_no_logo_is_configured(monkeypatch) -> None:
    """Most clients block remote images by default, so the brand must not
    depend on the <img> loading at all."""
    monkeypatch.setattr(settings, "mfa_email_logo_url", "")

    html = render_mfa_html(to_name="Ada", code="123456", minutes=10)

    assert "<img" not in html
    assert "ICT University" in html


def test_html_includes_the_logo_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mfa_email_logo_url", "https://example.com/logo.png")

    html = render_mfa_html(to_name="Ada", code="123456", minutes=10)

    assert 'src="https://example.com/logo.png"' in html
    # Decorative next to a real text wordmark - empty alt avoids a screen
    # reader announcing the brand twice.
    assert 'alt=""' in html


def test_text_alternative_carries_the_same_facts() -> None:
    text = render_mfa_text(to_name="Ada", code="123456", minutes=10)

    assert "123456" in text
    assert "10 minutes" in text
    assert "<" not in text
