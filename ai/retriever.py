#!/usr/bin/env python3
"""
Dexter Knowledge Retriever - Step 5 Implementation

Fetches relevant CBC knowledge snippets from the Markdown topic files in
config/topics/ so the AI engine can ground its answers in vetted,
curriculum-specific material (ARCHITECTURE.md sections 4.1, 7 and 11).

Public contract (architecture section 4.1 — must stay stable):

    @dataclass
    class Snippet:
        source_file: str
        content: str
        match_score: float

    def retrieve(query: str, max_snippets: int = 2) -> list[Snippet]

How v1 matching works (keyword matching, as specified for v1):
- Every Markdown file in config/topics/ is parsed into its metadata block
  (Grade, Learning area, Strand, Topic, Keywords — see
  config/topics/_template.md) and its '##' sections.
- A query is tokenized into lowercase terms; English stop-words, single
  characters and noise are dropped, and simple singular/plural and common
  suffix variants are matched (mixture/mixtures, separate/separating...).
- Each term is matched against, per file: the filename (strong), the
  section's '##' heading (strong bonus), the H1 title, the Keywords
  line and the Grade/Strand/Topic metadata (moderate). Contributions
  are summed, so a term central to a file (in its name, title,
  keywords and topic) ranks it above a file the term merely mentions.
  The best section of each file is returned, highest scoring files
  first, at most max_snippets files.
- Files whose names start with '_' (e.g. _template.md) and non-Markdown
  files are ignored.

Robustness:
- The retriever never raises to callers. A missing, empty or malformed
  knowledge directory yields an empty result list, and a failed reload
  keeps the previously loaded index (mirroring the persona reload rule).
- Additional CBC subjects/grades can be added by dropping more Markdown
  files into config/topics/ following _template.md — no code changes
  needed. Matching is metadata-driven, so grade/subject/strand/topic
  distinctions are respected when present in the files.

The matching method is an implementation detail behind retrieve() and may
be swapped later (e.g. TF-IDF per architecture section 13) without any
other module changing.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Default knowledge directory: <repo>/config/topics
TOPICS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "config", "topics")
)

# Scoring weights (per query term): the file-level signal (filename is the
# strongest), plus a bonus when the term names THIS section (its '##'
# heading or one of its '###' subheadings), so the right section of a file
# beats its siblings.
_WEIGHT_FILENAME = 3.0
_WEIGHT_TITLE = 2.0
_WEIGHT_KEYWORDS = 2.0
_WEIGHT_TOPIC = 2.0       # Topic metadata: what the file is actually about
_WEIGHT_STRAND = 1.0      # Strand metadata: shared by sibling files
_WEIGHT_GRADE_AREA = 0.5  # Grade/Learning area: near-universal in a
                          # single-grade corpus, so a weak signal only
_HEADING_BONUS = 2.0

# A section must score at least this to be returned (one real keyword hit).
MIN_SCORE = 2.0

# Upper bound for the injected text of one snippet, to keep prompts small.
MAX_SNIPPET_CHARS = 1200

# Metadata fields used for matching (Source is deliberately excluded —
# it names the original PDF, not the educational content).
_META_FIELDS = ("Grade", "Learning area", "Strand", "Topic", "Keywords")

_META_LINE_RE = re.compile(r"^-\s*\*\*(.+?):\*\*\s*(.*)$")

# Conservative stop-word list: articles, pronouns, auxiliaries, common
# prepositions and contentless question/instruction verbs. Deliberately
# does NOT include domain words like use/uses, types, work, water.
STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "am", "do", "does", "did", "doing", "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might",
    "must", "of", "in", "on", "at", "by", "for", "with", "from", "to",
    "into", "onto", "about", "between", "and", "or", "but", "not", "no",
    "nor", "so", "than", "then", "too", "very", "just", "what", "which",
    "who", "whom", "whose", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "only",
    "own", "same", "now", "i", "me", "my", "myself", "we", "our", "ours",
    "you", "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "they", "them", "their", "theirs", "this", "that",
    "these", "those", "please", "kindly", "hey", "hi", "hello", "tell",
    "explain", "describe", "define", "discuss", "give", "name", "list",
    "state", "show", "many", "much", "also", "there", "here",
    # Contentless instruction verbs (maths/general), same category as
    # explain/describe: "solve x + 3 = 7" should not match "problem solving".
    "solve", "find", "calculate", "compute", "convert", "help", "need",
    "want", "know", "learn", "study",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Snippet:
    """One retrievable piece of CBC knowledge (architecture section 4.1)."""
    source_file: str
    content: str
    match_score: float


@dataclass
class _Section:
    heading: str
    text: str
    heading_stems: frozenset = None

    def __post_init__(self) -> None:
        self.heading_stems = _stems_of_text(self.heading)

    def add_subheading(self, subheading: str) -> None:
        """Fold a '###' subheading into this section's matching stems."""
        self.heading_stems = self.heading_stems | _stems_of_text(subheading)


