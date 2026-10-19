"""Read a manuscript (PDF, Word or plain text) into title, abstract and full text.

Extraction is heuristic; the agent checks the title and abstract it reports and can override
them on the command line. For best PDF quality, parse with GROBID first and pass the resulting
text file.
"""
from __future__ import annotations

import re
from pathlib import Path

# "A B S T R A C T" (Elsevier) and similar letter-spaced headings
SPACED = re.compile(r"\b(?:[A-Z] ){3,}[A-Z]\b")
# a line that is only the heading, else a line opening with "Abstract:" — never a sentence
# that merely mentions an abstract, and never "Graphical abstract"
ABSTRACT = (re.compile(r"^[ \t]*abstract[ \t]*[:.]?[ \t]*$", re.I | re.M),
            re.compile(r"^[ \t]*abstract[ \t]*[:.—–-]", re.I | re.M))
STOP = re.compile(r"\n[ \t]*(?:keywords|key words|highlights|introduction|1\.?[ \t]+introduction"
                  r"|■[ \t]*introduction|graphical abstract|click here to|powered by editorial manager"
                  r"|suggested reviewers|opposed reviewers|order of authors)\b", re.I)
# page furniture that PDF reading order can drop into the middle of an abstract
FURNITURE = re.compile(r"(?i)^\s*(?:\*\s*corresponding author|e-?mail address|contents lists available"
                       r"|journal homepage|https?://doi\.org|received\b|available online)|©"
                       r"|creativecommons\.org")
NOT_TITLE = re.compile(r"(?i)^(arxiv:|manuscript|this document|--|contents lists|journal homepage)"
                       r"|^(environmental science & technology|water research|nature [a-z]+|one earth"
                       r"|access|review|article|analysis|research article)$")


def _clean(text: str) -> str:
    """Undo PDF line-wrapping artefacts that break verbatim matching."""
    text = text.replace("­\n", "").replace("­", "")      # soft hyphens split words
    return text.replace("ﬁ", "fi").replace("ﬂ", "fl")


def _flat(text: str, vocab: set[str] | None = None) -> str:
    """One paragraph: join wrapped lines. A word split at a line-end hyphen is joined when the
    document uses it unhyphenated elsewhere ("enhanc-/ing"), else the hyphen stays ("expert-led")."""
    def join(m):
        whole = m.group(1) + m.group(2)
        return whole if vocab and whole.lower() in vocab else f"{m.group(1)}-{m.group(2)}"
    text = re.sub(r"(\w+)-\n([a-z]\w*)", join, text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+\d{1,3}$", "", text)              # a trailing page or footnote number


def _pdf_first_page(doc) -> tuple[str, list[str]]:
    """Title (the largest text on page 1 that reads like a title) and page-1 text blocks."""
    d = doc[0].get_text("dict")
    lines = []                                   # (size, text) per line, in reading order
    blocks = []
    for b in d["blocks"]:
        btxt = []
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if spans:
                t = "".join(s["text"] for s in spans).strip()
                lines.append((round(max(s["size"] for s in spans), 1), t))
                btxt.append(t)
        if btxt:
            blocks.append(_clean("\n".join(btxt)))
    title = ""
    for size in sorted({s for s, _ in lines}, reverse=True)[:5]:
        cand = " ".join(t for s, t in lines if s == size)
        if len(cand.split()) >= 5 and not NOT_TITLE.search(cand.strip()):
            title = _flat(_clean(cand))
            break
    return title, blocks


def read_pdf(path: Path) -> tuple[str, str, list[str]]:
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
        title, blocks = _pdf_first_page(doc)
    return _clean(text), title, blocks


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)[0]
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


def _drop_furniture(chunk: str) -> str:
    """Cut each run of footer/header lines (corresponding author, e-mail, DOI, dates, licence,
    with the journal-name lines between them), so the abstract that continues after it joins up."""
    lines = chunk.split("\n")
    hits = [i for i, ln in enumerate(lines) if FURNITURE.search(ln)]
    drop, i = set(), 0
    while i < len(hits):
        j = i
        while j + 1 < len(hits) and hits[j + 1] - hits[j] <= 3:
            j += 1
        if hits[j] - hits[i] <= 15:
            drop.update(range(hits[i], hits[j] + 1))
        i = j + 1
    return "\n".join(ln for k, ln in enumerate(lines) if k not in drop)


def guess_abstract(text: str, limit: int = 2500, blocks: list[str] | None = None,
                   title: str = "") -> str:
    """The Abstract section if there is one; else the first paragraph-like block after the
    title (Nature-style papers have no heading); else the opening of the text."""
    vocab = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)}
    norm = SPACED.sub(lambda m: m.group(0).replace(" ", ""), text)
    m = ABSTRACT[0].search(norm) or ABSTRACT[1].search(norm)
    if m:
        chunk = _drop_furniture(norm[m.end():m.end() + 2 * limit])
        stop = STOP.search(chunk)
        flat = _flat(chunk[:stop.start()] if stop else chunk, vocab)[:limit]
        # a manuscript draft may repeat its title page right after the abstract
        again = re.search(re.escape(title[:30]), flat, re.I) if title else None
        return flat[:again.start()].strip() if again and again.start() > 200 else flat
    if blocks:
        seen_title = not title
        for b in blocks:
            flat = _flat(b, vocab)
            if not seen_title:
                seen_title = title[:40].lower() in flat.lower()
                continue
            if len(flat.split()) >= 60 and not re.search(r"(?i)universit|department|institute", flat):
                return flat[:limit]
    return _flat(text[:limit], vocab)


def load(path: Path, title: str | None = None, abstract: str | None = None) -> dict:
    if path.suffix.lower() == ".pdf":
        text, pdf_title, blocks = read_pdf(path)
        found_title = title or pdf_title or guess_title(text)
    else:
        text, blocks = read_text(path), None
        found_title = title or guess_title(text)
    return {"source": str(path), "title": found_title,
            "abstract": abstract or guess_abstract(text, blocks=blocks, title=found_title),
            "text": text, "chars": len(text)}
