"""V3 handling-editor runner: official scope, global evidence, binary decision.

This module deliberately keeps four responsibilities separate:

1. The model assesses five axes only: ``scope_fit``, ``genre_fit``,
   ``novelty_increment``, ``significance`` and ``novelty_magnitude``.
2. ``decision_engine.derive_decision`` converts those axes to 送审/拒稿.  The
   model never emits a decision or a transfer destination.
3. Every target journal for one manuscript receives the exact same global
   retrieval pack.  This file contains no journal filter, quota or weight.
4. An optional profile pass runs only after the decision is frozen.  Its schema
   cannot emit or modify a decision and labels the note 仅供参考.

Safety default: running this file without ``--execute`` is a dry run.  A paid
API call is possible only when ``--execute`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from decision_engine import (
    AssessmentValidationError,
    _MAGNITUDE_LANGUAGE_RE,
    _SIGNIFICANCE_DECORATIVE_LANGUAGE_RE,
    derive_decision,
    validate_assessment as _core_validate_assessment,
)


HERE = Path(__file__).resolve().parent
DEFAULT_PACK_DIR = HERE.parent
DEFAULT_REGISTRY = HERE / "journal_registry.json"
DEFAULT_TIERS = HERE / "tier_bars.json"
# Results go to runs/<timestamp>/ (see --run-dir); editor_results_v3.json is a record of the
# 2026-09-22 runs and is never written by default any more.
DEFAULT_MODEL = "gpt-5.6-sol"
# Prose language of the five-axis rationales (the evidence quotes stay verbatim).
PROSE_LANGUAGE = os.environ.get("ENVREVIEW_LANGUAGE", "English")
CORPUS_DESCRIPTION = (
    "40,453 research records from seven environmental journals; retrieval is "
    "global across the seven journals"
)
PROFILE_UI_LABEL = "仅供参考，不参与送审/拒稿决定"
# How many times one job may be re-asked when an evidence gate rejects its quotes.
EVIDENCE_REPAIR_ATTEMPTS = 3

_PROFILE_DECISION_LANGUAGE = re.compile(
    r"(?:送审|送交\s*(?:外审|同行评审)|外审|外部同行评审|"
    r"(?:进入|送入)\s*(?:外部)?(?:同行)?(?:评审|评议|审稿)(?:流程)?|"
    r"(?:不宜|不应|无需)\s*进入\s*(?:外部)?(?:同行)?(?:评审|评议|审稿)(?:流程)?|"
    r"(?:直接|建议|应当|应|宜|可以|不宜)?\s*(?:退稿|退回|拒收)|"
    r"另投|改投|转投|拒稿|录用|建议\s*(?:接收|录用|发表|送审|外审|拒稿|转投)|"
    r"desk\s*(?:reject|decision)|send\w*\s+(?:it\s+)?(?:to|for)\s+(?:external\s+)?review|"
    r"external\s+(?:peer\s+)?review|"
    r"\brecommend(?:s|ed|ing)?\s+(?:this\s+|the\s+)?(?:manuscript|paper|submission)\b|"
    r"\brecommend(?:s|ed|ing)?\s+(?:acceptance|rejection|transfer)\b|"
    r"\brecommend(?:s|ed|ing)?\s+(?:this\s+|the\s+)?(?:manuscript|paper|submission)"
    r"\s+for\s+(?:publication|peer\s+review|external\s+review)\b|"
    r"\brecommendation\s+to\s+(?:accept|reject|transfer|send)\b|"
    r"\b(?:accept|reject|transfer)\s+(?:this\s+|the\s+)?(?:manuscript|paper|submission)\b|"
    r"\b(?:manuscript|paper|submission)\s+(?:should\s+be\s+)?(?:accepted|rejected|transferred)\b|"
    r"^(?:accept|reject|transfer)[.!]?$)",
    re.IGNORECASE,
)

_ASSESSMENT_DECISION_LANGUAGE = _PROFILE_DECISION_LANGUAGE

_QUALITY_ONLY_SCOPE_LANGUAGE = re.compile(
    r"(?:significant|general\s+interest|broadly\s+relevant|generalizable|novel|"
    r"cutting[ -]edge|top[ -]quality|best\s+research|high[ -]impact|conceptual\s+advance|"
    r"重要|显著|广泛兴趣|高影响|前沿|新颖|概念推进)",
    re.IGNORECASE,
)

_SCOPE_DOMAIN_LANGUAGE = re.compile(
    r"(?:water|freshwater|anthropogenic\s+water\s+cycle|climate\s+change|earth\s+science|"
    r"geoscience|sustainab|environment|society\s+and\s+water|water\s+resources|"
    r"水|淡水|人为水循环|气候变化|地球科学|可持续|环境)",
    re.IGNORECASE,
)

# The post-novelty axes are orthogonal: significance (centrality of the contribution to
# the journal's core concern) and novelty_magnitude (magnitude of the increment against
# the tier).  Their concrete vocabularies are imported from decision_engine so the prompt
# and the validator cannot drift apart.  The old contribution-TYPE dimension enumeration
# (TIER_DIMENSION_RULES) is deliberately gone: it made methods/informatics papers
# structurally unable to satisfy any dimension.

_BOUNDARY_LANGUAGE = re.compile(
    r"(?:only|single|one|two|three|site|dataset|system|laborator|full[ -]scale|domain|"
    r"scope|boundary|demonstrat|evaluat|仅|只|单一|一个|两个|三个|场地|数据集|系统|"
    r"实验室|全规模|领域|范围|边界|展示|验证|评估)",
    re.IGNORECASE,
)

_GENRE_RULE_LANGUAGE = re.compile(
    r"(?:article|research\s+paper|review|perspective|analysis|comment|correspondence|"
    r"commission|unsolicited|primary\s+research|文章|研究论文|综述|观点|评论|通信|邀稿)",
    re.IGNORECASE,
)

_SYNTHESIS_LANGUAGE = re.compile(
    r"(?:^|[\n.!?:]\s*)(?:(?:this|a|an)\s+)?(?:systematic\s+)?review\b|"
    r"\b(?:this|a|an)\s+(?:systematic\s+)?review\b|\bsystematic\s+review\b|"
    r"\bwe\s+(?:systematically\s+)?review\b|"
    r"\b(?:comprehensive|systematic)\s+(?:review|overview)\b|\bmeta-analysis\b|"
    r"\bscoping\s+review\b|\b(?:this|an?)\s+overview\b|"
    r"(?:^|[\n:.!?]\s*)perspectives?\s+(?:on|in|for)\b|\bthis\s+perspective\b|"
    r"(?:^|[\n:.!?]\s*)viewpoint\b|\bthis\s+viewpoint\b|"
    r"(?:^|[\n:.!?]\s*)commentary\b|\bthis\s+commentary\b|"
    r"(?:^|[\n:.!?]\s*)editorial\b|\bthis\s+editorial\b",
    re.IGNORECASE,
)

_CONTRIBUTION_MODE_LANGUAGE = {
    "empirical_or_process": re.compile(
        r"(?:experiment|process|mechanis|reactor|treatment|synthesi|cataly|实验|过程|机制|反应器|处理|合成|催化)",
        re.IGNORECASE,
    ),
    "computational_or_method": re.compile(
        r"(?:model|machine\s+learning|algorithm|framework|method|controller|control|"
        r"computational|simulation|模型|机器学习|算法|框架|方法|控制|计算|模拟)",
        re.IGNORECASE,
    ),
    "observational_or_field": re.compile(
        r"(?:field|survey|monitor|observational|cohort|sampling|现场|调查|监测|观测|队列|采样)",
        re.IGNORECASE,
    ),
    "policy_or_social": re.compile(
        r"(?:policy|governance|social|economic|stakeholder|justice|政策|治理|社会|经济|利益相关|公平)",
        re.IGNORECASE,
    ),
    "synthesis_or_review": re.compile(
        r"(?:review|meta-analysis|overview|perspective|综述|荟萃分析|概述|观点)",
        re.IGNORECASE,
    ),
}

AXIS_KEYS = (
    "scope_fit",
    "genre_fit",
    "novelty_increment",
    "significance",
    "novelty_magnitude",
)

# delta_type classifies how much the manuscript adds beyond ONE specific retrieved
# precedent.  It is the load-bearing link between retrieval and the novelty_increment
# verdict: the verdict is a mechanical function of the smallest delta among the
# same/adjacent-genre comparisons, not a free-floating "insufficient novelty" feeling.
DELTA_TYPE_ENUM = [
    "reframe",                # changes understanding or reframes the problem
    "new_capability",         # enables previously-unobtainable results / a new class of outcome
    "method_transfer",        # applies an established method or approach in a new setting
    "site_or_dataset",        # same method + same application, new site or dataset
    "configuration_or_scale",  # same method + same application, config or scale change
    "validation_only",        # confirms or reproduces an established result
]
_SUBSTANTIAL_DELTA_TYPES = frozenset({"reframe", "new_capability"})
_LIMITED_DELTA_TYPES = frozenset(
    {"method_transfer", "site_or_dataset", "configuration_or_scale", "validation_only"}
)
# 2026-10-15: novelty_increment blocks only when the work has already been done (the delta
# to a direct precedent is validation_only). Whether a method-transfer, new-site or
# configuration increment is enough is a tier question and belongs to novelty_magnitude:
# WR publishes such increments when they add water-domain knowledge (MS13 was rejected at
# its own journal by the old rule).
_ALREADY_DONE_DELTA_TYPES = frozenset({"validation_only"})


TRACE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source_locator", "evidence_quote"],
    "properties": {
        "source_locator": {"type": "string"},
        "evidence_quote": {"type": "string"},
    },
}

OFFICIAL_TRACE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source_id", "official_quote"],
    "properties": {
        "source_id": {"type": "string"},
        "official_quote": {"type": "string"},
    },
}

DIRECT_PRECEDENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "doi",
        "evidence_quote",
        "evidence",
        "relationship",
        "genre_match",
    ],
    "properties": {
        "doi": {"type": "string"},
        "evidence_quote": {
            "type": "string",
            "description": "Verbatim excerpt from this DOI's supplied title or abstract.",
        },
        "evidence": {"type": "string"},
        "relationship": {"type": "string"},
        "genre_match": {
            "type": "string",
            "enum": ["same_genre", "unknown"],
        },
    },
}

SAME_GENRE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "doi",
        "manuscript_genre",
        "precedent_genre",
        "genre_match",
        "manuscript_genre_evidence",
        "genre_evidence",
        "what_it_already_did",
        "what_the_manuscript_adds",
        "delta_type",
    ],
    "properties": {
        "doi": {"type": "string"},
        "manuscript_genre": {
            "type": "string",
            "enum": [
                "empirical_or_process",
                "computational_or_method",
                "observational_or_field",
                "policy_or_social",
                "synthesis_or_review",
                "other",
                "unknown",
            ],
        },
        "precedent_genre": {
            "type": "string",
            "enum": [
                "empirical_or_process",
                "computational_or_method",
                "observational_or_field",
                "policy_or_social",
                "synthesis_or_review",
                "other",
                "unknown",
            ],
        },
        "genre_match": {
            "type": "string",
            "enum": ["same", "adjacent", "different", "unknown"],
        },
        "manuscript_genre_evidence": {
            "type": "string",
            "description": "Verbatim excerpt from the submitted title or abstract.",
        },
        "genre_evidence": {
            "type": "string",
            "description": "Verbatim excerpt from this DOI's supplied title or abstract.",
        },
        "what_it_already_did": {"type": "string"},
        "what_the_manuscript_adds": {"type": "string"},
        "delta_type": {
            "type": "string",
            "enum": DELTA_TYPE_ENUM,
            "description": (
                "How much the manuscript adds beyond this specific precedent. "
                "reframe and new_capability are substantial; method_transfer, "
                "site_or_dataset, configuration_or_scale and validation_only are limited."
            ),
        },
    },
}

SIGNIFICANCE_FINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "source_locator",
        "evidence_quote",
        "positive_contribution",
        "centrality",
        "gap_to_concern",
    ],
    "properties": {
        "source_locator": {"type": "string"},
        "evidence_quote": {"type": "string"},
        "positive_contribution": {
            "type": "string",
            "description": "The contribution's concrete claim, not a prestige adjective.",
        },
        "centrality": {
            "type": "string",
            "enum": [
                "central",
                "secondary_demonstration",
                "supporting_discipline",
                "unknown",
            ],
            "description": (
                "central: the core concern is the main result; "
                "secondary_demonstration: the core concern appears only as a secondary "
                "demonstration of a result from another discipline; "
                "supporting_discipline: a supporting discipline (chemistry, materials, "
                "AI/ML, etc.) advances understanding/prediction/management/operation of "
                "the relevant system; unknown: cannot be determined from the evidence."
            ),
        },
        "gap_to_concern": {"type": "string"},
    },
}

NOVELTY_MAGNITUDE_FINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "source_locator",
        "evidence_quote",
        "positive_finding",
        "demonstrated_scope_or_boundary",
        "gap_to_bar",
    ],
    "properties": {
        "source_locator": {"type": "string"},
        "evidence_quote": {"type": "string"},
        "positive_finding": {"type": "string"},
        "demonstrated_scope_or_boundary": {
            "type": "string",
            "description": "What scale, system, dataset, mechanism or consequence the manuscript actually demonstrates.",
        },
        "gap_to_bar": {"type": "string"},
    },
}

ASSESSMENT_SCHEMA = {
    "name": "editor_v3_five_axis_assessment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": list(AXIS_KEYS),
        "properties": {
            "scope_fit": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "verdict",
                    "rationale",
                    "official_basis",
                    "manuscript_basis",
                ],
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "warn", "block"],
                    },
                    "rationale": {"type": "string"},
                    "official_basis": {
                        "type": "array",
                        "items": OFFICIAL_TRACE_SCHEMA,
                    },
                    "manuscript_basis": {
                        "type": "array",
                        "items": TRACE_SCHEMA,
                    },
                },
            },
            "genre_fit": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "verdict",
                    "rationale",
                    "inferred_manuscript_genre",
                    "official_basis",
                    "manuscript_basis",
                ],
                "properties": {
                    "verdict": {"type": "string", "enum": ["pass", "block"]},
                    "rationale": {"type": "string"},
                    "inferred_manuscript_genre": {"type": "string"},
                    "official_basis": {
                        "type": "array",
                        "items": OFFICIAL_TRACE_SCHEMA,
                    },
                    "manuscript_basis": {
                        "type": "array",
                        "items": TRACE_SCHEMA,
                    },
                },
            },
            "novelty_increment": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "verdict",
                    "rationale",
                    "central_claim",
                    "manuscript_increment",
                    "direct_precedents",
                    "nearest_same_genre_precedents",
                ],
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "warn", "block"],
                    },
                    "rationale": {"type": "string"},
                    "central_claim": {"type": "string"},
                    "manuscript_increment": {"type": "string"},
                    "direct_precedents": {
                        "type": "array",
                        "items": DIRECT_PRECEDENT_SCHEMA,
                    },
                    "nearest_same_genre_precedents": {
                        "type": "array",
                        "items": SAME_GENRE_SCHEMA,
                    },
                },
            },
            "significance": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "verdict",
                    "rationale",
                    "required_concern",
                    "manuscript_findings",
                ],
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "warn", "block"],
                    },
                    "rationale": {"type": "string"},
                    "required_concern": {"type": "string"},
                    "manuscript_findings": {
                        "type": "array",
                        "items": SIGNIFICANCE_FINDING_SCHEMA,
                    },
                },
            },
            "novelty_magnitude": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "verdict",
                    "rationale",
                    "tier_id",
                    "required_bar",
                    "increment_summary",
                    "manuscript_findings",
                ],
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["pass", "warn", "block"],
                    },
                    "rationale": {"type": "string"},
                    "tier_id": {"type": "string"},
                    "required_bar": {"type": "string"},
                    "increment_summary": {"type": "string"},
                    "manuscript_findings": {
                        "type": "array",
                        "items": NOVELTY_MAGNITUDE_FINDING_SCHEMA,
                    },
                },
            },
        },
    },
}

PROFILE_SCHEMA = {
    "name": "editor_v3_reference_only_profile_note",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "profile_note",
            "review_attention",
            "reference_only_acknowledged",
        ],
        "properties": {
            "profile_note": {"type": "string"},
            "review_attention": {"type": "string"},
            "reference_only_acknowledged": {"type": "boolean"},
        },
    },
}


SYSTEM_PROMPT = """You are the handling editor of {journal_name}. You assess whether a new
submission should be sent to external peer review. Do not output a desk decision, a
transfer suggestion, a score, or a topic-profile interpretation. Output only the five
assessment axes required by the JSON schema. A separate deterministic program will derive
送审 or 拒稿 after your assessment.