@dataclass
class _TopicFile:
    filename: str
    title: str
    metadata: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)
    filename_stems: frozenset = field(default_factory=frozenset)
    title_stems: frozenset = field(default_factory=frozenset)
    keywords_stems: frozenset = field(default_factory=frozenset)
    topic_stems: frozenset = field(default_factory=frozenset)
    strand_stems: frozenset = field(default_factory=frozenset)
    area_stems: frozenset = field(default_factory=frozenset)


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens of a text."""
    return _TOKEN_RE.findall(text.lower())


def _stems(token: str) -> set:
    """
    Simple suffix variants of a token so that mixture/mixtures,
    separate/separating, acid/acids etc. all match each other.
    """
    stems = {token}
    if token.endswith("ies") and len(token) > 4:
        stems.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 4:
        stems.add(token[:-2])
    if token.endswith("s") and len(token) > 3:
        stems.add(token[:-1])
    if token.endswith("ing") and len(token) > 5:
        stems.add(token[:-3])
    if token.endswith("ed") and len(token) > 4:
        stems.add(token[:-2])
    if token.endswith("e") and len(token) >= 5:
        stems.add(token[:-1])
    return stems


def _stems_of_text(text: str) -> frozenset:
    """All stem variants of all tokens of a text."""
    result = set()
    for token in _tokens(text):
        result.update(_stems(token))
    return frozenset(result)


def query_terms(query: str) -> list[str]:
    """
    Meaningful, de-duplicated query terms (lowercase, stop-words and
    single characters removed, order preserved).
    """
    terms: list[str] = []
    seen = set()
    for token in _tokens(query):
        if token in STOPWORDS or len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _parse_topic_file(path: str, filename: str) -> Optional[_TopicFile]:
    """
    Parse one knowledge Markdown file.

    Returns None (and counts as skipped) when the file cannot be read,
    is not valid UTF-8, or is empty. Never raises.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8-sig")  # raises on binary junk
    except (OSError, UnicodeDecodeError, ValueError) as e:
        logger.warning(f"Skipping unreadable knowledge file {filename}: {e}")
        return None

    if not text.strip():
        logger.warning(f"Skipping empty knowledge file {filename}")
        return None

    title = ""
    metadata: dict = {}
    sections: list = []
    current: Optional[_Section] = None
    in_preamble = True

    for line in text.splitlines():
        stripped = line.strip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            in_preamble = False
            current = _Section(heading=line[3:].strip(), text=line)
            sections.append(current)
        elif line.startswith("### ") and current is not None:
            # Subheadings stay inside their '##' section (they only widen
            # the matching signal, they do not split the snippet).
            current.add_subheading(line[4:].strip())
            current.text += "\n" + line
        elif in_preamble:
            match = _META_LINE_RE.match(stripped)
            if match:
                metadata[match.group(1).strip()] = match.group(2).strip()
        elif current is not None:
            current.text += "\n" + line

    if not sections:
        # A file without '##' sections is treated as one whole-file
        # section so it remains retrievable via its title/filename.
        fallback = _Section(heading=title or filename, text=text)
        sections.append(fallback)

    stem_base = filename[:-3] if filename.endswith(".md") else filename
    topic_file = _TopicFile(
        filename=filename,
        title=title,
        metadata=metadata,
        sections=sections,
        filename_stems=_stems_of_text(stem_base.replace("-", " ")),
        title_stems=_stems_of_text(title),
        keywords_stems=_stems_of_text(metadata.get("Keywords", "")),
        topic_stems=_stems_of_text(metadata.get("Topic", "")),
        strand_stems=_stems_of_text(metadata.get("Strand", "")),
        area_stems=_stems_of_text(
            metadata.get("Grade", "") + " "
            + metadata.get("Learning area", "")),
    )
    return topic_file


