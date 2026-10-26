"""RepoPilot AI - Streamlit frontend.

All data comes from the Django REST API (see api_client.py). This file only contains page layout and
interaction logic. Run with:  streamlit run app.py
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

import components as ui
from api_client import BACKEND_URL, ApiClient, ApiError

st.set_page_config(page_title="RepoPilot AI", page_icon=":material/explore:", layout="wide", initial_sidebar_state="expanded")

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:2])


# Streamlit >= 1.50 uses width="stretch"; older versions use use_container_width=True.
STRETCH = {"width": "stretch"} if _version_tuple(st.__version__) >= (1, 50) else {"use_container_width": True}

PROTECTED = {"dashboard", "repos", "search", "assistant", "bugs", "fixes", "history"}
NAV = [("dashboard", "Dashboard"), ("repos", "Repositories"), ("search", "Search code"), ("assistant", "Ask the AI"),
       ("bugs", "Investigate a bug"), ("fixes", "Fix suggestions"), ("history", "History")]
EXAMPLE_QUESTIONS = ["Explain how this project works.", "Where is authentication implemented?",
                     "Which function handles database operations?", "How does the main API endpoint work?"]
MODES = {"Hybrid (recommended)": "hybrid", "Keyword (BM25)": "keyword", "Meaning (FAISS)": "semantic"}


# ------------------------------------------------------------------ helpers --
def state():
    return st.session_state


def api() -> ApiClient:
    return ApiClient(BACKEND_URL, state().get("token"))


def go(page: str) -> None:
    state().page = page


def flash(kind: str, title: str, body: str = "") -> None:
    state().flash = (kind, title, body)


def sign_out(expired: bool = False) -> None:
    if state().get("token") and not expired:
        try:
            api().logout()
        except ApiError:
            pass
    for key in list(state().keys()):
        del state()[key]
    state().page = "auth" if expired else "home"
    if expired:
        flash("warning", "Your session ended", "Please sign in again.")


def safe(fn, *args, **kwargs):
    """Call the API; show a friendly message and return None on failure."""
    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        if exc.status == 401 and state().get("token"):
            sign_out(expired=True)
            st.rerun()
        elif exc.code == "llm_not_configured":
            ui.notice("warning", "The AI assistant is not set up yet", exc.message)
        elif exc.code == "unreachable":
            ui.notice("error", "Backend not reachable", exc.message)
        else:
            ui.notice("error", "That did not work", exc.message)
        return None


def safe_markdown(text: str) -> str:
    """AI text is rendered as Markdown. Images and links are removed so a prompt-injected reply cannot
    make the browser load a remote URL (a data-leak trick)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image removed]", text)
    text = re.sub(r"\[([^\]]+)\]\((?:https?|ftp|data|javascript):[^)]*\)", r"\1", text, flags=re.I)
    return re.sub(r"<[^>]+>", "", text)


def active_repo() -> dict | None:
    return next((r for r in state().get("repos", []) if r["id"] == state().get("active_repo")), None)


def select_repo(repo_id: int, page: str) -> None:
    state().active_repo = repo_id
    state()["_active_sel"] = repo_id
    state().page = page


def on_repo_change() -> None:
    state().active_repo = state()["_active_sel"]


def run_analysis(repo: dict) -> None:
    with st.spinner("Analyzing: reading files, parsing code and building the search index. Large repositories can take a few minutes..."):
        result = safe(api().analyze, repo["id"])
    if result:
        semantic = result.get("metadata", {}).get("analysis", {}).get("semantic", {})
        mode = "keyword and meaning-based search" if semantic.get("indexed") else f"keyword search only ({semantic.get('error') or 'semantic search disabled'})"
        flash("success", f"Analysis complete for {result['name']}", f"Search is ready using {mode}.")
        st.rerun()


def require_repo(analyzed: bool = True) -> dict | None:
    repo = active_repo()
    if repo is None:
        ui.empty_state("Connect a repository first", "Add a public GitHub repository, analyze it, and this page will be ready to use.")
        st.button("Connect a repository", type="primary", on_click=go, args=("repos",), key="need_repo")
        return None
    if analyzed and repo["analysis_status"] != "completed":
        ui.notice("warning", f"{repo['name']} has not been analyzed yet", "Analysis builds the search index that every feature on this page relies on.")
        if st.button("Analyze now", type="primary", key=f"analyze_now_{repo['id']}"):
            run_analysis(repo)
        return None
    if repo.get("metadata", {}).get("index_stale"):
        ui.notice("info", "Files changed since the last analysis", "An approved fix was applied to the local copy. Re-analyze on the Repositories page to refresh search.")
    return repo