Use this fixed order and keep the questions distinct:
1. scope_fit: compare the manuscript's core research object with the supplied OFFICIAL
   scope text. Scope is categorical and is not relaxed by novelty or journal tier.
   Words such as significant, general interest, broadly relevant, novel, cutting-edge or
   top-quality are quality language, not subject boundaries. They cannot support a scope
   block. For a scope block, the cited verbatim official excerpt must itself state the
   relevant subject/remit boundary; the normalized scope is auxiliary interpretation only.
2. genre_fit: use only the supplied OFFICIAL content-type rules. Infer genre cautiously
   from title/abstract; a paper containing a tool can still be a research Article when it
   reports substantive new empirical, mechanistic or engineering findings.
   If the capture status is partial, conservative, access-restricted or otherwise
   incomplete, absence from the captured list does NOT mean the journal rejects that
   genre. In that situation, genre_fit may be blocked only by an explicitly captured
   official exclusion or restriction; otherwise default to pass and explain the unknown.
   Quality words in article descriptions (significant, novel, broad interest, and similar)
   also cannot support a genre block.
3. novelty_increment: identify what the manuscript adds relative to the GLOBAL retrieved
   literature. Compare first with papers of the same research genre. The retrieval pack
   does not contain reliable article-type metadata. Classify the *contribution mode* as one
   of empirical_or_process / computational_or_method / observational_or_field /
   policy_or_social / synthesis_or_review / other / unknown, using a verbatim excerpt for
   each classification. This is not merely the journal wrapper `Article`. `same` requires
   identical, non-unknown contribution-mode labels. Use `unknown` when unsupported. A
   review/synthesis cannot be relabelled as an empirical or computational study merely to
   make it a same-genre precedent. A novelty `block`
   requires at least one named DOI that directly covers the central claim AND at least one
   comparison marked `same` genre with that same DOI. If that evidence is absent, use warn
   rather than block.
   For every comparison, also set `delta_type` to how much the manuscript adds beyond that
   specific precedent: reframe / new_capability / method_transfer / site_or_dataset /
   configuration_or_scale / validation_only. The novelty_increment verdict is a mechanical
   function of these deltas and the validator enforces it:
   - `pass` is allowed only when every same/adjacent-genre comparison shows a substantial
     delta (reframe or new_capability). A single limited delta (method_transfer,
     site_or_dataset, configuration_or_scale, validation_only) forbids `pass`.
   - `block` means the contribution has already been made: it requires a same/adjacent-
     genre comparison with the direct precedent whose delta is validation_only (the
     manuscript confirms or reproduces what that precedent already showed). A
     method_transfer, site_or_dataset or configuration_or_scale delta is a real but limited
     increment: give `warn`, and let novelty_magnitude judge whether it is enough for the
     tier.
