"""Literature search over the index (a hidden feature): DOI lookup, natural-language search,
similar papers, full text, and links to a local folder of PDFs.

  envreview lit pdfs --dir D:\\papers                    once: map a PDF folder (any subfolders)
  envreview lit doi 10.1021/acs.est.4c10919 [DOI ...] [--open]
  envreview lit search "query" ["another query"] [--years 2020-2025] [--journal ES&T] [--top 20]
  envreview lit similar 10.1021/acs.est.4c10919 [--years ...] [--journal ...] [--top 20]
  envreview lit text 10.1016/j.watres.2024.122935 [--out paper.txt]

A PDF belongs to a paper when its file name is the part of the DOI after the first "/"
(10.1021/acs.est.4c10919 -> acs.est.4c10919.pdf), ignoring case; that part is unique across
the index. Water Research and One Earth papers came as publisher XML, so they have full text
(`lit text`) but usually no PDF.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import common as C

PDF_MAP = Path.home() / ".envreview" / "pdf_map.json"
DOI_IN = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")
ABSTRACT_CHARS = 320


def norm_doi(text: str) -> str | None:
    """'https://doi.org/10.1021/ACS.EST.4c10919.' -> '10.1021/acs.est.4c10919'"""
    m = DOI_IN.search(text.strip())
    return m.group(0).rstrip(".,;)]}").lower() if m else None


def years(spec: str | None) -> tuple[int | None, int | None]:
    """'2020-2025', '2020-', '-2019' or '2023' -> (after, before), both inclusive."""
    if not spec:
        return None, None
    m = re.fullmatch(r"\s*(\d{4})?\s*(-)?\s*(\d{4})?\s*", spec)
    if not m or not (m.group(1) or m.group(3)):
        sys.exit(f"--years: use e.g. 2020-2025, 2020-, -2019 or 2023 (got {spec!r})")
    if not m.group(2):
        return int(m.group(1)), int(m.group(1))
    return (int(m.group(1)) if m.group(1) else None), (int(m.group(3)) if m.group(3) else None)


def journal_names(names) -> list[str]:
    js = C.journals()
    return [js[C.resolve_journal(n)]["display_name"] for n in names or []]


# ---------------------------------------------------------------------------- PDFs

def load_pdf_map() -> dict:
    try:
        return json.loads(PDF_MAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pdf_path(doi: str, pdfs: dict) -> Path | None:
    rel = (pdfs.get("files") or {}).get(doi.lower())
    return Path(pdfs["dir"]) / rel if rel else None


def scan_pdfs(ix, folder: Path) -> dict:
    """Map every PDF under `folder` whose name is a DOI suffix in the index; save the map."""
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")
    by_suffix = {d.split("/", 1)[1]: d for d in ix.doi if "/" in d}
    files, foreign, broken = {}, 0, 0
    for root, _, names in os.walk(folder):
        for name in names:
            if not name.lower().endswith(".pdf"):
                continue
            p = Path(root) / name
            doi = by_suffix.get(name[:-4].lower())
            if doi is None:
                foreign += 1
                continue
            if p.stat().st_size < 1000:          # e.g. a saved "service unavailable" page
                broken += 1
                continue
            rel = str(p.relative_to(folder))
            if doi not in files or p.stat().st_size > (folder / files[doi]).stat().st_size:
                files[doi] = rel
    PDF_MAP.parent.mkdir(parents=True, exist_ok=True)
    data = {"dir": str(folder.resolve()), "scanned": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": files}
    PDF_MAP.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    per_journal = {}
    for doi in files:
        j = ix.d.journal_std.iat[ix.row(doi)]
        per_journal[j] = per_journal.get(j, 0) + 1
    return {"folder": data["dir"], "linked_pdfs": len(files), "pdfs_not_in_index": foreign,
            "too_small_skipped": broken, "by_journal": per_journal, "saved_to": str(PDF_MAP)}


def open_file(p: Path) -> None:
    if os.name == "nt":
        os.startfile(str(p))                     # noqa: S606 (the user's own file)
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(p)], check=False)


# ---------------------------------------------------------------------------- output

def _pdf_note(rec, pdfs) -> str:
    p = pdf_path(rec["doi"], pdfs)
    if p is not None:
        return f"PDF: {p}" if p.exists() else f"PDF mapped but not found ({p}); run `lit pdfs` again"
    if not pdfs:
        return "PDF: no PDF folder set (`lit pdfs --dir <folder>`)"
    return "no PDF" + ("; full text: `lit text`" if rec.get("has_fulltext") else "")


def _entry(n, rec, pdfs, extra="", full_abstract=False) -> str:
    ab = (rec.get("abstract") or "").strip()
    if not full_abstract and len(ab) > ABSTRACT_CHARS:
        ab = ab[:ABSTRACT_CHARS].rsplit(" ", 1)[0] + " …"
    lines = [f"{n}. **{rec['title']}**",
             f"   *{rec['journal']}*, {rec['year']} · https://doi.org/{rec['doi']}",
             f"   {rec['category']}{extra} · {_pdf_note(rec, pdfs)}"]
    if ab:
        lines.append(f"   > {ab}")
    return "\n".join(lines)


def _why(rec) -> str:
    paths = {p.split(":")[0] for p in rec.get("why_retrieved", "").split("; ") if p}
    names = {"emb": "meaning", "bm25": "keywords", "phrase": "exact phrase"}
    return " · matched by " + ", ".join(names[p] for p in ("emb", "bm25", "phrase") if p in paths) if paths else ""


def _filters(a) -> str:
    bits = []
    if a.years:
        bits.append(f"years {a.years}")
    if a.journal:
        bits.append(", ".join(journal_names(a.journal)))
    return f" ({'; '.join(bits)})" if bits else ""


# ---------------------------------------------------------------------------- commands

def cmd(a, ix) -> None:
    pdfs = load_pdf_map()
    if a.lit_cmd == "pdfs":
        if not a.dir:
            info = {k: pdfs.get(k) for k in ("dir", "scanned")} if pdfs else {}
            info["linked_pdfs"] = len(pdfs.get("files", {}))
            print(json.dumps(info, ensure_ascii=False, indent=1))
            return
        print(json.dumps(scan_pdfs(ix, Path(a.dir).expanduser()), ensure_ascii=False, indent=1))
        return

    if a.lit_cmd == "doi":
        out = []
        for raw in a.dois:
            doi = norm_doi(raw)
            i = ix.row(doi) if doi else None
            if i is None:
                out.append(f"- `{raw}`: not in the index (it holds research articles from the seven "
                           "journals, 2015–2026)" if doi else f"- `{raw}`: not a DOI")
                continue
            rec = ix.record(i)
            out.append(_entry(len(out) + 1, rec, pdfs, extra=f" · {rec['facets']}", full_abstract=True))
            p = pdf_path(rec["doi"], pdfs)
            if a.open and p is not None and p.exists():
                open_file(p)
        print("\n\n".join(out))
        return

    after, before = years(a.years) if a.lit_cmd in ("search", "similar") else (None, None)
    if a.lit_cmd == "search":
        recs = ix.search(a.queries, a.phrase or [], before=before, after=after,
                         journals=journal_names(a.journal), topk=a.top, per_path=300)
        head = f"## {len(recs)} papers for: " + " / ".join(f'"{q}"' for q in a.queries) + _filters(a)
        if ix.skipped_phrases:
            head += "\n\n(Too common to use as exact phrases: " + ", ".join(
                f'"{p}" ({n} papers)' for p, n in ix.skipped_phrases) + ")"
        body = [_entry(n, r, pdfs, extra=_why(r)) for n, r in enumerate(recs, 1)]
    elif a.lit_cmd == "similar":
        doi = norm_doi(a.doi)
        i = ix.row(doi) if doi else None
        if i is None:
            sys.exit(f"{a.doi} is not in the index.")
        seed = ix.record(i)
        recs = ix.similar(doi, topk=a.top, before=before, after=after, journals=journal_names(a.journal))
        head = (f"## {len(recs)} papers closest in content to: {seed['title']} "
                f"({seed['journal']}, {seed['year']}){_filters(a)}\n\n"
                "Similarity is the cosine between title+abstract embeddings, not citation links.")
        body = [_entry(n, r, pdfs, extra=f" · similarity {r['similarity']:.2f}")
                for n, r in enumerate(recs, 1)]
    elif a.lit_cmd == "text":
        doi = norm_doi(a.doi)
        got = ix.fulltext([doi], max_chars=10 ** 9)[0] if doi else {"found": False}
        if not got.get("found"):
            sys.exit(f"No full text for {a.doi} in the index.")
        out = Path(a.out) if a.out else Path.cwd() / f"{doi.split('/', 1)[1]}.txt"
        out.write_text(f"{got['title']}\n{got['journal']}, {got['year']}\nhttps://doi.org/{got['doi']}\n\n"
                       f"{got['text']}\n", encoding="utf-8")
        print(json.dumps({"doi": got["doi"], "title": got["title"], "chars": got["chars"],
                          "written_to": str(out.resolve())}, ensure_ascii=False, indent=1))
        return
    else:
        sys.exit(f"unknown lit command {a.lit_cmd}")
    if a.json:
        for r in recs:
            p = pdf_path(r["doi"], pdfs)
            r["pdf"] = str(p) if p is not None and p.exists() else None
        print(json.dumps(recs, ensure_ascii=False, indent=1))
    else:
        print(head + "\n\n" + "\n\n".join(body))


def add_parser(sp) -> None:
    p = sp.add_parser("lit", help="literature search: DOI lookup, natural-language search, "
                                  "similar papers, full text, local PDFs")
    lp = p.add_subparsers(dest="lit_cmd", required=True)
    q = lp.add_parser("pdfs", help="map a folder of PDFs named by DOI suffix (no --dir: show)")
    q.add_argument("--dir")
    q = lp.add_parser("doi", help="look up one or more DOIs")
    q.add_argument("dois", nargs="+")
    q.add_argument("--open", action="store_true", help="open the PDF if there is one")
    for name, helptext in (("search", "natural-language search"),
                           ("similar", "papers closest in content to one DOI")):
        q = lp.add_parser(name, help=helptext)
        if name == "search":
            q.add_argument("queries", nargs="+", help="one or more natural-language queries")
            q.add_argument("--phrase", action="append", help="exact phrase that must appear")
        else:
            q.add_argument("doi")
        q.add_argument("--years", help="e.g. 2020-2025, 2020-, -2019, 2023")
        q.add_argument("--journal", action="append", help="limit to a journal (repeatable)")
        q.add_argument("--top", type=int, default=20)
        q.add_argument("--json", action="store_true")
    q = lp.add_parser("text", help="write a paper's full text to a .txt file")
    q.add_argument("doi")
    q.add_argument("--out")
