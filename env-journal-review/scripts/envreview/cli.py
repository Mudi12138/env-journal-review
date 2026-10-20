"""envreview — the command-line half of the env-journal-review skill.

The agent (Claude, Codex, …) does the reading and writing; these commands do everything
mechanical: parse the manuscript, pick the reviewers, search the local index, fetch full texts,
build and check the editor's evidence, and assemble the report. Every command reads and writes
files in one run directory, so any step can be repeated.

  envreview start --input paper.pdf --journal "ES&T" --tag mypaper
  envreview editor-pack    --run DIR --query "..." --query "..." --phrase "..."
  envreview editor-prompt  --run DIR [--journal ID]      -> agent writes editor/<ID>/assessment.json
  envreview editor-decide  --run DIR [--journal ID]
  envreview reviewer-brief --run DIR --seat R1           -> agent writes seats/R1/queries.json
  envreview search         --run DIR --seat R1           -> agent writes seats/R1/screening.json
  envreview fulltext       --run DIR --seat R1           -> agent writes seats/R1/review.md
  envreview check          --run DIR --seat R1
  envreview letter-brief   --run DIR                     -> agent writes decision_letter.md
  envreview profile-brief  --run DIR                     -> agent writes profile_note.md
  envreview report         --run DIR
  envreview index-info [--verify]
  envreview setup                                        -> the skill's own Python environment (once)
  envreview index-download                               -> fetch the index pack (once)
  envreview lit doi|search|similar|text|pdfs ...         -> literature search (see lit.py)

Output is JSON on stdout unless a command prints instructions for the agent.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import common as C
from . import lit
from . import manuscript as M
from . import reviewer_prompts as RP

SEATS = ["R1", "R2", "R3"]
N_SCREEN, N_FULL, MAX_CHARS = 20, 5, 60000
LONG_REPORT = 1400           # words; in testing, longer reports were judged too long to read
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s`\"'<>()\[\]*]+")
DECISION_EN = {"送审": "send out for review", "拒稿": "reject", "校验失败": "validation failed"}
RECS = ["reject and resubmit", "minor revision", "major revision", "acceptance", "rejection",
        "accept", "reject"]

_INDEX = None
# import name -> pip name, as in requirements.txt
NEEDED = {"numpy": "numpy", "pandas": "pandas", "pyarrow": "pyarrow", "scipy": "scipy",
          "torch": "torch", "transformers": "transformers", "fitz": "pymupdf",
          "docx": "python-docx", "jsonschema": "jsonschema", "huggingface_hub": "huggingface_hub"}


def missing_packages() -> list[str]:
    """Packages this Python lacks, plus brotli if it is too old: the HTTP client behind
    huggingface_hub decodes compressed downloads with brotli and fails on brotli < 1.2
    (Anaconda ships 1.0.9), which breaks index-download and the model download."""
    missing = [pip for mod, pip in NEEDED.items() if importlib.util.find_spec(mod) is None]
    if importlib.util.find_spec("brotli") is not None:
        from importlib.metadata import PackageNotFoundError, version
        try:
            v = tuple(int(x) for x in version("brotli").split(".")[:2])
        except (PackageNotFoundError, ValueError):
            v = (0, 0)
        if v < (1, 2):
            missing.append("brotli>=1.2")
    return missing


def check_packages():
    """Fail early, with the install command for *this* interpreter, if a package is missing.

    Hosts often have several Pythons; without this the first sign is a traceback mid-review."""
    missing = missing_packages()
    if missing:
        req = Path(__file__).resolve().parents[2] / "requirements.txt"
        entry = Path(__file__).resolve().parents[1] / "envreview.py"
        sys.exit(f"Missing Python packages for {sys.executable}: {', '.join(missing)}.\n"
                 f"Set up the skill's own environment once (about 1.4 GB, a few minutes):\n"
                 f"  \"{sys.executable}\" \"{entry}\" setup\n"
                 f"or install them into this Python:\n"
                 f"  \"{sys.executable}\" -m pip install -r \"{req}\"")


def index():
    global _INDEX
    if _INDEX is None:
        root = C.index_dir()
        if not (root / "manifest.json").exists():
            sys.exit(f"Index pack not found at {root}. Run `envreview.py index-download` "
                     "(about 690 MB, once), or set ENVREVIEW_INDEX to a folder holding the pack.")
        from .index import LocalIndex
        _INDEX = LocalIndex(root)
    return _INDEX


def editor_mod():
    if str(C.EDITOR) not in sys.path:
        sys.path.insert(0, str(C.EDITOR))
    import editor_v3  # noqa: E402
    return editor_v3


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def say(text: str) -> None:
    print(text.strip() + "\n")


# ---------------------------------------------------------------------------------- start

def cmd_start(a):
    if not Path(a.input).is_file():
        sys.exit(f"Manuscript not found: {Path(a.input).resolve()}")
    run = C.Run(Path(a.out) if a.out else Path.cwd() / "envreview_runs" / a.tag)
    ms = M.load(Path(a.input), a.title,
                Path(a.abstract_file).read_text(encoding="utf-8") if a.abstract_file else None)
    jid = C.resolve_journal(a.journal)
    run.path("manuscript.txt").write_text(ms["text"], encoding="utf-8")
    picked = index().roles(ms["title"], ms["abstract"], exclude=a.exclude)
    if a.topics:
        tx = C.taxonomy()
        picked["roles"] = [{"code": c, "label": tx[c]["label"], "sim": None}
                           for c in a.topics.split(",")]
    state = {"tag": a.tag, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "source": ms["source"], "title": ms["title"], "abstract": ms["abstract"],
             "chars": ms["chars"], "journal_id": jid,
             "journal": C.journals()[jid]["display_name"],
             "before": a.before or date.today().year, "exclude": a.exclude, **picked,
             "seats": {s: {} for s in SEATS}, "editor": {}}
    run.save(state)
    out({k: state[k] for k in ("title", "journal", "before", "roles", "methods")}
        | {"run": str(run.dir), "abstract_preview": state["abstract"][:400]})
    say(f"""
