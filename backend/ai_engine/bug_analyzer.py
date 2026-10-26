"""Bug investigation: find the code an error points at, then ask the LLM for *hypotheses*.

Nothing here runs the repository's code. The result is always presented as a possible
explanation, never as a confirmed bug.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm
from .assistant import SYSTEM_PROMPT, _neutralise, build_context, build_outline, make_references
from .indexing import load_overview
from .search import hybrid_search, load_index

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([\w<>.]+))?')
_JS_FRAME = re.compile(r"at (?:([\w.$<>]+) )?\(?([^\s()]+\.(?:js|jsx|ts|tsx|mjs)):(\d+)(?::\d+)?\)?")
_JAVA_FRAME = re.compile(r"at ([\w.$]+)\((\w+\.java):(\d+)\)")
_GENERIC_FRAME = re.compile(r"([\w./\\-]+\.(?:py|js|jsx|ts|tsx|java|go|rb|php|rs|cs|kt)):(\d+)")
_EXCEPTION = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Failure|Warning))\b")

DISCLAIMER = ("This is an AI-generated hypothesis based on code excerpts. Nothing was executed, no bug was reproduced and no test was run. "
              "Treat it as a lead to verify, not as a confirmed bug.")

BUG_FORMAT = """Reply in Markdown with exactly these sections:
### Most likely cause (hypothesis)
State it as a hypothesis, with a confidence level (low / medium / high) and why.
### Evidence from the code
Bullets of the form `path:start-end` - what that code shows.
### Other possible causes
Short bullets, or "None identified".
### Debugging steps
Numbered, concrete steps the developer can try (logging, breakpoints, inputs to check, tests to write).
### What I could not determine
What is missing from the excerpts."""


def extract_error_signals(text: str) -> dict:
    """Find file/line hints, function names and exception types in an error message or traceback."""
    frames, seen = [], set()

    def add(path, line, func=""):
        path = path.replace("\\", "/")
        key = (path, int(line))
        if key not in seen:
            seen.add(key)
            frames.append({"path": path, "line": int(line), "function": func or ""})

    for m in _PY_FRAME.finditer(text):
        add(m.group(1), m.group(2), m.group(3))
    for m in _JS_FRAME.finditer(text):
        add(m.group(2), m.group(3), m.group(1))
    for m in _JAVA_FRAME.finditer(text):
        add(m.group(2), m.group(3), m.group(1).rsplit(".", 1)[-1])
    for m in _GENERIC_FRAME.finditer(text):
        add(m.group(1), m.group(2))
    exceptions = list(dict.fromkeys(_EXCEPTION.findall(text)))[:5]
    functions = list(dict.fromkeys(f["function"] for f in frames if f["function"] and f["function"] != "<module>"))[:8]
    message = ""
    for line in reversed([ln.strip() for ln in text.strip().splitlines() if ln.strip()]):
        if _EXCEPTION.search(line):
            message = line[:300]
            break
    return {"frames": frames[:15], "exceptions": exceptions, "functions": functions, "message": message}


def chunks_for_frames(chunks: list[dict], frames: list[dict]) -> list[dict]:
    """Chunks that contain a file:line mentioned in the error (matched by path suffix)."""
    found = []
    for frame in frames:
        tail = "/".join(frame["path"].strip("/").split("/")[-3:])
        for chunk in chunks:
            if (chunk["path"] == tail or chunk["path"].endswith("/" + tail) or tail.endswith("/" + chunk["path"])) \
                    and chunk["start_line"] <= frame["line"] <= chunk["end_line"]:
                found.append({**chunk, "score": 1.0, "source": "stack_trace", "keyword_rank": None, "semantic_rank": None})
    return found


def retrieve_for_bug(description: str, index_dir: Path, signals: dict, top_k: int = 8, embedder=None,
                     model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    """Stack-trace matches first, then hybrid search using the description plus extracted signals."""
    query = " ".join([description[:1500], signals["message"], " ".join(signals["exceptions"]), " ".join(signals["functions"])])
    search = hybrid_search(index_dir, query, top_k=top_k, embedder=embedder, model_name=model_name)
    results, ids = [], set()
    for chunk in chunks_for_frames(load_index(index_dir).chunks, signals["frames"]) + search["results"]:
        if chunk["id"] not in ids:
            ids.add(chunk["id"])
            results.append(chunk)
    search["results"] = results[:top_k + 2]
    return search


def investigate_bug(description: str, index_dir: Path, top_k: int = 8, embedder=None,
                    model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    llm.load_config()
    signals = extract_error_signals(description)
    search = retrieve_for_bug(description, index_dir, signals, top_k, embedder, model_name)
    if not search["results"]:
        return {"analysis": "No code in this repository matched the error or description, so I cannot suggest a cause from evidence. Include the file name, function name or full traceback if you have it.",
                "references": [], "signals": signals, "mode_used": search["mode_used"], "note": search["note"], "model": "",
                "llm_used": False, "disclaimer": DISCLAIMER}
    context, used = build_context(search["results"], max_chars=10000)
    outline = build_outline(load_overview(index_dir))
    prompt = (f"<repository_outline>\n{_neutralise(outline)}\n</repository_outline>\n\n{context}\n\n"
              f"Bug report or error message:\n<user_report>\n{_neutralise(description)}\n</user_report>\n\n{BUG_FORMAT}")
    analysis = llm.generate(SYSTEM_PROMPT, prompt)
    return {"analysis": analysis, "references": make_references(used), "signals": signals, "mode_used": search["mode_used"],
            "note": search["note"], "model": llm.model_name(), "llm_used": True, "disclaimer": DISCLAIMER}