def show_flash() -> None:
    if "flash" in state():
        kind, title, body = state().pop("flash")
        ui.notice(kind, title, body)


# ------------------------------------------------------------------ landing --
def page_home() -> None:
    logged_in = bool(state().get("token"))
    left, right = st.columns([8, 2], vertical_alignment="center")
    left.html(ui.nav_bar_html())
    right.button("Open dashboard" if logged_in else "Sign in", on_click=go, args=("dashboard" if logged_in else "auth",), key="nav_signin", **STRETCH)

    text_col, preview_col = st.columns([6, 5], gap="large")
    with text_col:
        ui.render(ui.hero_text_html())
        b1, b2, _ = st.columns([1.5, 1.5, 1])
        def start():
            state().after_login = "repos"
            go("repos" if logged_in else "auth")
        b1.button("Analyze Repository", type="primary", on_click=start, key="hero_cta", **STRETCH)
        b2.html('<a class="btn-link" href="#features" style="width:100%">Explore Features</a>')
        ui.render('<div class="hero-note">Public GitHub repositories. Nothing is ever pushed to GitHub.</div>')
    with preview_col:
        ui.render(ui.product_preview_html())
    ui.render(ui.features_html())
    ui.render(ui.how_it_works_html())
    ui.render(ui.footer_html())


# --------------------------------------------------------------------- auth --
def page_auth() -> None:
    st.button("Back to home", on_click=go, args=("home",), key="auth_back")
    _, mid, _ = st.columns([1, 1.5, 1])
    with mid:
        ui.render(f'<div style="margin:1.5rem 0 .5rem">{ui.brand()}</div><h2 style="margin:.2rem 0 1rem">Sign in to your workspace</h2>')
        show_flash()
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            with st.form("login_form"):
                username = st.text_input("Username", key="login_username")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Sign in", type="primary", **STRETCH)
            if submitted:
                if not username or not password:
                    ui.notice("error", "Enter your username and password")
                else:
                    with st.spinner("Signing in..."):
                        data = safe(api().login, username, password)
                    if data:
                        finish_login(data)
        with tab_up:
            with st.form("register_form", clear_on_submit=False):
                new_user = st.text_input("Username", key="reg_username", help="3-30 characters: letters, numbers and . @ + - _")
                email = st.text_input("Email (optional)", key="reg_email")
                pw1 = st.text_input("Password", type="password", key="reg_pw1", help="At least 8 characters, not too common, not all digits.")
                pw2 = st.text_input("Confirm password", type="password", key="reg_pw2")
                created = st.form_submit_button("Create account", type="primary", **STRETCH)
            if created:
                if pw1 != pw2:
                    ui.notice("error", "The passwords do not match")
                elif not new_user or not pw1:
                    ui.notice("error", "Choose a username and a password")
                else:
                    with st.spinner("Creating your account..."):
                        data = safe(api().register, new_user, pw1, email)
                    if data:
                        finish_login(data)


def finish_login(data: dict) -> None:
    state().token = data["token"]
    state().user = data["user"]
    destination = state().pop("after_login", "dashboard")
    state().page = destination
    flash("success", f"Welcome, {data['user']['username']}", "You are signed in.")
    st.rerun()


# ------------------------------------------------------------------ sidebar --
def sidebar() -> None:
    with st.sidebar:
        ui.render(f'<div style="padding:.4rem 0 .2rem">{ui.brand(inverse=True)}</div><div class="side-user">Signed in as {ui.esc(state().user["username"])}</div>')
        for key, label in NAV:
            st.button(label, key=f"nav_{key}", **STRETCH, type="primary" if state().page == key else "secondary", on_click=go, args=(key,))
        ui.render('<hr class="side-rule">')
        repos = safe(api().list_repositories)
        state().repos = repos or []
        if state().repos:
            ids = [r["id"] for r in state().repos]
            if state().get("active_repo") not in ids:
                state().active_repo = ids[0]
            state()["_active_sel"] = state().active_repo  # our own key survives visits to pages without a sidebar
            st.selectbox("Active repository", ids, key="_active_sel", on_change=on_repo_change,
                         format_func=lambda i: next(r["name"] for r in state().repos if r["id"] == i))
        else:
            ui.render('<div class="side-user">No repositories yet.</div>')
        ui.render('<hr class="side-rule">')
        st.button("Sign out", key="signout", **STRETCH, on_click=sign_out)


