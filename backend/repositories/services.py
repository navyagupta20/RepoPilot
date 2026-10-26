"""GitHub import, repository workspace handling and patch validation.

Security notes (see README "Security measures"):
  * Only https://github.com/<owner>/<repo> URLs are accepted. The URL is *parsed*, never fetched directly:
    we build our own request to api.github.com from the validated owner/repo names (no SSRF).
  * Redirects are followed manually and only to GitHub's own hosts over HTTPS.
  * Downloads and extraction have size, file-count and time limits; archive paths are sanitised (no zip-slip, no symlinks).
  * Filesystem paths shown to users are never absolute.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils import timezone

from ai_engine.indexing import Limits, build_index, is_candidate_path
from ai_engine.parser import detect_language

GITHUB_API = "https://api.github.com"
ALLOWED_DOWNLOAD_HOSTS = {"api.github.com", "codeload.github.com"}
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RepositoryImportError(Exception):
    """A problem importing a repository. `status_code` is the HTTP status the API should return."""

    status_code = 400


class InvalidRepositoryURL(RepositoryImportError):
    status_code = 400


class RepositoryNotFound(RepositoryImportError):
    status_code = 404


class PrivateRepositoryUnsupported(RepositoryImportError):
    status_code = 400


class GitHubRateLimited(RepositoryImportError):
    status_code = 429


class GitHubUnavailable(RepositoryImportError):
    status_code = 502


class RepositoryTooLarge(RepositoryImportError):
    status_code = 413


class PatchValidationError(Exception):
    pass


# ------------------------------------------------------------------ URL ------
def parse_github_url(url: str) -> tuple[str, str]:
    """Validate a GitHub repository URL and return (owner, repo). Raises InvalidRepositoryURL."""
    url = (url or "").strip()
    if not url or len(url) > 300:
        raise InvalidRepositoryURL("Enter a GitHub repository URL like https://github.com/owner/repository.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise InvalidRepositoryURL("That does not look like a valid URL.")
    if parts.scheme != "https":
        raise InvalidRepositoryURL("Only https:// GitHub URLs are supported.")
    if parts.username or parts.password:
        raise InvalidRepositoryURL("Do not put credentials in the URL. Only public repositories are supported.")
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com") or port is not None:
        raise InvalidRepositoryURL("Only repositories hosted on github.com are supported.")
    if parts.query or parts.fragment:
        raise InvalidRepositoryURL("Use the plain repository URL, without ?query or #fragment parts.")
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 2:
        raise InvalidRepositoryURL("Use the repository root URL: https://github.com/owner/repository.")
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo) or repo in (".", ".."):
        raise InvalidRepositoryURL("The owner or repository name contains characters GitHub does not allow.")
    return owner, repo


# --------------------------------------------------------------- GitHub ------
def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "RepoPilot-AI", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.GITHUB_TOKEN:  # optional, server-side only: only used to raise the rate limit for public data
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return headers


def _raise_for_github(response: requests.Response) -> None:
    if response.status_code in (403, 429) and (response.headers.get("X-RateLimit-Remaining") == "0" or response.status_code == 429):
        raise GitHubRateLimited("GitHub's rate limit was reached. Wait a few minutes, or set GITHUB_TOKEN on the server for a higher limit.")
    if response.status_code == 404:
        raise RepositoryNotFound("Repository not found. It may not exist or it may be private - private repositories are not supported yet.")
    if response.status_code in (401, 403):
        raise PrivateRepositoryUnsupported("GitHub refused access. Private repositories are not supported yet; use a public repository.")
    if response.status_code >= 400:
        raise GitHubUnavailable(f"GitHub returned an error (HTTP {response.status_code}). Try again later.")


def fetch_repo_metadata(owner: str, repo: str) -> dict:
    timeout = settings.HTTP_TIMEOUT_SECONDS
    try:
        response = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers(), timeout=timeout, allow_redirects=False)
        if response.status_code in (301, 302, 307, 308):  # renamed/transferred repo: GitHub redirects to a new API URL
            location = response.headers.get("Location", "")
            if urlsplit(location).hostname != "api.github.com":
                raise GitHubUnavailable("GitHub sent an unexpected redirect.")
            response = requests.get(location, headers=_headers(), timeout=timeout, allow_redirects=False)
        _raise_for_github(response)
        data = response.json()
        if data.get("private"):
            raise PrivateRepositoryUnsupported("This repository is private. Only public repositories are supported.")
        languages: dict = {}
        try:
            lang_response = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/languages", headers=_headers(), timeout=timeout, allow_redirects=False)
            if lang_response.status_code == 200:
                languages = lang_response.json()
        except requests.RequestException:
            pass  # languages are a nicety; local detection fills the gap
    except requests.Timeout as exc:
        raise GitHubUnavailable("GitHub took too long to respond. Try again.") from exc
    except requests.RequestException as exc:
        raise GitHubUnavailable("Could not reach GitHub. Check your internet connection.") from exc
    except ValueError as exc:
        raise GitHubUnavailable("GitHub returned an unreadable response.") from exc
    return {
        "full_name": data.get("full_name") or f"{owner}/{repo}", "description": data.get("description") or "",
        "default_branch": data.get("default_branch") or "", "stars": data.get("stargazers_count", 0),
        "primary_language": data.get("language") or "", "size_kb": data.get("size", 0), "languages": languages,
        "html_url": data.get("html_url") or f"https://github.com/{owner}/{repo}",
    }


def _download_archive(owner: str, repo: str, target: Path) -> None:
    """Stream the repository zip to `target`, following redirects only to GitHub hosts, with a size cap."""
    limit = settings.MAX_ARCHIVE_MB * 1024 * 1024
    url = f"{GITHUB_API}/repos/{owner}/{repo}/zipball"
    try:
        for _ in range(4):
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise GitHubUnavailable("GitHub sent the download to an unexpected address; import cancelled.")
            headers = _headers() if urlsplit(url).hostname == "api.github.com" else {"User-Agent": "RepoPilot-AI"}  # never send the token to another host
            with requests.get(url, headers=headers, timeout=settings.HTTP_TIMEOUT_SECONDS, stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = response.headers.get("Location", "")
                    continue
                _raise_for_github(response)
                written = 0
                with open(target, "wb") as handle:
                    for block in response.iter_content(chunk_size=64 * 1024):
                        written += len(block)
                        if written > limit:
                            raise RepositoryTooLarge(f"The repository download exceeds the {settings.MAX_ARCHIVE_MB} MB limit.")
                        handle.write(block)
                return
        raise GitHubUnavailable("Too many redirects while downloading the repository.")
    except requests.Timeout as exc:
        raise GitHubUnavailable("The download timed out. Try again.") from exc
    except requests.RequestException as exc:
        raise GitHubUnavailable("Could not download the repository. Check your internet connection.") from exc


def _extract_archive(archive: Path, dest: Path) -> int:
    """Safely extract only candidate source files. Returns the number of files written."""
    max_files = settings.MAX_FILES * 3
    max_total = settings.MAX_EXTRACTED_MB * 1024 * 1024
    max_file = settings.MAX_FILE_KB * 1024
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    written_files, total = 0, 0
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise GitHubUnavailable("GitHub returned a file that is not a valid archive.") from exc
    with zf:
        if sum(i.file_size for i in zf.infolist()) > max_total * 4:
            raise RepositoryTooLarge("The repository is too large to import.")
        for info in zf.infolist():
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # symbolic link: skip
            name = info.filename.replace("\\", "/")
            parts = name.split("/")[1:]  # GitHub wraps everything in one top-level folder
            if not parts or any(p in ("", ".", "..") for p in parts) or name.startswith("/"):
                continue
            rel = "/".join(parts)
            keep, _ = is_candidate_path(rel)
            if not keep or info.file_size == 0 or info.file_size > max_file:
                continue
            out = (dest / rel).resolve()
            if dest_root not in out.parents:
                continue  # zip-slip guard
            if written_files >= max_files or total + info.file_size > max_total:
                break
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                data = src.read(max_file + 1)  # never trust the declared size
                if len(data) > max_file:
                    continue
                dst.write(data)
            written_files += 1
            total += len(data)
    return written_files


# ------------------------------------------------------------ workspace ------
def source_dir(repo) -> Path:
    return Path(settings.WORKSPACE_ROOT) / repo.workspace_ref / "src"


def index_dir(repo) -> Path:
    return Path(settings.INDEX_ROOT) / repo.workspace_ref


def import_repository(owner_user, url: str):
    """Validate the URL, fetch metadata, download sources, and create the Repository row."""
    from .models import Repository

    owner, name = parse_github_url(url)
    canonical = f"https://github.com/{owner}/{name}"
    if Repository.objects.filter(owner=owner_user, github_url__iexact=canonical).exists():
        raise RepositoryImportError("You have already connected this repository.")
    meta = fetch_repo_metadata(owner, name)
    if meta["size_kb"] > settings.MAX_REPO_SIZE_KB:
        raise RepositoryTooLarge(f"This repository is {meta['size_kb'] // 1024} MB; the limit is {settings.MAX_REPO_SIZE_KB // 1024} MB.")
    repo = Repository(owner=owner_user, name=meta["full_name"], github_url=canonical)
    src = source_dir(repo)
    src.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=src.parent) as tmp:
            archive = Path(tmp) / "repo.zip"
            _download_archive(owner, name, archive)
            file_count = _extract_archive(archive, src)
        if file_count == 0:
            raise RepositoryImportError("No supported source files were found in this repository.")
        counts = Counter(detect_language(str(p.relative_to(src)).replace(os.sep, "/")) for p in src.rglob("*") if p.is_file())
        meta.update({"file_count": file_count, "local_languages": dict(counts.most_common()),
                     "primary_language": meta["primary_language"] or (counts.most_common(1)[0][0] if counts else "")})
        repo.metadata = meta
        repo.save()
    except Exception:
        shutil.rmtree(src.parent, ignore_errors=True)  # never leave half-imported files behind
        raise
    return repo


def delete_repository_files(repo) -> None:
    shutil.rmtree(source_dir(repo).parent, ignore_errors=True)
    shutil.rmtree(index_dir(repo), ignore_errors=True)


def limits_from_settings() -> Limits:
    return Limits(max_file_bytes=settings.MAX_FILE_KB * 1024, max_files=settings.MAX_FILES, max_chunks=settings.MAX_CHUNKS)


def run_analysis(repo) -> dict:
    """Build the search index for a repository and record the outcome in the database."""
    repo.analysis_status = repo.Status.ANALYZING
    repo.analysis_error = ""
    repo.save(update_fields=["analysis_status", "analysis_error", "updated_at"])
    try:
        summary = build_index(source_dir(repo), index_dir(repo), limits_from_settings(), use_semantic=settings.SEMANTIC_SEARCH_ENABLED,
                              model_name=settings.EMBEDDING_MODEL)
    except Exception as exc:
        repo.analysis_status = repo.Status.FAILED
        repo.analysis_error = str(exc)[:500] if isinstance(exc, ValueError) else f"Analysis failed ({type(exc).__name__})."
        repo.save(update_fields=["analysis_status", "analysis_error", "updated_at"])
        raise
    repo.metadata = {**repo.metadata, "analysis": summary, "index_stale": False}
    repo.analysis_status = repo.Status.COMPLETED
    repo.last_analyzed_at = timezone.now()
    repo.save(update_fields=["metadata", "analysis_status", "last_analyzed_at", "updated_at"])
    return summary


# -------------------------------------------------------------- patches ------
MAX_PATCH_LINES = 60


def resolve_inside(root: Path, relative_path: str) -> Path:
    """Resolve `relative_path` under `root`, rejecting anything that could escape it."""
    if not relative_path or "\x00" in relative_path or relative_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", relative_path):
        raise PatchValidationError("The target file path is not allowed.")
    normalised = relative_path.replace("\\", "/")
    if any(part in ("..", "") for part in normalised.split("/")):
        raise PatchValidationError("The target file path is not allowed.")
    root = Path(root).resolve()
    candidate = root / normalised
    if candidate.is_symlink():
        raise PatchValidationError("The target file path is not allowed.")
    resolved = candidate.resolve()
    if root not in resolved.parents:
        raise PatchValidationError("The target file is outside the repository workspace.")
    if not resolved.is_file():
        raise PatchValidationError("The target file does not exist in this repository.")
    return resolved


def _read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:  # newline="" keeps CRLF files intact
        return handle.read()


def _match_line_endings(content: str, snippet: str) -> str:
    if "\r\n" in content:
        return snippet.replace("\r\n", "\n").replace("\n", "\r\n")
    return snippet


def validate_patch(workspace: Path, file_path: str, original: str, proposed: str) -> Path:
    """Check a proposed change against the real file. Returns the safe resolved path or raises PatchValidationError."""
    if not original.strip():
        raise PatchValidationError("The change does not say which existing code to replace.")
    if original == proposed:
        raise PatchValidationError("The proposed code is identical to the original.")
    if max(original.count("\n"), proposed.count("\n")) + 1 > MAX_PATCH_LINES:
        raise PatchValidationError(f"The change is larger than {MAX_PATCH_LINES} lines; ask for a smaller, focused change.")
    target = resolve_inside(workspace, file_path)
    keep, _ = is_candidate_path(file_path.replace("\\", "/"))
    if not keep:
        raise PatchValidationError("Changes to this kind of file are not allowed.")
    content = _read_text(target)
    original = _match_line_endings(content, original)
    occurrences = content.count(original)
    if occurrences == 0:
        raise PatchValidationError("The original code was not found in the file exactly as written - the change cannot be applied safely.")
    if occurrences > 1:
        raise PatchValidationError("The original code appears more than once in the file, so the change is ambiguous.")
    return target


def make_diff(original: str, proposed: str, file_path: str) -> str:
    return "".join(difflib.unified_diff(original.splitlines(keepends=True), proposed.splitlines(keepends=True),
                                        fromfile=f"a/{file_path}", tofile=f"b/{file_path}", n=2))


def apply_patch(workspace: Path, file_path: str, original: str, proposed: str) -> None:
    """Write an APPROVED change to the local working copy (never to GitHub), atomically."""
    target = validate_patch(workspace, file_path, original, proposed)
    content = _read_text(target)
    updated = content.replace(_match_line_endings(content, original), _match_line_endings(content, proposed), 1)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".repopilot-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