Run directory: {run.dir}
Check that the title and abstract above are right (rerun with --title / --abstract-file if not).
Next: the editor stage (editor-pack) and the three reviewers (reviewer-brief --seat R1..R3).""")


# ---------------------------------------------------------------------------------- editor

def cmd_editor_pack(a):
    run = C.Run(Path(a.run))
    st = run.state
    if a.query:
        run.write_json("editor/queries.json", {"queries": a.query, "phrases": a.phrase or []})
    q = run.read_json("editor/queries.json")
    ix = index()
    wide = ix.search(q["queries"], q.get("phrases", []), before=st["before"],
                     exclude=st["exclude"], topk=100, per_path=300)
    dist = {}
    for h in wide:
        dist[h["journal"]] = dist.get(h["journal"], 0) + 1
    pack = {"id": st["tag"], "title": st["title"], "abstract": st["abstract"],
            "fulltext": run.path("manuscript.txt").read_text(encoding="utf-8"),
            "cutoff_year": st["before"], "excluded_self": st["exclude"],
            "queries": q["queries"], "phrases": q.get("phrases", []),
            "journal_distribution_top100": dist, "hits": wide[:20]}
    run.write_json("editor/pack.json", pack)
    out({"pack": str(run.path("editor/pack.json")), "hits": len(pack["hits"]),
         "top_hits": [f"{h['year']} {h['journal']}: {h['title'][:90]}" for h in pack["hits"][:8]],
         **_skipped(ix)})


def _skipped(ix):
    """Phrases the index ignored because they match too many papers to be an exact-term signal."""
    if not ix.skipped_phrases:
        return {}
    return {"phrases_skipped_as_too_common": [f'"{p}" ({n} papers)' for p, n in ix.skipped_phrases]}


def _editor_inputs(run, jid):
    E = editor_mod()
    registry = E.load_journal_registry(C.EDITOR / "journal_registry.json")
    tiers = E.load_tier_bars(C.EDITOR / "tier_bars.json")
    E.validate_journal_tier_membership(registry, tiers, C.EDITOR / "tier_bars.json")
    journal = registry[jid]
    return E, run.read_json("editor/pack.json"), journal, tiers[journal["tier_id"]]


def cmd_editor_prompt(a):
    run = C.Run(Path(a.run))
    jid = C.resolve_journal(a.journal) if a.journal else run.state["journal_id"]
    E, pack, journal, tier = _editor_inputs(run, jid)
    messages, meta = E.build_decision_messages(pack, journal, tier)
    d = f"editor/{jid}"
    run.path(f"{d}/system.md").write_text(messages[0]["content"], encoding="utf-8")
    run.path(f"{d}/user.md").write_text(messages[1]["content"], encoding="utf-8")
    run.write_json(f"{d}/schema.json", E.ASSESSMENT_SCHEMA["schema"])
    run.write_json(f"{d}/meta.json", meta)
    say(f"""
