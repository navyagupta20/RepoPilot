"""Reusable HTML building blocks for the RepoPilot interface.

Every piece of text that comes from the backend, the user or an AI model is passed through
html.escape before it is placed in HTML.
"""
from __future__ import annotations

import html
import re
from datetime import datetime

import streamlit as st

esc = html.escape

LOGO = (
    '<svg width="{s}" height="{s}" viewBox="0 0 32 32" role="img" aria-label="RepoPilot AI logo">'
    '<rect width="32" height="32" rx="8" fill="#2C4FE8"/>'
    '<path d="M7 22 L13 12 L18 17 L25 8" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="25" cy="8" r="3" fill="#F2A516"/></svg>'
)

_TOKEN = re.compile(
    r"(?P<c>#.*|//.*)|(?P<s>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|\b(?P<k>def|class|return|if|else|elif|for|while|import|from|raise|try|except|finally|function|const|let|var|async|await|new|None|True|False|"
    r"null|true|false|self|this|func|package|public|private|protected|static|void|export|default|in|not|and|or|with|as|yield|lambda|pass|interface|type)\b"
    r"|\b(?P<n>\d+(?:\.\d+)?)\b"
)

_NO_HIGHLIGHT = {
    "markdown", "text", "json", "yaml", "toml", "ini",
    "dockerfile", "makefile", "html", "css", "scss"
}


def highlight_line(line: str, language: str = "") -> str:
    """Very small syntax highlighter (approximate, single-line). Output is HTML-escaped."""
    if language.lower() in _NO_HIGHLIGHT:
        return esc(line)

    out, last = [], 0

    for m in _TOKEN.finditer(line):
        out.append(esc(line[last:m.start()]))
        out.append(f'<span class="{m.lastgroup}">{esc(m.group())}</span>')
        last = m.end()

    out.append(esc(line[last:]))
    return "".join(out)


def logo(size: int = 32) -> str:
    return LOGO.format(s=size)


def brand(inverse: bool = False, tagline: bool = False) -> str:
    extra = "<small>AI</small>" if tagline else ""
    return (
        f'<span class="brand{" inverse" if inverse else ""}">'
        f'{logo(38)}<span class="brand-name">REPOPILOT</span>{extra}</span>'
    )


def code_block(
    text: str,
    path: str = "",
    start_line: int = 1,
    language: str = "",
    tag: str = "",
    hit_lines: set | None = None,
    all_hit: bool = False,
    light: bool = True,
    max_lines: int = 60,
) -> str:
    """Numbered code with an amber evidence gutter on cited lines."""
    lines = text.split("\n")
    shown = lines[:max_lines]
    rows = []

    for i, line in enumerate(shown):
        number = start_line + i
        hit = all_hit or (hit_lines is not None and number in hit_lines)
        rows.append(
            f'<div class="ln{" hit" if hit else ""}">'
            f'<span class="no">{number}</span>'
            f'<span class="src">{highlight_line(line, language) or " "}</span></div>'
        )

    if len(lines) > max_lines:
        rows.append(
            f'<div class="ln"><span class="no"></span>'
            f'<span class="src c">... {len(lines) - max_lines} more lines</span></div>'
        )

    end = start_line + len(lines) - 1

    head = (
        f'<div class="codebox-head"><span><span class="path">{esc(path)}</span>'
        f'{f"<span class=tag>{esc(tag)}</span>" if tag else ""}</span>'
        f'<span>{"lines %d-%d" % (start_line, end) if path else ""} '
        f'{esc(language)}</span></div>'
    ) if path else ""

    return (
        f'<div class="codebox{" light" if light else ""}">'
        f'{head}<div class="codebody">{"".join(rows)}</div></div>'
    )


