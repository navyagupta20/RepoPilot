"""Tree-sitter code parsing.

`parse_source()` turns a source file into a list of *symbols* (functions,
classes, methods, ...) with line ranges. Languages without a Tree-sitter
grammar installed are NOT parsed: the caller gets `parsed=False` and falls back
to plain text chunking. We never pretend to understand a language we cannot parse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# file extension -> language label used for display / grammar lookup
EXTENSION_LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".java": "java", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".cc": "cpp", ".cs": "csharp", ".kt": "kotlin", ".swift": "swift", ".scala": "scala", ".sh": "shell",
    ".sql": "sql", ".html": "html", ".css": "css", ".scss": "scss", ".json": "json", ".yml": "yaml",
    ".yaml": "yaml", ".toml": "toml", ".md": "markdown", ".txt": "text", ".ini": "ini", ".cfg": "ini",
}
FILENAME_LANGUAGES = {"dockerfile": "dockerfile", "makefile": "makefile"}

# Languages with a Tree-sitter grammar wired up below.
PARSEABLE = {"python", "javascript", "typescript", "tsx", "java", "go"}

# Node types that define a symbol, per language: node_type -> kind
SYMBOL_NODES = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": {"function_declaration": "function", "generator_function_declaration": "function",
                   "class_declaration": "class", "method_definition": "method"},
    "typescript": {"function_declaration": "function", "generator_function_declaration": "function",
                   "class_declaration": "class", "method_definition": "method",
                   "interface_declaration": "interface", "enum_declaration": "enum", "type_alias_declaration": "type"},
    "java": {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum",
             "method_declaration": "method", "constructor_declaration": "method", "record_declaration": "class"},
    "go": {"function_declaration": "function", "method_declaration": "method", "type_spec": "type"},
}
SYMBOL_NODES["tsx"] = SYMBOL_NODES["typescript"]
CONTAINER_KINDS = {"class", "interface", "enum"}  # we look inside these for methods
FUNCTION_VALUE_NODES = {"arrow_function", "function_expression", "function"}  # const f = () => {}


@dataclass
class Symbol:
    name: str
    kind: str
    start_line: int  # 1-based, inclusive
    end_line: int
    children: list["Symbol"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "start_line": self.start_line, "end_line": self.end_line}


@dataclass
class ParsedFile:
    language: str
    parsed: bool                      # True only if Tree-sitter really parsed it
    symbols: list[Symbol] = field(default_factory=list)  # top-level symbols (with nested children)

    def flat_symbols(self) -> list[Symbol]:
        out: list[Symbol] = []

        def visit(items):
            for s in items:
                out.append(s)
                visit(s.children)

        visit(self.symbols)
        return out


def detect_language(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1].lower()
    if name in FILENAME_LANGUAGES:
        return FILENAME_LANGUAGES[name]
    dot = name.rfind(".")
    return EXTENSION_LANGUAGES.get(name[dot:], "text") if dot != -1 else "text"


_parsers: dict[str, object] = {}


def _get_parser(language: str):
    """Build (and cache) a Tree-sitter parser; returns None if unavailable."""
    if language in _parsers:
        return _parsers[language]
    parser = None
    try:
        from tree_sitter import Language, Parser

        if language == "python":
            import tree_sitter_python as mod
            lang = mod.language()
        elif language == "javascript":
            import tree_sitter_javascript as mod
            lang = mod.language()
        elif language == "typescript":
            import tree_sitter_typescript as mod
            lang = mod.language_typescript()
        elif language == "tsx":
            import tree_sitter_typescript as mod
            lang = mod.language_tsx()
        elif language == "java":
            import tree_sitter_java as mod
            lang = mod.language()
        elif language == "go":
            import tree_sitter_go as mod
            lang = mod.language()
        else:
            lang = None
        if lang is not None:
            parser = Parser(Language(lang))
    except Exception as exc:  # ImportError or version mismatch: degrade, do not crash
        logger.warning("Tree-sitter grammar for %s unavailable: %s", language, exc)
    _parsers[language] = parser
    return parser


def _symbol_from_node(node, language: str):
    """Return (Symbol, descend_into) if `node` defines a symbol, else None."""
    kinds = SYMBOL_NODES[language]
    kind = kinds.get(node.type)
    range_node = node
    name_node = None
    if kind:
        name_node = node.child_by_field_name("name")
        parent = node.parent
        if parent is not None and parent.type in ("decorated_definition", "export_statement"):
            range_node = parent  # include decorators / `export` keyword in the range
    elif language in ("javascript", "typescript", "tsx") and node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value is not None and value.type in FUNCTION_VALUE_NODES:
            kind, name_node = "function", node.child_by_field_name("name")
            parent = node.parent
            if parent is not None and parent.type in ("lexical_declaration", "variable_declaration"):
                range_node = parent
                if parent.parent is not None and parent.parent.type == "export_statement":
                    range_node = parent.parent
    if not kind or name_node is None:
        return None
    name = name_node.text.decode("utf-8", errors="replace")
    symbol = Symbol(name=name, kind=kind, start_line=range_node.start_point[0] + 1, end_line=range_node.end_point[0] + 1)
    return symbol, kind in CONTAINER_KINDS


def _walk(node, language: str, container: list[Symbol]) -> None:
    for child in node.children:
        found = _symbol_from_node(child, language)
        if found is None:
            _walk(child, language, container)
            continue
        symbol, descend = found
        container.append(symbol)
        if descend:  # look for methods inside classes; nested functions stay inside their parent chunk
            _walk(child, language, symbol.children)


def parse_source(rel_path: str, text: str) -> ParsedFile:
    """Parse one file. Unsupported languages return `parsed=False` and no symbols."""
    language = detect_language(rel_path)
    if language not in PARSEABLE:
        return ParsedFile(language=language, parsed=False)
    parser = _get_parser(language)
    if parser is None:
        return ParsedFile(language=language, parsed=False)
    try:
        tree = parser.parse(text.encode("utf-8", errors="replace"))
        symbols: list[Symbol] = []
        _walk(tree.root_node, language, symbols)
        return ParsedFile(language=language, parsed=True, symbols=symbols)
    except Exception as exc:  # a parser bug must never break a whole analysis
        logger.warning("Parsing %s failed: %s", rel_path, exc)
        return ParsedFile(language=language, parsed=False)