EDITOR TASK — {journal['display_name']} ({journal['tier_id']})
Read {run.path(d, 'system.md')} as your instructions and {run.path(d, 'user.md')} as the material.
Write ONE JSON object, valid against {run.path(d, 'schema.json')}, to {run.path(d, 'assessment.json')}.
You give evidence on five axes only; the decision is derived by the next command. Then run:
  envreview editor-decide --run "{run.dir}" --journal {jid}""")


def cmd_editor_decide(a):
    run = C.Run(Path(a.run))
    jid = C.resolve_journal(a.journal) if a.journal else run.state["journal_id"]
    E, pack, journal, tier = _editor_inputs(run, jid)
    d = f"editor/{jid}"
    try:
        assessment = run.read_json(f"{d}/assessment.json")
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        sys.exit(f"cannot read {d}/assessment.json: {exc}")
    import jsonschema
    try:
        jsonschema.validate(assessment, E.ASSESSMENT_SCHEMA["schema"])
        E.validate_assessment(assessment, pack, journal, tier)
        decision = E.derive_decision(assessment)
    except (jsonschema.ValidationError, ValueError) as exc:
        msg = getattr(exc, "message", None) or str(exc)
        print(json.dumps({"valid": False, "errors": msg}, ensure_ascii=False, indent=1))
        say("Fix assessment.json so that it meets these rules (quotes must be copied verbatim), "
            "then run editor-decide again.")
        sys.exit(2)
    decision["decision_en"] = DECISION_EN.get(decision["decision"], decision["decision"])
    run.write_json(f"{d}/decision.json", decision)
    st = run.state
    st["editor"][jid] = {"decision": decision["decision_en"],
                         "blocking_axes": decision.get("blocking_axes", []),
                         "verdicts": {ax: assessment[ax]["verdict"] for ax in assessment}}
    run.save(st)
    out({"journal": journal["display_name"], **st["editor"][jid]})


# ---------------------------------------------------------------------------------- reviewers

def role_text(st, seat):
    tx = C.taxonomy()
    codes = [r["code"] for r in st["roles"]]
    me = codes[SEATS.index(seat)]
    others = [f"{c} {tx[c]['label']}" for c in codes if c != me]
    covers = tx[me]["covers"][0].lower() + tx[me]["covers"][1:]
    return RP.ROLE.format(label=tx[me]["label"], covers=covers,
                          methods="; ".join(st["methods"]) or "the methods described in it",
                          other_1=others[0], other_2=others[1])


def cmd_reviewer_brief(a):
    run = C.Run(Path(a.run))
    st = run.state
    d = f"seats/{a.seat}"
    say(f"""
REVIEWER {a.seat} — step 1 of 3: search queries
{RP.QUERY_SYS.format(journal=st['journal'], role=role_text(st, a.seat))}

The manuscript is {run.path('manuscript.txt')}.
Write {{"queries": [...], "phrases": [...]}} to {run.path(d, 'queries.json')}, then run:
  envreview search --run "{run.dir}" --seat {a.seat}""")


def _cands_block(cands, screen=None):
    marks = {p["doi"].lower(): p for p in (screen or {}).get("papers", [])}
    full = {x.lower() for x in (screen or {}).get("read_in_full", [])}
    rows = []
    for i, c in enumerate(cands, 1):
        m = marks.get(c["doi"].lower())
        head = f"[{i}] DOI {c['doi']} | {c['year']} | {c['journal']}"
        if m:
            head += f" | your label: {m['label']}" + (" | read in full" if c["doi"].lower() in full else "")
        body = f"TITLE: {c['title']}\nABSTRACT: {c['abstract'] or '(no abstract)'}"
        if m:
            body += f"\nYOUR NOTE: {m['note']}"
        rows.append(f"{head}\n{body}")
    return "\n\n".join(rows)


def cmd_search(a):
    run = C.Run(Path(a.run))
    st = run.state
    d = f"seats/{a.seat}"
    q = run.read_json(f"{d}/queries.json")
    ix = index()
    ranked = ix.search(q["queries"], q.get("phrases", []), before=st["before"],
                       exclude=st["exclude"], topk=60, per_path=300)
    if ix.skipped_phrases:
        say("Note: " + "; ".join(_skipped(ix)["phrases_skipped_as_too_common"])
            + " matched too many papers and were left out of the exact-term search.")
    cands = [h for h in ranked if h["has_fulltext"]][:N_SCREEN]
    run.write_json(f"{d}/candidates.json", cands)
    run.path(d, "candidates.md").write_text(_cands_block(cands), encoding="utf-8")
    run.write_json(f"{d}/screening.schema.json", RP.SCREEN_SCHEMA["schema"])
    say(f"""
