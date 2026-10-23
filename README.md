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
3. **A short note** on how common the manuscript's topics are in the target journal (reference
   only), and, if you ask for one, an **editor's letter** consolidating the three reports.
4. **One report** for the author: verdicts, the closest precedents, the screening by axis, the
   three reports and the literature each reviewer used.

Before starting, the agent asks a few questions: the target journal, whether the reviews are
written by **the agent you are using** (default) or by **a model API** (OpenAI or DeepSeek; you
see a cost estimate first), whether you want the editor's letter, and whether to compare other
journals.

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

## Using a model API instead of your agent

By default the agent you are using writes the editor's evidence and the reviews. You can instead
have a model API do every step (`api-run`); the agent shows a cost estimate first.

| `--provider` | Service | Key variable | Default model |
|---|---|---|---|
| `openai` | OpenAI | `OPENAI_API_KEY` | `gpt-5.6-sol` |
| `claude` | Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| `gemini` | Google | `GEMINI_API_KEY` | — |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` |
| `qwen` | Alibaba DashScope | `DASHSCOPE_API_KEY` | — |
| `doubao` | Volcano Ark | `ARK_API_KEY` | — |
| `kimi` | Moonshot | `MOONSHOT_API_KEY` | — |
| `glm` | Zhipu | `ZHIPUAI_API_KEY` | — |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | — |
| `ollama` | local Ollama | none | — |
| `custom` | any OpenAI-compatible endpoint | `ENVREVIEW_API_KEY` + `ENVREVIEW_API_BASE_URL` | — |

Where there is no default, pass `--model`; `api-check --provider <p> --models` lists the ids a
key can use, and `api-check --provider <p> --model <id>` tests the setup with two tiny calls.
A provider's base URL can be overridden with `ENVREVIEW_<PROVIDER>_BASE_URL` (e.g. a regional
endpoint); the standard `OPENAI_BASE_URL` is deliberately ignored.

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

## Hidden feature: literature search

Not part of the review workflow, and not needed for it: the same index can be searched on its own.
Ask your agent, for example, *"find recent ES&T papers on N2O from wastewater treatment"* or
*"look up 10.1021/acs.est.4c10919"*, or run the commands yourself:

```
python env-journal-review/scripts/envreview.py lit doi 10.1021/acs.est.4c10919
python env-journal-review/scripts/envreview.py lit search "machine learning prediction of N2O emissions from WWTPs" --years 2020-2025
python env-journal-review/scripts/envreview.py lit similar 10.1021/acs.est.4c10919 --journal "ES&T"
python env-journal-review/scripts/envreview.py lit text 10.1016/j.watres.2024.122935
```

`similar` ranks papers by the cosine similarity of their title-and-abstract embeddings, so it
finds papers on the same subject whether or not they cite each other. If you have the PDFs of
these papers, each named by the part of its DOI after the first `/` (`acs.est.4c10919.pdf`), run
`lit pdfs --dir <folder>` once; results then show each paper's PDF, and `lit doi ... --open`
opens it. No PDFs are distributed with this repository.
