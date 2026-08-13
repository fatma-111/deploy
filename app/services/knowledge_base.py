"""Local RAG for repeated errors.

The idea: most bugs are not novel. If BugHound has already diagnosed this exact
kind of failure — from the seed knowledge base extracted from the PDF, or from
a case it solved earlier in this process's lifetime — serve that answer
directly and skip every LLM call for the investigation.

Retrieval is TF-IDF + cosine similarity (scikit-learn), held entirely in
memory. This is deliberately not a heavy embedding model: TF-IDF needs no
download, no GPU, and no network call, and for matching error signatures
against a few hundred known patterns it is more than adequate. It is exactly
the "in-memory vector store" option the project's own RAG-decision section
allows.

Two stores, one index:
  - seed:    data/knowledge_base_seed.json, extracted from the PDF, read-only.
  - learned: data/learned_cases.jsonl, appended to after an investigation this
             process completes and approves. A flat append-only file, not a
             database engine — no SQL, no server, no migrations — but it is
             genuine persistence across restarts, which is a deliberate,
             narrow exception to the project's original stateless design,
             made because the entire point of this feature is to remember.

Confidence from a match is always reported honestly below what a fresh,
code-specific diagnosis could reach, and every report says plainly that the
answer came from the knowledge base rather than a live analysis.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config.settings import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SEED_PATH = DATA_DIR / "knowledge_base_seed.json"
LEARNED_PATH = DATA_DIR / "learned_cases.jsonl"

_STOPWORDS_EXTRA = {"error", "exception", "traceback", "line", "file"}


class KnowledgeEntry(BaseModel):
    id: str
    title: str
    language: str = "General"
    framework: str = "General"
    tags: List[str] = Field(default_factory=list)
    error_pattern: str = ""
    root_cause: str = ""
    fix: str = ""
    patch: str = ""
    confidence: float = 0.75
    source: str = "seed"  # "seed" | "learned"
    added_at: Optional[float] = None


class KnowledgeMatch(BaseModel):
    entry: KnowledgeEntry
    score: float  # cosine similarity, 0..1
    exact_signature: bool = False


def _strip_type_prefix(error_type: str, error_message: str) -> str:
    """Avoid double-counting the error type.

    Standard tracebacks already embed the type in the message
    ("ModuleNotFoundError: No module named ..."), so combining error_type with
    the raw message doubles that token's weight and can out-rank a more
    specific entry whose title happens to repeat the generic type name.
    """
    message = (error_message or "").strip()
    prefix = f"{error_type}:"
    if error_type and message.lower().startswith(prefix.lower()):
        return message[len(prefix) :].strip()
    return message


def _signature(error_type: str, error_message: str, framework: str = "") -> str:
    """A short, normalized string that identifies the *kind* of error.

    Numbers, quoted values, file paths and hex addresses are stripped so that
    "KeyError: 'user_id'" and "KeyError: 'order_id'" are recognised as the same
    kind of problem, while still keeping enough text for TF-IDF to tell truly
    different errors apart.
    """
    text = f"{error_type} {framework} {error_message}".lower()
    text = re.sub(r"0x[0-9a-f]+", " ", text)
    text = re.sub(r"[\"'][^\"']{1,80}[\"']", " ", text)
    text = re.sub(r"[/\\][\w./\\-]+", " ", text)
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    tokens = [t for t in text.split() if t not in _STOPWORDS_EXTRA and len(t) > 1]
    return " ".join(tokens)


def _index_text(entry: "KnowledgeEntry") -> str:
    """Text used to build the searchable index for one entry.

    Deliberately excludes ``root_cause``: that field is long, explanatory
    prose whose vocabulary (words like "moved", "restructure", "current
    releases") repeats across unrelated entries and would dilute similarity.
    The title, error pattern, tags and framework are short and specific —
    much closer in shape to what an incoming query looks like.
    """
    parts = [
        entry.title,
        entry.error_pattern,
        " ".join(entry.tags),
        entry.framework,
        entry.language,
    ]
    return _signature(" ".join(parts), "", "")


class KnowledgeBase:
    """In-memory TF-IDF index over the seed and learned entries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: List[KnowledgeEntry] = []
        self._signatures: List[str] = []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._matrix = None
        self._loaded = False

    # ------------------------------------------------------------------ load
    def _load_seed(self) -> List[KnowledgeEntry]:
        if not SEED_PATH.exists():
            logger.warning(
                "%s not found. Run scripts/build_knowledge_pdf.py and "
                "scripts/build_knowledge_index.py to generate it.",
                SEED_PATH,
            )
            return []
        try:
            raw = json.loads(SEED_PATH.read_text())
            return [KnowledgeEntry(**item) for item in raw]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load seed knowledge base: %s", exc)
            return []

    def _load_learned(self) -> List[KnowledgeEntry]:
        if not LEARNED_PATH.exists():
            return []
        entries: List[KnowledgeEntry] = []
        try:
            for line in LEARNED_PATH.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(KnowledgeEntry(**json.loads(line)))
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load learned cases: %s", exc)
        # Cap and keep the most recent: unbounded growth is not the goal here.
        return entries[-settings.kb_max_learned_entries :]

    def ensure_loaded(self, force: bool = False) -> None:
        with self._lock:
            if self._loaded and not force:
                return
            entries = self._load_seed() + self._load_learned()
            self._entries = entries
            self._signatures = [_index_text(e) for e in entries]
            if self._signatures:
                self._vectorizer = TfidfVectorizer(
                    ngram_range=(1, 2), min_df=1, max_features=4000
                )
                self._matrix = self._vectorizer.fit_transform(self._signatures)
            else:
                self._vectorizer = None
                self._matrix = None
            self._loaded = True
            logger.info(
                "Knowledge base loaded: %d seed, %d learned",
                sum(1 for e in entries if e.source == "seed"),
                sum(1 for e in entries if e.source == "learned"),
            )

    # --------------------------------------------------------------- lookup
    def lookup(
        self, error_type: str, error_message: str, framework: str = ""
    ) -> Optional[KnowledgeMatch]:
        """Return the best match, or None if nothing clears the threshold."""
        self.ensure_loaded()
        if not self._vectorizer or not self._entries:
            return None

        query_sig = _signature(
            error_type, _strip_type_prefix(error_type, error_message), framework
        )
        if not query_sig.strip():
            return None

        query_vec = self._vectorizer.transform([query_sig])
        scores = cosine_similarity(query_vec, self._matrix)[0]
        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score < settings.kb_match_threshold:
            return None

        matched_entry = self._entries[best_idx]
        pattern_sig = _signature(matched_entry.error_pattern, "", "")
        exact = bool(pattern_sig) and query_sig == pattern_sig
        return KnowledgeMatch(entry=matched_entry, score=best_score, exact_signature=exact)

    # ---------------------------------------------------------------- learn
    def learn(
        self,
        *,
        error_type: str,
        error_message: str,
        framework: str,
        language: str,
        root_cause: str,
        fix: str,
        patch: str,
        confidence: float,
    ) -> None:
        """Append a newly-solved case so the next identical error skips the LLM.

        Confidence is stored slightly reduced from the original diagnosis: the
        next match is generic pattern-matching, not a fresh look at that
        specific codebase, and the report should say so honestly.
        """
        if not settings.kb_learning_enabled:
            return

        entry = KnowledgeEntry(
            id=f"L{int(time.time() * 1000)}",
            title=f"{error_type} ({framework or language or 'General'})",
            language=language or "General",
            framework=framework or "General",
            tags=["learned"],
            error_pattern=f"{error_type}: {error_message[:200]}",
            root_cause=root_cause,
            fix=fix,
            patch=patch,
            confidence=max(0.5, min(0.9, confidence - 0.05)),
            source="learned",
            added_at=time.time(),
        )

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with LEARNED_PATH.open("a") as f:
                f.write(entry.model_dump_json() + "\n")
        except OSError as exc:  # noqa: BLE001
            logger.warning("Could not persist learned case: %s", exc)
            return

        self._prune_if_needed()
        self.ensure_loaded(force=True)

    def _prune_if_needed(self) -> None:
        """Keep the learned file bounded rather than growing forever."""
        if not LEARNED_PATH.exists():
            return
        lines = [l for l in LEARNED_PATH.read_text().splitlines() if l.strip()]
        if len(lines) > settings.kb_max_learned_entries:
            LEARNED_PATH.write_text(
                "\n".join(lines[-settings.kb_max_learned_entries :]) + "\n"
            )

    # ---------------------------------------------------------------- stats
    def stats(self) -> Dict[str, Any]:
        self.ensure_loaded()
        seed = [e for e in self._entries if e.source == "seed"]
        learned = [e for e in self._entries if e.source == "learned"]
        by_framework: Dict[str, int] = {}
        for e in self._entries:
            by_framework[e.framework] = by_framework.get(e.framework, 0) + 1
        return {
            "seed_count": len(seed),
            "learned_count": len(learned),
            "total": len(self._entries),
            "by_framework": by_framework,
            "match_threshold": settings.kb_match_threshold,
            "learning_enabled": settings.kb_learning_enabled,
            "seed_source": str(SEED_PATH),
            "learned_source": str(LEARNED_PATH),
        }

    def all_entries(self) -> List[KnowledgeEntry]:
        self.ensure_loaded()
        return list(self._entries)

    def clear_learned(self) -> None:
        """Testing / reset hook. Never touches the seed data."""
        if LEARNED_PATH.exists():
            LEARNED_PATH.unlink()
        self.ensure_loaded(force=True)


knowledge_base = KnowledgeBase()