4. significance: take the identified contribution as given and ask whether it is central
   and meaningful to the journal's core concern. The supplied core concern is:
   {required_concern}
   Contribution TYPE is not the criterion: a methods, computational or informatics
   contribution is first-class when it enables previously-unobtainable results or a
   meaningful advance in understanding, predicting, managing or operating the relevant
   system. For every finding, set centrality to central, secondary_demonstration,
   supporting_discipline or unknown. A block requires at least one finding whose
   centrality is secondary_demonstration or supporting_discipline, and whose gap_to_concern
   states why the core concern is only decorative or secondary (not central).
5. novelty_magnitude: take the identified increment as given and ask whether its magnitude
   reaches the supplied {tier_id} bar. Judge only magnitude — do not re-litigate the
   contribution's type or relevance, do not re-decide scope, and do not invent a higher
   rejection rate. For every finding, state the demonstrated_scope_or_boundary (what scale,
   system, dataset, mechanism or consequence is actually demonstrated) and a gap_to_bar
   that names the magnitude shortfall relative to the bar, or explains why the magnitude
   is sufficient.
   Judge magnitude in the currency of the manuscript's contribution mode. For
   policy_or_social and synthesis_or_review work (perspectives, analyses, reviews), the
   magnitude is how far the argument changes how the problem is understood, prioritised or
   acted on, and how well it is substantiated from existing evidence; do not count the
   absence of new datasets, models or quantification as a shortfall in itself. Whether the
   journal publishes that kind of article is genre_fit's question, not this axis's.

Evidence discipline:
- Scope and genre findings must quote or closely excerpt an official source and a
  manuscript passage. Use the supplied source IDs exactly.
- Novelty statements must name only DOIs present in the retrieval pack. For every nearest
  comparison, state manuscript genre, precedent genre, genre_match, genre evidence, what
  the precedent did, and what the manuscript adds.
- direct_precedents.evidence_quote and each comparison's genre evidence must be copied
  verbatim from the corresponding supplied title/abstract; never reconstruct a quote.
- The retrieved set is selected for similarity and will look crowded by construction.
  Mere similarity, topic frequency, or absence of exceptional novelty is not a block.
- Seven journals are not the whole literature. Say `no precedent in the retrieved set`,
  never claim world-first status from absence here.
- Write prose fields in {prose_language}. Keep official source IDs, DOI strings, journal names and
  tier IDs unchanged.
- In significance.required_concern and novelty_magnitude.required_bar, copy the supplied
  normalized concern / bar verbatim; do not paraphrase or invent a different threshold.
- A generic statement such as `not exceptional enough for this journal` or `insufficient
  for a top journal` is never a significance or novelty_magnitude block. Blocks must name
  the concrete magnitude shortfall and the demonstrated boundary (novelty_magnitude), or
  the concrete way the core concern is only secondary/decorative (significance).
- Do not write any decision or editorial-action language anywhere in the five-axis JSON,
  including rationales, quotes or nested evidence. Forbidden examples include 送审、外审、
  拒稿、转投、accept、reject、desk decision and recommend. Describe evidence and gaps only.