def diff_block(diff: str) -> str:
    rows = []

    for line in diff.splitlines():
        kind = (
            "meta" if line.startswith(("---", "+++", "@@"))
            else "add" if line.startswith("+")
            else "del" if line.startswith("-")
            else ""
        )
        rows.append(
            f'<div class="ln {kind}"><span class="no"></span>'
            f'<span class="src">{esc(line) or " "}</span></div>'
        )

    return (
        '<div class="codebox light diff">'
        '<div class="codebox-head"><span class="path">Proposed change</span>'
        '<span>unified diff</span></div>'
        f'<div class="codebody">{"".join(rows)}</div></div>'
    )


def render(html_text: str) -> None:
    st.html(html_text)


def notice(kind: str, title: str, body: str = "") -> None:
    """kind: error | success | warning | info"""
    safe_kind = kind if kind in {"error", "success", "warning", "info"} else "info"
    role = "alert" if safe_kind == "error" else "status"
    render(
        f'<div class="notice {safe_kind}" role="{role}">'
        f'<b>{esc(title)}</b>{esc(body)}</div>'
    )


def empty_state(title: str, body: str) -> None:
    render(f'<div class="empty"><h3>{esc(title)}</h3><p>{esc(body)}</p></div>')


def page_head(title: str, subtitle: str = "") -> None:
    subtitle_html = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    render(f'<div class="page-head"><h1>{esc(title)}</h1>{subtitle_html}</div>')


def stat(label: str, value) -> str:
    return (
        f'<div class="stat"><div class="v">{esc(str(value))}</div>'
        f'<div class="l">{esc(label)}</div></div>'
    )


STATUS_LABELS = {
    "completed": "Analyzed",
    "failed": "Failed",
    "analyzing": "Analyzing",
    "not_analyzed": "Not analyzed",
    "pending": "Pending review",
    "approved": "Approved",
    "rejected": "Rejected",
    "applied": "Applied locally",
}


def pill(status: str) -> str:
    safe_status = (
        status if re.fullmatch(r"[a-zA-Z0-9_-]+", status or "")
        else "unknown"
    )
    return (
        f'<span class="pill {esc(safe_status)}">'
        f'{esc(STATUS_LABELS.get(status, status))}</span>'
    )


def fmt_dt(value: str | None) -> str:
    if not value:
        return "never"

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return value


def repo_header(repo: dict) -> str:
    meta = repo.get("metadata", {})
    language = repo.get("primary_language") or "language unknown"

    desc = meta.get("description", "")
    analyzed = (
        f"Last analysis: {fmt_dt(repo.get('last_analyzed_at'))}"
        if repo.get("analysis_status") == "completed"
        else ""
    )
    stale = (
        " - files changed since analysis, re-analyze to refresh"
        if meta.get("index_stale")
        else ""
    )

    return (
        f'<div class="repo-name">'
        f'{esc(str(repo.get("name", "Repository")))}'
        f'{pill(str(repo.get("analysis_status", "not_analyzed")))}</div>'
        f'<div class="repo-meta">{esc(str(language))} &nbsp;|&nbsp; '
        f'{esc(str(repo.get("file_count", 0)))} files &nbsp;|&nbsp; '
        f'<a href="{esc(str(repo.get("github_url", "#")))}" '
        f'target="_blank" rel="noopener noreferrer">GitHub</a></div>'
        f'{f"<div class=repo-desc>{esc(str(desc))}</div>" if desc else ""}'
        f'{f"<div class=hint>{esc(analyzed)}{esc(stale)}</div>" if analyzed else ""}'
    )


