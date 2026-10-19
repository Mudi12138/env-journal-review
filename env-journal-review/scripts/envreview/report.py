"""Assemble everything in a run directory into one report for the author (report.md)."""
from __future__ import annotations

import json

from . import common as C

AXES = [("scope_fit", "Scope fit"), ("genre_fit", "Article type"),
        ("novelty_increment", "Novelty vs. prior work"), ("significance", "Significance"),
        ("novelty_magnitude", "Size of the advance")]
MARK = {"pass": "pass", "warn": "warn", "block": "**block**"}


def _read(run, *parts):
    p = run.dir.joinpath(*parts)
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


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
        L += ["## Editor's letter", "", letter, ""]
    note = _read(run, "profile_note.md")
    if note:
        L += ["### The journal's record for these topics (reference only)", "", note, ""]

    # 2. novelty
    L += ["## How new is the work?", "",
          "Each reviewer screened the 20 closest papers in the corpus and counted those doing "
          "essentially the same thing.", ""]
    for i, s in enumerate(["R1", "R2", "R3"], 1):
        p = run.dir / "seats" / s / "screening.json"
        if not p.exists():
            continue
        sc = json.loads(p.read_text(encoding="utf-8"))
        cands = {c["doi"].lower(): c for c in json.loads(
            (run.dir / "seats" / s / "candidates.json").read_text(encoding="utf-8"))}
        L += [f"**Reviewer {i}** — truly similar: {sc['n_truly_similar']} of {len(cands)}. "
              f"{sc['novelty_note']}", ""]
        for x in sc["papers"]:
            if x["label"] == "direct_precedent" and x["doi"].lower() in cands:
                c = cands[x["doi"].lower()]
                L.append(f"- {c['title']} ({c['journal']}, {c['year']}, `{c['doi']}`) — {x['note']}")
        L.append("")

    # 3. editor screening
    if st.get("editor"):
        L += ["## Editor's screening", ""]
        for jid in st["editor"]:
            a = json.loads((run.dir / "editor" / jid / "assessment.json").read_text(encoding="utf-8"))
            L += [f"### {C.journals()[jid]['display_name']} — {st['editor'][jid]['decision']}", "",
                  "| Axis | Verdict | Reason |", "|---|---|---|"]
            for k, label in AXES:
                if k in a:
                    reason = (a[k].get("rationale") or "").replace("\n", " ").replace("|", "/")
                    L.append(f"| {label} | {MARK.get(a[k]['verdict'], a[k]['verdict'])} | {reason} |")
            L.append("")

    # 4. reviews
    L += ["## Reviewer reports", ""]
    for i, (s, r) in enumerate(zip(["R1", "R2", "R3"], st["roles"]), 1):
        rep = _read(run, "seats", s, "review.md")
        if rep:
            L += [f"### Reviewer {i} — {tx[r['code']]['label']}", "", rep, ""]

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
            L.append(f"| {j} | {c['title'][:90]} ({c['journal']}, {c['year']}, `{c['doi']}`) | "
                     f"{labels.get(k, '')} | {'yes' if k in full else ''} | {'yes' if k in cited else ''} |")
        L.append("")
    p = run.dir / "report.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p
