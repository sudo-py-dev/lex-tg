import html
from html.parser import HTMLParser

import pytest

from src.plugins.ai_assistant.telegram_markdown import render_pyrogram_html
from src.utils.text import smart_split


class ParsedHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("**Bold** and *italic*", "<b>Bold</b> and <i>italic</i>"),
        ("`a < b && c`", "<code>a &lt; b &amp;&amp; c</code>"),
        (
            '```python\nprint("<b>**literal**</b>")\n```',
            '<pre><code class="language-python">print(&quot;&lt;b&gt;**literal**&lt;/b&gt;&quot;)</code></pre>',
        ),
        ("<b>Hello</b>", "<b>Hello</b>"),
        (
            "[Docs](https://example.com/?a=1&b=2)",
            '<a href="https://example.com/?a=1&amp;b=2">Docs</a>',
        ),
        ("# Title", "<b>Title</b>"),
    ],
)
def test_markdown_and_legacy_html_render_safely(source, expected):
    assert render_pyrogram_html(source) == expected


def test_raw_html_and_unsafe_links_cannot_create_telegram_entities():
    text = render_pyrogram_html(
        '<script>alert(1)</script>\n\n<a href="javascript:alert(1)">click</a>'
    )
    assert "<script>" not in text
    assert '<a href="javascript:' not in text
    assert "&lt;script&gt;" in text


@pytest.mark.parametrize(
    "text",
    [
        "<b>" + "🙂" * 5000 + "</b>",
        '<pre><code class="language-python">'
        + html.escape("x < 2 && y > 0\n") * 1000
        + "</code></pre>",
        "<b>outer <i>" + "word " * 3000 + "</i> done</b>",
        "plain " * 2000,
    ],
)
def test_long_replies_split_with_balanced_tags_intact_entities_and_unicode(text):
    expected = ParsedHTML()
    expected.feed(text)
    chunks = smart_split(text)
    assert len(chunks) > 1
    recovered = []
    for chunk in chunks:
        assert len(chunk.encode("utf-16-le")) // 2 <= 4096
        parser = ParsedHTML()
        parser.feed(chunk)
        assert not parser.stack
        recovered.extend(parser.text)
    assert "".join(recovered) == "".join(expected.text)