# ---------------------------------------------------------------- dashboard --
def page_dashboard() -> None:
    ui.page_head(f"Welcome back, {state().user['username']}", "Your connected repositories and recent AI analyses.")
    show_flash()
    data = safe(api().dashboard)
    if data is None:
        return
    top = st.columns([1, 1, 1, 1, 1.3], vertical_alignment="center")
    for col, (label, value) in zip(top, [("Connected repositories", data["repository_count"]), ("Repositories analyzed", data["repositories_analyzed"]),
                                         ("Completed AI analyses", data["analysis_count"]), ("Fix suggestions", data["fix_suggestion_count"])]):
        col.html(ui.stat(label, value))
    top[4].button("Connect repository", type="primary", on_click=go, args=("repos",), key="dash_connect", **STRETCH)

    repos = state().repos
    ui.render('<div class="sec-label">Repositories</div>')
    if not repos:
        ui.empty_state("Your workspace is empty", "Connect a public GitHub repository to start. RepoPilot will download its source files, index them, and let you ask questions about the code.")
    else:
        cols = st.columns(2)
        for i, repo in enumerate(repos):
            with cols[i % 2].container(border=True, key=f"repo_card_{repo['id']}"):
                ui.render(ui.repo_header(repo))
                actions = st.columns(3)
                actions[0].button("Search code", key=f"d_s_{repo['id']}", on_click=select_repo, args=(repo["id"], "search"), **STRETCH)
                actions[1].button("Ask AI", key=f"d_a_{repo['id']}", on_click=select_repo, args=(repo["id"], "assistant"), **STRETCH)
                actions[2].button("Investigate bug", key=f"d_b_{repo['id']}", on_click=select_repo, args=(repo["id"], "bugs"), **STRETCH)
    ui.render('<div class="sec-label">Recent analyses</div>')
    if not data["recent_analyses"]:
        ui.empty_state("No analyses yet", "Ask a question about a repository or investigate a bug and it will show up here.")
    for item in data["recent_analyses"]:
        with st.expander(f"{item['analysis_type_label']} on {item['repository_name']} ({ui.fmt_dt(item['created_at'])})"):
            st.markdown(f"**Your input**\n\n> {item['user_input'][:300]}")
            st.markdown(safe_markdown(item["ai_response"][:1200]))


# ------------------------------------------------------------- repositories --
ANALYSIS_STEPS = [
    "**Read files** - RepoPilot walks the downloaded project and skips dependency folders, generated files, lock files, binaries, very large files and anything that looks like a secret (such as `.env`).",
    "**Understand structure** - For Python, JavaScript, TypeScript, Java and Go, Tree-sitter finds functions, classes and methods. Other file types are indexed as plain text; RepoPilot does not pretend to parse them.",
    "**Split into chunks** - Each function or method becomes one chunk, so a search can land on exactly the right piece of code.",
    "**Build two indexes** - A keyword index (BM25) finds exact names and words. A meaning index (embeddings + FAISS) finds code that does the same thing with different words.",
    "**Search together** - When you search or ask, both indexes are used and their rankings are merged. Only the top excerpts are ever sent to the AI.",
]


