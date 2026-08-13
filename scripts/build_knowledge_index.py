"""Extracts data/error_knowledge_base.pdf back into structured entries.

This is the real ingestion step: the PDF's text is what gets parsed, using the
"=== ENTRY <id> ===" / "=== END <id> ===" markers laid down by
build_knowledge_pdf.py. The output is cached as knowledge_base_seed.json so the
running app loads instantly instead of re-parsing PDF text on every start.

Run this after editing the PDF directly, or after regenerating it from
data/error_knowledge_seed.py:
    python scripts/build_knowledge_pdf.py
    python scripts/build_knowledge_index.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "error_knowledge_base.pdf"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base_seed.json"

ENTRY_BLOCK = re.compile(
    r"=== ENTRY (?P<id>\w+) ===\s*\n"
    r"(?P<title>.+?)\n"
    r"Language:\s*(?P<language>.+?)\s*\|\s*"
    r"Framework:\s*(?P<framework>.+?)\s*\|\s*"
    r"Tags:\s*(?P<tags>.+?)\s*\|\s*"
    r"Confidence:\s*(?P<confidence>[\d.]+)\s*\n"
    r"Error Pattern:\s*\n?(?P<error_pattern>.+?)\n"
    r"Root Cause:\s*\n?(?P<root_cause>.+?)\n"
    r"Fix:\s*\n?(?P<fix>.+?)\n"
    r"(?:Patch Template:\s*\n?(?P<patch>.*?)\n)?"
    r"=== END \1 ===",
    re.DOTALL,
)


def extract_text(pdf_path: Path) -> str:
    """Pull every page's text, in order, into one string."""
    chunks: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            chunks.append(text)
    return "\n".join(chunks)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_entries(raw_text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for match in ENTRY_BLOCK.finditer(raw_text):
        fields = match.groupdict()
        patch = (fields.get("patch") or "").strip()
        # The patch block is the one field that must keep its original line
        # breaks; pdfplumber preserves them, so only strip the block, not the
        # newlines inside it.
        entries.append(
            {
                "id": fields["id"],
                "title": _clean(fields["title"]),
                "language": _clean(fields["language"]),
                "framework": _clean(fields["framework"]),
                "tags": [t.strip() for t in fields["tags"].split(",") if t.strip()],
                "confidence": float(fields["confidence"]),
                "error_pattern": _clean(fields["error_pattern"]),
                "root_cause": _clean(fields["root_cause"]),
                "fix": _clean(fields["fix"]),
                "patch": patch,
                "source": "seed",
            }
        )
    return entries


def build_index() -> List[Dict[str, Any]]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(
            f"{PDF_PATH} does not exist. Run scripts/build_knowledge_pdf.py first."
        )
    raw_text = extract_text(PDF_PATH)
    entries = parse_entries(raw_text)
    OUTPUT_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    return entries


if __name__ == "__main__":
    entries = build_index()
    print(f"Parsed {len(entries)} entries from {PDF_PATH.name} -> {OUTPUT_PATH.name}")
    if not entries:
        print("WARNING: zero entries parsed — check the marker regex against the PDF text.")
