"""Shared pytest fixtures. Environment/settings for tests live in config/test_settings.py."""

# ----------------------------------------------------------------- fixtures --
import pytest  # noqa: E402

SAMPLE_FILES = {
    "app.py": 'import os\n\nfrom auth.login import login_user\n\n\ndef main():\n    """Entry point."""\n    return login_user("a", "b")\n',
    "auth/login.py": ('from django.contrib.auth import authenticate\n\n\ndef login_user(username, password):\n'
                      '    """Authenticate a user with the password check."""\n    user = authenticate(username=username, password=password)\n'
                      '    if user is None:\n        raise ValueError("bad credentials")\n    return user\n'),
    "db/store.py": ('class Database:\n    """Stores records in PostgreSQL."""\n\n    def save_record(self, record):\n'
                    '        return self.connection.execute("INSERT INTO records VALUES (%s)", record)\n\n'
                    '    def load_record(self, record_id):\n        return self.connection.execute("SELECT * FROM records WHERE id=%s", record_id)\n'),
    "README.md": "# Demo\nA tiny demo project with login and a database layer.\n",
}


@pytest.fixture(autouse=True)
def isolated_data_dirs(settings, tmp_path):
    settings.WORKSPACE_ROOT = tmp_path / "workspaces"
    settings.INDEX_ROOT = tmp_path / "indexes"
    settings.SEMANTIC_SEARCH_ENABLED = False


@pytest.fixture
def make_user(db):
    from django.contrib.auth import get_user_model

    def _make(username="alice", password="S3cure-pass-123"):
        return get_user_model().objects.create_user(username=username, password=password)

    return _make


@pytest.fixture
def client_for(db):
    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    def _client(user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=user)[0].key}")
        return client

    return _client


@pytest.fixture
def make_repo(db, settings):
    """Create a Repository whose source files exist on disk (optionally analyzed)."""
    from repositories import services
    from repositories.models import Repository

    def _make(owner, name="demo/app", analyze=True, files=None):
        repo = Repository.objects.create(owner=owner, name=name, github_url=f"https://github.com/{name}",
                                         metadata={"primary_language": "python", "file_count": len(files or SAMPLE_FILES)})
        src = services.source_dir(repo)
        for rel, text in (files or SAMPLE_FILES).items():
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if analyze:
            services.run_analysis(repo)
            repo.refresh_from_db()
        return repo

    return _make


@pytest.fixture
def fake_llm(monkeypatch):
    """Configure the LLM env and replace the network call with a controllable fake."""
    from ai_engine import llm

    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    state = {"reply": "### Answer\nIt works.\n### Evidence\n- `auth/login.py:1-8`\n### Assumptions and gaps\nNone", "calls": []}

    def fake_generate(system, user, max_tokens=None):
        state["calls"].append((system, user))
        if isinstance(state["reply"], Exception):
            raise state["reply"]
        return state["reply"]

    monkeypatch.setattr(llm, "generate", fake_generate)
    return state