def page_repos() -> None:
    ui.page_head("Repositories", "Connect a public GitHub repository, then analyze it so you can search it and ask questions.")
    show_flash()
    with st.form("connect_form"):
        url = st.text_input("GitHub repository URL", placeholder="https://github.com/owner/repository")
        submitted = st.form_submit_button("Connect repository", type="primary")
    if submitted:
        if not url.strip():
            ui.notice("error", "Paste a repository URL", "For example https://github.com/owner/repository")
        else:
            with st.spinner("Checking the URL, asking GitHub for details and downloading source files..."):
                repo = safe(api().add_repository, url.strip())
            if repo:
                state().active_repo = repo["id"]
                state()["_active_sel"] = repo["id"]
                flash("success", f"Connected {repo['name']}", f"{repo['file_count']} source files downloaded. Run the analysis to make it searchable.")
                st.rerun()
    with st.expander("What happens when I analyze a repository?"):
        for step in ANALYSIS_STEPS:
            st.markdown(f"- {step}")
    ui.render('<div class="sec-label">Connected repositories</div>')
    repos = safe(api().list_repositories) or []
    state().repos = repos
    if not repos:
        ui.empty_state("Nothing connected yet", "Paste a GitHub URL above. Only public repositories are supported in this version.")
    for repo in repos:
        with st.container(border=True, key=f"repo_card_{repo['id']}"):
            ui.render(ui.repo_header(repo))
            semantic = repo.get("metadata", {}).get("analysis", {}).get("semantic")
            if semantic is not None:
                ui.render(f'<div class="hint">Search mode: {"keyword + meaning" if semantic.get("indexed") else "keyword only - " + ui.esc(semantic.get("error") or "semantic search disabled")}</div>')
            if repo["analysis_status"] == "failed" and repo.get("analysis_error"):
                ui.notice("error", "The last analysis failed", repo["analysis_error"])
            c = st.columns([1.3, 1.3, 1, 3])
            label = "Re-analyze" if repo["analysis_status"] == "completed" else "Analyze"
            if c[0].button(label, key=f"an_{repo['id']}", type="primary" if repo["analysis_status"] != "completed" else "secondary", **STRETCH):
                run_analysis(repo)
            c[1].button("Open in search", key=f"os_{repo['id']}", on_click=select_repo, args=(repo["id"], "search"), **STRETCH, disabled=repo["analysis_status"] != "completed")
            confirm_key = f"confirm_rm_{repo['id']}"
            if state().get(confirm_key):
                if c[2].button("Confirm remove", key=f"rmc_{repo['id']}", **STRETCH):
                    if safe(api().delete_repository, repo["id"]) is None:
                        state().pop(confirm_key, None)
                        flash("success", f"Removed {repo['name']}", "Its files, index, history and fix suggestions were deleted.")
                        st.rerun()
            elif c[2].button("Remove", key=f"rm_{repo['id']}", **STRETCH):
                state()[confirm_key] = True
                st.rerun()
            if state().get(confirm_key):
                c[3].caption("This deletes the repository's downloaded files, search index, history and fix suggestions.")


# ------------------------------------------------------------------- search --
def page_search() -> None:
    ui.page_head("Search code", "Find the code behind a feature by name or by what it does.")
    show_flash()
    repo = require_repo()
    if repo is None:
        return
    tab_search, tab_overview = st.tabs(["Search", "Repository overview"])
    with tab_search:
        with st.form("search_form"):
            query = st.text_input("What are you looking for?", placeholder="e.g. password check, save record to database, createSessionToken")
            c1, c2 = st.columns([2, 1])
            mode_label = c1.selectbox("Search method", list(MODES))
            top_k = c2.slider("Results", 3, 15, 8)
            submitted = st.form_submit_button("Search", type="primary")
        if submitted:
            if not query.strip():
                ui.notice("error", "Type something to search for")
            else:
                with st.spinner("Searching..."):
                    result = safe(api().search, repo["id"], query.strip(), MODES[mode_label], top_k)
                state().search_result = {"repo": repo["id"], "data": result} if result else None
        shown = state().get("search_result")
        if shown and shown["repo"] == repo["id"]:
            data = shown["data"]
            if data.get("note"):
                ui.notice("info", "Showing keyword results", data["note"])
            if not data["results"]:
                ui.empty_state("No matches", "Try a function name, a file name, or fewer and simpler words.")
            else:
                ui.render(f'<div class="hint">{len(data["results"])} results using <b>{ui.esc(data["mode_used"])}</b> search.</div>')
                for r in data["results"]:
                    tag = "keyword + meaning" if r.get("keyword_rank") and r.get("semantic_rank") else "keyword" if r.get("keyword_rank") else "meaning"
                    ui.render(ui.code_block(r["text"], r["path"] + (f" - {r['symbol']}" if r.get("symbol") else ""), r["start_line"], r.get("language", ""), tag, all_hit=True))
    with tab_overview:
        overview = safe(api().overview, repo["id"])
        if overview:
            render_overview(overview)


