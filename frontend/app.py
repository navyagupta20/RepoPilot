"""RepoPilot AI - Streamlit frontend.

All application data comes from the Django REST API.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

import components as ui
from api_client import BACKEND_URL, ApiClient, ApiError


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="RepoPilot AI",
    page_icon=":material/code:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _version_tuple(version: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:2])


STRETCH = (
    {"width": "stretch"}
    if _version_tuple(st.__version__) >= (1, 50)
    else {"use_container_width": True}
)


# ============================================================
# NAVIGATION
# ============================================================

PROTECTED = {
    "dashboard",
    "repos",
    "search",
    "assistant",
    "bugs",
    "fixes",
    "history",
}

NAV_GROUPS = [
    (
        "WORKSPACE",
        [
            ("dashboard", "Dashboard", "dashboard"),
            ("repos", "Repositories", "folder_open"),
        ],
    ),
    (
        "CODE INTELLIGENCE",
        [
            ("search", "Code Search", "search"),
            ("assistant", "AI Assistant", "psychology"),
            ("bugs", "Bug Analyzer", "bug_report"),
            ("fixes", "Fix Suggestions", "difference"),
        ],
    ),
    (
        "ACTIVITY",
        [
            ("history", "History", "history"),
        ],
    ),
]

NAV = [
    (page, label)
    for _, items in NAV_GROUPS
    for page, label, _ in items
]

PAGE_INFO = {
    "dashboard": (
        "Dashboard",
        "Your development workspace at a glance.",
        "WORKSPACE",
    ),
    "repos": (
        "Repositories",
        "Connect and manage your GitHub repositories.",
        "WORKSPACE",
    ),
    "search": (
        "Code Search",
        "Explore your codebase using keyword and meaning-based search.",
        "CODE INTELLIGENCE",
    ),
    "assistant": (
        "AI Assistant",
        "Ask questions and get answers grounded in repository code.",
        "CODE INTELLIGENCE",
    ),
    "bugs": (
        "Bug Analyzer",
        "Investigate errors and identify potentially related code.",
        "CODE INTELLIGENCE",
    ),
    "fixes": (
        "Fix Suggestions",
        "Review, approve and apply AI-proposed code changes.",
        "CODE INTELLIGENCE",
    ),
    "history": (
        "History",
        "Review previous questions and bug investigations.",
        "ACTIVITY",
    ),
}

EXAMPLE_QUESTIONS = [
    "Explain how this project works.",
    "Where is authentication implemented?",
    "Which function handles database operations?",
    "How does the main API endpoint work?",
]

MODES = {
    "Hybrid (recommended)": "hybrid",
    "Keyword (BM25)": "keyword",
    "Meaning (FAISS)": "semantic",
}


# ============================================================
# SESSION STATE AND API HELPERS
# ============================================================

def state():
    return st.session_state


def api() -> ApiClient:
    return ApiClient(
        BACKEND_URL,
        state().get("token"),
    )


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
        flash(
            "warning",
            "Your session ended",
            "Please sign in again.",
        )


def safe(fn, *args, **kwargs):
    """Call the API and show a friendly error when something fails."""
    try:
        return fn(*args, **kwargs)

    except ApiError as exc:
        if exc.status == 401 and state().get("token"):
            sign_out(expired=True)
            st.rerun()

        elif exc.code == "llm_not_configured":
            ui.notice(
                "warning",
                "The AI assistant is not configured",
                exc.message,
            )

        elif exc.code == "unreachable":
            ui.notice(
                "error",
                "Backend not reachable",
                exc.message,
            )

        else:
            ui.notice(
                "error",
                "That operation failed",
                exc.message,
            )

        return None


def safe_markdown(text: str) -> str:
    """Remove unsafe HTML, images and external links from AI responses."""
    text = re.sub(
        r"!\[[^\]]*\]\([^)]*\)",
        "[image removed]",
        text,
    )

    text = re.sub(
        r"\[([^\]]+)\]\((?:https?|ftp|data|javascript):[^)]*\)",
        r"\1",
        text,
        flags=re.I,
    )

    return re.sub(r"<[^>]+>", "", text)


def active_repo() -> dict | None:
    return next(
        (
            repo
            for repo in state().get("repos", [])
            if repo["id"] == state().get("active_repo")
        ),
        None,
    )


def select_repo(repo_id: int, page: str) -> None:
    state().active_repo = repo_id
    state()["_active_sel"] = repo_id
    state().page = page


def on_repo_change() -> None:
    state().active_repo = state()["_active_sel"]


def show_flash() -> None:
    if "flash" in state():
        kind, title, body = state().pop("flash")
        ui.notice(kind, title, body)


def run_analysis(repo: dict) -> None:
    with st.spinner(
        "Analyzing repository, parsing files and building search indexes..."
    ):
        result = safe(
            api().analyze,
            repo["id"],
        )

    if result:
        semantic = (
            result.get("metadata", {})
            .get("analysis", {})
            .get("semantic", {})
        )

        mode = (
            "keyword and meaning-based search"
            if semantic.get("indexed")
            else (
                "keyword search only "
                f"({semantic.get('error') or 'semantic search disabled'})"
            )
        )

        flash(
            "success",
            f"Analysis complete for {result['name']}",
            f"Search is ready using {mode}.",
        )

        st.rerun()


def require_repo(analyzed: bool = True) -> dict | None:
    repo = active_repo()

    if repo is None:
        ui.empty_state(
            "Connect a repository first",
            "Add a public GitHub repository, analyze it, "
            "and this workspace will be ready to use.",
        )

        st.button(
            "Connect repository",
            type="primary",
            on_click=go,
            args=("repos",),
            key="need_repo",
        )

        return None

    if analyzed and repo["analysis_status"] != "completed":
        ui.notice(
            "warning",
            f"{repo['name']} has not been analyzed yet",
            "Analysis builds the search index required by this feature.",
        )

        if st.button(
            "Analyze now",
            type="primary",
            key=f"analyze_now_{repo['id']}",
        ):
            run_analysis(repo)

        return None

    if repo.get("metadata", {}).get("index_stale"):
        ui.notice(
            "info",
            "Repository index may be outdated",
            "An approved fix was applied to the local copy. "
            "Re-analyze the repository to refresh search.",
        )

    return repo


# ============================================================
# SHARED WORKSPACE INTERFACE
# ============================================================

def workspace_toolbar() -> None:
    """Consistent toolbar displayed above every authenticated page."""
    repo = active_repo()

    st.html(
        """
        <div class="workspace-toolbar">
            <div class="workspace-toolbar-left">
                <span class="toolbar-label">REPOPILOT</span>
                <span class="toolbar-separator">/</span>
                <span class="toolbar-context">DEVELOPER WORKSPACE</span>
            </div>
            <div class="toolbar-description">
                Repository intelligence and code analysis
            </div>
        </div>
        """
    )

    left, right = st.columns(
        [5, 1.5],
        vertical_alignment="center",
    )

    with left:
        if repo:
            status = repo.get("analysis_status", "unknown")

            st.caption(
                f"ACTIVE REPOSITORY  /  {repo['name']}  ·  "
                f"STATUS: {status.replace('_', ' ').upper()}"
            )
        else:
            st.caption("ACTIVE REPOSITORY  /  No repository selected")

    with right:
        if st.button(
            "Connect repository",
            key="toolbar_connect",
            **STRETCH,
        ):
            go("repos")
            st.rerun()


def page_heading(page: str) -> None:
    """Shared page heading and section context."""
    title, description, section = PAGE_INFO[page]

    st.html(
        f"""
        <div class="app-page-heading">
            <div class="app-breadcrumb">
                WORKSPACE
                <span>/</span>
                {ui.esc(section)}
            </div>
            <h1>{ui.esc(title)}</h1>
            <p>{ui.esc(description)}</p>
        </div>
        """
    )


def section_heading(title: str, description: str = "") -> None:
    st.html(
        f"""
        <div class="workspace-section-heading">
            <div>
                <h3>{ui.esc(title)}</h3>
                <p>{ui.esc(description)}</p>
            </div>
        </div>
        """
    )


def repository_context(repo: dict) -> None:
    st.html(
        f"""
        <div class="repository-context">
            <span class="repository-context-label">CURRENT REPOSITORY</span>
            <strong>{ui.esc(repo['name'])}</strong>
            <span class="repository-context-status">
                {ui.esc(repo['analysis_status'].replace('_', ' ').upper())}
            </span>
        </div>
        """
    )


# ============================================================
# LANDING PAGE
# ============================================================

def page_home() -> None:
    logged_in = bool(state().get("token"))

    left, right = st.columns(
        [8.5, 1.5],
        vertical_alignment="center",
        gap="small",
    )

    with left:
        st.html(ui.nav_bar_html())

    st.html("""
    <style>
    .st-key-nav_signin {
        transform: translateY(20px);
    }
    </style>
    """)

    with right:
        st.button(
            "Open dashboard" if logged_in else "Sign in",
            on_click=go,
            args=("dashboard" if logged_in else "auth",),
            key="nav_signin",
            type="secondary",
            **STRETCH,
        )

    text_col, preview_col = st.columns(
        [6, 5],
        gap="large",
    )

    with text_col:
        ui.render(ui.hero_text_html())

        b1, b2, _ = st.columns([1.5, 1.5, 1])

        def start():
            state().after_login = "repos"
            go("repos" if logged_in else "auth")

        b1.button(
            "Analyze Repository",
            type="primary",
            on_click=start,
            key="hero_cta",
            **STRETCH,
        )

        b2.html(
            '<a class="btn-link" href="#features" '
            'style="width:100%">Explore Features</a>'
        )

        ui.render(
            '<div class="hero-note">'
            'Public GitHub repositories. '
            'Nothing is ever pushed to GitHub.'
            '</div>'
        )

    with preview_col:
        ui.render(ui.product_preview_html())

    ui.render(ui.features_html())
    ui.render(ui.how_it_works_html())
    ui.render(ui.footer_html())


# ============================================================
# AUTHENTICATION
# ============================================================

def page_auth() -> None:
    # Authentication-specific styling.
    st.html(
        """
        <style>
        /* Hide unnecessary top spacing on the authentication page */
        .stMainBlockContainer {
            padding-top: 1.5rem !important;
            max-width: 1250px !important;
        }

        /* Back button */
        .st-key-auth_back button {
            border: 1px solid #E4E3DF !important;
            background: #FFFFFF !important;
            color: #42484B !important;
            border-radius: 9px !important;
            font-size: 13px !important;
            min-height: 38px !important;
        }

        .st-key-auth_back button:hover {
            border-color: #E58A4B !important;
            color: #CC7138 !important;
        }

        /* Left branding panel */
        .auth-visual {
            background:
                radial-gradient(
                    circle at 85% 15%,
                    rgba(229,138,75,.18),
                    transparent 32%
                ),
                linear-gradient(145deg, #252A2E, #171A1C);
            border: 1px solid #343A3E;
            border-radius: 20px;
            min-height: 560px;
            padding: 44px 38px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            color: #F7F6F3;
            overflow: hidden;
            position: relative;
        }

        .auth-visual-brand {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 21px;
            font-weight: 700;
            letter-spacing: -.7px;
            color: #FFFFFF;
        }

        .auth-visual-brand span {
            color: #E58A4B;
        }

        .auth-visual-kicker {
            color: #E58A4B;
            font-family: 'DM Mono', monospace;
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 2px;
            margin-top: 65px;
            margin-bottom: 17px;
        }

        .auth-visual h1 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(34px, 3.4vw, 47px);
    font-weight: 700;
    line-height: 1.13;
    letter-spacing: -1.8px;
    color: #FFFFFF !important;
    margin: 0 0 18px;
}

