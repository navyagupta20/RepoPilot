"""API tests: authentication, ownership, URL validation, history permissions, LLM failures, fix validation."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from ai_engine import llm
from repositories import services
from repositories.models import AnalysisHistory, FixSuggestion, Repository

pytestmark = pytest.mark.django_db
PASSWORD = "S3cure-pass-123"


# ------------------------------------------------------------ authentication --
class TestAuthentication:
    def test_register_returns_token_and_hashes_password(self):
        res = APIClient().post("/api/auth/register/", {"username": "newuser", "password": PASSWORD}, format="json")
        assert res.status_code == 201 and res.data["token"]
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.get(username="newuser")
        assert user.password != PASSWORD and user.password.startswith(("pbkdf2_", "argon2", "bcrypt"))
        assert PASSWORD not in json.dumps(res.data)

    def test_register_rejects_weak_password_and_duplicate_username(self, make_user):
        make_user("taken")
        assert APIClient().post("/api/auth/register/", {"username": "someone", "password": "12345678"}, format="json").status_code == 400
        dup = APIClient().post("/api/auth/register/", {"username": "Taken", "password": PASSWORD}, format="json")
        assert dup.status_code == 400 and "username" in dup.data

    def test_login_success_and_failure(self, make_user):
        make_user("bob")
        ok = APIClient().post("/api/auth/login/", {"username": "bob", "password": "S3cure-pass-123"}, format="json")
        assert ok.status_code == 200 and ok.data["token"]
        bad = APIClient().post("/api/auth/login/", {"username": "bob", "password": "wrong"}, format="json")
        assert bad.status_code == 400 and bad.data["code"] == "invalid_credentials"

    def test_logout_invalidates_token(self, make_user, client_for):
        client = client_for(make_user())
        assert client.get("/api/auth/me/").status_code == 200
        assert client.post("/api/auth/logout/").status_code == 204
        assert client.get("/api/auth/me/").status_code == 401


PROTECTED = [("get", "/api/auth/me/"), ("get", "/api/dashboard/"), ("get", "/api/repositories/"), ("post", "/api/repositories/"),
             ("get", "/api/repositories/1/"), ("delete", "/api/repositories/1/"), ("post", "/api/repositories/1/analyze/"),
             ("post", "/api/repositories/1/search/"), ("post", "/api/repositories/1/ask/"), ("post", "/api/repositories/1/investigate/"),
             ("post", "/api/repositories/1/suggest-fix/"), ("get", "/api/fixes/"), ("post", "/api/fixes/1/review/"),
             ("post", "/api/fixes/1/apply/"), ("get", "/api/history/"), ("get", "/api/history/1/"), ("delete", "/api/history/1/")]


@pytest.mark.parametrize("method,url", PROTECTED)
def test_endpoints_reject_anonymous_requests(method, url):
    assert getattr(APIClient(), method)(url).status_code == 401


# ------------------------------------------------------------------ ownership --
class TestRepositoryOwnership:
    def test_list_only_returns_own_repositories(self, make_user, client_for, make_repo):
        alice, bob = make_user("alice"), make_user("bob")
        make_repo(alice, "a/one", analyze=False)
        make_repo(bob, "b/two", analyze=False)
        names = [r["name"] for r in client_for(alice).get("/api/repositories/").data]
        assert names == ["a/one"]

    def test_other_users_repository_is_404_for_every_action(self, make_user, client_for, make_repo):
        alice, bob = make_user("alice"), make_user("bob")
        repo = make_repo(alice)
        client = client_for(bob)
        base = f"/api/repositories/{repo.id}/"
        assert client.get(base).status_code == 404
        assert client.post(base + "analyze/").status_code == 404
        assert client.get(base + "overview/").status_code == 404
        assert client.post(base + "search/", {"query": "login"}, format="json").status_code == 404
        assert client.post(base + "ask/", {"question": "x"}, format="json").status_code == 404
        assert client.delete(base).status_code == 404
        assert Repository.objects.filter(pk=repo.id).exists()

    def test_response_never_exposes_filesystem_references(self, make_user, client_for, make_repo):
        alice = make_user()
        repo = make_repo(alice)
        body = json.dumps(client_for(alice).get(f"/api/repositories/{repo.id}/").data)
        assert repo.workspace_ref not in body and "workspaces" not in body

    def test_delete_removes_files_and_row(self, make_user, client_for, make_repo):
        alice = make_user()
        repo = make_repo(alice)
        src = services.source_dir(repo).parent
        assert src.exists()
        assert client_for(alice).delete(f"/api/repositories/{repo.id}/").status_code == 204
        assert not src.exists() and not Repository.objects.filter(pk=repo.id).exists()

    def test_dashboard_reports_real_counts(self, make_user, client_for, make_repo):
        alice = make_user()
        client = client_for(alice)
        empty = client.get("/api/dashboard/").data
        assert empty["repository_count"] == 0 and empty["analysis_count"] == 0 and empty["recent_analyses"] == []
        make_repo(alice)
        assert client.get("/api/dashboard/").data["repositories_analyzed"] == 1


# -------------------------------------------------------------- URL validation --
@pytest.mark.parametrize("url,expected", [
    ("https://github.com/psf/requests", ("psf", "requests")),
    ("https://github.com/psf/requests/", ("psf", "requests")),
    ("https://github.com/psf/requests.git", ("psf", "requests")),
    ("https://www.github.com/Owner/Repo.name", ("Owner", "Repo.name")),
])
def test_valid_github_urls(url, expected):
    assert services.parse_github_url(url) == expected


@pytest.mark.parametrize("url", [
    "", "not a url", "http://github.com/a/b", "ftp://github.com/a/b", "https://gitlab.com/a/b",
    "https://github.com.evil.com/a/b", "https://evil.com/github.com/a/b", "https://user:pw@github.com/a/b",
    "https://evil.com@github.com/a/b", "https://localhost/a/b", "https://127.0.0.1/a/b", "https://169.254.169.254/latest/meta-data",
    "https://github.com:8443/a/b", "https://github.com/a", "https://github.com/a/b/tree/main", "https://github.com/a/b?x=1",
    "https://github.com/a/b#frag", "https://github.com/../etc", "https://github.com/a/..", "https://github.com/-bad/repo",
    "https://github.com/a/b c", "file:///etc/passwd", "https://github.com/" + "a" * 300,
])
def test_invalid_github_urls_are_rejected(url):
    with pytest.raises(services.InvalidRepositoryURL):
        services.parse_github_url(url)


def test_create_repository_endpoint_validates_url_and_maps_errors(make_user, client_for, monkeypatch):
    client = client_for(make_user())
    assert client.post("/api/repositories/", {"url": "http://localhost/x/y"}, format="json").status_code == 400

    def not_found(user, url):
        raise services.RepositoryNotFound("Repository not found.")

    monkeypatch.setattr(services, "import_repository", not_found)
    res = client.post("/api/repositories/", {"url": "https://github.com/no/such"}, format="json")
    assert res.status_code == 404 and res.data["code"] == "RepositoryNotFound"


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(b"",), json_data=None):
        self.status_code, self.headers, self._chunks, self._json = status, headers or {}, chunks, json_data

    def iter_content(self, chunk_size=0):
        return iter(self._chunks)

    def json(self):
        return self._json

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_refuses_redirect_to_non_github_host(monkeypatch, tmp_path):
    monkeypatch.setattr(services.requests, "get", lambda url, **kw: FakeResponse(302, {"Location": "https://evil.example.com/x.zip"}))
    with pytest.raises(services.GitHubUnavailable):
        services._download_archive("a", "b", tmp_path / "x.zip")


def test_download_refuses_oversized_archive(monkeypatch, tmp_path, settings):
    settings.MAX_ARCHIVE_MB = 1
    monkeypatch.setattr(services.requests, "get", lambda url, **kw: FakeResponse(200, chunks=[b"x" * (1024 * 1024)] * 2))
    with pytest.raises(services.RepositoryTooLarge):
        services._download_archive("a", "b", tmp_path / "x.zip")


def test_rate_limit_and_missing_repo_messages(monkeypatch):
    monkeypatch.setattr(services.requests, "get", lambda url, **kw: FakeResponse(403, {"X-RateLimit-Remaining": "0"}))
    with pytest.raises(services.GitHubRateLimited):
        services.fetch_repo_metadata("a", "b")
    monkeypatch.setattr(services.requests, "get", lambda url, **kw: FakeResponse(404))
    with pytest.raises(services.RepositoryNotFound):
        services.fetch_repo_metadata("a", "b")


def test_private_repository_is_rejected(monkeypatch):
    monkeypatch.setattr(services.requests, "get", lambda url, **kw: FakeResponse(200, json_data={"private": True, "full_name": "a/b"}))
    with pytest.raises(services.PrivateRepositoryUnsupported):
        services.fetch_repo_metadata("a", "b")


def test_extraction_blocks_zip_slip_symlinks_and_filters_files(tmp_path, settings):
    settings.MAX_FILE_KB = 10
    archive = tmp_path / "r.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo-abc/src/main.py", "print('hi')\n")
        zf.writestr("repo-abc/../../evil.py", "boom = 1\n")
        zf.writestr("repo-abc/node_modules/lib/index.js", "x=1\n")
        zf.writestr("repo-abc/.env", "SECRET=1\n")
        zf.writestr("repo-abc/big.py", "x = 1\n" * 5000)
        zf.writestr("repo-abc/logo.png", "binary")
        link = zipfile.ZipInfo("repo-abc/link.py")
        link.external_attr = (0o120777 << 16)
        zf.writestr(link, "/etc/passwd")
    dest = tmp_path / "out" / "src"
    count = services._extract_archive(archive, dest)
    extracted = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert extracted == ["src/main.py"] and count == 1
    assert not (tmp_path / "evil.py").exists() and not (tmp_path / "out" / "evil.py").exists()


# -------------------------------------------------------------- analysis flow --
def test_analyze_then_search_and_overview(make_user, client_for, make_repo):
    alice = make_user()
    repo = make_repo(alice, analyze=False)
    client = client_for(alice)
    assert client.post(f"/api/repositories/{repo.id}/search/", {"query": "login"}, format="json").status_code == 409
    res = client.post(f"/api/repositories/{repo.id}/analyze/")
    assert res.status_code == 200 and res.data["analysis_status"] == "completed"
    found = client.post(f"/api/repositories/{repo.id}/search/", {"query": "authenticate user password"}, format="json").data
    assert found["results"][0]["path"] == "auth/login.py"
    assert found["mode_used"] == "keyword" and found["note"]  # semantic disabled in tests: reported honestly
    overview = client.get(f"/api/repositories/{repo.id}/overview/").data
    names = {s["name"] for f in overview["files"] for s in f["symbols"]}
    assert {"login_user", "Database", "save_record", "main"} <= names


# ----------------------------------------------------------------- AI endpoints --
class TestAskAndHistory:
    def test_missing_llm_credentials_gives_setup_message(self, make_user, client_for, make_repo, monkeypatch):
        for var in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        alice = make_user()
        repo = make_repo(alice)
        res = client_for(alice).post(f"/api/repositories/{repo.id}/ask/", {"question": "How does login work?"}, format="json")
        assert res.status_code == 503 and res.data["code"] == "llm_not_configured" and "LLM_API_KEY" in res.data["detail"]
        assert AnalysisHistory.objects.count() == 0

    def test_llm_error_is_reported_and_nothing_saved(self, make_user, client_for, make_repo, fake_llm):
        fake_llm["reply"] = llm.LLMError("The LLM provider rate limit was reached. Wait a moment and try again.")
        alice = make_user()
        repo = make_repo(alice)
        res = client_for(alice).post(f"/api/repositories/{repo.id}/ask/", {"question": "How does login work?"}, format="json")
        assert res.status_code == 502 and res.data["code"] == "llm_error"
        assert AnalysisHistory.objects.count() == 0

    def test_ask_saves_history_with_references(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        res = client_for(alice).post(f"/api/repositories/{repo.id}/ask/", {"question": "Where is the user authenticated?"}, format="json")
        assert res.status_code == 200 and res.data["llm_used"] and res.data["history_id"]
        record = AnalysisHistory.objects.get()
        assert record.owner == alice and record.analysis_type == "question" and record.file_references
        assert any(ref["path"] == "auth/login.py" for ref in record.file_references)
        system, prompt = fake_llm["calls"][0]
        assert "UNTRUSTED" in system and "<excerpt" in prompt

    def test_ask_rejects_empty_and_oversized_questions(self, make_user, client_for, make_repo):
        alice = make_user()
        repo = make_repo(alice)
        client = client_for(alice)
        assert client.post(f"/api/repositories/{repo.id}/ask/", {"question": ""}, format="json").status_code == 400
        assert client.post(f"/api/repositories/{repo.id}/ask/", {"question": "x" * 2001}, format="json").status_code == 400

    def test_bug_investigation_flags_hypothesis(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        trace = 'Traceback (most recent call last):\n  File "/srv/app/auth/login.py", line 6, in login_user\nValueError: bad credentials'
        res = client_for(alice).post(f"/api/repositories/{repo.id}/investigate/", {"description": trace}, format="json").data
        assert "hypothesis" in res["disclaimer"].lower() and "no bug was reproduced" in res["disclaimer"].lower()
        assert res["references"][0]["source"] == "stack_trace" and res["references"][0]["path"] == "auth/login.py"
        assert res["signals"]["exceptions"] == ["ValueError"]
        assert AnalysisHistory.objects.get().analysis_type == "bug"

    def test_history_is_private_to_its_owner(self, make_user, client_for, make_repo, fake_llm):
        alice, bob = make_user("alice"), make_user("bob")
        repo = make_repo(alice)
        client_for(alice).post(f"/api/repositories/{repo.id}/ask/", {"question": "login"}, format="json")
        record = AnalysisHistory.objects.get()
        bob_client = client_for(bob)
        assert bob_client.get("/api/history/").data == []
        assert bob_client.get(f"/api/history/{record.id}/").status_code == 404
        assert bob_client.delete(f"/api/history/{record.id}/").status_code == 404
        assert AnalysisHistory.objects.filter(pk=record.id).exists()
        alice_client = client_for(alice)
        assert alice_client.get(f"/api/history/{record.id}/").status_code == 200
        assert alice_client.get("/api/history/?type=bug").data == []
        assert alice_client.delete(f"/api/history/{record.id}/").status_code == 204
        assert not AnalysisHistory.objects.filter(pk=record.id).exists()


# ------------------------------------------------------------ fix suggestions --
GOOD_FIX = {"file_path": "auth/login.py", "original_code": '    if user is None:\n        raise ValueError("bad credentials")\n',
            "proposed_code": '    if user is None:\n        raise PermissionError("bad credentials")\n', "explanation": "More specific exception."}


class TestFixSuggestions:
    def suggest(self, client, repo):
        return client.post(f"/api/repositories/{repo.id}/suggest-fix/", {"description": "login raises the wrong exception"}, format="json")

    def test_valid_suggestion_is_saved_as_pending_and_unverified(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        fake_llm["reply"] = "```json\n" + json.dumps(GOOD_FIX) + "\n```"
        res = self.suggest(client_for(alice), repo)
        assert res.status_code == 201
        fix = res.data["suggestion"]
        assert fix["review_decision"] == "pending" and fix["verified"] is False and "-        raise ValueError" in fix["diff"]

    @pytest.mark.parametrize("override", [
        {"file_path": "../../etc/passwd"}, {"file_path": "/etc/passwd"}, {"file_path": "C:\\Windows\\win.ini"},
        {"file_path": "auth/missing.py"}, {"original_code": "this text is not in the file"}, {"original_code": ""},
        {"proposed_code": GOOD_FIX["original_code"]}, {"original_code": "user"},
    ])
    def test_malformed_or_unsafe_patches_are_rejected_and_not_saved(self, make_user, client_for, make_repo, fake_llm, override):
        alice = make_user()
        repo = make_repo(alice)
        fake_llm["reply"] = json.dumps({**GOOD_FIX, **override})
        res = self.suggest(client_for(alice), repo)
        assert res.status_code == 422 and res.data["code"] == "invalid_patch"
        assert FixSuggestion.objects.count() == 0

    def test_non_json_reply_and_cannot_fix_reply(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        fake_llm["reply"] = "Sure! Just change line 6."
        assert self.suggest(client_for(alice), repo).status_code == 502
        fake_llm["reply"] = json.dumps({"cannot_fix_reason": "Need the settings module."})
        res = self.suggest(client_for(alice), repo)
        assert res.status_code == 200 and res.data["suggestion"] is None and "settings" in res.data["cannot_fix_reason"]

    def test_review_then_apply_only_after_approval_and_only_locally(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        client = client_for(alice)
        fake_llm["reply"] = json.dumps(GOOD_FIX)
        fix_id = self.suggest(client, repo).data["suggestion"]["id"]
        target = services.source_dir(repo) / "auth/login.py"
        before = target.read_text()
        assert client.post(f"/api/fixes/{fix_id}/apply/").status_code == 409  # not approved yet
        assert target.read_text() == before
        assert client.post(f"/api/fixes/{fix_id}/review/", {"decision": "maybe"}, format="json").status_code == 400
        assert client.post(f"/api/fixes/{fix_id}/review/", {"decision": "approved"}, format="json").data["review_decision"] == "approved"
        applied = client.post(f"/api/fixes/{fix_id}/apply/")
        assert applied.status_code == 200 and applied.data["applied_at"]
        assert "PermissionError" in target.read_text() and "ValueError" not in target.read_text()
        assert client.post(f"/api/fixes/{fix_id}/apply/").status_code == 409  # cannot apply twice
        repo.refresh_from_db()
        assert repo.metadata["index_stale"] is True

    def test_rejected_fix_cannot_be_applied(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        client = client_for(alice)
        fake_llm["reply"] = json.dumps(GOOD_FIX)
        fix_id = self.suggest(client, repo).data["suggestion"]["id"]
        client.post(f"/api/fixes/{fix_id}/review/", {"decision": "rejected"}, format="json")
        assert client.post(f"/api/fixes/{fix_id}/apply/").status_code == 409

    def test_fix_changed_file_since_suggestion_is_not_applied(self, make_user, client_for, make_repo, fake_llm):
        alice = make_user()
        repo = make_repo(alice)
        client = client_for(alice)
        fake_llm["reply"] = json.dumps(GOOD_FIX)
        fix_id = self.suggest(client, repo).data["suggestion"]["id"]
        client.post(f"/api/fixes/{fix_id}/review/", {"decision": "approved"}, format="json")
        (services.source_dir(repo) / "auth/login.py").write_text("# rewritten\n")
        res = client.post(f"/api/fixes/{fix_id}/apply/")
        assert res.status_code == 422 and res.data["code"] == "invalid_patch"

    def test_other_user_cannot_see_review_or_apply_fix(self, make_user, client_for, make_repo, fake_llm):
        alice, bob = make_user("alice"), make_user("bob")
        repo = make_repo(alice)
        fake_llm["reply"] = json.dumps(GOOD_FIX)
        fix_id = self.suggest(client_for(alice), repo).data["suggestion"]["id"]
        bob_client = client_for(bob)
        assert bob_client.get("/api/fixes/").data == []
        assert bob_client.get(f"/api/fixes/{fix_id}/").status_code == 404
        assert bob_client.post(f"/api/fixes/{fix_id}/review/", {"decision": "approved"}, format="json").status_code == 404
        assert bob_client.post(f"/api/fixes/{fix_id}/apply/").status_code == 404
        assert bob_client.delete(f"/api/fixes/{fix_id}/").status_code == 404


class TestPatchValidationUnit:
    @pytest.fixture
    def workspace(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\ny = 2\nx = 1\n")
        (tmp_path / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "m.py").write_text("print('m')\n")
        return tmp_path

    def test_ambiguous_original_is_rejected(self, workspace):
        with pytest.raises(services.PatchValidationError, match="more than once"):
            services.validate_patch(workspace, "a.py", "x = 1", "x = 2")

    def test_symlink_escape_is_rejected(self, workspace, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside") / "secret.py"
        outside.write_text("token = 1\n")
        (workspace / "link.py").symlink_to(outside)
        with pytest.raises(services.PatchValidationError):
            services.validate_patch(workspace, "link.py", "token = 1", "token = 2")

    @pytest.mark.parametrize("path", ["../a.py", "sub/../../a.py", "/abs.py", "sub//m.py", "", "a.py\x00.txt", "\\\\server\\share\\x.py"])
    def test_path_escapes_are_rejected(self, workspace, path):
        with pytest.raises(services.PatchValidationError):
            services.validate_patch(workspace, path, "x = 1", "x = 2")

    def test_secret_and_non_source_files_are_not_patchable(self, workspace):
        (workspace / ".env").write_text("KEY=1\n")
        with pytest.raises(services.PatchValidationError):
            services.validate_patch(workspace, ".env", "KEY=1", "KEY=2")

    def test_too_large_change_is_rejected(self, workspace):
        with pytest.raises(services.PatchValidationError, match="larger"):
            services.validate_patch(workspace, "a.py", "y = 2", "z = 1\n" * 100)

    def test_apply_preserves_crlf_line_endings(self, workspace):
        services.apply_patch(workspace, "crlf.py", "b = 2\n", "b = 3\n")
        assert (workspace / "crlf.py").read_bytes() == b"a = 1\r\nb = 3\r\n"

    def test_diff_output(self):
        diff = services.make_diff("a\n", "b\n", "f.py")
        assert "--- a/f.py" in diff and "-a" in diff and "+b" in diff
