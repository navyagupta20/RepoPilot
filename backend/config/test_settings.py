"""Settings used by pytest only: always SQLite in memory, never a real database, offline-friendly."""
import os

os.environ["DB_ENGINE"] = "sqlite"
os.environ["SQLITE_PATH"] = ":memory:"
os.environ["DJANGO_DEBUG"] = "true"
os.environ["DJANGO_SECRET_KEY"] = "test-secret-key"
os.environ["AUTH_THROTTLE_RATE"] = "10000/min"
os.environ["LLM_THROTTLE_RATE"] = "10000/min"
os.environ["SEMANTIC_SEARCH_ENABLED"] = "false"

from .settings import *  # noqa: E402,F401,F403