class TopicRetriever:
    """
    Keyword-matching retriever over the Markdown files of a topics
    directory (config/topics/ by default).

    Usage:
        retriever = TopicRetriever()          # default directory
        retriever = TopicRetriever("/path")   # explicit directory (tests)
        snippets = retriever.retrieve(query)
    """

    def __init__(self, topics_dir: Optional[str] = None):
        self._topics_dir = os.path.abspath(topics_dir) if topics_dir else TOPICS_DIR
        self._files: list = []
        self._loaded = False

    @property
    def topics_dir(self) -> str:
        return self._topics_dir

    @property
    def file_count(self) -> int:
        return len(self._files)

    def reload(self) -> tuple:
        """
        (Re)read the knowledge directory from disk.

        Returns (success, message). Individual unreadable files are
        skipped and reported; if the directory itself is missing, the
        previously loaded index is kept (mirroring the persona reload
        rule: a bad reload never leaves us worse off). Never raises.
        """
        try:
            if not os.path.isdir(self._topics_dir):
                if self._loaded and self._files:
                    return False, (f"topics directory not found, "
                                   f"keeping previous {len(self._files)} files")
                self._files = []
                self._loaded = True
                return False, "topics directory not found"

            files = []
            skipped = 0
            for name in sorted(os.listdir(self._topics_dir)):
                if not name.endswith(".md") or name.startswith("_"):
                    continue
                parsed = _parse_topic_file(
                    os.path.join(self._topics_dir, name), name)
                if parsed is None:
                    skipped += 1
                    continue
                files.append(parsed)

            self._files = files
            self._loaded = True
            message = f"{len(files)} topic files loaded"
            if skipped:
                message += f", {skipped} skipped (unreadable or empty)"
            return True, message
        except Exception as e:  # never raise out of reload
            logger.error(f"Knowledge reload failed: {e}")
            return False, f"topics reload failed: {e}"

    def retrieve(self, query: str, max_snippets: int = 2) -> list:
        """
        Return up to max_snippets knowledge snippets relevant to the
        query, best match first. Never raises; returns [] when nothing
        matches or no knowledge is loaded.
        """
        try:
            if not self._loaded:
                self.reload()
            terms = query_terms(query)
            if not terms or max_snippets <= 0:
                return []

            scored = []  # (score, topic_file, section)
            for topic_file in self._files:
                best = None  # (score, section)
                for section in topic_file.sections:
                    score = 0.0
                    for term in terms:
                        term_stems = _stems(term)
                        # File-level signals are SUMMED, not elif-chained:
                        # a term that appears in the filename AND the title
                        # AND the keywords AND the Topic metadata is more
                        # central to that file than one that only names it.
                        # This keeps definitional files ("Acids, Bases and
                        # Alkalis") above narrower siblings ("... Indicators
                        # and the pH Scale") for broad questions.
                        if term_stems & topic_file.filename_stems:
                            score += _WEIGHT_FILENAME
                        if term_stems & topic_file.title_stems:
                            score += _WEIGHT_TITLE
                        if term_stems & topic_file.keywords_stems:
                            score += _WEIGHT_KEYWORDS
                        if term_stems & topic_file.topic_stems:
                            score += _WEIGHT_TOPIC
                        if term_stems & topic_file.strand_stems:
                            score += _WEIGHT_STRAND
                        if term_stems & topic_file.area_stems:
                            score += _WEIGHT_GRADE_AREA
                        # Bonus when this term names the section itself.
                        if term_stems & section.heading_stems:
                            score += _HEADING_BONUS
                    if score > 0 and (best is None or score > best[0]):
                        best = (score, section)
                if best is not None and best[0] >= MIN_SCORE:
                    scored.append((best[0], topic_file, best[1]))

            # Best file first; ties broken deterministically by filename.
            scored.sort(key=lambda item: (-item[0], item[1].filename))
            scored = scored[:max_snippets]

            max_term_score = (
                _WEIGHT_FILENAME + _WEIGHT_TITLE + _WEIGHT_KEYWORDS
                + _WEIGHT_TOPIC + _WEIGHT_STRAND + _WEIGHT_GRADE_AREA
                + _HEADING_BONUS
            )
            snippets = []
            for score, topic_file, section in scored:
                match_score = round(
                    min(1.0, score / (max_term_score * len(terms))), 3)
                snippets.append(Snippet(
                    source_file=topic_file.filename,
                    content=self._build_content(topic_file, section),
                    match_score=match_score,
                ))
            return snippets
        except Exception as e:  # retrieval must never break answering
            logger.error(f"Knowledge retrieval failed: {e}")
            return []

    @staticmethod
    def _build_content(topic_file: _TopicFile, section: _Section) -> str:
        """
        Self-contained snippet text: source context (so the snippet stays
        understandable on its own) plus the matched section, bounded in
        size to keep prompts small.
        """

        def clip(value: str, limit: int = 80) -> str:
            value = " ".join(value.split())
            return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"

        context_parts = []
        for meta_field, label in (
            ("Grade", "Grade"),
            ("Learning area", "Subject"),
            ("Strand", "Strand"),
        ):
            value = topic_file.metadata.get(meta_field, "")
            if value:
                context_parts.append(f"{label}: {clip(value)}")

        parts = [f"Source: {topic_file.filename}"]
        if context_parts:
            parts.append(" | ".join(context_parts))

        body = section.text
        if len(body) > MAX_SNIPPET_CHARS:
            body = body[:MAX_SNIPPET_CHARS].rstrip() + "\n[... truncated]"
        parts.append(body)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Default singleton behind the architecture's retrieve() interface
# ---------------------------------------------------------------------------

_default_retriever: Optional[TopicRetriever] = None


def get_retriever() -> TopicRetriever:
    """Get (lazily creating) the shared retriever for config/topics/."""
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = TopicRetriever()
    return _default_retriever


def retrieve(query: str, max_snippets: int = 2) -> list:
    """
    Retrieve knowledge snippets for a query (architecture section 4.1).

    def retrieve(query: str, max_snippets: int = 2) -> list[Snippet]
    """
    return get_retriever().retrieve(query, max_snippets)


def reload_topics() -> tuple:
    """Reload the knowledge directory; returns (success, message)."""
    return get_retriever().reload()
