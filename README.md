# env-journal-review

AI pre-submission review for environmental science and engineering manuscripts, packaged as an
agent skill for Claude Code, Codex and other agents that read `SKILL.md`.

Give it a manuscript and a target journal — **Environmental Science & Technology**, **Water
Research**, **Nature Water**, **Nature Sustainability**, **Nature Climate Change**, **Nature
Geoscience** or **One Earth** — and it runs a small editorial process:

1. **Editor's screening.** The editor reads the manuscript against the journal's official scope
   and content types, a fixed bar for the journal's tier, and the 20 closest papers in the
   index. It returns evidence on five axes (scope, article type, novelty against prior work,
   significance, size of the advance); a deterministic rule turns that into **send out** or
   **reject**.
2. **Three reviewers.** Each comes from one of the three environmental topics (out of 60) closest
   to the manuscript. Each writes its own searches, screens the 20 closest abstracts, counts the
   papers that already do what the manuscript claims, reads up to five of them in full, and
   writes a report focused on **whether the contribution is new** and **whether the conclusions
   are supported**.
3. **Editor's letter** consolidating the three reports, and a short note on how common the
   manuscript's topics are in the target journal (reference only).
4. **One report** for the author: verdicts, the letter, the closest precedents, the screening by
   axis, the three reports and the literature each reviewer used.

The agent you are already using does the reading and writing; the bundled command-line tool does
the mechanical work (parsing, retrieval, validation, assembly). Nothing is sent to a third-party
service by the skill itself.

## Install

You need git and Python 3.10 or newer.

```
git clone https://github.com/Mudi12138/env-journal-review
cd env-journal-review
python env-journal-review/scripts/envreview.py setup            # once: ~1.4 GB, a few minutes
python env-journal-review/scripts/envreview.py index-download   # once: ~690 MB
```

Then copy the skill folder to your agent's skills folder:

| Agent | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| Claude Code | `cp -r env-journal-review ~/.claude/skills/` | `Copy-Item -Recurse env-journal-review $HOME\.claude\skills\` |
| Codex | `cp -r env-journal-review ~/.codex/skills/` | `Copy-Item -Recurse env-journal-review $HOME\.codex\skills\` |

Open a new session and ask, for example: *"Pre-review paper.pdf for Water Research"* or
*"预审这篇稿子，投 ES&T"*.

Details:

- **`setup`** builds the skill's own environment in `~/.envreview/venv`; afterwards every
  command runs there, whichever Python starts it. To use an environment of your own instead,
  install `env-journal-review/requirements.txt` into it (a CPU build of torch is enough).
- **`index-download`** fetches tag `v1` of
  [`Mudi12137/env-journal-index`](https://huggingface.co/datasets/Mudi12137/env-journal-index)
  to `~/.envreview/env-journal-index-v1/` and checks every file; it resumes if interrupted. To
  keep the index elsewhere, set `ENVREVIEW_INDEX` to that folder first.
- The first search downloads the embedding model `BAAI/bge-large-en-v1.5` (~1.3 GB). After
  that, loading takes about 30 s and each search about 2 s on a laptop CPU.
- If you skip these steps, the agent will tell you what is missing and offer to run them.

## The index pack

**About 40,000 research papers** published 2015–2026 in the seven journals: DOI, title, abstract,
journal, year, one of 60 environmental topic labels, method/purpose/system facets, bge-large
embeddings, a BM25 index, topic centroids, and parsed full texts in a compressed SQLite file.
Retrieval fuses three rankings — embeddings, BM25 and exact terms — and **runs entirely on your
machine**.

## Limitations

- The literature is seven journals. "No similar paper found" means *not in these journals*.
- The editor's verdicts have been checked against a small number of published papers only; the
  tool has not been calibrated against real desk rejections. Treat its output as a structured
  second opinion for revising the manuscript, **not as a forecast**.
- Reviews are written by whichever model your agent runs; results vary between models and runs.

## Repository layout

```
env-journal-review/          the skill (copy this folder)
  SKILL.md                   workflow the agent follows
  scripts/envreview.py       command-line entry point
  scripts/envreview/         retrieval, editor engine, reviewer prompts, report assembly
  assets/                    topic taxonomy, journal topic profiles
pack/                        maintainer tools that build the index pack
```

## License

Code and prompts: MIT (see LICENSE). The index pack is hosted separately on Hugging Face; its
dataset card states its terms.