.auth-visual h1 span {
    color: #E58A4B !important;
}

        .auth-visual h1 span {
            color: #E58A4B;
        }

        .auth-visual-description {
            color: #B8BEC0;
            font-size: 14px;
            line-height: 1.8;
            max-width: 390px;
        }

        .auth-feature-list {
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-top: 34px;
        }

        .auth-feature {
            display: flex;
            align-items: center;
            gap: 12px;
            color: #E3E5E4;
            font-size: 13px;
        }

        .auth-feature-icon {
            width: 27px;
            height: 27px;
            border-radius: 8px;
            background: rgba(229,138,75,.13);
            border: 1px solid rgba(229,138,75,.24);
            color: #EFA36F;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            flex-shrink: 0;
        }

        .auth-visual-footer {
            border-top: 1px solid rgba(255,255,255,.12);
            padding-top: 20px;
            margin-top: 48px;
            color: #858D90;
            font-family: 'DM Mono', monospace;
            font-size: 10px;
            letter-spacing: .7px;
        }
/* Hide "Press Enter to submit form" */
[data-testid="InputInstructions"] {
    display: none !important;
}
        /* Form panel */
        .st-key-auth_form_panel {
            background: #FFFFFF;
            border: 1px solid #E7E5E0;
            border-radius: 20px;
            padding: 32px 34px 28px;
            box-shadow: 0 12px 40px rgba(35,39,41,.045);
        }

        .auth-form-heading {
            font-family: 'Space Grotesk', sans-serif;
            color: #252A2E;
            font-size: 27px;
            font-weight: 700;
            letter-spacing: -.8px;
            margin: 0 0 7px;
        }

        .auth-form-subheading {
            color: #858C90;
            font-size: 13px;
            line-height: 1.6;
            margin-bottom: 23px;
        }

        .auth-form-caption {
            color: #92989A;
            font-family: 'DM Mono', monospace;
            font-size: 10px;
            letter-spacing: 1.2px;
            margin-bottom: 8px;
        }

        .st-key-auth_form_panel [data-testid="stTextInput"] label {
            color: #42484B !important;
            font-size: 12px !important;
            font-weight: 600 !important;
        }

        .st-key-auth_form_panel [data-testid="stTextInput"] input {
            background: #FAFAF8 !important;
            border: 1px solid #E4E3DF !important;
            border-radius: 9px !important;
            min-height: 43px !important;
        }

        .st-key-auth_form_panel [data-testid="stTextInput"] input:focus {
            border-color: #E58A4B !important;
            box-shadow: 0 0 0 1px #E58A4B !important;
        }

        .st-key-auth_form_panel [data-testid="stFormSubmitButton"] button {
            background: #E58A4B !important;
            border: 1px solid #E58A4B !important;
            color: #202326 !important;
            border-radius: 9px !important;
            font-weight: 700 !important;
            min-height: 44px !important;
            margin-top: 10px;
        }

        .st-key-auth_form_panel [data-testid="stFormSubmitButton"] button:hover {
            background: #CC7138 !important;
            border-color: #CC7138 !important;
            color: #FFFFFF !important;
        }

        .st-key-auth_form_panel [data-testid="stTabs"] button {
            font-size: 13px !important;
            font-weight: 600 !important;
        }

        .auth-security-note {
            border-top: 1px solid #ECEAE6;
            padding-top: 17px;
            margin-top: 22px;
            color: #92989A;
            font-size: 11px;
            line-height: 1.6;
            text-align: center;
        }

        .auth-security-note span {
            color: #CC7138;
            font-weight: 600;
        }

        /* Responsive layout */
        @media (max-width: 850px) {
            .auth-visual {
                min-height: auto;
                padding: 30px 25px;
            }

            .auth-visual-kicker {
                margin-top: 35px;
            }

            .auth-visual-footer {
                margin-top: 30px;
            }

            .st-key-auth_form_panel {
                padding: 25px 20px;
            }
        }
        </style>
        """
    )

    st.button(
        "←  Back to home",
        on_click=go,
        args=("home",),
        key="auth_back",
    )

    st.write("")

    visual_col, form_col = st.columns(
        [1.05, 0.95],
        gap="large",
        vertical_alignment="center",
    )

    with visual_col:
        st.html(
            """
            <div class="auth-visual">
                <div>
                    <div class="auth-visual-brand">
                        RepoPilot<span>.</span>
                    </div>

                    <div class="auth-visual-kicker">
                        REPOSITORY INTELLIGENCE
                    </div>

                    <h1>
                        Understand your code<br>
                        <span>Build with confidence</span>
                    </h1>

                    <p class="auth-visual-description">
                        Your codebase, made easier to understand.
                        Search repositories, explore code relationships
                        and get AI-powered insights in one workspace.
                    </p>

                    <div class="auth-feature-list">
                        <div class="auth-feature">
                            <div class="auth-feature-icon">⌕</div>
                            <span>Search code by keywords and meaning</span>
                        </div>

                        <div class="auth-feature">
                            <div class="auth-feature-icon">✳</div>
                            <span>Ask questions about your repository</span>
                        </div>

                        <div class="auth-feature">
                            <div class="auth-feature-icon">⌘</div>
                            <span>Investigate bugs and review AI fixes</span>
                        </div>
                    </div>
                </div>

                <div class="auth-visual-footer">
                    YOUR CODEBASE. BETTER UNDERSTOOD.
                </div>
            </div>
            """
        )

    with form_col:
        with st.container(key="auth_form_panel"):
            ui.render(
                """
                <div class="auth-form-caption">
                    DEVELOPER WORKSPACE
                </div>
                <div class="auth-form-heading">
                    Welcome to RepoPilot
                </div>
                <div class="auth-form-subheading">
                    Sign in to continue or create an account
                    to get started.
                </div>
                """
            )

            show_flash()

            tab_in, tab_up = st.tabs(
                ["Sign in", "Create account"]
            )

            with tab_in:
                with st.form("login_form"):
                    username = st.text_input(
                        "Username",
                        key="login_username",
                        placeholder="Enter your username",
                    )

                    password = st.text_input(
                        "Password",
                        type="password",
                        key="login_password",
                        placeholder="Enter your password",
                    )

                    submitted = st.form_submit_button(
                        "Sign in to your workspace",
                        type="primary",
                        **STRETCH,
                    )

                if submitted:
                    if not username or not password:
                        ui.notice(
                            "error",
                            "Enter your username and password",
                        )
                    else:
                        with st.spinner("Signing in..."):
                            data = safe(
                                api().login,
                                username,
                                password,
                            )

                        if data:
                            finish_login(data)

            with tab_up:
                with st.form(
                    "register_form",
                    clear_on_submit=False,
                ):
                    new_user = st.text_input(
                        "Username",
                        key="reg_username",
                        placeholder="Choose a username",
                        help=(
                            "3-30 characters: letters, numbers "
                            "and . @ + - _"
                        ),
                    )

                    email = st.text_input(
                        "Email (optional)",
                        key="reg_email",
                        placeholder="you@example.com",
                    )

                    pw1 = st.text_input(
                        "Password",
                        type="password",
                        key="reg_pw1",
                        placeholder="Create a password",
                        help=(
                            "At least 8 characters, "
                            "not too common, not all digits."
                        ),
                    )

                    pw2 = st.text_input(
                        "Confirm password",
                        type="password",
                        key="reg_pw2",
                        placeholder="Enter your password again",
                    )

                    created = st.form_submit_button(
                        "Create my account",
                        type="primary",
                        **STRETCH,
                    )

                if created:
                    if pw1 != pw2:
                        ui.notice(
                            "error",
                            "The passwords do not match",
                        )
                    elif not new_user or not pw1:
                        ui.notice(
                            "error",
                            "Choose a username and password",
                        )
                    else:
                        with st.spinner("Creating your account..."):
                            data = safe(
                                api().register,
                                new_user,
                                pw1,
                                email,
                            )

                        if data:
                            finish_login(data)

            ui.render(
                """
                <div class="auth-security-note">
                    Your account is managed securely by the
                    RepoPilot backend.<br>
                    <span>Built for developers, by developers.</span>
                </div>
                """
            )


def finish_login(data: dict) -> None:
    state().token = data["token"]
    state().user = data["user"]

    destination = state().pop(
        "after_login",
        "dashboard",
    )

    state().page = destination

    flash(
        "success",
        f"Welcome, {data['user']['username']}",
        "You are signed in.",
    )

    st.rerun()


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

def sidebar() -> None:
    with st.sidebar:
        ui.render(
            f"""
            <div class="sidebar-brand">
                {ui.brand(inverse=True)}
            </div>

            <div class="sidebar-profile">
                <span class="sidebar-profile-label">SIGNED IN AS</span>
                <strong>{ui.esc(state().user['username'])}</strong>
            </div>
            """
        )

        for group_name, items in NAV_GROUPS:
            ui.render(
                f"""
                <div class="sidebar-group-label">
                    {ui.esc(group_name)}
                </div>
                """
            )

            for key, label, icon in items:
                active = state().page == key

                st.button(
                    label,
                    key=f"nav_{key}",
                    type="primary" if active else "secondary",
                    on_click=go,
                    args=(key,),
                    **STRETCH,
                )

        ui.render('<div class="sidebar-divider"></div>')

        ui.render(
            '<div class="sidebar-group-label">'
            'REPOSITORY CONTEXT'
            '</div>'
        )

        repos = safe(api().list_repositories)
        state().repos = repos or []

        if state().repos:
            ids = [
                repo["id"]
                for repo in state().repos
            ]

            if state().get("active_repo") not in ids:
                state().active_repo = ids[0]

            state()["_active_sel"] = state().active_repo

            st.selectbox(
                "Active repository",
                ids,
                key="_active_sel",
                on_change=on_repo_change,
                format_func=lambda repo_id: next(
                    repo["name"]
                    for repo in state().repos
                    if repo["id"] == repo_id
                ),
            )

            repo = active_repo()

            if repo:
                st.caption(
                    f"Status: "
                    f"{repo['analysis_status'].replace('_', ' ')}"
                )

                st.caption(
                    f"Files: {repo.get('file_count', 0)}"
                )
        else:
            ui.render(
                '<div class="sidebar-empty">'
                'No repositories connected yet.'
                '</div>'
            )

        ui.render('<div class="sidebar-divider"></div>')

        st.button(
            "Sign out",
            key="signout",
            **STRETCH,
            on_click=sign_out,
        )


# ============================================================
# DASHBOARD
# ============================================================

def page_dashboard() -> None:
    page_heading("dashboard")
    show_flash()

    data = safe(api().dashboard)

    if data is None:
        return

    metrics = [
        ("Connected repositories", data["repository_count"]),
        ("Repositories analyzed", data["repositories_analyzed"]),
        ("Completed AI analyses", data["analysis_count"]),
        ("Fix suggestions", data["fix_suggestion_count"]),
    ]

    cols = st.columns(4)

    for col, (label, value) in zip(cols, metrics):
        with col:
            ui.render(ui.stat(label, value))

    st.write("")

    section_heading(
        "Repository workspace",
        "Your connected projects and available actions.",
    )

    repos = state().repos

    if not repos:
        ui.empty_state(
            "Your workspace is empty",
            "Connect a public GitHub repository to start. "
            "RepoPilot will download its source files, "
            "index them and let you ask questions.",
        )

        st.button(
            "Connect your first repository",
            type="primary",
            on_click=go,
            args=("repos",),
            key="empty_dash_connect",
        )
    else:
        cols = st.columns(2, gap="medium")

        for index, repo in enumerate(repos):
            with cols[index % 2].container(
                border=True,
                key=f"repo_card_{repo['id']}",
            ):
                ui.render(ui.repo_header(repo))
                st.divider()

                actions = st.columns(3)

                actions[0].button(
                    "Search code",
                    key=f"d_s_{repo['id']}",
                    on_click=select_repo,
                    args=(repo["id"], "search"),
                    **STRETCH,
                )

                actions[1].button(
                    "Ask AI",
                    key=f"d_a_{repo['id']}",
                    on_click=select_repo,
                    args=(repo["id"], "assistant"),
                    **STRETCH,
                )

                actions[2].button(
                    "Investigate",
                    key=f"d_b_{repo['id']}",
                    on_click=select_repo,
                    args=(repo["id"], "bugs"),
                    **STRETCH,
                )

    st.write("")

    section_heading(
        "Recent analyses",
        "Previously completed questions and investigations.",
    )

    recent = data["recent_analyses"]

    if not recent:
        ui.empty_state(
            "No analyses yet",
            "Ask a question about a repository or investigate "
            "a bug to see activity here.",
        )
    else:
        for item in recent:
            with st.expander(
                f"{item['analysis_type_label']}  ·  "
                f"{item['repository_name']}  ·  "
                f"{ui.fmt_dt(item['created_at'])}"
            ):
                st.markdown("**Your input**")
                st.markdown(f"> {item['user_input'][:300]}")

                st.markdown("**AI response**")
                st.markdown(
                    safe_markdown(
                        item["ai_response"][:1200]
                    )
                )


# ============================================================
# REPOSITORIES
# ============================================================

ANALYSIS_STEPS = [
    (
        "**Read files** - RepoPilot walks the downloaded project "
        "and skips dependency folders, generated files, lock files, "
        "binaries, very large files and anything that looks like a secret."
    ),
    (
        "**Understand structure** - For Python, JavaScript, "
        "TypeScript, Java and Go, Tree-sitter finds functions, "
        "classes and methods. Other file types are indexed as plain text."
    ),
    (
        "**Split into chunks** - Each function or method becomes "
        "one chunk, helping searches find relevant code."
    ),
    (
        "**Build two indexes** - BM25 finds exact names and words. "
        "Embeddings and FAISS find code with similar meaning."
    ),
    (
        "**Search together** - Both indexes contribute to search "
        "results. Only relevant excerpts are sent to the AI."
    ),
]


def page_repos() -> None:
    page_heading("repos")
    show_flash()

    section_heading(
        "Connect a repository",
        "Add a public GitHub repository to your workspace.",
    )

    with st.container(border=True):
        with st.form("connect_form"):
            url = st.text_input(
                "GitHub repository URL",
                placeholder="https://github.com/owner/repository",
            )

            submitted = st.form_submit_button(
                "Connect repository",
                type="primary",
            )

        if submitted:
            if not url.strip():
                ui.notice(
                    "error",
                    "Paste a repository URL",
                    "For example: https://github.com/owner/repository",
                )
            else:
                with st.spinner(
                    "Checking the URL and downloading source files..."
                ):
                    repo = safe(
                        api().add_repository,
                        url.strip(),
                    )

                if repo:
                    state().active_repo = repo["id"]
                    state()["_active_sel"] = repo["id"]

                    flash(
                        "success",
                        f"Connected {repo['name']}",
                        (
                            f"{repo['file_count']} source files downloaded. "
                            "Run analysis to make the repository searchable."
                        ),
                    )

                    st.rerun()

    with st.expander("How repository analysis works"):
        for step in ANALYSIS_STEPS:
            st.markdown(f"- {step}")

    st.write("")

    section_heading(
        "Connected repositories",
        "Manage and analyze your connected projects.",
    )

    repos = safe(api().list_repositories) or []
    state().repos = repos

    if not repos:
        ui.empty_state(
            "Nothing connected yet",
            "Paste a GitHub URL above. "
            "Only public repositories are supported in this version.",
        )
        return

    for repo in repos:
        with st.container(
            border=True,
            key=f"repo_manage_{repo['id']}",
        ):
            ui.render(ui.repo_header(repo))

            semantic = (
                repo.get("metadata", {})
                .get("analysis", {})
                .get("semantic")
            )

            if semantic is not None:
                search_mode = (
                    "Keyword + meaning"
                    if semantic.get("indexed")
                    else (
                        "Keyword only - "
                        + (
                            semantic.get("error")
                            or "semantic search disabled"
                        )
                    )
                )

                st.caption(f"Search mode: {search_mode}")

            if (
                repo["analysis_status"] == "failed"
                and repo.get("analysis_error")
            ):
                ui.notice(
                    "error",
                    "The last analysis failed",
                    repo["analysis_error"],
                )

            st.divider()

            c1, c2, c3, c4 = st.columns([1.3, 1.3, 1, 2])

            label = (
                "Re-analyze"
                if repo["analysis_status"] == "completed"
                else "Analyze"
            )

            if c1.button(
                label,
                key=f"an_{repo['id']}",
                type=(
                    "primary"
                    if repo["analysis_status"] != "completed"
                    else "secondary"
                ),
                **STRETCH,
            ):
                run_analysis(repo)

            c2.button(
                "Open in search",
                key=f"os_{repo['id']}",
                on_click=select_repo,
                args=(repo["id"], "search"),
                **STRETCH,
                disabled=repo["analysis_status"] != "completed",
            )

            confirm_key = f"confirm_rm_{repo['id']}"

            if state().get(confirm_key):
                if c3.button(
                    "Confirm remove",
                    key=f"rmc_{repo['id']}",
                    **STRETCH,
                ):
                    if safe(
                        api().delete_repository,
                        repo["id"],
                    ) is None:
                        state().pop(confirm_key, None)

                        flash(
                            "success",
                            f"Removed {repo['name']}",
                            (
                                "Its files, index, history and "
                                "fix suggestions were deleted."
                            ),
                        )

                        st.rerun()
            elif c3.button(
                "Remove",
                key=f"rm_{repo['id']}",
                **STRETCH,
            ):
                state()[confirm_key] = True
                st.rerun()

            if state().get(confirm_key):
                c4.caption(
                    "This deletes the repository's downloaded files, "
                    "search index, history and fix suggestions."
                )


# ============================================================
# CODE SEARCH
# ============================================================

def page_search() -> None:
    page_heading("search")
    show_flash()

    repo = require_repo()

    if repo is None:
        return

    repository_context(repo)

    tab_search, tab_overview = st.tabs(
        ["Code Search", "Repository Overview"]
    )

    with tab_search:
        section_heading(
            "Search your codebase",
            "Find code using exact keywords or natural-language descriptions.",
        )

        with st.container(border=True):
            with st.form("search_form"):
                query = st.text_input(
                    "Search query",
                    placeholder=(
                        "e.g. password check, save record to database, "
                        "createSessionToken"
                    ),
                )

                c1, c2 = st.columns([2, 1])

                mode_label = c1.selectbox(
                    "Search method",
                    list(MODES),
                )

                top_k = c2.slider(
                    "Maximum results",
                    3,
                    15,
                    8,
                )

                submitted = st.form_submit_button(
                    "Search code",
                    type="primary",
                )

            if submitted:
                if not query.strip():
                    ui.notice(
                        "error",
                        "Type something to search for",
                    )
                else:
                    with st.spinner("Searching repository..."):
                        result = safe(
                            api().search,
                            repo["id"],
                            query.strip(),
                            MODES[mode_label],
                            top_k,
                        )

                    state().search_result = (
                        {
                            "repo": repo["id"],
                            "data": result,
                        }
                        if result
                        else None
                    )

        shown = state().get("search_result")

        if shown and shown["repo"] == repo["id"]:
            data = shown["data"]

            if data.get("note"):
                ui.notice(
                    "info",
                    "Showing keyword results",
                    data["note"],
                )

            if not data["results"]:
                ui.empty_state(
                    "No matches found",
                    "Try a function name, file name or simpler search terms.",
                )
            else:
                section_heading(
                    f"{len(data['results'])} search results",
                    f"Search method: {data['mode_used']}",
                )

                for result in data["results"]:
                    tag = (
                        "keyword + meaning"
                        if (
                            result.get("keyword_rank")
                            and result.get("semantic_rank")
                        )
                        else (
                            "keyword"
                            if result.get("keyword_rank")
                            else "meaning"
                        )
                    )

                    ui.render(
                        ui.code_block(
                            result["text"],
                            result["path"]
                            + (
                                f" - {result['symbol']}"
                                if result.get("symbol")
                                else ""
                            ),
                            result["start_line"],
                            result.get("language", ""),
                            tag,
                            all_hit=True,
                        )
                    )

    with tab_overview:
        section_heading(
            "Repository structure",
            "Inspect indexed files, languages and detected code symbols.",
        )

        overview = safe(
            api().overview,
            repo["id"],
        )

        if overview:
            render_overview(overview)


def render_overview(overview: dict) -> None:
    counts = overview.get("symbol_counts", {})

    metrics = [
        ("Files indexed", overview["total_files"]),
        ("Code chunks", overview["total_chunks"]),
        (
            "Functions and methods",
            counts.get("function", 0)
            + counts.get("method", 0),
        ),
        (
            "Classes and types",
            sum(
                counts.get(key, 0)
                for key in ("class", "interface", "enum", "type")
            ),
        ),
    ]

    cols = st.columns(4)

    for col, (label, value) in zip(cols, metrics):
        with col:
            ui.render(ui.stat(label, value))

    semantic = overview.get("semantic", {})

    st.write("")

    ui.render(
        f"""
        <div class="notice info">
            <b>Meaning-based search</b>
            {"Enabled" if semantic.get("indexed") else "Disabled"}
            {
                ""
                if semantic.get("indexed")
                else " - " + ui.esc(
                    semantic.get("error") or "disabled"
                )
            }
        </div>
        """
    )

    parsed = sum(
        1
        for file in overview["files"]
        if file["parsed_with_tree_sitter"]
    )

    st.caption(
        f"{parsed} of {len(overview['files'])} files "
        "were parsed with Tree-sitter. "
        "The remaining files are indexed as plain text."
    )

    section_heading(
        "Language distribution",
        "Languages detected in the repository.",
    )

    st.dataframe(
        [
            {"Language": key, "Files": value}
            for key, value in sorted(
                overview["languages"].items(),
                key=lambda item: -item[1],
            )
        ],
        hide_index=True,
        **STRETCH,
    )

    if overview.get("skipped"):
        labels = {
            "excluded_directory": "in dependency/build folders",
            "possible_secret": "that may contain secrets",
            "generated_or_lock_file": "generated or lock files",
            "unsupported_type": "of unsupported types",
            "binary": "binary",
            "file_too_large": "over the size limit",
            "empty": "empty",
            "symlink": "symbolic links",
            "file_limit_reached": "past the file limit",
            "chunk_limit_reached": "past the chunk limit",
        }

        skipped = ", ".join(
            f"{number} {labels.get(key, key)}"
            for key, number in overview["skipped"].items()
        )

        st.caption(f"Skipped files: {skipped}")

    section_heading(
        "Files and detected code structure",
        "Filter files and inspect their functions and classes.",
    )

    needle = st.text_input(
        "Filter by file path",
        key="overview_filter",
        placeholder="e.g. auth",
    )

    files = [
        file
        for file in overview["files"]
        if needle.lower() in file["path"].lower()
    ]

    st.dataframe(
        [
            {
                "Path": file["path"],
                "Language": file["language"],
                "Lines": file["lines"],
                "Symbols": len(file["symbols"]),
                "Parsed": (
                    "Yes"
                    if file["parsed_with_tree_sitter"]
                    else "Text only"
                ),
            }
            for file in files
        ],
        hide_index=True,
        **STRETCH,
        height=300,
    )

    with_symbols = [
        file
        for file in files
        if file["symbols"]
    ]

    if with_symbols:
        choice = st.selectbox(
            "Inspect symbols in",
            [file["path"] for file in with_symbols],
            key="overview_file",
        )

        selected_file = next(
            file
            for file in with_symbols
            if file["path"] == choice
        )

        st.dataframe(
            [
                {
                    "Name": symbol["name"],
                    "Kind": symbol["kind"],
                    "Lines": (
                        f"{symbol['start_line']}-"
                        f"{symbol['end_line']}"
                    ),
                }
                for symbol in selected_file["symbols"]
            ],
            hide_index=True,
            **STRETCH,
        )


# ============================================================
# AI ASSISTANT
# ============================================================

def set_example(text: str) -> None:
    state().ask_text = text


def page_assistant() -> None:
    page_heading("assistant")
    show_flash()

    repo = require_repo()

    if repo is None:
        return

    repository_context(repo)

    section_heading(
        "Ask about your code",
        "Ask natural-language questions and inspect the retrieved evidence.",
    )

    st.caption("Try one of these questions:")

    example_cols = st.columns(4)

    for col, question in zip(
        example_cols,
        EXAMPLE_QUESTIONS,
    ):
        col.button(
            question,
            key=f"ex_{question[:12]}",
            on_click=set_example,
            args=(question,),
            **STRETCH,
        )

    with st.container(border=True):
        question = st.text_area(
            "Your question",
            key="ask_text",
            height=120,
            max_chars=2000,
            placeholder=(
                "e.g. Where is the password checked "
                "when a user signs in?"
            ),
        )

        if st.button(
            "Ask the AI",
            type="primary",
            key="ask_btn",
        ):
            if not question.strip():
                ui.notice(
                    "error",
                    "Write a question first",
                )
            else:
                with st.spinner(
                    "Finding relevant code and asking the AI..."
                ):
                    result = safe(
                        api().ask,
                        repo["id"],
                        question.strip(),
                    )

                state().ask_result = (
                    {
                        "repo": repo["id"],
                        "question": question.strip(),
                        "data": result,
                    }
                    if result
                    else None
                )

    shown = state().get("ask_result")

    if shown and shown["repo"] == repo["id"]:
        data = shown["data"]

        st.write("")

        section_heading(
            "AI response",
            "Review the answer and its supporting repository references.",
        )

        if data.get("note"):
            ui.notice(
                "info",
                "Keyword results only",
                data["note"],
            )

        if not data.get("llm_used"):
            ui.notice(
                "warning",
                "No AI answer was generated",
                (
                    "No matching code was found, "
                    "so nothing was sent to the AI."
                ),
            )

        answer_col, evidence_col = st.columns(
            [1.7, 1],
            gap="large",
        )

        with answer_col:
            with st.container(
                border=True,
                key="answer_box",
            ):
                st.markdown(
                    safe_markdown(data["answer"])
                )

        with evidence_col:
            with st.container(border=True):
                st.markdown("**Answer details**")
                st.caption(
                    f"Model: {data.get('model') or 'None'}"
                )
                st.caption(
                    f"Retrieval: {data['mode_used']}"
                )
                st.caption("Saved to history.")
                st.caption(
                    "AI answers can be wrong. "
                    "Always check the cited code."
                )

        section_heading(
            "Supporting code references",
            "Source excerpts used to generate the answer.",
        )

        ui.render_references(data["references"])


# ============================================================
# BUG ANALYZER
# ============================================================

def page_bugs() -> None:
    page_heading("bugs")
    show_flash()

    repo = require_repo()

    if repo is None:
        return

    repository_context(repo)

    section_heading(
        "Describe the problem",
        "Paste an error message, traceback or bug description.",
    )

    with st.container(border=True):
        description = st.text_area(
            "Error message or bug description",
            key="bug_text",
            height=180,
            max_chars=6000,
            placeholder=(
                "Paste the full traceback if you have one, "
                "or describe what goes wrong and when."
            ),
        )

        if st.button(
            "Investigate bug",
            type="primary",
            key="bug_btn",
        ):
            if not description.strip():
                ui.notice(
                    "error",
                    "Describe the bug or paste an error first",
                )
            else:
                with st.spinner(
                    "Matching the error to code and asking the AI..."
                ):
                    result = safe(
                        api().investigate,
                        repo["id"],
                        description.strip(),
                    )

                state().bug_result = (
                    {
                        "repo": repo["id"],
                        "description": description.strip(),
                        "data": result,
                    }
                    if result
                    else None
                )

    shown = state().get("bug_result")

    if shown and shown["repo"] == repo["id"]:
        data = shown["data"]

        st.write("")

        section_heading(
            "Investigation results",
            "Potentially related code and AI-generated analysis.",
        )

        ui.render(
            '<span class="badge-hyp">'
            'Hypothesis — not a confirmed bug'
            '</span>'
        )

        ui.render(
            f"""
            <div class="hint" style="margin:.5rem 0 1rem">
                {ui.esc(data['disclaimer'])}
            </div>
            """
        )

        signals = data["signals"]

        chips = "".join(
            f'<span class="chip">{ui.esc(item)}</span>'
            for item in (
                signals["exceptions"]
                + [
                    (
                        f"{frame['path'].split('/')[-1]}:"
                        f"{frame['line']}"
                    )
                    for frame in signals["frames"][:6]
                ]
            )
        )

        if chips:
            ui.render(
                f"""
                <div class="hint">Detected in your report</div>
                <div>{chips}</div>
                """
            )

        if data.get("note"):
            ui.notice(
                "info",
                "Keyword results only",
                data["note"],
            )

        with st.container(
            border=True,
            key="answer_box",
        ):
            st.markdown(
                safe_markdown(data["analysis"])
            )

        section_heading(
            "Related code",
            "Code references that may help explain the issue.",
        )

        ui.render_references(
            data["references"],
            "Code that may be involved",
        )

        if data.get("llm_used"):
            if st.button(
                "Propose a fix for this bug",
                type="primary",
                key="bug_to_fix",
            ):
                with st.spinner(
                    "Asking the AI for a minimal change..."
                ):
                    outcome = safe(
                        api().suggest_fix,
                        repo["id"],
                        shown["description"],
                    )

                if outcome and outcome.get("suggestion"):
                    flash(
                        "success",
                        "Fix suggestion saved",
                        "Review the proposed change before applying it.",
                    )

                    go("fixes")
                    st.rerun()

                elif outcome:
                    ui.notice(
                        "warning",
                        "The AI could not propose a safe change",
                        outcome.get("cannot_fix_reason", ""),
                    )


# ============================================================
# FIX SUGGESTIONS
# ============================================================

def page_fixes() -> None:
    page_heading("fixes")
    show_flash()

    repo = require_repo()

    if repo is None:
        return

    repository_context(repo)

    ui.notice(
        "warning",
        "AI-generated suggestions are not verified",
        (
            "RepoPilot does not run your tests. "
            "Read every diff and test the change yourself."
        ),
    )

    section_heading(
        "Generate a fix",
        "Describe the issue and let the AI propose a minimal change.",
    )

    with st.container(border=True):
        with st.form("fix_form"):
            description = st.text_area(
                "What should be fixed?",
                height=110,
                max_chars=4000,
                placeholder=(
                    "Describe the bug or paste the error. "
                    "The AI will propose one minimal change."
                ),
            )

            submitted = st.form_submit_button(
                "Suggest a fix",
                type="primary",
            )

        if submitted:
            if not description.strip():
                ui.notice(
                    "error",
                    "Describe the problem first",
                )
            else:
                with st.spinner(
                    "Retrieving code and validating the proposed change..."
                ):
                    outcome = safe(
                        api().suggest_fix,
                        repo["id"],
                        description.strip(),
                    )

                if outcome and outcome.get("suggestion"):
                    flash(
                        "success",
                        "Fix suggestion saved",
                        "Review the proposed change below.",
                    )
                    st.rerun()

                elif outcome:
                    ui.notice(
                        "warning",
                        "The AI could not propose a safe change",
                        outcome.get("cannot_fix_reason", ""),
                    )

    fixes = safe(
        api().list_fixes,
        repo["id"],
    ) or []

    st.write("")

    section_heading(
        f"Suggestions for {repo['name']}",
        "Review changes before approving or applying them.",
    )

    if not fixes:
        ui.empty_state(
            "No suggestions yet",
            (
                "Describe a problem above, or use "
                "Propose a fix from a bug investigation."
            ),
        )
        return

    for fix in fixes:
        status = (
            "applied"
            if fix["applied_at"]
            else fix["review_decision"]
        )

        with st.expander(
            f"{fix['target_file']}  ·  "
            f"{ui.STATUS_LABELS[status]}  ·  "
            f"{ui.fmt_dt(fix['created_at'])}",
            expanded=fix["review_decision"] == "pending",
        ):
            st.caption(
                f"Problem: {fix['problem_description'][:400]}"
            )

            ui.render(
                f'<span class="badge-hyp">'
                f'AI suggestion — not verified'
                f'</span> {ui.pill(status)}'
            )

            st.markdown("**Explanation**")
            st.markdown(
                safe_markdown(fix["explanation"])
            )

            section_heading(
                "Proposed diff",
                "Review the exact lines that would change.",
            )

            ui.render(
                ui.diff_block(fix["diff"])
            )

            original, proposed = st.columns(2)

            with original:
                st.markdown("**Original code**")
                st.html(
                    ui.code_block(
                        fix["original_code"],
                        fix["target_file"],
                        1,
                        "",
                        "before",
                    )
                )

            with proposed:
                st.markdown("**Proposed code**")
                st.html(
                    ui.code_block(
                        fix["proposed_code"],
                        fix["target_file"],
                        1,
                        "",
                        "after",
                    )
                )

            if fix["applied_at"]:
                ui.notice(
                    "success",
                    "Applied to the local working copy",
                    (
                        f"Written on {ui.fmt_dt(fix['applied_at'])}. "
                        "GitHub was not changed."
                    ),
                )
            else:
                st.divider()

                c1, c2, c3, c4 = st.columns([1, 1, 1.6, 1])

                if c1.button(
                    "Approve",
                    key=f"ap_{fix['id']}",
                    disabled=fix["review_decision"] == "approved",
                    **STRETCH,
                ):
                    if safe(
                        api().review_fix,
                        fix["id"],
                        "approved",
                    ):
                        st.rerun()

                if c2.button(
                    "Reject",
                    key=f"rj_{fix['id']}",
                    disabled=fix["review_decision"] == "rejected",
                    **STRETCH,
                ):
                    if safe(
                        api().review_fix,
                        fix["id"],
                        "rejected",
                    ):
                        st.rerun()

                if c3.button(
                    "Apply to local copy",
                    key=f"ay_{fix['id']}",
                    type="primary",
                    disabled=fix["review_decision"] != "approved",
                    **STRETCH,
                    help=(
                        "Writes the approved change to "
                        "RepoPilot's downloaded copy only."
                    ),
                ):
                    if safe(
                        api().apply_fix,
                        fix["id"],
                    ):
                        flash(
                            "success",
                            "Change applied to the local copy",
                            "Re-analyze the repository to refresh search.",
                        )
                        st.rerun()

                if c4.button(
                    "Delete",
                    key=f"dl_{fix['id']}",
                    **STRETCH,
                ):
                    if safe(
                        api().delete_fix,
                        fix["id"],
                    ) is None:
                        st.rerun()


# ============================================================
# HISTORY
# ============================================================

def page_history() -> None:
    page_heading("history")
    show_flash()

    section_heading(
        "Analysis history",
        "Review previous questions and bug investigations.",
    )

    c1, c2 = st.columns(2)

    kind = c1.selectbox(
        "Analysis type",
        [
            "All",
            "Code questions",
            "Bug investigations",
        ],
        key="hist_kind",
    )

    scope = c2.selectbox(
        "Repository filter",
        [
            "All repositories",
            "Active repository only",
        ],
        key="hist_scope",
    )

    repo = (
        active_repo()
        if scope == "Active repository only"
        else None
    )

    records = safe(
        api().list_history,
        repo["id"] if repo else None,
        {
            "Code questions": "question",
            "Bug investigations": "bug",
        }.get(kind),
    ) or []

    if not records:
        ui.empty_state(
            "No history yet",
            "Ask a question or investigate a bug "
            "and the result will be saved here.",
        )
        return

    st.caption(f"{len(records)} history records")

    for record in records:
        with st.expander(
            f"{record['analysis_type_label']}  ·  "
            f"{record['repository_name']}  ·  "
            f"{record['user_input'][:70].strip()}"
        ):
            st.markdown("**Your input**")

            st.code(
                record["user_input"],
                language=None,
                wrap_lines=True,
            )

            st.markdown("**AI response**")

            st.markdown(
                safe_markdown(record["ai_response"])
            )

            st.caption(
                f"Model: {record['llm_model'] or 'None'}"
            )

            ui.render_references(
                record["file_references"],
                "Referenced code",
            )

            key = f"confirm_h_{record['id']}"

            if state().get(key):
                if st.button(
                    "Confirm delete",
                    key=f"hc_{record['id']}",
                ):
                    if safe(
                        api().delete_history,
                        record["id"],
                    ) is None:
                        state().pop(key, None)
                        st.rerun()

            elif st.button(
                "Delete this record",
                key=f"hd_{record['id']}",
            ):
                state()[key] = True
                st.rerun()


# ============================================================
# PAGE ROUTER
# ============================================================

PAGES = {
    "home": page_home,
    "auth": page_auth,
    "dashboard": page_dashboard,
    "repos": page_repos,
    "search": page_search,
    "assistant": page_assistant,
    "bugs": page_bugs,
    "fixes": page_fixes,
    "history": page_history,
}


def main() -> None:
    """Load the theme and render the selected application page."""

    css_path = Path(__file__).parent / "styles.css"

    # Load the Graphite + Burnt Orange stylesheet.
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        st.html(f"<style>{css}</style>")
    else:
        st.error(
            "styles.css was not found. "
            "Make sure it is inside the frontend folder."
        )

    # Initialize navigation.
    state().setdefault("page", "home")

    logged_in = bool(state().get("token"))
    page = state().page

    # Protect authenticated pages.
    if page in PROTECTED and not logged_in:
        page = state().page = "auth"

    # Prevent logged-in users from returning to authentication.
    if page == "auth" and logged_in:
        page = state().page = "dashboard"

    # Render authenticated workspace.
    if logged_in and page in PROTECTED:
        sidebar()
        workspace_toolbar()

    else:
        # Hide the sidebar on landing and authentication pages.
        st.html(
            """
            <style>
                [data-testid='stSidebar'],
                [data-testid='stSidebarCollapsedControl'],
                [data-testid='stExpandSidebarButton'] {
                    display: none !important;
                }
            </style>
            """
        )

    # Render the selected page.
    PAGES.get(page, page_home)()


if __name__ == "__main__":
    main()