def render_overview(ov: dict) -> None:
    counts = ov.get("symbol_counts", {})
    cols = st.columns(4)
    for col, (label, value) in zip(cols, [("Files indexed", ov["total_files"]), ("Code chunks", ov["total_chunks"]),
                                          ("Functions and methods", counts.get("function", 0) + counts.get("method", 0)), ("Classes and types", sum(counts.get(k, 0) for k in ("class", "interface", "enum", "type")))]):
        col.html(ui.stat(label, value))
    semantic = ov.get("semantic", {})
    ui.render(f'<div class="hint" style="margin:.6rem 0">Meaning-based (semantic) search: <b>{"on" if semantic.get("indexed") else "off"}</b>'
              f'{"" if semantic.get("indexed") else " - " + ui.esc(semantic.get("error") or "disabled")}</div>')
    parsed = sum(1 for f in ov["files"] if f["parsed_with_tree_sitter"])
    ui.render(f'<div class="hint">{parsed} of {len(ov["files"])} files were parsed with Tree-sitter; the rest are indexed as plain text.</div>')
    st.markdown("**Languages**")
    st.dataframe([{"Language": k, "Files": v} for k, v in sorted(ov["languages"].items(), key=lambda kv: -kv[1])], hide_index=True, **STRETCH)
    if ov.get("skipped"):
        labels = {"excluded_directory": "in dependency/build folders", "possible_secret": "that may contain secrets", "generated_or_lock_file": "generated or lock files",
                  "unsupported_type": "of unsupported types", "binary": "binary", "file_too_large": "over the size limit", "empty": "empty", "symlink": "symbolic links",
                  "file_limit_reached": "past the file limit", "chunk_limit_reached": "past the chunk limit"}
        st.markdown("**Skipped files** (not read, not indexed): " + ", ".join(f"{n} {labels.get(k, k)}" for k, n in ov["skipped"].items()))
    st.markdown("**Files and detected code structure**")
    needle = st.text_input("Filter by path", key="overview_filter", placeholder="e.g. auth")
    files = [f for f in ov["files"] if needle.lower() in f["path"].lower()]
    st.dataframe([{"Path": f["path"], "Language": f["language"], "Lines": f["lines"], "Symbols": len(f["symbols"]), "Parsed": "yes" if f["parsed_with_tree_sitter"] else "text only"} for f in files],
                 hide_index=True, **STRETCH, height=300)
    with_symbols = [f for f in files if f["symbols"]]
    if with_symbols:
        choice = st.selectbox("Show functions and classes in", [f["path"] for f in with_symbols], key="overview_file")
        file = next(f for f in with_symbols if f["path"] == choice)
        st.dataframe([{"Name": s["name"], "Kind": s["kind"], "Lines": f"{s['start_line']}-{s['end_line']}"} for s in file["symbols"]], hide_index=True, **STRETCH)


# ---------------------------------------------------------------- assistant --
def set_example(text: str) -> None:
    state().ask_text = text


def page_assistant() -> None:
    ui.page_head("Ask the AI", "Questions are answered from code retrieved from your repository. The answer lists its evidence and what it could not confirm.")
    show_flash()
    repo = require_repo()
    if repo is None:
        return
    ui.render(f'<div class="hint">Repository: <b>{ui.esc(repo["name"])}</b></div>')
    ex = st.columns(len(EXAMPLE_QUESTIONS))
    for col, q in zip(ex, EXAMPLE_QUESTIONS):
        col.button(q, key=f"ex_{q[:12]}", on_click=set_example, args=(q,), **STRETCH)
    question = st.text_area("Your question", key="ask_text", height=110, max_chars=2000, placeholder="e.g. Where is the password checked when a user signs in?")
    if st.button("Ask", type="primary", key="ask_btn"):
        if not question.strip():
            ui.notice("error", "Write a question first")
        else:
            with st.spinner("Finding relevant code and asking the AI..."):
                result = safe(api().ask, repo["id"], question.strip())
            state().ask_result = {"repo": repo["id"], "question": question.strip(), "data": result} if result else None
    shown = state().get("ask_result")
    if shown and shown["repo"] == repo["id"]:
        data = shown["data"]
        if data.get("note"):
            ui.notice("info", "Keyword results only", data["note"])
        if not data.get("llm_used"):
            ui.notice("warning", "No AI answer was generated", "No matching code was found, so nothing was sent to the AI.")
        with st.container(key="answer_box"):
            st.markdown(safe_markdown(data["answer"]))
        ui.render(f'<div class="hint">Saved to history. Model: {ui.esc(data.get("model") or "none")}. Retrieval: {ui.esc(data["mode_used"])}. AI answers can be wrong; check the cited code.</div>')
        ui.render_references(data["references"])


