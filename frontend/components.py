"""Reusable HTML building blocks for RepoPilot AI.

All dynamic text is escaped before being inserted into HTML.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

import streamlit as st

esc = html.escape


# ============================================================
# BRAND
# ============================================================

LOGO = (
    '<svg width="{s}" height="{s}" viewBox="0 0 32 32" '
    'role="img" aria-label="RepoPilot AI logo">'
    '<rect width="32" height="32" rx="9" fill="#E58A4B"/>'
    '<path d="M7 22 L13 12 L18 17 L25 8" fill="none" '
    'stroke="#252A2E" stroke-width="2.6" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="25" cy="8" r="3" fill="#FFFFFF"/>'
    '</svg>'
)


def logo(size: int = 32) -> str:
    return LOGO.format(s=size)


def brand(inverse: bool = False, tagline: bool = False) -> str:
    extra = '<small class="brand-ai">AI</small>' if tagline else ""

    return (
        f'<span class="brand{" inverse" if inverse else ""}">'
        f'{logo(40)}'
        '<span class="brand-name">RepoPilot</span>'
        f'{extra}</span>'
    )


# ============================================================
# SYNTAX HIGHLIGHTING
# ============================================================

_TOKEN = re.compile(
    r"(?P<c>#.*|//.*)|"
    r"(?P<s>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|\b(?P<k>def|class|return|if|else|elif|for|while|import|from|"
    r"raise|try|except|finally|function|const|let|var|async|await|"
    r"new|None|True|False|null|true|false|self|this|func|package|"
    r"public|private|protected|static|void|export|default|in|not|"
    r"and|or|with|as|yield|lambda|pass|interface|type)\b"
    r"|\b(?P<n>\d+(?:\.\d+)?)\b"
)

_NO_HIGHLIGHT = {
    "markdown", "text", "json", "yaml", "toml", "ini",
    "dockerfile", "makefile", "html", "css", "scss",
}


def highlight_line(line: str, language: str = "") -> str:
    if language.lower() in _NO_HIGHLIGHT:
        return esc(line)

    output = []
    last = 0

    for match in _TOKEN.finditer(line):
        output.append(esc(line[last:match.start()]))
        output.append(
            f'<span class="{match.lastgroup}">'
            f'{esc(match.group())}</span>'
        )
        last = match.end()

    output.append(esc(line[last:]))
    return "".join(output)


# ============================================================
# CODE DISPLAY
# ============================================================

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

    lines = text.split("\n")
    shown = lines[:max_lines]
    rows = []

    for index, line in enumerate(shown):
        number = start_line + index
        hit = all_hit or (
            hit_lines is not None and number in hit_lines
        )

        rows.append(
            f'<div class="ln{" hit" if hit else ""}">'
            f'<span class="no">{number}</span>'
            f'<span class="src">'
            f'{highlight_line(line, language) or " "}'
            f'</span></div>'
        )

    if len(lines) > max_lines:
        rows.append(
            '<div class="ln">'
            '<span class="no"></span>'
            f'<span class="src c">... '
            f'{len(lines) - max_lines} more lines</span></div>'
        )

    end = start_line + len(lines) - 1

    head = ""
    if path:
        head = (
            '<div class="codebox-head">'
            '<span>'
            f'<span class="path">{esc(path)}</span>'
            f'{"<span class=tag>" + esc(tag) + "</span>" if tag else ""}'
            '</span>'
            f'<span>lines {start_line}-{end} {esc(language)}</span>'
            '</div>'
        )

        return (
        f'<div class="codebox vscode-code">'
        f'{head}'
        f'<div class="codebody">{"".join(rows)}</div>'
        '</div>'
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
            f'<div class="ln {kind}">'
            '<span class="no"></span>'
            f'<span class="src">{esc(line) or " "}</span>'
            '</div>'
        )

    return (
        '<div class="codebox vscode-code diff">'
        '<div class="codebox-head">'
        '<span class="path">Proposed change</span>'
        '<span>UNIFIED DIFF</span>'
        '</div>'
        f'<div class="codebody">{"".join(rows)}</div>'
        '</div>'
    )


# ============================================================
# RENDERING AND NOTICES
# ============================================================

def render(html_text: str) -> None:
    st.html(html_text)


def notice(kind: str, title: str, body: str = "") -> None:
    safe_kind = (
        kind if kind in {"error", "success", "warning", "info"}
        else "info"
    )
    role = "alert" if safe_kind == "error" else "status"

    render(
        f'<div class="notice {safe_kind}" role="{role}">'
        f'<b>{esc(title)}</b>'
        f'<span>{esc(body)}</span>'
        '</div>'
    )


def empty_state(title: str, body: str) -> None:
    render(
        '<div class="empty">'
        '<div class="empty-icon">⌕</div>'
        f'<h3>{esc(title)}</h3>'
        f'<p>{esc(body)}</p>'
        '</div>'
    )


def page_head(title: str, subtitle: str = "") -> None:
    subtitle_html = (
        f"<p>{esc(subtitle)}</p>" if subtitle else ""
    )

    render(
        '<div class="page-head">'
        f'<h1>{esc(title)}</h1>'
        f'{subtitle_html}'
        '</div>'
    )


def stat(label: str, value) -> str:
    return (
        '<div class="stat">'
        '<div class="stat-icon"><span></span></div>'
        f'<div class="v">{esc(str(value))}</div>'
        f'<div class="l">{esc(label)}</div>'
        '</div>'
    )


# ============================================================
# STATUS PILLS
# ============================================================

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
        status
        if re.fullmatch(r"[a-zA-Z0-9_-]+", status or "")
        else "unknown"
    )

    return (
        f'<span class="pill {esc(safe_status)}">'
        f'{esc(STATUS_LABELS.get(status, status))}'
        '</span>'
    )


# ============================================================
# DATE AND REPOSITORY HELPERS
# ============================================================

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
    language = repo.get("primary_language") or "Language unknown"
    description = meta.get("description", "")

    analyzed = (
        f"Last analyzed {fmt_dt(repo.get('last_analyzed_at'))}"
        if repo.get("analysis_status") == "completed"
        else ""
    )

    stale = (
        " · Files changed since analysis"
        if meta.get("index_stale")
        else ""
    )

    return (
        '<div class="repo-card-header">'
        '<div>'
        f'<div class="repo-name">'
        f'{esc(str(repo.get("name", "Repository")))}'
        '</div>'
        '<div class="repo-meta">'
        f'{esc(str(language))} · '
        f'{esc(str(repo.get("file_count", 0)))} files'
        '</div>'
        '</div>'
        f'{pill(str(repo.get("analysis_status", "not_analyzed")))}'
        '</div>'
        f'<div class="repo-desc">{esc(str(description))}</div>'
        '<div class="repo-card-bottom">'
        f'<span>{esc(analyzed)}{esc(stale)}</span>'
        f'<a href="{esc(str(repo.get("github_url", "#")))}" '
        'target="_blank" rel="noopener noreferrer">'
        'View on GitHub ↗</a>'
        '</div>'
    )


# ============================================================
# REFERENCES
# ============================================================

def render_references(
    refs: list[dict],
    heading: str = "Code references",
) -> None:
    if not refs:
        return

    chips = "".join(
        '<span class="cite">'
        f'{esc(str(ref.get("path", "unknown")))}:'
        f'{esc(str(ref.get("start_line", "?")))}-'
        f'{esc(str(ref.get("end_line", "?")))}'
        '</span>'
        for ref in refs
    )

    render(
        f'<div class="sec-label">{esc(heading)}</div>'
        '<div class="hint">'
        'These source excerpts support the result.'
        '</div>'
        f'<div class="reference-chips">{chips}</div>'
    )

    for ref in refs:
        tag = {"stack_trace": "Stack trace match"}.get(
            ref.get("source", ""), ""
        )

        if not tag and ref.get("keyword_rank") and ref.get("semantic_rank"):
            tag = "Keyword + meaning"
        elif not tag and ref.get("keyword_rank"):
            tag = "Keyword match"
        elif not tag and ref.get("semantic_rank"):
            tag = "Meaning match"

        label = str(ref.get("path", "unknown"))

        if ref.get("symbol"):
            label += f" · {ref['symbol']}"

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


# ============================================================
# LANDING PAGE
# ============================================================

def nav_brand_html() -> str:
    """Render the landing-page brand and shared navigation styling."""
    return (
        """
        <style>
            .rp-top-brand {
                display: flex;
                align-items: center;
                min-height: 64px;
                white-space: nowrap;
            }

            .rp-top-brand .brand {
                display: inline-flex;
                align-items: center;
                gap: 12px;
            }

            .rp-top-brand .brand svg {
                width: 43px;
                height: 43px;
                flex-shrink: 0;
            }

            .rp-top-brand .brand-name {
                color: #252A2E;
                font-family: 'Space Grotesk', sans-serif;
                font-size: 29px;
                font-weight: 700;
                letter-spacing: -1.35px;
                line-height: 1;
            }

            .rp-top-links {
                display: flex;
                align-items: center;
                justify-content: flex-end;
                gap: clamp(16px, 2.5vw, 34px);
                min-height: 64px;
                white-space: nowrap;
            }

            .rp-top-links a {
                position: relative;
                color: #626A6F;
                text-decoration: none;
                font-family: 'DM Sans', sans-serif;
                font-size: 13px;
                font-weight: 600;
                padding: 9px 0;
                transition: color .2s ease;
            }

            .rp-top-links a::after {
                content: "";
                position: absolute;
                left: 0;
                bottom: 2px;
                width: 0;
                height: 2px;
                background: #E58A4B;
                transition: width .2s ease;
            }

            .rp-top-links a:hover {
                color: #B86D39;
            }

            .rp-top-links a:hover::after {
                width: 100%;
            }

            .rp-nav-divider {
                width: 100%;
                height: 1px;
                background: #DADBD7;
                margin: 7px 0 34px;
            }

            [class*="st-key-nav_signin"] button {
                min-height: 42px;
                border-radius: 8px;
                font-family: 'DM Sans', sans-serif;
                font-size: 13px;
                font-weight: 700;
                padding: 0 17px;
                white-space: nowrap;
            }

            @media (max-width: 900px) {
                .rp-top-brand .brand-name {
                    font-size: 25px;
                }

                .rp-top-brand .brand svg {
                    width: 38px;
                    height: 38px;
                }

                .rp-top-links {
                    gap: 15px;
                }

                .rp-top-links a {
                    font-size: 12px;
                }
            }

            @media (max-width: 640px) {
                .rp-top-brand {
                    min-height: 48px;
                }

                .rp-top-links {
                    justify-content: flex-start;
                    min-height: 42px;
                    flex-wrap: wrap;
                    gap: 16px;
                }

                .rp-nav-divider {
                    margin: 10px 0 25px;
                }
            }
        </style>
        <div class="rp-top-brand">
        """
        + brand()
        + "</div>"
    )


def nav_links_html() -> str:
    """Render landing-page links in a separate Streamlit column."""
    return (
        '<nav class="rp-top-links" aria-label="Main navigation">'
        '<a href="#top">Home</a>'
        '<a href="#features">Capabilities</a>'
        '<a href="#how-it-works">How it works</a>'
        '</nav>'
    )


def nav_bar_html() -> str:
    """Backward-compatible combined navbar helper."""
    return (
        '<div style="display:flex;align-items:center;'
        'justify-content:space-between;gap:24px;width:100%;">'
        + nav_brand_html()
        + nav_links_html()
        + '</div><div class="rp-nav-divider"></div>'
    )


def hero_text_html() -> str:
    return (
        '<div id="top"></div>'
        '<div class="hero">'
        '<div class="hero-eyebrow">'
        'REPOSITORY INTELLIGENCE'
        '</div>'
        '<h1 class="hero-title">'
        'Make sense of your codebase<br>'
        '<span class="hero-accent">'
        'Build with more confidence'
        '</span>'
        '</h1>'
        '<p class="hero-sub">'
        'Search code by meaning, understand unfamiliar functions, '
        'investigate errors and review AI-generated changes '
        'with the source code in view.'
        '</p>'
        '</div>'
    )


def product_preview_html() -> str:
    """A simple example showing how RepoPilot answers a code question."""

    sample = (
        "def resolve_user(request):\n"
        "    user = request.user\n"
        "    if not user.is_authenticated:\n"
        '        raise PermissionError("Sign in required")\n'
        "    return user"
    )

    code = code_block(
        sample,
        "src/auth.py",
        1,
        "python",
        hit_lines={3, 4},
        light=True,
        max_lines=10,
    )

    return (
        '<div class="preview-simple" style="'
        'background:#FFFFFF;'
        'border:1px solid #E3E2DE;'
        'border-radius:14px;'
        'padding:24px;'
        'color:#252A2E;'
        'box-shadow:0 12px 35px rgba(37,42,46,.06);'
        '">'
        '<div style="'
        'font-size:11px;'
        'font-weight:700;'
        'letter-spacing:1.3px;'
        'color:#B86D39;'
        'margin-bottom:22px;'
        '">EXAMPLE WORKFLOW</div>'

        '<div style="margin-bottom:18px;">'
        '<div style="'
        'font-size:11px;'
        'font-weight:700;'
        'color:#8A8F91;'
        'margin-bottom:8px;'
        '">01 · ASK A QUESTION</div>'
        '<div style="'
        'background:#F3F4F2;'
        'border:1px solid #E3E2DE;'
        'border-radius:8px;'
        'padding:13px 15px;'
        'font-size:14px;'
        'line-height:1.6;'
        '">Where is authentication checked in this project?</div>'
        '</div>'

        '<div style="'
        'height:1px;'
        'background:#E9E7E2;'
        'margin:18px 0;'
        '"></div>'

        '<div style="margin-bottom:18px;">'
        '<div style="'
        'font-size:11px;'
        'font-weight:700;'
        'color:#8A8F91;'
        'margin-bottom:9px;'
        '">02 · FIND RELEVANT CODE</div>'
        f'{code}'
        '</div>'

        '<div style="'
        'height:1px;'
        'background:#E9E7E2;'
        'margin:18px 0;'
        '"></div>'

        '<div>'
        '<div style="'
        'font-size:11px;'
        'font-weight:700;'
        'color:#8A8F91;'
        'margin-bottom:8px;'
        '">03 · UNDERSTAND THE RESULT</div>'
        '<div style="'
        'font-size:13px;'
        'line-height:1.75;'
        'color:#42494D;'
        '">'
        'RepoPilot found the authentication check inside '
        '<strong>resolve_user()</strong>. It verifies that '
        'the request user is authenticated before returning '
        'the user object.'
        '</div>'
        '<div style="'
        'margin-top:10px;'
        'font-size:11px;'
        'color:#9A6A48;'
        'font-weight:600;'
        '">Source: src/auth.py, lines 3–4</div>'
        '</div>'

        '<div style="'
        'border-top:1px solid #E9E7E2;'
        'margin-top:20px;'
        'padding-top:12px;'
        'font-size:11px;'
        'color:#858B8E;'
        '">Illustrative example · Not live repository data</div>'
        '</div>'
    )


def features_html() -> str:
    """Display RepoPilot capabilities in a responsive card layout."""

    capabilities = [
        (
            "01",
            "Repository Analysis",
            "Understand your codebase.",
            "Explore repository files, functions, classes and methods "
            "with structural analysis powered by Tree-sitter."
        ),
        (
            "02",
            "Intelligent Code Search",
            "Find code by meaning.",
            "Combine BM25 keyword search and FAISS semantic retrieval "
            "to locate relevant code across your repository."
        ),
        (
            "03",
            "AI Code Assistant",
            "Ask questions about your code.",
            "Get AI-generated explanations and answers grounded in "
            "relevant source files and code references."
        ),
        (
            "04",
            "Bug Investigation",
            "Trace errors to their source.",
            "Analyze tracebacks and bug descriptions to identify "
            "potentially related files and code sections."
        ),
        (
            "05",
            "AI Fix Suggestions",
            "Review changes before applying.",
            "Inspect proposed changes through minimal diffs. Approve "
            "or reject suggestions before applying them locally."
        ),
        (
            "06",
            "Analysis History",
            "Keep track of your investigations.",
            "Revisit previous questions, bug investigations and "
            "their supporting code references."
        ),
    ]

    cards = []

    for number, title, tagline, description in capabilities:
        cards.append(
            f"""
            <article class="rp-feature-card">
                <div class="rp-feature-top">
                    <span class="rp-feature-number">{esc(number)}</span>
                    <span class="rp-feature-line"></span>
                </div>
                <h3>{esc(title)}</h3>
                <div class="rp-feature-tagline">{esc(tagline)}</div>
                <p>{esc(description)}</p>
            </article>
            """
        )

    return (
        """
        <style>
            .rp-capabilities-section,
            .rp-workflow-section {
                width: 100%;
                max-width: 1240px;
                margin-left: auto;
                margin-right: auto;
                box-sizing: border-box;
            }

            /* CAPABILITIES */

            .rp-capabilities-section {
                margin-top: 34px;
                margin-bottom: 0;
                padding: 0;
                font-family: 'DM Sans', sans-serif;
            }

            .rp-capabilities-shell {
                box-sizing: border-box;
                width: 100%;
                padding: 36px;
                background: #F8F8F6;
                border: 1px solid #E3E2DE;
                border-radius: 17px;
                box-shadow: 0 10px 30px rgba(37, 42, 46, .035);
            }

            .rp-capabilities-heading {
                max-width: 720px;
                margin-bottom: 30px;
                padding-bottom: 21px;
                border-bottom: 1px solid #E8E5DF;
            }

            .rp-capabilities-eyebrow {
                color: #B86D39;
                font-family: 'DM Mono', monospace;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.7px;
                margin-bottom: 13px;
            }

            .rp-capabilities-heading h2 {
                color: #252A2E;
                font-family: 'Space Grotesk', sans-serif;
                font-size: clamp(29px, 3.5vw, 40px);
                font-weight: 600;
                letter-spacing: -1.3px;
                line-height: 1.2;
                margin: 0 0 12px;
            }

            .rp-capabilities-heading p {
                color: #687075;
                font-size: 14px;
                line-height: 1.8;
                margin: 0;
                max-width: 620px;
            }

            .rp-feature-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 16px;
                width: 100%;
            }

            .rp-feature-card {
                min-height: 185px;
                box-sizing: border-box;
                background: #FFFFFF;
                border: 1px solid #E5E3DE;
                border-radius: 11px;
                padding: 23px 25px 24px;
                transition:
                    border-color .2s ease,
                    transform .2s ease,
                    box-shadow .2s ease;
            }

            .rp-feature-card:hover {
                border-color: #D9A17B;
                transform: translateY(-3px);
                box-shadow: 0 9px 24px rgba(37, 42, 46, .055);
            }

            .rp-feature-top {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 18px;
            }

            .rp-feature-number {
                color: #C97943;
                font-family: 'DM Mono', monospace;
                font-size: 12px;
                font-weight: 700;
            }

            .rp-feature-line {
                height: 1px;
                width: 35px;
                background: #E8C7AE;
            }

            .rp-feature-card h3 {
                color: #252A2E;
                font-family: 'Space Grotesk', sans-serif;
                font-size: 18px;
                font-weight: 600;
                letter-spacing: -.35px;
                line-height: 1.35;
                margin: 0 0 5px;
            }

            .rp-feature-tagline {
                color: #B86D39;
                font-size: 12px;
                font-weight: 600;
                margin-bottom: 10px;
            }

            .rp-feature-card p {
                color: #687075;
                font-size: 13px;
                line-height: 1.75;
                margin: 0;
                max-width: 520px;
            }

            /* WORKFLOW */

            .rp-workflow-section {
                margin-top: 0 !important;
                padding: 25px 0 45px;
                font-family: 'DM Sans', sans-serif;
            }

            .rp-workflow-section .section-kicker {
                display: inline-block;
                padding: 7px 11px;
                margin-bottom: 12px;
                border-radius: 4px;
                background: #F5D9C3;
                color: #98552E;
                font-family: 'DM Mono', monospace;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.3px;
            }

            .rp-workflow-section h2 {
                margin-top: 0;
                padding-bottom: 15px;
                border-bottom: 1px solid #E3E2DE;
            }

            @media (max-width: 700px) {
                .rp-capabilities-section {
                    margin-top: 28px;
                }

                .rp-capabilities-shell {
                    padding: 23px 18px;
                    border-radius: 13px;
                }

                .rp-feature-grid {
                    grid-template-columns: 1fr;
                    gap: 12px;
                }

                .rp-feature-card {
                    min-height: auto;
                    padding: 21px;
                }

                .rp-workflow-section {
                    padding-top: 15px;
                }
            }

            @media (prefers-reduced-motion: reduce) {
                .rp-feature-card {
                    transition: none;
                }
            }
        </style>

        <section class="rp-capabilities-section" id="features">
            <div class="rp-capabilities-shell">
            <div class="rp-capabilities-heading">
                <div class="rp-capabilities-eyebrow">
                    CAPABILITIES
                </div>

                <h2>
                    Everything you need to understand your codebase
                </h2>

                <p>
                    A structured set of tools for repository analysis,
                    intelligent search, debugging and AI-assisted
                    code review.
                </p>
            </div>

            <div class="rp-feature-grid">
        """
        + "".join(cards)
        + """
            </div>
            </div>
        </section>
        """
    )


def how_it_works_html() -> str:
    return (
        '<section class="band workflow-band rp-workflow-section" '
        'id="how-it-works">'
        '<div class="section-kicker">THE WORKFLOW</div>'
        '<h2>Three steps from code to clarity</h2>'
        '<p class="lead">'
        'Connect a repository, let RepoPilot index it, '
        'then explore it with AI-assisted tools.'
        '</p>'
        '<div class="steps">'
        '<div class="step">'
        '<div class="step-top">'
        '<span class="num">01</span>'
        '</div>'
        '<h4>Connect</h4>'
        '<p>Add a public GitHub repository to your workspace.</p>'
        '<div class="step-bottom">CONNECT REPOSITORY</div>'
        '</div>'
        '<div class="step">'
        '<div class="step-top">'
        '<span class="num">02</span>'
        '</div>'
        '<h4>Analyze</h4>'
        '<p>Parse code structure and build search indexes.</p>'
        '<div class="step-bottom">INDEX CODE</div>'
        '</div>'
        '<div class="step">'
        '<div class="step-top">'
        '<span class="num">03</span>'
        '</div>'
        '<h4>Explore</h4>'
        '<p>Ask questions, investigate bugs and review fixes.</p>'
        '<div class="step-bottom">GET INSIGHTS</div>'
        '</div>'
        '</div>'
        '<div class="trust-strip">'
        '<div>'
        '<strong>Your code. Your decisions.</strong>'
        '<p>Review source references and proposed changes. '
        'RepoPilot does not push changes to GitHub.</p>'
        '</div></div></section>'
    )


def footer_html() -> str:
    return (
        '<footer class="footer">'
        '<div class="footer-brand">'
        f'{brand(inverse=True)}'
        '<div class="fine">'
        'Understand your codebase. Build with confidence.'
        '</div></div>'
        '<div class="footer-links">'
        '<a href="#top">Home</a>'
        '<a href="#features">Capabilities</a>'
        '<a href="#how-it-works">How it works</a>'
        '</div>'
        '</footer>'
    )