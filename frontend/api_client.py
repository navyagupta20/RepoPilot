"""Thin client for the RepoPilot Django REST API.

The Streamlit server holds the auth token in `st.session_state` (server memory, never sent to the
browser as a cookie or stored in the page) and sends it as `Authorization: Token <key>`.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

try:  # local runs read BACKEND_URL from the project's .env; Docker passes real environment variables
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


class ApiError(Exception):
    """An API call failed. `message` is safe to show to the user."""

    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _flatten_errors(data) -> str:
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        parts = []
        for field, value in data.items():
            text = " ".join(_flatten_errors(v) for v in value) if isinstance(value, list) else _flatten_errors(value)
            parts.append(text if field in ("non_field_errors",) else f"{field}: {text}")
        return " ".join(parts)
    if isinstance(data, list):
        return " ".join(_flatten_errors(v) for v in data)
    return str(data)


class ApiClient:
    def __init__(self, base_url: str = BACKEND_URL, token: str | None = None):
        self.base_url, self.token = base_url.rstrip("/"), token

    def _request(self, method: str, path: str, *, timeout: int = 30, **kwargs):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        try:
            response = requests.request(method, f"{self.base_url}/api{path}", headers=headers, timeout=timeout, **kwargs)
        except requests.Timeout:
            raise ApiError(0, "The request took too long. If you just started an analysis, give it a moment and refresh.", "timeout")
        except requests.RequestException:
            raise ApiError(0, f"Cannot reach the RepoPilot backend at {self.base_url}. Is it running?", "unreachable")
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            message = _flatten_errors(data) if data is not None else f"Unexpected server response (HTTP {response.status_code})."
            raise ApiError(response.status_code, message, (data or {}).get("code", "") if isinstance(data, dict) else "")
        return data

    # --- auth
    def register(self, username, password, email=""):
        return self._request("POST", "/auth/register/", json={"username": username, "password": password, "email": email})

    def login(self, username, password):
        return self._request("POST", "/auth/login/", json={"username": username, "password": password})

    def logout(self):
        return self._request("POST", "/auth/logout/")

    def health(self):
        return self._request("GET", "/health/", timeout=5)

    # --- dashboard / repositories
    def dashboard(self):
        return self._request("GET", "/dashboard/")

    def list_repositories(self):
        return self._request("GET", "/repositories/")

    def add_repository(self, url):
        return self._request("POST", "/repositories/", json={"url": url}, timeout=300)

    def delete_repository(self, repo_id):
        return self._request("DELETE", f"/repositories/{repo_id}/")

    def analyze(self, repo_id):
        return self._request("POST", f"/repositories/{repo_id}/analyze/", timeout=1800)

    def overview(self, repo_id):
        return self._request("GET", f"/repositories/{repo_id}/overview/", timeout=60)

    def search(self, repo_id, query, mode="hybrid", top_k=8):
        return self._request("POST", f"/repositories/{repo_id}/search/", json={"query": query, "mode": mode, "top_k": top_k}, timeout=120)

    # --- AI
    def ask(self, repo_id, question):
        return self._request("POST", f"/repositories/{repo_id}/ask/", json={"question": question}, timeout=180)

    def investigate(self, repo_id, description):
        return self._request("POST", f"/repositories/{repo_id}/investigate/", json={"description": description}, timeout=180)

    def suggest_fix(self, repo_id, description):
        return self._request("POST", f"/repositories/{repo_id}/suggest-fix/", json={"description": description}, timeout=180)

    # --- fixes
    def list_fixes(self, repo_id=None):
        return self._request("GET", "/fixes/", params={"repository": repo_id} if repo_id else None)

    def review_fix(self, fix_id, decision):
        return self._request("POST", f"/fixes/{fix_id}/review/", json={"decision": decision})

    def apply_fix(self, fix_id):
        return self._request("POST", f"/fixes/{fix_id}/apply/")

    def delete_fix(self, fix_id):
        return self._request("DELETE", f"/fixes/{fix_id}/")

    # --- history
    def list_history(self, repo_id=None, kind=None):
        params = {k: v for k, v in (("repository", repo_id), ("type", kind)) if v}
        return self._request("GET", "/history/", params=params or None)

    def delete_history(self, record_id):
        return self._request("DELETE", f"/history/{record_id}/")