REVIEWER {a.seat} — step 2 of 3: screen {len(cands)} abstracts
{RP.SCREEN_SYS.format(journal=st['journal'], role=role_text(st, a.seat), n=len(cands), before=st['before'])}

Manuscript: {run.path('manuscript.txt')}
Titles and abstracts to screen: {run.path(d, 'candidates.md')}
Write one JSON object valid against {run.path(d, 'screening.schema.json')} to
{run.path(d, 'screening.json')}, then run:
  envreview fulltext --run "{run.dir}" --seat {a.seat}""")


def cmd_fulltext(a):
    run = C.Run(Path(a.run))
    st = run.state
    d = f"seats/{a.seat}"
    cands = run.read_json(f"{d}/candidates.json")
    screen = run.read_json(f"{d}/screening.json")
    import jsonschema
    jsonschema.validate(screen, RP.SCREEN_SCHEMA["schema"])
    known = {c["doi"].lower(): c["doi"] for c in cands}
    chosen = list(dict.fromkeys(known[x.lower()] for x in screen["read_in_full"]
                                if x.lower() in known))[:N_FULL]
    screen["read_in_full"] = chosen
    run.write_json(f"{d}/screening.json", screen)
    texts = [t for t in index().fulltext(chosen, max_chars=MAX_CHARS) if t.get("found")]
    run.path(d, "screening_table.md").write_text(
        f"Truly similar: {screen['n_truly_similar']}. {screen['novelty_note']}\n\n"
        + _cands_block(cands, screen), encoding="utf-8")
    run.path(d, "fulltexts.md").write_text("\n\n".join(
        f"---\n[{i + 1}] DOI {t['doi']} | {t['year']} | {t['journal']}\nTITLE: {t['title']}\n\n{t['text']}"
        for i, t in enumerate(texts)) or "(none chosen)", encoding="utf-8")
    qs = "\n".join(f"  - {x}" for x in run.read_json(f"{d}/queries.json")["queries"])
    say(f"""
REVIEWER {a.seat} — step 3 of 3: write the report
{RP.REVIEW_SYS.format(journal=st['journal'], role=role_text(st, a.seat), n_screened=len(cands),
                      n_full=len(texts), queries=qs, before=st['before'])}

