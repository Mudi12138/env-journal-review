"""Assemble everything in a run directory into one report for the author (report.md)."""
from __future__ import annotations

import json
import re

from . import common as C

AXES = [("scope_fit", "Scope fit"), ("genre_fit", "Article type"),
        ("novelty_increment", "Novelty vs. prior work"), ("significance", "Significance"),
        ("novelty_magnitude", "Size of the advance")]
MARK = {"pass": "pass", "warn": "warn", "block": "**block**"}
# screening labels that mean "close to this manuscript", most specific first
CLOSE = {"direct_precedent": "does what the manuscript claims",
         "same_method_other_object": "same method, other object",
         "same_object_other_method": "same object, other method"}
HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$", re.M)
MAJOR = re.compile(r"^[ \t]*(?:\*\*)?Major Comments:?(?:\*\*)?[ \t]*$", re.M | re.I)


def _read(run, *parts):
    p = run.dir.joinpath(*parts)
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _embed(text):
    """Agent-written text sits under the report's own headings, so its headings become bold lines."""
    return MAJOR.sub("**Major Comments**", HEADING.sub(r"**\1**", text))


def _who(nums):
    if len(nums) == 3:
        return "all three reviewers"
    return ("Reviewer " if len(nums) == 1 else "Reviewers ") + " and ".join(map(str, nums))


def build(run: C.Run):
    st = run.state
    tx = C.taxonomy()
    L = [f"# Pre-submission review: {st['title']}", "",
         f"Target journal: **{st['journal']}**  ", f"Literature considered: published up to {st['before']}  ",
         f"Generated: {st['created'][:10]}", "",
         "> This report is written by AI editors and reviewers working from a fixed corpus of seven "
         "environmental journals. It is meant to help you prepare the submission; it is not a "
         "prediction of the editorial outcome.", ""]

    # 1. at a glance
    L += ["## At a glance", "", "| | Verdict |", "|---|---|"]
    for jid, e in st.get("editor", {}).items():
        why = f" ({', '.join(e['blocking_axes'])})" if e.get("blocking_axes") else ""
        L.append(f"| Editor, {C.journals()[jid]['display_name']} | {e['decision']}{why} |")
    for i, (s, r) in enumerate(zip(["R1", "R2", "R3"], st["roles"]), 1):
        rec = st["seats"].get(s, {}).get("recommendation", "—")
        L.append(f"| Reviewer {i} ({tx[r['code']]['label']}) | {rec} |")
    L.append("")

    letter = _read(run, "decision_letter.md")
    if letter:
        L += ["## Editor's letter", "", _embed(letter), ""]
    note = _read(run, "profile_note.md")
    if note:
        L += ["### The journal's record for these topics (reference only)", "", _embed(note), ""]

    # 2. novelty: the closest papers across the three reviewers, then each reviewer's reading
    L += ["## How new is the work?", "",
          "Each reviewer screened the 20 closest papers in the corpus, counted those that already "
          "do what the manuscript does, and read the most relevant in full.", ""]
    close, notes = {}, []
    for i, s in enumerate(["R1", "R2", "R3"], 1):
        d = run.dir / "seats" / s
        if not (d / "screening.json").exists():
            continue
        sc = json.loads((d / "screening.json").read_text(encoding="utf-8"))
        cands = {c["doi"].lower(): c for c in json.loads(
            (d / "candidates.json").read_text(encoding="utf-8"))}
        full = {x.lower() for x in sc["read_in_full"]}
        notes.append(f"**Reviewer {i}** — truly similar: {sc['n_truly_similar']} of {len(cands)}. "
                     f"{sc['novelty_note'].strip()}")
        for x in sc["papers"]:
            k = x["doi"].lower()
            if x["label"] in CLOSE and k in cands:
                e = close.setdefault(k, {"paper": cands[k], "by": [], "full": [], "labels": []})
                e["by"].append(i)
                e["labels"].append(x["label"])
                if k in full:
                    e["full"].append(i)
    if close:
        L += ["**Closest published work**", ""]
        order = list(CLOSE)
        for e in sorted(close.values(), key=lambda e: (min(map(order.index, e["labels"])),
                                                       -len(e["by"]), -len(e["full"]))):
            c = e["paper"]
            kind = CLOSE[order[min(map(order.index, e["labels"]))]]
            read = f"; read in full by {len(e['full'])}" if e["full"] else ""
            L += [f"- {c['title']} — *{c['journal']}*, {c['year']}, `{c['doi']}`  ",
                  f"  {kind} (flagged by {_who(e['by'])}{read})"]
        L.append("")
    for n in notes:
        L += [n, ""]

    # 3. editor screening: verdicts first, reasons below
    if st.get("editor"):
        L += ["## Editor's screening", ""]
        for jid in st["editor"]:
            a = json.loads((run.dir / "editor" / jid / "assessment.json").read_text(encoding="utf-8"))
            L += [f"### {C.journals()[jid]['display_name']} — {st['editor'][jid]['decision']}", "",
                  "| Axis | Verdict |", "|---|---|"]
            L += [f"| {label} | {MARK.get(a[k]['verdict'], a[k]['verdict'])} |"
                  for k, label in AXES if k in a]
            L.append("")
            for k, label in AXES:
                if k in a and (a[k].get("rationale") or "").strip():
                    L += [f"**{label}** ({a[k]['verdict']}). {a[k]['rationale'].strip()}", ""]

    # 4. reviews
    L += ["## Reviewer reports", ""]
    for i, (s, r) in enumerate(zip(["R1", "R2", "R3"], st["roles"]), 1):
        rep = _read(run, "seats", s, "review.md")
        if rep:
            L += [f"### Reviewer {i} — {tx[r['code']]['label']}", "", _embed(rep), ""]

    # appendix
    L += ["## Appendix: the literature each reviewer used", ""]
    for i, s in enumerate(["R1", "R2", "R3"], 1):
        d = run.dir / "seats" / s
        if not (d / "screening.json").exists():
            continue
        q = json.loads((d / "queries.json").read_text(encoding="utf-8"))
        sc = json.loads((d / "screening.json").read_text(encoding="utf-8"))
        cands = json.loads((d / "candidates.json").read_text(encoding="utf-8"))
        labels = {x["doi"].lower(): x["label"].replace("_", " ") for x in sc["papers"]}
        full = {x.lower() for x in sc["read_in_full"]}
        cited = {x.lower() for x in st["seats"].get(s, {}).get("cited", [])}
        L += [f"### Reviewer {i}", "", "Queries: " + " · ".join(q["queries"]), "",
              "| # | Paper | Label | Read in full | Cited |", "|---|---|---|---|---|"]
        for j, c in enumerate(cands, 1):
            k = c["doi"].lower()
            title = c["title"].replace("|", "/")
            L.append(f"| {j} | {title} ({c['journal']}, {c['year']}, `{c['doi']}`) | "
                     f"{labels.get(k, '')} | {'yes' if k in full else ''} | {'yes' if k in cited else ''} |")
        L.append("")
    p = run.dir / "report.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p
