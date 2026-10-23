"""API mode: run the whole review with a model API instead of the host agent.

Same prompts, retrieval, validation and outputs as the agent workflow; every step that the
agent would do is one model call here. Providers: OpenAI, Claude, Gemini, DeepSeek, Qwen,
Doubao, Kimi, GLM, OpenRouter, Ollama, or any OpenAI-compatible endpoint (see providers.py).
Without --yes it only prints a cost estimate.

  python scripts/envreview.py api-check --list                       # providers and keys found
  python scripts/envreview.py api-check --provider deepseek          # is the key/model usable?
  python scripts/envreview.py api-run --input paper.pdf --journal "Water Research"       --tag mypaper --provider deepseek [--model deepseek-v4-pro] [--letter] [--yes]
"""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cli
from . import common as C
from . import providers as P
from . import reviewer_prompts as RP

# USD per million tokens (input, output); DeepSeek at peak price (upper bound)
PRICES = {"gpt-5.6-sol": (4.0, 20.0), "deepseek-v4-pro": (1.32, 3.96), "deepseek-flash": (0.30, 1.20)}

EDITOR_QUERY_SYS = """You are the handling editor at {journal}. Before judging a submission you
search the journal-level literature for the work closest to what it claims as new.

Write two or three search queries in English, as natural-language sentences, and three to six
precise terms for an exact-match search (a generic term found in hundreds of abstracts is ignored). They will be run against the titles and abstracts of
about 40,000 research papers from seven leading environmental journals."""


# set by run() / check(): the provider every call in this process uses
PROVIDER = {"name": None}


def _client(model):
    E = cli.editor_mod()
    P.install(E, PROVIDER.get("max_tokens"))
    provider = PROVIDER["name"] or P.resolve(None, model)[0]
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
    if not getattr(r, "choices", None) or not r.choices[0].message.content:
        raise RuntimeError(f"{provider} returned an empty answer")
    return r.choices[0].message.content.strip(), E._usage_dict(r)


CHECK_SCHEMA = {"name": "check", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["ok", "journal"],
    "properties": {"ok": {"type": "boolean"}, "journal": {"type": "string"}}}}


def check(a):
    """One tiny structured call and one text call: is the key, endpoint and model usable?"""
    import time

    if a.list:
        rows = [{"provider": n, "service": s["label"], "default_model": s["model"] or "(give --model)",
                 "key": P.key_status(n)} for n, s in P.PRESETS.items()]
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if a.models:
        provider = a.provider or P.resolve(None, a.model or "x")[0]
        try:
            ids = sorted(m.id for m in P.Client(provider).raw.models.list())
        except Exception as exc:
            sys.exit(f"{provider} does not list its models here ({type(exc).__name__}); "
                     "see the provider's documentation for model ids.")
        flt = (a.model or "").lower()
        print("\n".join(i for i in ids if flt in i.lower()))
        return
    provider, model = P.resolve(a.provider, a.model)
    PROVIDER.update(name=provider, max_tokens=a.max_tokens)
    out = {"provider": provider, "model": model, "endpoint": P.base_url(provider) or "api.openai.com",
           "json_mode": P.PRESETS[provider]["json"]}
    t = time.time()
    try:
        data, _ = call_json(model, "Answer in JSON.", "Is Water Research an environmental "
                            "journal? Set ok accordingly and name the journal.", CHECK_SCHEMA)
        out["structured_answer"] = data
        text, usage = call_text(model, "Reply in one short sentence.", "Say hello.")
        out["text_answer"] = text[:120]
        out["seconds"] = round(time.time() - t, 1)
        out["ok"] = True
    except SystemExit:
        raise
    except Exception as exc:                      # report the provider's own message
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if not out["ok"]:
        sys.exit(1)


def estimate(chars, model):
    """Rough token budget: the manuscript is read ~13 times, plus abstracts and full texts."""
    ms = chars / 4
    tin = ms * 13 + 3 * (8_000 + 5 * 15_000) + 30_000
    tout = 60_000
    out = {"input_tokens": int(tin), "output_tokens": tout}
    if model in PRICES:
        pin, pout = PRICES[model]
        out["usd"] = round(tin / 1e6 * pin + tout / 1e6 * pout, 2)
    else:
        out["usd"] = None
        out["note"] = "price unknown for this model: multiply the tokens by the provider's prices"
    return out


def run(a):
    from . import manuscript as M
    provider, a.model = P.resolve(a.provider, a.model)
    PROVIDER.update(name=provider, max_tokens=a.max_tokens)
    P.install(cli.editor_mod(), a.max_tokens)
    chars = len(M.read_text(Path(a.input)))
    est = estimate(chars, a.model)
    print(json.dumps({"provider": provider, "model": a.model, "key": P.key_status(provider),
                      "estimate": est}, indent=1))
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
                    provider, 5)
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
        run.path(f"seats/{s}/review.md").write_text(rep + "\n", encoding="utf-8")
        return [u1, u2, u3]

    with ThreadPoolExecutor(3) as ex:
        for us in ex.map(seat, cli.SEATS):
            for x in us:
                log(x)
    for s in cli.SEATS:
        cli.cmd_check(Namespace(run=str(run_dir), seat=s))

    if getattr(a, "letter", False):
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
    done = {"calls": len(usage), "input_tokens": tin, "output_tokens": tout}
    if a.model in PRICES:
        pin, pout = PRICES[a.model]
        done["usd_approx"] = round(tin / 1e6 * pin + tout / 1e6 * pout, 2)
    print(json.dumps(done, indent=1))


def _quiet(fn, ns):
    """Run a CLI step whose printed agent instructions are not needed in API mode."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        fn(ns)