# --------------------------------------------------------------------- bugs --
def page_bugs() -> None:
    ui.page_head("Investigate a bug", "Paste an error message, traceback or description. RepoPilot finds the related code and suggests what to check.")
    show_flash()
    repo = require_repo()
    if repo is None:
        return
    ui.render(f'<div class="hint">Repository: <b>{ui.esc(repo["name"])}</b></div>')
    description = st.text_area("Error message or bug description", key="bug_text", height=180, max_chars=6000,
                               placeholder="Paste the full traceback if you have one, or describe what goes wrong and when.")
    if st.button("Investigate", type="primary", key="bug_btn"):
        if not description.strip():
            ui.notice("error", "Describe the bug or paste an error first")
        else:
            with st.spinner("Matching the error to code and asking the AI..."):
                result = safe(api().investigate, repo["id"], description.strip())
            state().bug_result = {"repo": repo["id"], "description": description.strip(), "data": result} if result else None
    shown = state().get("bug_result")
    if shown and shown["repo"] == repo["id"]:
        data = shown["data"]
        ui.render('<span class="badge-hyp">Hypothesis, not a confirmed bug</span>')
        ui.render(f'<div class="hint" style="margin:.4rem 0 .8rem">{ui.esc(data["disclaimer"])}</div>')
        sig = data["signals"]
        chips = "".join(f'<span class="chip">{ui.esc(x)}</span>' for x in sig["exceptions"] + [f'{f["path"].split("/")[-1]}:{f["line"]}' for f in sig["frames"][:6]])
        if chips:
            ui.render(f'<div class="hint">Detected in your report</div><div>{chips}</div>')
        if data.get("note"):
            ui.notice("info", "Keyword results only", data["note"])
        with st.container(key="answer_box"):
            st.markdown(safe_markdown(data["analysis"]))
        ui.render_references(data["references"], "Code that may be involved")
        if data.get("llm_used"):
            if st.button("Propose a fix for this", key="bug_to_fix"):
                with st.spinner("Asking the AI for one minimal change and validating it against the file..."):
                    outcome = safe(api().suggest_fix, repo["id"], shown["description"])
                if outcome and outcome.get("suggestion"):
                    flash("success", "Fix suggestion saved", "Review the change below. Nothing has been applied.")
                    go("fixes")
                    st.rerun()
                elif outcome:
                    ui.notice("warning", "The AI could not propose a safe change", outcome.get("cannot_fix_reason", ""))


