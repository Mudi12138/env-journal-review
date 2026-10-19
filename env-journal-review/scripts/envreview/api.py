"""API mode: run the whole review with a model API instead of the host agent.

Same prompts, retrieval, validation and outputs as the agent workflow; every step that the
agent would do is one model call here. Providers: OpenAI (OPENAI_API_KEY) and DeepSeek
(DEEPSEEK_API_KEY). Without --yes it only prints a cost estimate.

  python scripts/envreview.py api-run --input paper.pdf --journal "Water Research" \
      --tag mypaper --model gpt-5.6-sol [--yes]
"""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cli
from . import common as C
from . import reviewer_prompts as RP

# USD per million tokens (input, output); DeepSeek at peak price (upper bound)
PRICES = {"gpt-5.6-sol": (4.0, 20.0), "deepseek-v4-pro": (1.32, 3.96), "deepseek-flash": (0.30, 1.20)}

EDITOR_QUERY_SYS = """You are the handling editor at {journal}. Before judging a submission you
search the journal-level literature for the work closest to what it claims as new.

Write two or three search queries in English, as natural-language sentences, and three to six
precise terms for an exact-match search (a generic term found in hundreds of abstracts is ignored). They will be run against the titles and abstracts of
about 40,000 research papers from seven leading environmental journals."""


def _client(model):
    E = cli.editor_mod()
    provider = E.provider_for(model)
    return E, E.make_client(provider), provider


def call_json(model, system, user, schema):
    E, client, provider = _client(model)
    data, usage = E._call_structured(client, model, "medium",
                                     [{"role": "system", "content": system},
                                      {"role": "user", "content": user}], schema, provider)
    return data, usage


def call_text(model, system, user):
    E, client, provider = _client(model)
    kw = {"model": model, "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]}
    if E.PROVIDERS[provider]["reasoning_effort"]:
        kw["reasoning_effort"] = "high"
    r = client.chat.completions.create(**kw)
    return r.choices[0].message.content.strip(), E._usage_dict(r)


def estimate(chars, model):
    """Rough token budget: the manuscript is read ~13 times, plus abstracts and full texts."""
    ms = chars / 4
    tin = ms * 13 + 3 * (8_000 + 5 * 15_000) + 30_000
    tout = 60_000
    pin, pout = PRICES.get(model, (4.0, 20.0))
    return {"input_tokens": int(tin), "output_tokens": tout,
            "usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 2)}


def run(a):
    from . import manuscript as M
    chars = len(M.read_text(Path(a.input)))
    est = estimate(chars, a.model)
    print(json.dumps({"model": a.model, "estimate": est}, indent=1))
    if not a.yes:
        print("Estimate only. Add --yes to run.")
        return
    usage = []

    def log(u):
        usage.append((u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))

    cli.cmd_start(Namespace(input=a.input, journal=a.journal, tag=a.tag, out=a.out, title=a.title,
                            abstract_file=a.abstract_file, before=a.before, exclude=a.exclude,
                            topics=a.topics))
    run_dir = Path(a.out) if a.out else Path.cwd() / "envreview_runs" / a.tag
    run = C.Run(run_dir)
    st = run.state
    text = run.path("manuscript.txt").read_text(encoding="utf-8")
    manuscript = f"# Manuscript: {st['title']}\n\n{text}"

    # editor: queries -> pack -> five-axis evidence -> mechanical decision
    q, u = call_json(a.model, EDITOR_QUERY_SYS.format(journal=st["journal"]), manuscript,
                     RP.QUERY_SCHEMA)
    log(u)
    cli.cmd_editor_pack(Namespace(run=str(run_dir), query=q["queries"], phrase=q["phrases"]))
    E, pack, journal, tier = cli._editor_inputs(run, st["journal_id"])
    res = E.execute({st["tag"]: pack}, {st["journal_id"]: journal}, {tier["tier_id"]: tier},
                    a.model, "high", 1, None, run.dir / "editor" / "api",
                    E.provider_for(a.model), 5)
    rec = next(iter(res["results"].values()), None)
    if rec:
        log(rec["usage"])
        run.write_json(f"editor/{st['journal_id']}/assessment.json", rec["assessment"])
        if rec["decision"]["decision"] != "校验失败":
            cli.cmd_editor_decide(Namespace(run=str(run_dir), journal=None))

    # three reviewers in parallel; each seat runs its own three calls
    def seat(s):
        role = cli.role_text(st, s)
        q, u1 = call_json(a.model, RP.QUERY_SYS.format(journal=st["journal"], role=role),
                          manuscript, RP.QUERY_SCHEMA)
        run.write_json(f"seats/{s}/queries.json", q)
        _quiet(cli.cmd_search, Namespace(run=str(run_dir), seat=s))
        cands = run.read_json(f"seats/{s}/candidates.json")
        sc, u2 = call_json(a.model, RP.SCREEN_SYS.format(journal=st["journal"], role=role,
                                                         n=len(cands), before=st["before"]),
                           f"{manuscript}\n\n# Titles and abstracts to screen\n\n"
                           + cli._cands_block(cands), RP.SCREEN_SCHEMA)
        run.write_json(f"seats/{s}/screening.json", sc)
        _quiet(cli.cmd_fulltext, Namespace(run=str(run_dir), seat=s))
        sc = run.read_json(f"seats/{s}/screening.json")
        full = run.path(f"seats/{s}/fulltexts.md").read_text(encoding="utf-8")
        sysmsg = RP.REVIEW_SYS.format(journal=st["journal"], role=role, n_screened=len(cands),
                                      n_full=len(sc["read_in_full"]), before=st["before"],
                                      queries="\n".join(f"  - {x}" for x in q["queries"]))
        user = (f"{manuscript}\n\n# Your screening of {len(cands)} papers\n\n"
                + run.path(f"seats/{s}/screening_table.md").read_text(encoding="utf-8")
                + f"\n\n# The papers you read in full\n\n{full}")
        rep, u3 = call_text(a.model, sysmsg, user)
        run.path(f"seats/{s}/report.md").write_text(rep + "\n", encoding="utf-8")
        return [u1, u2, u3]

    with ThreadPoolExecutor(3) as ex:
        for us in ex.map(seat, cli.SEATS):
            for x in us:
                log(x)
    for s in cli.SEATS:
        cli.cmd_check(Namespace(run=str(run_dir), seat=s))

    _quiet(cli.cmd_letter_brief, Namespace(run=str(run_dir)))
    letter, u = call_text(a.model, RP.LETTER_SYS.format(journal=st["journal"]),
                          run.path("letter_input.md").read_text(encoding="utf-8"))
    log(u)
    run.path("decision_letter.md").write_text(letter + "\n", encoding="utf-8")
    try:
        _quiet(cli.cmd_profile_brief, Namespace(run=str(run_dir)))
        note, u = call_text(a.model, RP.PROFILE_SYS.format(journal=st["journal"]),
                            run.path("profile_input.md").read_text(encoding="utf-8"))
        log(u)
        run.path("profile_note.md").write_text(note + "\n", encoding="utf-8")
    except SystemExit:
        pass
    cli.cmd_report(Namespace(run=str(run_dir)))
    tin, tout = sum(x for x, _ in usage), sum(y for _, y in usage)
    pin, pout = PRICES.get(a.model, (4.0, 20.0))
    print(json.dumps({"calls": len(usage), "input_tokens": tin, "output_tokens": tout,
                      "usd_approx": round(tin / 1e6 * pin + tout / 1e6 * pout, 2)}, indent=1))


def _quiet(fn, ns):
    """Run a CLI step whose printed agent instructions are not needed in API mode."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        fn(ns)