Manuscript: {run.path('manuscript.txt')}
Your screening table: {run.path(d, 'screening_table.md')}
The papers you read in full: {run.path(d, 'fulltexts.md')}
Write the report (Markdown) to {run.path(d, 'review.md')}, then run:
  envreview check --run "{run.dir}" --seat {a.seat}""")


def recommendation(report):
    para = report.strip().split("\n\n")[0].lower()
    m = re.search(r"recommend\s+(?:a\s+|an\s+)?([a-z ]+?)[.\n]", para)
    found = m.group(1) if m else para
    for r in RECS:
        if r in found:
            return {"accept": "acceptance", "reject": "rejection"}.get(r, r)
    return "?"


def cmd_check(a):
    run = C.Run(Path(a.run))
    st = run.state
    d = f"seats/{a.seat}"
    report = run.path(d, "review.md").read_text(encoding="utf-8")
    cands = {c["doi"].lower(): c["doi"] for c in run.read_json(f"{d}/candidates.json")}
    full = {x.lower() for x in run.read_json(f"{d}/screening.json")["read_in_full"]}
    found = sorted({x.rstrip(".,;:").lower() for x in DOI_RE.findall(report)})
    res = {"recommendation": recommendation(report),
           "cited": [cands[x] for x in found if x in cands],
           "cited_abstract_only": [cands[x] for x in found if x in cands and x not in full],
           "cited_outside_screening": [x for x in found if x not in cands],
           "words": len(report.split())}
    st["seats"][a.seat] = res
    run.save(st)
    out(res)
    if res["cited_outside_screening"]:
        say("WARNING: the report cites DOIs that were not in this reviewer's screening table. "
            "Remove them or replace them with screened papers.")
    if res["recommendation"] == "?":
        say('WARNING: no recommendation found; the first paragraph must end "I therefore recommend X."')
    if res["words"] > LONG_REPORT:
        say(f"NOTE: the report is {res['words']} words; readers take in about {LONG_REPORT} in the few "
            "minutes they give a review. Consider one tightening pass: where a comment asks for "
            "several changes, keep the one or two that matter most, and cut repeated context. Then "
            "run check again. Do not drop a problem that affects the conclusions to save words.")


# ---------------------------------------------------------------------------------- editor letter

def cmd_letter_brief(a):
    run = C.Run(Path(a.run))
    st = run.state
    tx = C.taxonomy()
    parts = []
    for i, (s, r) in enumerate(zip(SEATS, st["roles"]), 1):
        p = run.path("seats", s, "review.md")
        if not p.exists():
            sys.exit(f"reviewer {s} has no report yet ({p})")
        parts.append(f"# Reviewer {i} ({tx[r['code']]['label']})\n\n{p.read_text(encoding='utf-8')}")
    run.path("letter_input.md").write_text(f"# Manuscript: {st['title']}\n\n" + "\n\n".join(parts),
                                            encoding="utf-8")
    say(f"""
EDITOR'S DECISION LETTER
{RP.LETTER_SYS.format(journal=st['journal'])}

The three reports: {run.path('letter_input.md')}
Write the letter (Markdown) to {run.path('decision_letter.md')}.""")


EN = {"稳定": "stable", "下降": "declining", "上升": "rising", "不可用": "not available",
      "充分": "sufficient", "有限": "limited", "不足": "insufficient", "不适用": "not applicable",
      "较低": "low", "中等": "medium", "较高": "high", "仅展示": "display only"}


def journal_profile(journal_name, codes):
    with open(C.ASSETS / "journal_topic_profiles.csv", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r["journal"].lower() == journal_name.lower() and r["category"] in codes]
    res = []
    for code in codes:
        r = next((x for x in rows if x["category"] == code), None)
        if r is None:
            continue
        res.append({
            "topic": f"{code} {r['category_label']}",
            "recent_papers_2023_2025": int(r["recent_count"]),
            "share_of_journal_research_articles_per_100": round(float(r["recent_share_per100"]), 2),
            "share_trend_vs_2020_2022": EN.get(r["trend_label"], r["trend_label"]),
            "share_relative_to_the_other_six_journals": EN.get(r["pressure_band"], r["pressure_band"]),
            "citation_percentile_within_journal_and_year_2019_2023":
                round(float(r["citation_score"]), 1) if r["citation_score"] else None,
            "citation_papers": int(float(r["citation_n"] or 0)),
            "citation_evidence": EN.get(r["citation_evidence"], r["citation_evidence"]),
            "note": "citation percentile 50 = median paper of the same journal and year"})
    return res


def cmd_profile_brief(a):
    run = C.Run(Path(a.run))
    st = run.state
    rows = journal_profile(st["journal"], [r["code"] for r in st["roles"]])
    if not rows:
        sys.exit(f"no profile data for {st['journal']}")
    run.path("profile_input.md").write_text(
        f"# Manuscript\n\nTitle: {st['title']}\n\nAbstract: {st['abstract']}\n\n"
        f"# Publication record of {st['journal']} for the manuscript's topics\n\n"
        + json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"""
EDITOR'S NOTE ON THE JOURNAL PROFILE — write this without looking at the reviews or the decision
{RP.PROFILE_SYS.format(journal=st['journal'])}