{evidence_vocabulary}
No profile, publication-density or citation-performance data are present. They are not
decision evidence and must not be mentioned."""


PROFILE_SYSTEM_PROMPT = """Write a neutral topic-profile background note. This pass is
reference-only (仅供参考). It receives no editorial assessment or outcome. Describe recent
publication density and historical citation performance separately; never combine them
into a score. State only what a human may inspect more carefully. Do not propose any
editorial action or recommendation."""


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _first_text(record: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _nested_text(record: dict[str, Any], parent: str, names: Iterable[str]) -> str:
    value = record.get(parent)
    if not isinstance(value, dict):
        return ""
    return _first_text(value, names)


def _normalise_sources(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("scope_sources") or record.get("sources") or []
    if isinstance(raw, dict):
        raw = [raw]
    sources: list[dict[str, Any]] = []
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        source = deepcopy(item)
        source.setdefault("source_id", source.get("id") or f"scope_source_{i}")
        sources.append(source)
    if not sources:
        url = _first_text(record, ["scope_source_url", "source_url", "url"])
        if url:
            sources.append({"source_id": "scope_source_1", "url": url})
    return sources


def _flatten_nonempty_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if value.strip():
            strings.append(value.strip())
    elif isinstance(value, dict):
        for child in value.values():
            strings.extend(_flatten_nonempty_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_flatten_nonempty_strings(child))
    return strings


def _verified_snapshot_path(registry_path: Path, relative_path: str) -> Path:
    root = registry_path.resolve().parent
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Snapshot escapes registry directory: {relative_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_journal_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Load and normalise either a list-style or mapping-style registry."""

    raw = _read_json(path)
    container = raw.get("journals", raw) if isinstance(raw, dict) else raw
    records: list[tuple[str | None, Any]]
    if isinstance(container, list):
        records = [(None, item) for item in container]
    elif isinstance(container, dict):
        records = list(container.items())
    else:
        raise ValueError(f"Unsupported journal registry shape in {path}")

    journals: dict[str, dict[str, Any]] = {}
    for map_key, raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        record = deepcopy(raw_record)
        journal_id = str(record.get("journal_id") or map_key or "").strip()
        display_name = _first_text(record, ["display_name", "journal_name", "name"])
        tier_id = str(record.get("tier_id") or record.get("tier") or "").strip()

        # The production registry intentionally stores only identity+tier and a path to a
        # versioned, immutable official-scope snapshot.  Load it here rather than silently
        # falling back to model knowledge or a hand-written card.
        snapshot: dict[str, Any] | None = None
        snapshot_ref = record.get("snapshot")
        if snapshot_ref:
            snapshot_path = _verified_snapshot_path(path, str(snapshot_ref))
            snapshot_raw = _read_json(snapshot_path)
            if not isinstance(snapshot_raw, dict):
                raise ValueError(f"Snapshot must be an object: {snapshot_path}")
            snapshot = snapshot_raw
            if snapshot.get("journal_id") != journal_id:
                raise ValueError(
                    f"Snapshot journal_id {snapshot.get('journal_id')!r} does not match {journal_id!r}"
                )
            if snapshot.get("display_name") not in {None, display_name}:
                raise ValueError(
                    f"Snapshot display_name does not match registry for {journal_id}"
                )

        scope_record = snapshot.get("scope", {}) if snapshot else {}
        scope_text = _first_text(
            scope_record or record,
            ["scope_text", "scope_text_verbatim", "official_scope_text"],
        ) or _first_text(scope_record, ["text"]) or _nested_text(
            record, "official_scope", ["text", "full_text", "verbatim"]
        )
        content_types = (
            snapshot.get("content_types") if snapshot else None
        ) or record.get("article_types") or record.get("content_types")
        sources = _normalise_sources(snapshot or record)
        raw_official_excerpts = scope_record.get("official_excerpts") or []
        scope_source_refs = scope_record.get("source_refs") or []
        content_source_refs = (
            content_types.get("source_refs", []) if isinstance(content_types, dict) else []
        )
        content_official_excerpts = (
            content_types.get("official_excerpts", [])
            if isinstance(content_types, dict)
            else []
        )

        if snapshot:
            for required_content_field in (
                "capture_completeness",
                "absence_is_not_exclusion",
            ):
                if not isinstance(content_types, dict) or required_content_field not in content_types:
                    raise ValueError(
                        f"Snapshot {snapshot_ref} content_types lacks "
                        f"{required_content_field}"
                    )
            stored_hash = str(scope_record.get("text_sha256") or "").strip().lower()
            if not stored_hash or stored_hash.startswith("__"):
                raise ValueError(f"Snapshot {snapshot_ref} has no completed scope.text_sha256")
            calculated_hash = _sha256_text(scope_text)
            if calculated_hash != stored_hash:
                raise ValueError(
                    f"Snapshot {snapshot_ref} scope.text_sha256 mismatch: "
                    f"stored {stored_hash}, calculated {calculated_hash}"
                )
            if not isinstance(raw_official_excerpts, list) or not raw_official_excerpts:
                raise ValueError(f"Snapshot {snapshot_ref} has no scope.official_excerpts")
            official_excerpts = []
            for index, excerpt in enumerate(raw_official_excerpts):
                if not isinstance(excerpt, dict):
                    raise ValueError(f"{snapshot_ref} official_excerpts[{index}] must be an object")
                excerpt_text = excerpt.get("text")
                if not excerpt.get("source_ref") or not excerpt_text:
                    raise ValueError(
                        f"{snapshot_ref} official_excerpts[{index}] needs source_ref and text"
                    )
                if excerpt["source_ref"] not in scope_source_refs:
                    raise ValueError(
                        f"{snapshot_ref} official_excerpts[{index}] cites a source_ref "
                        "outside scope.source_refs"
                    )
                normalized_excerpt = deepcopy(excerpt)
                normalized_excerpt["text"] = str(excerpt_text).strip()
                official_excerpts.append(normalized_excerpt)
            if not isinstance(content_official_excerpts, list) or not content_official_excerpts:
                raise ValueError(
                    f"Snapshot {snapshot_ref} has no content_types.official_excerpts"
                )
            for index, excerpt in enumerate(content_official_excerpts):
                if not isinstance(excerpt, dict) or not excerpt.get("source_ref") or not excerpt.get("text"):
                    raise ValueError(
                        f"{snapshot_ref} content_types.official_excerpts[{index}] "
                        "needs source_ref and text"
                    )
                if excerpt["source_ref"] not in content_source_refs:
                    raise ValueError(
                        f"{snapshot_ref} content_types.official_excerpts[{index}] cites a "
                        "source_ref outside content_types.source_refs"
                    )
        else:
            official_excerpts = raw_official_excerpts

        known_source_ids = {str(item["source_id"]) for item in sources}
        unknown_scope_refs = set(map(str, scope_source_refs)) - known_source_ids
        unknown_content_refs = set(map(str, content_source_refs)) - known_source_ids
        if unknown_scope_refs or unknown_content_refs:
            raise ValueError(
                f"Journal {journal_id} uses unregistered source refs: "
                f"scope={sorted(unknown_scope_refs)}, content={sorted(unknown_content_refs)}"
            )

        missing = [
            name
            for name, value in (
                ("journal_id", journal_id),
                ("display_name", display_name),
                ("tier_id", tier_id),
                ("official scope text", scope_text),
                ("official scope source", sources),
                ("official content/article types", content_types),
                ("official scope source refs", scope_source_refs),
                ("official content-type source refs", content_source_refs),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Journal record {journal_id or map_key!r} is missing: {', '.join(missing)}"
            )

        record["journal_id"] = journal_id
        record["display_name"] = display_name
        record["tier_id"] = tier_id
        record["_scope_text"] = scope_text
        record["_official_excerpts"] = official_excerpts
        record["_content_types"] = content_types
        record["_content_type_strings"] = _flatten_nonempty_strings(content_types)
        record["_content_official_excerpts"] = content_official_excerpts
        record["_content_capture_status"] = (
            content_types.get("capture_status", "complete")
            if isinstance(content_types, dict)
            else "unknown"
        )
        record["_content_capture_completeness"] = (
            content_types.get("capture_completeness", "unknown")
            if isinstance(content_types, dict)
            else "unknown"
        )
        record["_absence_is_not_exclusion"] = bool(
            content_types.get("absence_is_not_exclusion", False)
            if isinstance(content_types, dict)
            else False
        )
        record["_content_explicit_exclusions"] = (
            content_types.get("official_exclusions_or_restrictions", [])
            if isinstance(content_types, dict)
            else []
        )
        record["_sources"] = sources
        record["_source_ids"] = [str(x["source_id"]) for x in sources]
        record["_scope_source_ids"] = [str(x) for x in scope_source_refs]
        record["_content_source_ids"] = [str(x) for x in content_source_refs]
        record["_snapshot"] = snapshot
        if journal_id in journals:
            raise ValueError(f"Duplicate journal_id: {journal_id}")
        journals[journal_id] = record

    if not journals:
        raise ValueError(f"No journal records found in {path}")
    return journals


def load_tier_bars(path: Path) -> dict[str, dict[str, Any]]:
    raw = _read_json(path)
    container = raw.get("tiers", raw) if isinstance(raw, dict) else raw
    if not isinstance(container, dict):
        raise ValueError(f"Unsupported tier registry shape in {path}")
    tiers: dict[str, dict[str, Any]] = {}
    for key, value in container.items():
        if not isinstance(value, dict):
            continue
        tier_id = str(value.get("tier_id") or key)
        significance = value.get("significance")
        novelty_magnitude = value.get("novelty_magnitude")
        if not isinstance(significance, dict) or not isinstance(novelty_magnitude, dict):
            raise ValueError(
                f"Tier {tier_id} requires significance and novelty_magnitude objects"
            )
        required_concern = _first_text(significance, ["bar"])
        required_bar = _first_text(novelty_magnitude, ["bar"])
        if not required_concern:
            raise ValueError(f"Tier {tier_id} has no significance.bar")
        if not required_bar:
            raise ValueError(f"Tier {tier_id} has no novelty_magnitude.bar")
        tier = deepcopy(value)
        tier["tier_id"] = tier_id
        tier["_required_concern"] = required_concern
        tier["_required_bar"] = required_bar
        tiers[tier_id] = tier
    if not tiers:
        raise ValueError(f"No tier definitions found in {path}")
    return tiers


def validate_journal_tier_membership(
    journals: dict[str, dict[str, Any]],
    tiers: dict[str, dict[str, Any]],
    tier_path: Path,
) -> None:
    """Fail fast on registry/tier drift before any model call."""

    raw = _read_json(tier_path)
    if not isinstance(raw, dict) or raw.get("order_high_to_low") != ["T3", "T2", "T1"]:
        raise ValueError("tier_bars.order_high_to_low must be exactly ['T3', 'T2', 'T1']")
    for journal_id, journal in journals.items():
        memberships = [
            tier_id
            for tier_id, tier in tiers.items()
            if journal_id in (tier.get("member_journals") or [])
        ]
        if memberships != [journal["tier_id"]]:
            raise ValueError(
                f"Journal {journal_id} must appear exactly once in member_journals for "
                f"{journal['tier_id']}; found {memberships}"
            )


def _format_sources(sources: list[dict[str, Any]]) -> str:
    blocks = []
    for source in sources:
        ordered = {
            "source_id": source.get("source_id"),
            "source_type": source.get("source_type"),
            "title": source.get("title"),
            "url": source.get("url"),
            "retrieved_at": source.get("retrieved_at"),
            "content_hash": source.get("content_hash") or source.get("sha256"),
        }
        blocks.append(_canonical_json({k: v for k, v in ordered.items() if v}))
    return "\n".join(blocks)


def hit_block(hit: dict[str, Any], index: int) -> str:
    """Render one hit without changing, filtering or reordering the pack."""

    abstract = hit.get("abstract") or "(title only; weak evidence)"
    if len(abstract) > 1800:
        abstract = abstract[:1800] + " …"
    article_type = hit.get("article_type") or hit.get("research_genre") or (
        "unknown; infer cautiously from title/abstract"
    )
    return (
        f"[{index}] DOI: {hit.get('doi', '')}\n"
        f"YEAR: {hit.get('year', '')}\n"
        f"JOURNAL: {hit.get('journal', '')}\n"
        f"TOPIC: {hit.get('category', '')}\n"
        f"FACETS: {hit.get('facets', '')}\n"
        f"PACK ARTICLE TYPE: {article_type}\n"
        f"WHY RETRIEVED: {hit.get('why_retrieved', '')}\n"
        f"TITLE: {hit.get('title', '')}\n"
        f"ABSTRACT: {abstract}"
    )


def build_decision_messages(
    pack: dict[str, Any],
    journal: dict[str, Any],
    tier: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Build pass-1 messages from the untouched global pack."""

    if journal["tier_id"] != tier["tier_id"]:
        raise ValueError(
            f"Journal {journal['journal_id']} points to {journal['tier_id']}, "
            f"not supplied tier {tier['tier_id']}"
        )
    hits = pack.get("hits")
    if not isinstance(hits, list) or not hits:
        raise ValueError(f"Retrieval pack {pack.get('id', '(unknown)')} has no hits")

    pack_hash_before = sha256_json(pack)
    system = SYSTEM_PROMPT.format(
        journal_name=journal["display_name"],
        tier_id=tier["tier_id"],
        required_concern=tier["_required_concern"],
        required_bar=tier["_required_bar"],
        evidence_vocabulary=_evidence_vocabulary_block(tier["tier_id"]),
        prose_language=PROSE_LANGUAGE,
    )
    sources = _format_sources(journal["_sources"])
    official_supplements = journal.get("scope_supplements") or []
    user = f"""# TARGET JOURNAL
{journal['display_name']} ({journal['journal_id']})

# OFFICIAL SCOPE SOURCES
{sources}

# OFFICIAL VERBATIM SCOPE EXCERPTS — primary authority for scope_fit
{_canonical_json(journal['_official_excerpts'])}

# SOURCE-GROUNDED SCOPE NORMALIZATION — auxiliary summary, not a substitute for excerpts
{journal['_scope_text']}

# OFFICIAL SCOPE SUPPLEMENTS
{_canonical_json(official_supplements)}

# OFFICIAL CONTENT/ARTICLE-TYPE RULES — authoritative for genre_fit
Capture completeness: {journal['_content_capture_completeness']}
Absence is not exclusion: {journal['_absence_is_not_exclusion']}
Capture status: {journal['_content_capture_status']}
{_canonical_json(journal['_content_types'])}

# JOURNAL TIER BARS — significance and novelty_magnitude only
{_canonical_json({k: v for k, v in tier.items() if not k.startswith('_')})}
Normalized significance concern: {tier['_required_concern']}
Normalized novelty_magnitude bar: {tier['_required_bar']}

# SUBMITTED MANUSCRIPT
MANUSCRIPT ID: {pack.get('id', '')}
TITLE: {pack.get('title', '')}
ABSTRACT: {pack.get('abstract', '')}

FULL TEXT (the manuscript's own full text; quote verbatim from here when needed):
{pack.get('fulltext', '') or '(full text not supplied)'}

# GLOBAL RETRIEVAL PACK
Corpus: {CORPUS_DESCRIPTION}
Cut-off year: {pack.get('cutoff_year', '')}
Self exclusions: {_canonical_json(pack.get('excluded_self', []))}
Pack SHA-256: {pack_hash_before}
Hits below are the original shared pack in original order. They have not been filtered,
reserved, re-ranked or weighted for {journal['display_name']}.

{chr(10).join(hit_block(hit, i) for i, hit in enumerate(hits, 1))}
"""
    if sha256_json(pack) != pack_hash_before:
        raise RuntimeError("Prompt construction mutated the retrieval pack")
    metadata = {
        "retrieval_pack_sha256": pack_hash_before,
        "journal_config_sha256": sha256_json(
            {k: v for k, v in journal.items() if not k.startswith("_")}
        ),
        "tier_config_sha256": sha256_json(
            {k: v for k, v in tier.items() if not k.startswith("_")}
        ),
        "scope_snapshot_sha256": sha256_json(journal.get("_snapshot")),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], metadata


_PROVENANCE_TEXT_FIELDS = {
    "official_quote",
    "evidence_quote",
    "genre_evidence",
    "manuscript_genre_evidence",
}


def _iter_free_text(value: Any, path: str = "assessment") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            # Verbatim fields are validated against their source below.  They can
            # legitimately quote terms such as policy recommendations or decision-making;
            # those source words are not the model's editorial conclusion.
            if key in _PROVENANCE_TEXT_FIELDS:
                continue
            yield from _iter_free_text(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_free_text(child, f"{path}[{index}]")


def _normalise_evidence(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _text_contains_verbatim(haystack: str, quote: str) -> bool:
    needle = _normalise_evidence(quote)
    return bool(needle) and needle in _normalise_evidence(haystack)


def _quote_has_minimum_substance(quote: str) -> bool:
    words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", quote)
    cjk_chars = re.findall(r"[\u3400-\u9fff]", quote)
    return len(words) >= 4 or len(cjk_chars) >= 12


def _quote_supports_contribution_mode(quote: str, mode: str) -> bool:
    if mode in {"unknown", "other"}:
        return True
    pattern = _CONTRIBUTION_MODE_LANGUAGE.get(mode)
    return bool(pattern and pattern.search(quote))


def _doi_map(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    answer: dict[str, dict[str, Any]] = {}
    for hit in pack.get("hits", []):
        doi = str(hit.get("doi", "")).strip().lower()
        if doi:
            answer[doi] = hit
    return answer


def _hit_text(hit: dict[str, Any]) -> str:
    return f"{hit.get('title', '')}\n{hit.get('abstract', '')}"


def _manuscript_text(pack: dict[str, Any]) -> str:
    """The manuscript's own citable text: title + abstract + full text (if supplied).

    Precedent full text is deliberately NOT included; the editor reads only the submitted
    manuscript's full text.  The full text is user-provided on the pack, never fetched here.
    """

    parts = [
        pack.get("title", ""),
        pack.get("abstract", ""),
        pack.get("fulltext", "") or "",
    ]
    return "\n".join(part for part in parts if part)


def _obvious_contribution_mode(text: str) -> str | None:
    """Return only high-confidence modes used to catch clear review mislabelling."""

    if _SYNTHESIS_LANGUAGE.search(text):
        return "synthesis_or_review"
    return None


def _pattern_keywords(pattern: "re.Pattern[str]", limit: int = 14) -> str:
    """Render a validator regex as the keyword list the model is actually required to use.

    Several evidence gates accept a quote only if it contains vocabulary belonging to the
    label the quote carries.  The prompt left that contract implicit and 16 of the first
    28 paid jobs died on it.  Deriving the hint from the very pattern the validator
    applies keeps the prompt and the gate from drifting apart.
    """

    body = re.sub(r"\(\?:", "", pattern.pattern).replace("(", "").replace(")", "")
    words = []
    for raw in body.split("|"):
        word = raw.replace(r"\s+", " ").replace(r"\s*", " ").replace("[ -]", "-")
        word = word.replace(r"\b", "").strip()
        if word and not word.startswith("?") and re.search(r"[A-Za-z一-鿿]", word):
            words.append(word)
    return ", ".join(words[:limit])


def _evidence_vocabulary_block(tier_id: str) -> str:
    """The lexical contract of the evidence gates, stated instead of left to guesswork."""

    modes = "\n".join(
        f"  - {name}: the cited excerpt must itself contain one of "
        f"[{_pattern_keywords(pattern)}]"
        for name, pattern in _CONTRIBUTION_MODE_LANGUAGE.items()
    )
    return (
        "Vocabulary the validator enforces. These are checks on the words inside your "
        "quotes, not style advice; an answer that fails them is rejected outright.\n"
        "* contribution_mode evidence: when you label the manuscript or a precedent with a "
        "mode, the verbatim excerpt you cite for that label must itself carry the mode's "
        "vocabulary. Pick the excerpt accordingly, or label the mode `unknown`.\n"
        f"{modes}\n"
        "* significance: if significance blocks, at least one finding's gap_to_concern must "
        "carry decorativeness / secondary-demonstration vocabulary, in words such as "
        f"[{_pattern_keywords(_SIGNIFICANCE_DECORATIVE_LANGUAGE_RE)}].\n"
        "* novelty_magnitude: if novelty_magnitude blocks, gap_to_bar must name a concrete "
        "magnitude shortfall, in words such as "
        f"[{_pattern_keywords(_MAGNITUDE_LANGUAGE_RE)}], and "
        "demonstrated_scope_or_boundary must name the limit the manuscript actually shows, "
        f"in words such as [{_pattern_keywords(_BOUNDARY_LANGUAGE, 12)}].\n"
        "* every official_quote is copied character for character from the excerpts given "
        "for that axis — genre_fit quotes only from the content-type excerpts, scope_fit "
        "quotes only from the scope excerpts — and is at least four words long.\n"
    )


def validate_assessment(
    assessment: dict[str, Any],
    pack: dict[str, Any],
    journal: dict[str, Any],
    tier: dict[str, Any],
) -> None:
    """Business validation beyond JSON Schema.

    Structured Outputs constrains shape.  This validator constrains provenance and the
    cross-field rules the schema cannot express.
    """

    if set(assessment) != set(AXIS_KEYS):
        raise ValueError(
            f"Assessment must contain exactly {AXIS_KEYS}; got {tuple(assessment)}"
        )
    for key in AXIS_KEYS:
        axis = assessment[key]
        if not isinstance(axis, dict) or not axis.get("verdict") or not axis.get("rationale"):
            raise ValueError(f"{key} must contain verdict and rationale")

    for path, text in _iter_free_text(assessment):
        if _ASSESSMENT_DECISION_LANGUAGE.search(text):
            raise ValueError(
                f"Assessment contains forbidden decision/action language at {path}"
            )

    allowed_ids = {
        "scope_fit": set(journal["_scope_source_ids"]),
        "genre_fit": set(journal["_content_source_ids"]),
    }
    for axis_name in ("scope_fit", "genre_fit"):
        axis = assessment[axis_name]
        if not axis.get("official_basis") or not axis.get("manuscript_basis"):
            raise ValueError(f"{axis_name} requires official and manuscript evidence")
        unknown = {
            item.get("source_id")
            for item in axis["official_basis"]
            if item.get("source_id") not in allowed_ids[axis_name]
        }
        if unknown:
            raise ValueError(f"{axis_name} cites unknown official source IDs: {unknown}")

    manuscript_text = _manuscript_text(pack)
    for axis_name in ("scope_fit", "genre_fit"):
        for item in assessment[axis_name]["manuscript_basis"]:
            quote = str(item.get("evidence_quote", "")).strip()
            if not _text_contains_verbatim(manuscript_text, quote):
                raise ValueError(
                    f"{axis_name} manuscript evidence is not a verbatim title/abstract/full-text excerpt: {quote!r}"
                )

    official_scope_quotes = "\n".join(
        str(item.get("text", "")) for item in journal["_official_excerpts"]
    )
    for item in assessment["scope_fit"]["official_basis"]:
        quote = str(item.get("official_quote", "")).strip()
        if not _text_contains_verbatim(official_scope_quotes, quote):
            raise ValueError(
                "scope_fit official_quote must be copied from an official verbatim excerpt"
            )
    if assessment["scope_fit"]["verdict"] == "block":
        boundary_quotes = [
            str(item.get("official_quote", ""))
            for item in assessment["scope_fit"]["official_basis"]
        ]
        if not any(_SCOPE_DOMAIN_LANGUAGE.search(quote) for quote in boundary_quotes):
            raise ValueError(
                "scope_fit block requires a verbatim official excerpt that directly states "
                "a subject/remit boundary; quality language alone is insufficient"
            )

    official_content_text = "\n".join(
        str(item.get("text", ""))
        for item in journal["_content_official_excerpts"]
        if isinstance(item, dict)
    )
    if not official_content_text.strip():
        raise ValueError("Journal snapshot has no canonical content_types.official_excerpts")
    for item in assessment["genre_fit"]["official_basis"]:
        quote = str(item.get("official_quote", "")).strip()
        if not _text_contains_verbatim(official_content_text, quote):
            raise ValueError(
                "genre_fit official_quote must be copied from captured content-type evidence"
            )
    if assessment["genre_fit"]["verdict"] == "block" and not any(
        _GENRE_RULE_LANGUAGE.search(str(item.get("official_quote", "")))
        for item in assessment["genre_fit"]["official_basis"]
    ):
        raise ValueError(
            "genre_fit block requires an explicit official content-type rule; quality "
            "language alone is insufficient"
        )
    if (
        assessment["genre_fit"]["verdict"] == "block"
        and journal["_absence_is_not_exclusion"]
        and not journal["_content_explicit_exclusions"]
    ):
        raise ValueError(
            "genre_fit cannot block from a partial conservative capture without an "
            "explicit official exclusion or restriction"
        )

    if assessment["genre_fit"]["verdict"] not in {"pass", "block"}:
        raise ValueError("genre_fit supports pass/block only")

    novelty = assessment["novelty_increment"]
    comparisons = novelty.get("nearest_same_genre_precedents") or []
    if not comparisons:
        raise ValueError("novelty_increment requires at least one genre-aware comparison")
    hits_by_doi = _doi_map(pack)
    cited = list(novelty.get("direct_precedents") or []) + list(comparisons)
    for item in cited:
        doi = str(item.get("doi", "")).strip().lower()
        if doi not in hits_by_doi:
            raise ValueError(f"Novelty assessment cites DOI outside retrieval pack: {doi}")
    for item in novelty.get("direct_precedents") or []:
        doi = str(item.get("doi", "")).strip().lower()
        quote = str(item.get("evidence_quote", "")).strip()
        if not _text_contains_verbatim(_hit_text(hits_by_doi[doi]), quote):
            raise ValueError(
                f"Direct precedent {doi} evidence_quote is not from that DOI's title/abstract"
            )
        if not _quote_has_minimum_substance(quote):
            raise ValueError(
                f"Direct precedent {doi} evidence_quote is too short or general to ground provenance"
            )

    # Title + abstract only, like the precedents: any full text mentions "a comprehensive
    # review of ..." somewhere, which would force every research paper to be labelled a review.
    manuscript_obvious_mode = _obvious_contribution_mode(_hit_text(pack))
    for item in comparisons:
        doi = str(item.get("doi", "")).strip().lower()
        hit_text = _hit_text(hits_by_doi[doi])
        manuscript_genre_quote = str(item.get("manuscript_genre_evidence", "")).strip()
        precedent_genre_quote = str(item.get("genre_evidence", "")).strip()
        if not _text_contains_verbatim(manuscript_text, manuscript_genre_quote):
            raise ValueError(
                "same-genre comparison manuscript_genre_evidence is not from the "
                "submitted title/abstract/full text"
            )
        if not _text_contains_verbatim(hit_text, precedent_genre_quote):
            raise ValueError(
                f"Same-genre comparison {doi} genre_evidence is not from that DOI's "
                "title/abstract"
            )
        manuscript_mode = item.get("manuscript_genre")
        precedent_mode = item.get("precedent_genre")
        precedent_obvious_mode = _obvious_contribution_mode(hit_text)
        if manuscript_obvious_mode and manuscript_mode != manuscript_obvious_mode:
            raise ValueError(
                f"Manuscript is clearly {manuscript_obvious_mode} but was labelled {manuscript_mode}"
            )
        if precedent_obvious_mode and precedent_mode != precedent_obvious_mode:
            raise ValueError(
                f"DOI {doi} is clearly {precedent_obvious_mode} but was labelled {precedent_mode}"
            )
        if not _quote_supports_contribution_mode(manuscript_genre_quote, str(manuscript_mode)):
            raise ValueError(
                "manuscript_genre_evidence does not explicitly support its contribution mode"
            )
        if not _quote_supports_contribution_mode(precedent_genre_quote, str(precedent_mode)):
            raise ValueError(
                f"DOI {doi} genre_evidence does not explicitly support its contribution mode"
            )
        if item.get("genre_match") == "same":
            if (
                manuscript_mode == "unknown"
                or precedent_mode == "unknown"
                or manuscript_mode != precedent_mode
            ):
                raise ValueError(
                    "genre_match=same requires identical, non-unknown contribution modes"
                )
    if novelty["verdict"] == "block":
        if not novelty.get("direct_precedents"):
            raise ValueError("novelty block requires at least one direct_precedent")
        if not any(item.get("genre_match") == "same" for item in comparisons):
            raise ValueError("novelty block requires a same-genre precedent comparison")
        if not any(
            item.get("genre_match") == "same_genre"
            for item in novelty.get("direct_precedents", [])
        ):
            raise ValueError("novelty block direct precedent must be marked same_genre")
        direct_same_dois = {
            str(item.get("doi", "")).strip().lower()
            for item in novelty.get("direct_precedents", [])
            if item.get("genre_match") == "same_genre"
        }
        comparison_same_dois = {
            str(item.get("doi", "")).strip().lower()
            for item in comparisons
            if item.get("genre_match") == "same"
        }
        if not direct_same_dois.intersection(comparison_same_dois):
            raise ValueError(
                "novelty block direct precedent must match a same-genre comparison by DOI"
            )

    # The novelty_increment verdict must be a monotonic function of the delta to the
    # closest retrieved precedents.  This is what makes retrieval load-bearing: a limited
    # delta (method transfer / new site or dataset / config or scale / validation-only)
    # forbids `pass`, and a `block` must be grounded in such a limited delta rather than a
    # free-floating "insufficient novelty" judgement.
    delta_types = [
        item.get("delta_type")
        for item in comparisons
        if item.get("genre_match") in {"same", "adjacent"}
    ]
    if novelty["verdict"] == "pass":
        limited = sorted({dt for dt in delta_types if dt in _LIMITED_DELTA_TYPES})
        if limited:
            raise ValueError(
                "novelty_increment cannot be pass when a same/adjacent-genre comparison "
                "has a limited delta "
                f"({', '.join(_LIMITED_DELTA_TYPES)}): {', '.join(limited)}"
            )
    if novelty["verdict"] == "block":
        if not any(dt in _ALREADY_DONE_DELTA_TYPES for dt in delta_types):
            raise ValueError(
                "novelty_increment block must be grounded in a same/adjacent-genre comparison "
                "whose delta is validation_only (the contribution has already been made); a "
                "method_transfer, site_or_dataset or configuration_or_scale increment is warn, "
                "and its sufficiency is judged by novelty_magnitude"
            )

    significance = assessment["significance"]
    if significance.get("required_concern") != tier["_required_concern"]:
        raise ValueError("significance.required_concern must copy the frozen concern verbatim")
    if not significance.get("manuscript_findings"):
        raise ValueError("significance requires manuscript_findings")
    for item in significance["manuscript_findings"]:
        quote = str(item.get("evidence_quote", "")).strip()
        if not _text_contains_verbatim(manuscript_text, quote):
            raise ValueError(
                "significance manuscript evidence must be a verbatim "
                "title/abstract/full-text excerpt"
            )

    magnitude = assessment["novelty_magnitude"]
    if magnitude.get("tier_id") != journal["tier_id"]:
        raise ValueError(
            f"novelty_magnitude used {magnitude.get('tier_id')}, expected {journal['tier_id']}"
        )
    if magnitude.get("required_bar") != tier["_required_bar"]:
        raise ValueError(
            "novelty_magnitude.required_bar must copy the frozen tier bar verbatim"
        )
    if not magnitude.get("manuscript_findings"):
        raise ValueError("novelty_magnitude requires manuscript_findings")
    for item in magnitude["manuscript_findings"]:
        quote = str(item.get("evidence_quote", "")).strip()
        if not _text_contains_verbatim(manuscript_text, quote):
            raise ValueError(
                "novelty_magnitude manuscript evidence must be a verbatim "
                "title/abstract/full-text excerpt"
            )

    # Delegate the post-novelty block rules (magnitude shortfall, demonstrated boundary,
    # decorativeness, generic-prestige-gap rejection) to decision_engine so the two
    # validators cannot drift apart.
    _core_validate_assessment(assessment)


def build_profile_messages(
    pack: dict[str, Any],
    journal: dict[str, Any],
    profile: Any,
) -> list[dict[str, str]]:
    """Build the physically separate, reference-only pass-2 prompt."""

    user = f"""# MANUSCRIPT IDENTITY
Journal: {journal['display_name']}
Manuscript: {pack.get('id', '')} | {pack.get('title', '')}

# TOPIC PROFILE — 仅供参考
{_canonical_json(profile)}

Write a short Chinese background note. Keep recent publication density and historical
citation performance separate. State what a reviewer may inspect more carefully, but do
not express a verdict or editorial action."""
    return [
        {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def validate_profile_note(note: dict[str, Any]) -> None:
    expected = {"profile_note", "review_attention", "reference_only_acknowledged"}
    if set(note) != expected:
        raise ValueError(f"Profile pass must contain exactly {sorted(expected)}")
    if note.get("reference_only_acknowledged") is not True:
        raise ValueError("Profile pass did not acknowledge reference-only status")
    for field in ("profile_note", "review_attention"):
        text = note.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Profile pass {field} must be non-empty")
        if _PROFILE_DECISION_LANGUAGE.search(text):
            raise ValueError(
                f"Profile pass {field} contains forbidden decision language"
            )


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


# Model providers. OpenAI enforces the JSON schema server-side; providers that only offer a
# JSON mode get the schema in the prompt and are checked against it here, and a mismatch goes
# through the same repair loop as an evidence-gate failure.
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": None, "key_env": ("OPENAI_API_KEY_default", "OPENAI_API_KEY"),
               "json_schema": True, "reasoning_effort": True},
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": ("DEEPSEEK_API_KEY",),
                 "json_schema": False, "reasoning_effort": False, "max_tokens": 32768},
}


def provider_for(model: str, explicit: str | None = None) -> str:
    if explicit and explicit != "auto":
        return explicit
    return "deepseek" if model.lower().startswith("deepseek") else "openai"


def make_client(provider: str) -> Any:
    from openai import OpenAI

    spec = PROVIDERS[provider]
    api_key = next((os.environ[k] for k in spec["key_env"] if os.environ.get(k)), None)
    if not api_key:
        raise RuntimeError(f"none of {spec['key_env']} is readable for provider {provider}")
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 900, "max_retries": 3}
    if spec["base_url"]:
        kwargs["base_url"] = spec["base_url"]
    return OpenAI(**kwargs)


class SchemaMismatchError(ValueError):
    """A JSON-mode answer that does not match the schema (repairable, like an evidence gate)."""


def _call_structured(
    client: Any,
    model: str,
    reasoning_effort: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    provider: str = "openai",
) -> tuple[dict[str, Any], dict[str, int]]:
    spec = PROVIDERS[provider]
    kwargs: dict[str, Any] = {"model": model}
    if spec["reasoning_effort"]:
        kwargs["reasoning_effort"] = reasoning_effort
    if spec.get("max_tokens"):
        kwargs["max_tokens"] = spec["max_tokens"]
    if spec["json_schema"]:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": schema}
    else:
        kwargs["response_format"] = {"type": "json_object"}
        messages = messages + [{
            "role": "user",
            "content": "Return one JSON object only, with no other text. It must be valid "
            "against this JSON Schema (all listed properties required, no others):\n"
            + json.dumps(schema["schema"], ensure_ascii=False),
        }]
    # An overloaded provider (seen with DeepSeek at peak hours, 2026-10-15) holds the
    # connection and then returns a body without choices; json.loads/indexing on it raised an
    # opaque "'NoneType' object is not subscriptable". Back off and retry, then fail clearly.
    for wait in (30, 120, 300, None):
        response = client.chat.completions.create(messages=messages, **kwargs)
        if getattr(response, "choices", None):
            break
        if wait is None:
            raise ProviderOverloadedError(
                f"{provider} returned no choices four times (provider overloaded?); "
                "rerun with the same --run-dir later, ideally off-peak"
            )
        time.sleep(wait)
    choice = response.choices[0]
    content = choice.message.content
    if not content:
        # a refusal or a length cut-off returns no JSON; json.loads(None) would raise a
        # TypeError that nothing downstream expects
        raise EmptyResponseError(
            f"empty response (finish_reason={getattr(choice, 'finish_reason', None)!r}, "
            f"refusal={getattr(choice.message, 'refusal', None)!r})"
        )
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SchemaMismatchError(f"answer is not valid JSON: {exc}") from exc
    if not spec["json_schema"]:
        import jsonschema

        try:
            jsonschema.validate(data, schema["schema"])
        except jsonschema.ValidationError as exc:
            where = "/".join(str(p) for p in exc.absolute_path) or "(top level)"
            raise SchemaMismatchError(f"schema mismatch at {where}: {exc.message}") from exc
    return data, _usage_dict(response)


class EmptyResponseError(RuntimeError):
    """The model returned no content (refusal or truncation)."""


class ProviderOverloadedError(RuntimeError):
    """The provider kept returning responses without choices (overload)."""


def _job_file(run_dir: Path, kind: str, key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key.replace("||", "__"))
    return run_dir / kind / f"{safe}.json"


def _save_job(path: Path, record: dict[str, Any]) -> None:
    """Write one finished job at once, atomically, so a later crash cannot lose it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_job(path: Path) -> dict[str, Any] | None:
    return _read_json(path) if path.exists() else None


def discover_packs(pack_dir: Path, selected: list[str] | None) -> dict[str, dict[str, Any]]:
    if selected:
        paths = [pack_dir / f"pack_{name}.json" for name in selected]
    else:
        paths = sorted(pack_dir.glob("pack_*.json"))
    packs: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        pack = _read_json(path)
        pack_id = str(pack.get("id") or path.stem.removeprefix("pack_"))
        if pack_id in packs:
            raise ValueError(f"Duplicate manuscript pack id: {pack_id}")
        packs[pack_id] = pack
    if not packs:
        raise ValueError(f"No pack_*.json files found in {pack_dir}")
    return packs


def _select_journals(
    registry: dict[str, dict[str, Any]], selected: list[str] | None
) -> dict[str, dict[str, Any]]:
    if not selected:
        return registry
    aliases: dict[str, str] = {}
    for journal_id, record in registry.items():
        aliases[journal_id.lower()] = journal_id
        aliases[record["display_name"].lower()] = journal_id
    answer: dict[str, dict[str, Any]] = {}
    for name in selected:
        journal_id = aliases.get(name.lower())
        if journal_id is None:
            raise KeyError(f"Unknown journal selection: {name}")
        answer[journal_id] = registry[journal_id]
    return answer


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _profile_for(
    raw_profiles: Any,
    manuscript_id: str,
    journal: dict[str, Any],
) -> Any:
    """Resolve one manuscript-topic x journal profile without guessing its Topic."""

    if isinstance(raw_profiles, dict) and "profiles" in raw_profiles:
        raw_profiles = raw_profiles["profiles"]
    if not isinstance(raw_profiles, dict):
        raise ValueError("Profile file must be a mapping, optionally under 'profiles'")

    flat_key = f"{manuscript_id}||{journal['journal_id']}"
    if flat_key in raw_profiles:
        return raw_profiles[flat_key]

    manuscript_profiles = raw_profiles.get(manuscript_id)
    if isinstance(manuscript_profiles, dict):
        if journal["journal_id"] in manuscript_profiles:
            return manuscript_profiles[journal["journal_id"]]

    raise KeyError(
        f"No exact profile for manuscript/journal combination "
        f"{manuscript_id}||{journal['journal_id']}"
    )


def _build_jobs(
    packs: dict[str, dict[str, Any]], journals: dict[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    return [(pack_id, journal_id) for pack_id in packs for journal_id in journals]


def dry_run(
    packs: dict[str, dict[str, Any]],
    journals: dict[str, dict[str, Any]],
    tiers: dict[str, dict[str, Any]],
    raw_profiles: Any | None,
) -> dict[str, Any]:
    jobs = _build_jobs(packs, journals)
    pack_hashes_by_manuscript: dict[str, set[str]] = {key: set() for key in packs}
    prompt_rows = []
    for pack_id, journal_id in jobs:
        journal = journals[journal_id]
        tier = tiers[journal["tier_id"]]
        messages, metadata = build_decision_messages(packs[pack_id], journal, tier)
        pack_hashes_by_manuscript[pack_id].add(metadata["retrieval_pack_sha256"])
        prompt_rows.append(
            {
                "manuscript_id": pack_id,
                "journal_id": journal_id,
                "tier_id": journal["tier_id"],
                "hits": len(packs[pack_id]["hits"]),
                "retrieval_pack_sha256": metadata["retrieval_pack_sha256"],
                "prompt_sha256": sha256_json(messages),
            }
        )
        if raw_profiles is not None:
            profile = _profile_for(
                raw_profiles,
                pack_id,
                journal,
            )
            build_profile_messages(packs[pack_id], journal, profile)

    unstable = {key: hashes for key, hashes in pack_hashes_by_manuscript.items() if len(hashes) != 1}
    if unstable:
        raise RuntimeError(f"Different retrieval packs reached journals: {unstable}")
    return {
        "mode": "dry-run",
        "paid_api_calls": 0,
        "manuscripts": len(packs),
        "journals": len(journals),
        "decision_jobs": len(jobs),
        "profile_jobs": len(jobs) if raw_profiles is not None else 0,
        "schema_top_level": list(ASSESSMENT_SCHEMA["schema"]["properties"]),
        "rows": prompt_rows,
    }


def execute(
    packs: dict[str, dict[str, Any]],
    journals: dict[str, dict[str, Any]],
    tiers: dict[str, dict[str, Any]],
    model: str,
    reasoning_effort: str,
    workers: int,
    raw_profiles: Any | None,
    run_dir: Path,
    provider: str = "openai",
    repair_attempts: int = EVIDENCE_REPAIR_ATTEMPTS,
) -> dict[str, Any]:
    """Run every manuscript x journal job.

    Each finished job is written to <run_dir>/decisions/ (and its profile note to
    <run_dir>/profiles/) the moment it completes; a rerun with the same run_dir skips them.
    A job that raises is recorded under "errors" and retried on the next run; it never takes
    the other, already-paid jobs down with it.
    """
    client = make_client(provider)
    jobs = _build_jobs(packs, journals)
    errors: dict[str, str] = {}

    def run_decision_safe(job: tuple[str, str]) -> tuple[str, dict[str, Any] | None]:
        key = f"{job[0]}||{job[1]}"
        path = _job_file(run_dir, "decisions", key)
        done = _load_job(path)
        if done is not None:
            return key, done
        try:
            key, record = run_decision(job)
        except Exception as exc:  # noqa: BLE001 — isolate the failure, keep the batch
            errors[key] = f"{type(exc).__name__}: {exc}"
            return key, None
        _save_job(path, record)
        return key, record

    def run_decision(job: tuple[str, str]) -> tuple[str, dict[str, Any]]:
        pack_id, journal_id = job
        pack = packs[pack_id]
        journal = journals[journal_id]
        tier = tiers[journal["tier_id"]]
        messages, metadata = build_decision_messages(pack, journal, tier)
        key = f"{pack_id}||{journal_id}"
        total = {"prompt_tokens": 0, "completion_tokens": 0}
        attempts: list[str] = []

        # An evidence gate rejects a paraphrased quote.  That is a repairable output error,
        # not a reason to abandon the other jobs: hand the validator's own message back to
        # the model, and if it still cannot comply, record the failure so the run reports
        # it instead of dying on it.
        for attempt in range(1, repair_attempts + 1):
            try:
                assessment, usage = _call_structured(
                    client,
                    model,
                    reasoning_effort,
                    messages,
                    ASSESSMENT_SCHEMA,
                    provider,
                )
            except SchemaMismatchError as exc:
                # JSON-mode providers only: the answer did not fit the schema. Same repair
                # loop as an evidence-gate failure, minus the (unusable) previous answer.
                attempts.append(f"attempt {attempt}: {exc}")
                if attempt == repair_attempts:
                    raise
                messages = messages + [{
                    "role": "user",
                    "content": f"Your previous answer was rejected: {exc}\n\n"
                    "Answer the whole schema again as one JSON object.",
                }]
                continue
            for field in total:
                total[field] += int((usage or {}).get(field, 0) or 0)
            try:
                validate_assessment(assessment, pack, journal, tier)
                decision = derive_decision(assessment)
            except (ValueError, AssessmentValidationError) as exc:
                attempts.append(f"attempt {attempt}: {exc}")
                if attempt == repair_attempts:
                    return key, {
                        "manuscript_id": pack_id,
                        "journal_id": journal_id,
                        "journal_name": journal["display_name"],
                        "tier_id": journal["tier_id"],
                        **metadata,
                        "assessment": assessment,
                        "decision": {"decision": "校验失败", "validation_errors": attempts},
                        "usage": total,
                    }
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(assessment, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            "Your previous answer was rejected by the evidence validator:\n"
                            f"{exc}\n\n"
                            "Answer the whole schema again. Every official_quote must be "
                            "copied character for character from the official excerpts "
                            "supplied above, and from the section that axis belongs to: "
                            "genre_fit quotes come only from the content-type excerpts, "
                            "scope_fit quotes only from the scope excerpts. Do not "
                            "translate, shorten, merge or paraphrase a quote. If no "
                            "quotable excerpt supports a block, do not block."
                        ),
                    },
                ]
                continue
            record = {
                "manuscript_id": pack_id,
                "journal_id": journal_id,
                "journal_name": journal["display_name"],
                "tier_id": journal["tier_id"],
                **metadata,
                "assessment": assessment,
                "decision": decision,
                "usage": total,
            }
            if attempts:
                record["evidence_repair"] = attempts
            return key, record

    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for key, record in pool.map(run_decision_safe, jobs):
            if record is None:
                print(f"decision {key}: FAILED — {errors[key]}", flush=True)
                continue
            results[key] = record
            note = " (repaired)" if record.get("evidence_repair") else ""
            print(
                f"decision {record['manuscript_id']} -> {record['journal_name']}: "
                f"{record['decision']['decision']}{note}",
                flush=True,
            )

    # Physical pass boundary: no profile was available above this line.  The profile call
    # receives no assessment or decision at all and therefore cannot replace that field.
    if raw_profiles is not None:
        def run_profile(job: tuple[str, str]) -> tuple[str, dict[str, Any] | None]:
            pack_id, journal_id = job
            key = f"{pack_id}||{journal_id}"
            path = _job_file(run_dir, "profiles", key)
            done = _load_job(path)
            if done is not None:
                return key, done
            try:
                journal = journals[journal_id]
                profile = _profile_for(raw_profiles, pack_id, journal)
                messages = build_profile_messages(packs[pack_id], journal, profile)
                note, usage = _call_structured(client, model, "medium", messages, PROFILE_SCHEMA,
                                               provider)
                validate_profile_note(note)
            except Exception as exc:  # noqa: BLE001 — a profile note is optional
                errors[f"profile:{key}"] = f"{type(exc).__name__}: {exc}"
                return key, None
            item = {"note": note, "usage": usage}
            _save_job(path, item)
            return key, item

        profile_jobs = [job for job in jobs if f"{job[0]}||{job[1]}" in results]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for key, item in pool.map(run_profile, profile_jobs):
                if item is None:
                    print(f"profile {key}: FAILED — {errors[f'profile:{key}']}", flush=True)
                    continue
                frozen = deepcopy(results[key]["decision"])
                results[key]["profile_pass"] = {
                    "ui_label": PROFILE_UI_LABEL,
                    "content": item["note"],
                }
                results[key]["profile_usage"] = item["usage"]
                if results[key]["decision"] != frozen:
                    raise RuntimeError("Profile pass changed a frozen decision")

    # Integrity problems are reported, not raised: raising here would discard the paid results.
    problems: list[str] = []
    pack_hashes: dict[str, set[str]] = {key: set() for key in packs}
    for record in results.values():
        pack_hashes[record["manuscript_id"]].add(record["retrieval_pack_sha256"])
    for manuscript_id, hashes in pack_hashes.items():
        if len(hashes) > 1:
            problems.append(f"{manuscript_id} did not use one identical global pack across journals")

    return {
        "version": "editor-v3",
        "model": model,
        "provider": provider,
        "repair_attempts": repair_attempts,
        "decision_is_mechanical": True,
        "profile_is_reference_only": True,
        "run_dir": str(run_dir),
        "results": results,
        "errors": errors,
        "integrity_problems": problems,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Make paid API calls. Without this flag, perform a zero-call dry run.",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--packs", help="Comma-separated pack IDs; default: all pack_*.json")
    parser.add_argument(
        "--journals", help="Comma-separated journal IDs or exact display names; default: all"
    )
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="e.g. gpt-5.6-sol, deepseek-v4-pro, deepseek-flash")
    parser.add_argument("--repair-attempts", type=int, default=EVIDENCE_REPAIR_ATTEMPTS,
                        help="answers allowed per job before it is recorded as 校验失败")
    parser.add_argument("--provider", choices=["auto", *PROVIDERS], default="auto",
                        help="default: inferred from the model name")
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "xhigh"],
        default="high",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Where each finished job is saved (default: runs/<timestamp>). Reusing a run "
        "directory resumes it: finished jobs are not paid for again.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Combined results file (default: <run-dir>/editor_results.json). An existing "
        "file is never overwritten unless --overwrite is given.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = load_journal_registry(args.registry)
    tiers = load_tier_bars(args.tiers)
    validate_journal_tier_membership(registry, tiers, args.tiers)
    journals = _select_journals(registry, _split_csv(args.journals))
    for journal in journals.values():
        if journal["tier_id"] not in tiers:
            raise KeyError(
                f"Journal {journal['journal_id']} references undefined tier {journal['tier_id']}"
            )
    packs = discover_packs(args.pack_dir, _split_csv(args.packs))
    raw_profiles = _read_json(args.profile_file) if args.profile_file else None

    if not args.execute:
        report = dry_run(packs, journals, tiers, raw_profiles)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    run_dir = args.run_dir or HERE / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = args.output or run_dir / "editor_results.json"
    if output_path.exists() and not args.overwrite and output_path.parent != run_dir:
        # results files outside a run directory are records of earlier runs: never clobber them
        raise FileExistsError(f"{output_path} exists; choose another --output or pass --overwrite")
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Run directory: {run_dir}", flush=True)
    output = execute(
        packs,
        journals,
        tiers,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        workers=args.workers,
        raw_profiles=raw_profiles,
        run_dir=run_dir,
        provider=provider_for(args.model, args.provider),
        repair_attempts=args.repair_attempts,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".part")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(output_path)
    print(f"Saved: {output_path} ({len(output['results'])} decisions)")
    for key, message in output["errors"].items():
        print(f"ERROR {key}: {message}")
    for message in output["integrity_problems"]:
        print(f"INTEGRITY {message}")
    return 1 if output["errors"] or output["integrity_problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