def render_references(
    refs: list[dict],
    heading: str = "Code the answer is based on"
) -> None:
    if not refs:
        return

    chips = "".join(
        f'<span class="cite">{esc(str(r.get("path", "unknown")))}:'
        f'{esc(str(r.get("start_line", "?")))}-'
        f'{esc(str(r.get("end_line", "?")))}</span> '
        for r in refs
    )

    render(
        f'<div class="sec-label">{esc(heading)}</div>'
        '<div class="hint">Amber bars mark the retrieved lines the AI was given as evidence.</div>'
        f'<div style="margin:.5rem 0 .3rem">{chips}</div>'
    )

    for ref in refs:
        tag = {"stack_trace": "matches your stack trace"}.get(
            ref.get("source", ""), ""
        )

        if not tag and ref.get("keyword_rank") and ref.get("semantic_rank"):
            tag = "keyword + meaning"
        elif not tag and ref.get("keyword_rank"):
            tag = "keyword match"
        elif not tag and ref.get("semantic_rank"):
            tag = "meaning match"

        label = str(ref.get("path", "unknown"))
        if ref.get("symbol"):
            label += f" - {ref['symbol']}"

        render(
            code_block(
                str(ref.get("text", "")),
                label,
                int(ref.get("start_line", 1)),
                str(ref.get("language", "")),
                tag,
                all_hit=True,
            )
        )


# ------------------------------------------------------------- landing page --

def nav_bar_html() -> str:
    return (
        f'<div class="nav">{brand()}'
        '<a class="nav-link" href="#top">Home</a>'
        '<a class="nav-link" href="#features">Features</a>'
        '<a class="nav-link" href="#how-it-works">How it works</a></div>'
    )


def hero_text_html() -> str:
    return (
        '<div id="top"></div>'
        '<div class="hero-eyebrow"><span class="hero-dot"></span>'
        'AI-POWERED REPOSITORY INTELLIGENCE</div>'
        '<h1 class="hero-title">Understand your codebase.<br>'
        'Find answers. <span class="hero-accent">Fix bugs with confidence.</span></h1>'
        '<p class="hero-sub">Connect a GitHub repository and explore how your code works. '
        'Find relevant functions, trace errors to their source, and review AI-generated '
        'fixes before making changes.</p>'
    )


def product_preview_html() -> str:
    sample = (
        "from django.contrib.auth import authenticate\n\n"
        "def login_user(username, password):\n"
        '    """Authenticate a user with the password check."""\n'
        "    user = authenticate(username=username, password=password)\n"
        "    if user is None:\n"
        '        raise ValueError("bad credentials")\n'
        "    return user"
    )

    return (
        '<div class="preview"><div class="preview-top">'
        '<span class="preview-dot"></span><span class="preview-dot"></span>'
        '<span class="preview-dot"></span>'
        '<span class="preview-label">REPOSITORY EXPLORER</span>'
        '<span class="preview-status">EXAMPLE</span></div>'
        '<div class="q">Where is the password checked when someone signs in?</div>'
        '<div class="a">Sign-in goes through <code>login_user</code>, which hands the credentials '
        'to Django\'s <code>authenticate</code> function and raises an error when no user matches. '
        'It never compares passwords itself.</div>'
        '<div style="margin-bottom:.5rem"><span class="cite">auth/login.py:5-8</span></div>'
        + code_block(
            sample,
            "auth/login.py",
            1,
            "python",
            "keyword + meaning",
            hit_lines={5, 6, 7, 8},
            light=False,
        )
        + '<div class="caption">Illustrative example. Actual answers should be grounded in the connected repository.</div></div>'
    )