Material: {run.path('profile_input.md')}
Write the note (Markdown, a few sentences) to {run.path('profile_note.md')}.""")


# ---------------------------------------------------------------------------------- report

def cmd_report(a):
    from .report import build
    run = C.Run(Path(a.run))
    p = build(run)
    out({"report": str(p)})


def cmd_index_info(a):
    ix = index()
    info = {k: ix.manifest[k] for k in ("name", "version", "papers", "with_abstract",
                                         "with_fulltext", "journals", "years")}
    info["location"] = str(ix.root)
    if a.verify:
        from .index_tools import verify
        info["verify"] = verify(ix.root, ix.manifest)
    out(info)


def cmd_index_download(a):
    """Fetch the index pack from Hugging Face into the index folder, then verify every file."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("Needs huggingface_hub: pip install -r requirements.txt")
    from .index_tools import verify
    dest = C.index_dir()
    say(f"Downloading {C.HF_REPO} ({C.HF_REVISION}, about 690 MB) to {dest}. "
        "An interrupted download resumes when you run this again.")
    snapshot_download(repo_id=C.HF_REPO, repo_type="dataset", revision=C.HF_REVISION,
                      local_dir=dest, allow_patterns=["manifest.json", "*.parquet", "*.npy",
                                                      "*.npz", "*.json", "*.sqlite"])
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    res = verify(dest, manifest)
    out({"location": str(dest), "papers": manifest["papers"], "verify": res})
    if not res["ok"]:
        sys.exit("Some files do not match the manifest; run index-download again.")


def cmd_api_run(a):
    from .api import run
    run(a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="envreview", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("start", help="parse the manuscript, pick the three reviewers")
    p.add_argument("--input", required=True, help="manuscript: .pdf, .docx, .txt or .md")
    p.add_argument("--journal", required=True, help="target journal (name, id or abbreviation)")
    p.add_argument("--tag", required=True, help="short name for this run")
    p.add_argument("--out", help="run directory (default ./envreview_runs/<tag>)")
    p.add_argument("--title")
    p.add_argument("--abstract-file")
    p.add_argument("--before", type=int, help="only use literature up to this year")
    p.add_argument("--exclude", nargs="*", default=[], help="DOIs kept out of retrieval")
    p.add_argument("--topics", help="override the reviewer topics, e.g. D1,C7,I5")

    p = sp.add_parser("editor-pack")
    p.add_argument("--run", required=True)
    p.add_argument("--query", action="append")
    p.add_argument("--phrase", action="append")
    for name in ("editor-prompt", "editor-decide"):
        p = sp.add_parser(name)
        p.add_argument("--run", required=True)
        p.add_argument("--journal")
    for name in ("reviewer-brief", "search", "fulltext", "check"):
        p = sp.add_parser(name)
        p.add_argument("--run", required=True)
        p.add_argument("--seat", required=True, choices=SEATS)
    for name in ("letter-brief", "profile-brief", "report"):
        p = sp.add_parser(name)
        p.add_argument("--run", required=True)
    p = sp.add_parser("index-info")
    p.add_argument("--verify", action="store_true")
    sp.add_parser("index-download", help="fetch and verify the index pack (about 690 MB, once)")
    sp.add_parser("setup", help="create ~/.envreview/venv with the required packages (once)")
    lit.add_parser(sp)
    p = sp.add_parser("api-run", help="run every step with a model API (estimate unless --yes)")
    p.add_argument("--input", required=True)
    p.add_argument("--journal", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--model", default="gpt-5.6-sol",
                   help="gpt-5.6-sol (OPENAI_API_KEY) or deepseek-v4-pro / deepseek-flash "
                        "(DEEPSEEK_API_KEY)")
    p.add_argument("--yes", action="store_true", help="actually run (paid)")
    p.add_argument("--out")
    p.add_argument("--title")
    p.add_argument("--abstract-file")
    p.add_argument("--before", type=int)
    p.add_argument("--exclude", nargs="*", default=[])
    p.add_argument("--topics")

    a = ap.parse_args(argv)
    check_packages()
    {"start": cmd_start, "editor-pack": cmd_editor_pack, "editor-prompt": cmd_editor_prompt,
     "editor-decide": cmd_editor_decide, "reviewer-brief": cmd_reviewer_brief,
     "search": cmd_search, "fulltext": cmd_fulltext, "check": cmd_check,
     "letter-brief": cmd_letter_brief, "profile-brief": cmd_profile_brief,
     "report": cmd_report, "index-info": cmd_index_info, "index-download": cmd_index_download,
     "setup": lambda a: sys.exit("Run setup as: python scripts/envreview.py setup"),
     "lit": lambda a: lit.cmd(a, index()),
     "api-run": cmd_api_run}[a.cmd](a)


if __name__ == "__main__":
    main()
