"""Frontend unit tests: HTML escaping, code rendering and API error messages. Run: pytest (inside frontend/)."""
import components as ui
from api_client import ApiClient, ApiError, _flatten_errors


def test_code_block_escapes_html_and_marks_evidence():
    html = ui.code_block('x = "<script>alert(1)</script>"', "evil</div>.py", 10, "python", all_hit=True)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "evil</div>" not in html and 'class="ln hit"' in html and ">10<" in html


def test_diff_block_classes_and_escaping():
    html = ui.diff_block("--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-<b>old</b>\n+new")
    assert "ln del" in html and "ln add" in html and "<b>old</b>" not in html


def test_notice_and_pill_escape_values(monkeypatch):
    captured = []
    monkeypatch.setattr(ui.st, "html", lambda h: captured.append(h))
    ui.notice("error", "<img src=x>", "a & b")
    assert "<img" not in captured[0] and "a &amp; b" in captured[0]
    assert "<script>" not in ui.pill("<script>")


def test_repo_header_escapes_backend_text():
    repo = {"name": "o/<r>", "github_url": "https://github.com/o/r", "analysis_status": "completed", "file_count": 3,
            "primary_language": "Python", "last_analyzed_at": None, "metadata": {"description": "<b>hi</b>"}}
    assert "<b>hi</b>" not in ui.repo_header(repo) and "o/&lt;r&gt;" in ui.repo_header(repo)


def test_error_flattening():
    assert _flatten_errors({"detail": "Nope"}) == "Nope"
    assert "password: Too short." in _flatten_errors({"password": ["Too short."]})


def test_unreachable_backend_gives_friendly_error():
    try:
        ApiClient("http://127.0.0.1:9", None).health()
    except ApiError as exc:
        assert exc.code == "unreachable" and "Is it running" in exc.message
    else:
        raise AssertionError("expected ApiError")
