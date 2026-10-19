"""Read a manuscript (PDF, Word or plain text) into title, abstract and full text.

Extraction is deliberately simple; the agent checks the title and abstract it reports and
can override them on the command line. For best PDF quality, parse with GROBID first and
pass the resulting text file.
"""
from __future__ import annotations

import re
from pathlib import Path


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="ignore")


def guess_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 15 and not re.match(r"(?i)^(abstract|keywords|manuscript|this document)", line):
            return line[:300]
    return ""


def guess_abstract(text: str, limit: int = 2500) -> str:
    """The Abstract section if the manuscript has one, otherwise its opening."""
    m = re.search(r"^\s*abstract\s*[:.]?\s*$|\babstract\s*[:.]", text, re.I | re.M)
    start = m.end() if m else 0
    chunk = text[start:start + limit]
    stop = re.search(r"\n\s*(keywords|key words|introduction|1\.\s+introduction)\b", chunk, re.I)
    return (chunk[:stop.start()] if stop else chunk).strip()


def load(path: Path, title: str | None = None, abstract: str | None = None) -> dict:
    text = read_text(path)
    return {"source": str(path), "title": title or guess_title(text),
            "abstract": abstract or guess_abstract(text), "text": text, "chars": len(text)}