# -------------------------------------------------------------------- fixes --
def page_fixes() -> None:
    ui.page_head("Fix suggestions", "Review small AI-proposed changes. Nothing is applied until you approve it, and nothing is ever pushed to GitHub.")
    show_flash()
    repo = require_repo()
    if repo is None:
        return
    ui.notice("warning", "AI-generated suggestions are not verified", "RepoPilot does not run your tests. Read each diff, and test the change yourself before using it.")
    with st.form("fix_form"):
        description = st.text_area("What should be fixed?", height=110, max_chars=4000, placeholder="Describe the bug or paste the error. The AI will propose one minimal change.")
        submitted = st.form_submit_button("Suggest a fix", type="primary")
    if submitted:
        if not description.strip():
            ui.notice("error", "Describe the problem first")
        else:
            with st.spinner("Retrieving code, asking the AI, and validating the proposed change..."):
                outcome = safe(api().suggest_fix, repo["id"], description.strip())
            if outcome and outcome.get("suggestion"):
                flash("success", "Fix suggestion saved", "Review it below.")
                st.rerun()
            elif outcome:
                ui.notice("warning", "The AI could not propose a safe change", outcome.get("cannot_fix_reason", ""))
    fixes = safe(api().list_fixes, repo["id"]) or []
    ui.render(f'<div class="sec-label">Suggestions for {ui.esc(repo["name"])}</div>')
    if not fixes:
        ui.empty_state("No suggestions yet", "Describe a problem above, or use Propose a fix from a bug investigation.")
    for fix in fixes:
        status = "applied" if fix["applied_at"] else fix["review_decision"]
        with st.expander(f"{fix['target_file']} - {ui.STATUS_LABELS[status]} ({ui.fmt_dt(fix['created_at'])})", expanded=fix["review_decision"] == "pending"):
            ui.render(f'<div class="hint">Problem: {ui.esc(fix["problem_description"][:400])}</div>')
            ui.render(f'<span class="badge-hyp">AI suggestion, not verified</span>{ui.pill(status)}')
            st.markdown("**Why this change**")
            st.markdown(safe_markdown(fix["explanation"]))
            ui.render(ui.diff_block(fix["diff"]))
            o, n = st.columns(2)
            o.markdown("**Original**")
            o.html(ui.code_block(fix["original_code"], fix["target_file"], 1, "", "before"))
            n.markdown("**Proposed**")
            n.html(ui.code_block(fix["proposed_code"], fix["target_file"], 1, "", "after"))
            if fix["applied_at"]:
                ui.notice("success", "Applied to the local working copy", f"Written on {ui.fmt_dt(fix['applied_at'])}. GitHub was not changed.")
            else:
                c = st.columns([1, 1, 1.6, 1])
                if c[0].button("Approve", key=f"ap_{fix['id']}", disabled=fix["review_decision"] == "approved", **STRETCH):
                    if safe(api().review_fix, fix["id"], "approved"):
                        st.rerun()
                if c[1].button("Reject", key=f"rj_{fix['id']}", disabled=fix["review_decision"] == "rejected", **STRETCH):
                    if safe(api().review_fix, fix["id"], "rejected"):
                        st.rerun()
                if c[2].button("Apply to local copy", key=f"ay_{fix['id']}", type="primary", disabled=fix["review_decision"] != "approved", **STRETCH,
                               help="Writes the approved change to RepoPilot's downloaded copy only."):
                    if safe(api().apply_fix, fix["id"]):
                        flash("success", "Change applied to the local copy", "Re-analyze the repository to refresh search.")
                        st.rerun()
                if c[3].button("Delete", key=f"dl_{fix['id']}", **STRETCH):
                    if safe(api().delete_fix, fix["id"]) is None:
                        st.rerun()


# ------------------------------------------------------------------ history --
def page_history() -> None:
    ui.page_head("History", "Every question and bug investigation you have run, with the code that supported it.")
    show_flash()
    c1, c2 = st.columns(2)
    kind = c1.selectbox("Type", ["All", "Code questions", "Bug investigations"], key="hist_kind")
    scope = c2.selectbox("Repository", ["All repositories", "Active repository only"], key="hist_scope")
    repo = active_repo() if scope == "Active repository only" else None
    records = safe(api().list_history, repo["id"] if repo else None, {"Code questions": "question", "Bug investigations": "bug"}.get(kind)) or []
    if not records:
        ui.empty_state("No history yet", "Ask a question or investigate a bug and the result will be saved here.")
    for rec in records:
        with st.expander(f"{rec['analysis_type_label']}: {rec['user_input'][:70].strip()} ({rec['repository_name']}, {ui.fmt_dt(rec['created_at'])})"):
            st.markdown("**Your input**")
            st.code(rec["user_input"], language=None, wrap_lines=True)
            st.markdown("**Response**")
            st.markdown(safe_markdown(rec["ai_response"]))
            ui.render(f'<div class="hint">Model: {ui.esc(rec["llm_model"] or "none")}</div>')
            ui.render_references(rec["file_references"], "Referenced code")
            key = f"confirm_h_{rec['id']}"
            if state().get(key):
                if st.button("Confirm delete", key=f"hc_{rec['id']}"):
                    if safe(api().delete_history, rec["id"]) is None:
                        state().pop(key, None)
                        st.rerun()
            elif st.button("Delete this record", key=f"hd_{rec['id']}"):
                state()[key] = True
                st.rerun()


# ------------------------------------------------------------------- router --
PAGES = {"home": page_home, "auth": page_auth, "dashboard": page_dashboard, "repos": page_repos, "search": page_search,
         "assistant": page_assistant, "bugs": page_bugs, "fixes": page_fixes, "history": page_history}


def main() -> None:
    css = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")
    state().setdefault("page", "home")
    logged_in = bool(state().get("token"))
    page = state().page
    if page in PROTECTED and not logged_in:
        page = state().page = "auth"
    if page == "auth" and logged_in:
        page = state().page = "dashboard"
    if logged_in and page in PROTECTED:
        sidebar()
    else:
        st.html("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'], [data-testid='stExpandSidebarButton']{display:none !important}</style>")
    PAGES.get(page, page_home)()


main()