def features_html() -> str:
    return (
        '<div class="band" id="features">'
        '<div class="section-kicker">WHAT REP﻿OPILOT CAN DO</div>'
        '<h2>Navigate complex code without the guesswork.</h2>'
        '<p class="lead">Four tools to help you understand unfamiliar code, '
        'investigate errors, and review changes with confidence.</p>'

        '<div class="feat-grid">'

        '<div class="feat-main">'
        '<div class="feature-icon feature-icon-blue"><span>&lt;/&gt;</span></div>'
        '<div class="feature-tag">01 · CODE UNDERSTANDING</div>'
        '<h3>Understand how your code connects.</h3>'
        '<p>Explore functions, classes, and methods using syntax-aware analysis. Ask about '
        '<code>login_user</code> and trace the answer to the relevant function instead of '
        'searching through unrelated lines.</p>'
        '<div class="tree"><div class="tree-root">◈ repo/</div>'
        '<div class="tree-line">├── app.py</div><div class="tree-line">├── auth/</div>'
        '<div class="tree-line tree-hit">│   └── login.py <span>login_user()</span></div>'
        '<div class="tree-line">└── db/</div>'
        '<div class="tree-line">    └── store.py <span>Database.save_record()</span></div></div>'
        '<div class="feature-foot"><span class="status-dot"></span>Function-level context</div>'
        '</div>'

        '<div class="feature-side">'

        '<div class="feat-row">'
        '<div class="feature-icon feature-icon-purple"><span>⌕</span></div>'
        '<div class="feature-tag">02 · SMART SEARCH</div>'
        '<h3>Search by name or by meaning.</h3>'
        '<p>Combine keyword and semantic search to find relevant code, even when you remember '
        'what it does but not what it is called.</p>'
        '<div class="feature-foot">Keyword + meaning-based retrieval</div>'
        '</div>'

        '<div class="feat-row">'
        '<div class="feature-icon feature-icon-amber"><span>⌁</span></div>'
        '<div class="feature-tag">03 · BUG INVESTIGATION</div>'
        '<h3>Trace errors to their source.</h3>'
        '<p>Share a traceback or describe a symptom. Locate relevant lines and examine likely '
        'causes, clearly marked as hypotheses.</p>'
        '<div class="feature-foot">Evidence-led debugging</div>'
        '</div>'

        '<div class="feat-row">'
        '<div class="feature-icon feature-icon-green"><span>↗</span></div>'
        '<div class="feature-tag">04 · AI FIX SUGGESTIONS</div>'
        '<h3>Review every change before applying it.</h3>'
        '<p>Get focused code suggestions as diffs. Inspect the proposed change and decide whether '
        'to apply it. Suggestions are not treated as verified unless relevant tests have actually '
        'run successfully.</p>'
        '<div class="feature-foot">Human approval before changes</div>'
        '</div>'

        '</div></div></div>'
    )


def how_it_works_html() -> str:
    return (
        '<div class="band workflow-band" id="how-it-works">'
        '<div class="section-kicker">A SIMPLE WORKFLOW</div>'
        '<h2>From repository to insight in three steps.</h2>'
        '<p class="lead">Spend less time hunting through files and more time understanding how your project works.</p>'

        '<div class="steps">'

        '<div class="step">'
        '<div class="step-top"><span class="num">01</span><span class="step-icon">↗</span></div>'
        '<h4>Connect your repository</h4>'
        '<p>Enter a public GitHub repository URL. RepoPilot checks the URL and retrieves readable source files for analysis.</p>'
        '<div class="step-bottom">01 / CONNECT</div>'
        '</div>'

        '<div class="step">'
        '<div class="step-top"><span class="num">02</span><span class="step-icon">&lt;/&gt;</span></div>'
        '<h4>Analyze the codebase</h4>'
        '<p>Identify functions and classes, then index code for keyword and meaning-based search.</p>'
        '<div class="step-bottom">02 / ANALYZE</div>'
        '</div>'

        '<div class="step">'
        '<div class="step-top"><span class="num">03</span><span class="step-icon">⌕</span></div>'
        '<h4>Ask, investigate, and review</h4>'
        '<p>Ask questions about your code, investigate errors, and inspect suggested changes before deciding what to apply.</p>'
        '<div class="step-bottom">03 / REVIEW</div>'
        '</div>'

        '</div>'

        '<div class="trust-strip"><div class="trust-icon">✓</div><div>'
        '<strong>You stay in control.</strong>'
        '<p>Check cited source locations, review proposed changes, and verify results with tests where available.</p>'
        '</div></div></div>'
    )


def footer_html() -> str:
    return (
        f'<div class="footer"><div>{brand(inverse=True)}'
        '<div class="fine">Understand your codebase. Find answers grounded in code. '
        'AI output can be wrong, so always review the evidence.</div></div>'
        '<div><a href="#top">Home</a><a href="#features">Features</a>'
        '<a href="#how-it-works">How it works</a></div></div>'
    )