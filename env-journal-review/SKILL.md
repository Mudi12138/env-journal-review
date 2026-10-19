---
name: env-journal-review
description: "Pre-submission peer review for environmental science and engineering manuscripts targeting Environmental Science & Technology, Water Research, Nature Water, Nature Sustainability, Nature Climate Change, Nature Geoscience or One Earth. An AI editor screens the manuscript against the target journal's official scope and tier, and three AI reviewers — each from the environmental topic closest to the paper — search a local index of ~40,000 papers from these journals, screen the 20 closest, read the most relevant in full, and write reports focused on whether the contribution is new and whether the conclusions are supported. Produces an editor's decision letter and a single report for the author. Use when the user asks to review, pre-review, critique or assess a manuscript before submission to one of these journals, asks whether a paper is likely to be desk-rejected or what reviewers will say, or says 预审, 审稿, 投稿前评估, 模拟审稿, 看看能不能投 ES&T / Water Research / Nature Water."
---

# Environmental journal pre-submission review

You run an editorial process for one manuscript and one target journal: an editor's screening,
three independent reviewers, and an editor's letter, all grounded in a local literature index.
The mechanical parts are commands; the reading and writing are yours.

Command prefix used below: `ENVR="python <this skill folder>/scripts/envreview.py"`. Every
command takes `--run <run directory>`; all files live there, so any step can be redone.

## 0. Before you start

- **Index pack.** `$ENVR index-info` must print the pack details. If it says the pack is missing,
  stop and tell the user to download `env-journal-index-v1` and unpack it to
  `~/.envreview/env-journal-index-v1` (or set `ENVREVIEW_INDEX`) — see README.md.
- **Python packages:** numpy, pandas, pyarrow, scipy, torch, transformers, pymupdf, python-docx,
  jsonschema. The first search downloads the embedding model `BAAI/bge-large-en-v1.5` (~1.3 GB).
- Ask for the **target journal** if the user has not named one. Ask for the **latest year of
  literature** only if the manuscript is already published (use the year before publication);
  otherwise the default (this year) is right.

## 1. Start

```
$ENVR start --input <manuscript.pdf|.docx|.txt> --journal "<journal>" --tag <short-name>
```

It extracts the title and abstract and picks the three reviewer topics. **Check the title and
abstract it prints**; if extraction went wrong, rerun with `--title` and `--abstract-file`.
For a published manuscript pass its DOI with `--exclude <doi>` so it cannot review itself.

## 2. Editor's screening (send out or reject)

1. Read the manuscript and write 2–3 search queries (natural-language sentences) plus 3–6 exact
   terms that would find the work closest to its central claim. Then:
   `$ENVR editor-pack --run <dir> --query "..." --query "..." --phrase "..."`
2. `$ENVR editor-prompt --run <dir>` writes `editor/<journal>/system.md`, `user.md` and
   `schema.json`. **In a fresh context** (a subagent if you can start one), follow `system.md`
   on the material in `user.md` and write the JSON to `editor/<journal>/assessment.json`.
3. `$ENVR editor-decide --run <dir>` validates the evidence and derives the decision. If it
   reports errors (usually a quote that is not verbatim), fix `assessment.json` and run it
   again — up to five attempts. The decision comes from the rule, never from you.

Optional: repeat steps 2–3 with `--journal <other>` to show how the same manuscript fares at the
other six journals.

## 3. Three reviewers — independently

Run each seat **in its own subagent** (Claude Code: one Task/agent per seat; other hosts: one
after another, and do not let a later reviewer read an earlier one's files). Give each subagent
only its seat and the run directory, and tell it to follow the printed instructions exactly:

```
$ENVR reviewer-brief --run <dir> --seat R1   # role + how to write queries -> seats/R1/queries.json
$ENVR search         --run <dir> --seat R1   # 20 closest abstracts        -> seats/R1/screening.json
$ENVR fulltext       --run <dir> --seat R1   # chosen papers in full       -> seats/R1/report.md
$ENVR check          --run <dir> --seat R1   # recommendation, citations
```

Each command prints the reviewer's instructions for the next step and the files to read and
write. The reviewer screens all 20 abstracts, picks at most five to read in full, and writes a
report: one paragraph of overall assessment ending "I therefore recommend X.", then
"Major Comments". If `check` warns about DOIs outside the screening table or a missing
recommendation, the reviewer fixes the report and runs `check` again. Do the same for R2 and R3.

## 4. Editor's letter and journal note

- `$ENVR letter-brief --run <dir>` — write `decision_letter.md` from the three reports.
- `$ENVR profile-brief --run <dir>` — **in a fresh context that has not seen the reviews or the
  decision**, write `profile_note.md` (a few sentences, reference only).

## 5. Report

`$ENVR report --run <dir>` assembles `report.md`: verdicts at a glance, the editor's letter,
how crowded the manuscript's niche is and its closest precedents, the editor's screening by
axis, the three reports, and the literature each reviewer used.

Then give the user, in their language: the editor's verdict, the reviewers' recommendations,
the three to five changes that matter most (from the letter), and the path to `report.md`.
Keep the reports themselves in English. Say plainly that this is an AI pre-review for preparing
the submission, not a prediction of the editorial outcome.

## Rules that keep the review honest

- Reviewers cite only papers from their own screening table, by DOI; comparisons of methods or
  results only from papers they read in full. The corpus covers seven journals from 2015 on:
  "not found" means "not in these journals".
- The editor gives evidence only; `editor-decide` turns it into send-out or reject.
- Keep the three reviewers, the editor's screening and the journal note in separate contexts.
