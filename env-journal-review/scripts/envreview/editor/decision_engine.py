"""Deterministic decision engine for the v3 handling-editor stage.

The LLM is allowed to assess evidence, but it is deliberately not allowed to
choose a decision.  ``derive_decision`` validates the five assessment axes and
maps them to exactly one of ``送审`` or ``拒稿``.

Expected input shape (non-blocking axes may omit their evidence-only fields)::

    {
      "scope_fit": {"verdict": "pass|warn|block", "rationale": "..."},
      "genre_fit": {"verdict": "pass|block", "rationale": "..."},
      "novelty_increment": {
        "verdict": "pass|warn|block",
        "rationale": "...",
        "direct_precedents": [
          {
            "doi": "10....",
            "evidence": "...",
            "relationship": "...",
            "genre_match": "same_genre|unknown"
          }
        ]
      },
      "significance": {
        "verdict": "pass|warn|block",
        "rationale": "...",
        "required_concern": "...",
        "manuscript_findings": [
          {
            "source_locator": "abstract/contribution statement/...",
            "evidence_quote": "...",
            "positive_contribution": "what the manuscript's main contribution actually is",
            "centrality": "central|secondary_demonstration|supporting_discipline|unknown",
            "gap_to_concern": "why the core contribution is not central to the journal's concern"
          }
        ]
      },
      "novelty_magnitude": {
        "verdict": "pass|warn|block",
        "rationale": "...",
        "tier_id": "T1|T2|T3",
        "required_bar": "...",
        "manuscript_findings": [
          {
            "source_locator": "abstract/contribution statement/...",
            "evidence_quote": "...",
            "positive_finding": "what the manuscript actually does",
            "demonstrated_scope_or_boundary": "...",
            "gap_to_bar": "the specific magnitude gap between that finding and the tier bar"
          }
        ]
      }
    }

Evidence requirements are asymmetric on purpose.  A novelty ``block`` needs a
named, direct DOI precedent; a significance ``block`` needs a positive,
manuscript-grounded contribution and a concrete claim that it is decorative or a
supporting discipline rather than central; a novelty-magnitude ``block`` needs a
positive, manuscript-grounded finding and a specific magnitude comparison with
the frozen tier bar.  Merely saying that a paper is "not exceptional" can never
trigger a desk rejection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


AXIS_PRECEDENCE = (
    "scope_fit",
    "genre_fit",
    "novelty_increment",
    "significance",
    "novelty_magnitude",
)

ALLOWED_VERDICTS = {
    "scope_fit": frozenset({"pass", "warn", "block"}),
    "genre_fit": frozenset({"pass", "block"}),
    "novelty_increment": frozenset({"pass", "warn", "block"}),
    "significance": frozenset({"pass", "warn", "block"}),
    "novelty_magnitude": frozenset({"pass", "warn", "block"}),
}

ALLOWED_TIERS = frozenset({"T1", "T2", "T3"})

# How the model names whether the contribution is central to the journal's core
# concern.  A significance block must land on one of the non-central values.
ALLOWED_CENTRALITY = frozenset(
    {"central", "secondary_demonstration", "supporting_discipline", "unknown"}
)

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_FORBIDDEN_DECISION_KEYS = frozenset(
    {
        "decision",
        "editorial_decision",
        "final_decision",
        "decision_driver",
        "primary_blocking_axis",
        "blocking_axes",
        "transfer",
        "transfer_target",
        "recommendation",
        "action",
        "outcome",
    }
)

# A tier rejection must state what the manuscript positively contributes.  These
# expressions are conclusions about prestige, not positive manuscript findings.
_NEGATIVE_FINDING_RE = re.compile(
    r"(?:\b(?:not|no|lacks?|lacking|fails?|failed|without|insufficient)\b|"
    r"不够|不足|缺乏|没有|未能|未达到|并非)",
    re.IGNORECASE,
)

_GENERIC_GAP_PHRASES = {
    "not exceptional",
    "not sufficiently exceptional",
    "not innovative enough",
    "not sufficiently innovative",
    "insufficient novelty",
    "not high impact",
    "not high impact enough",
    "does not meet the bar",
    "does not meet the journal bar",
    "not suitable for this tier",
    "不够卓越",
    "不够突出",
    "不够创新",
    "创新性不足",
    "影响力不足",
    "不够高影响力",
    "未达到顶刊水平",
    "未达到期刊门槛",
    "不符合该层级",
}

# Catch extended versions that evade exact-phrase matching, for example
# "This work is not exceptional enough for this journal."  These are prestige
# conclusions, not comparisons between a manuscript finding and a frozen bar.
_GENERIC_PRESTIGE_GAP_RE = re.compile(
    r"(?:"
    r"\b(?:this\s+)?(?:work|paper|manuscript|study|contribution)\s+"
    r"(?:is|seems|appears)?\s*not\s+(?:sufficiently\s+)?"
    r"(?:exceptional|innovative|significant|impactful|novel)"
    r"(?:\s+enough)?(?:\s+for\s+(?:this|the|a)?\s*(?:journal|tier|venue))?\b"
    r"|\binsufficient\s+(?:impact|novelty|innovation|significance)"
    r"(?:\s+for\s+(?:this|the|a)?\s*(?:journal|tier|venue))?\b"
    r"|\bnot\s+enough\s+for\s+(?:this|the|a)?\s*(?:journal|tier|venue)\b"
    r"|\bnot\s+(?:good|strong|important|impactful|novel)\s+enough\s+"
    r"for\s+(?:this|the|a)?\s*(?:journal|tier|venue)\b"
    r"|\b(?:does\s+not|fails?\s+to)\s+meet\s+"
    r"(?:(?:this|the|a)\s+)?(?:t[123]\s+)?"
    r"(?:(?:journal|tier|venue)(?:'s)?\s+)?(?:bar|standard|threshold)\b"
    r")",
    re.IGNORECASE,
)

# A concrete novelty-magnitude comparison must name the magnitude of the increment
# (incremental vs substantial, or its scope/transferability) AND the demonstrated
# boundary of this manuscript.  Magnitude replaces the old contribution-TYPE
# dimension, so a methods or informatics paper is no longer structurally excluded.
# The bilingual vocabulary is intentionally small and concrete.
_MAGNITUDE_LANGUAGE_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9])(?:increment(?:al)?|routine|modest|marginal|small|minor|narrow|"
    r"gradual|step[- ]wise|limited|confined|"
    r"transferab(?:le|ility)?|generali[sz](?:e|ed|able|ation)|applicability|scope|breadth|scale|reach|"
    r"substantial|conceptual|significant|fundamental|broad|transformative|paradigm|advance|understanding)(?![A-Za-z0-9])"
    r"|增量|渐进|常规|有限|局限|微小|边际|次要|实质性|概念性|重大|根本性|"
    r"范式|泛化|推广|广泛|突破|推进|可迁移|迁移性|适用|适用范围|尺度|广度|覆盖面|认识"
    r")",
    re.IGNORECASE,
)

# Why a significance block: the contribution is decorative or a supporting
# discipline rather than central to the journal's core concern.  Vocabulary comes
# from the editorials (secondary demonstration, supporting discipline, relevance
# asserted only in motivation/conclusion, connection not established).
_SIGNIFICANCE_DECORATIVE_LANGUAGE_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9])(?:secondary|decorative|peripheral|tangential|auxiliary|"
    r"demonstration|supporting[- ]discipline|"
    r"motivation|introductory|conclusion(?:s)?[- ]only|"
    r"merely|only\s+an?\s+application|assumed|"
    r"central|connection|connected|"
    r"establish(?:ed|es|ing)?\s+(?:a\s+)?(?:strong\s+)?connection)(?![A-Za-z0-9])"
    r"|次要|装饰|附属|边缘|辅助|仅作为|只是|演示|支撑学科|引言|结论|"
    r"未建立|联系|核心|没有建立|缺乏联系|不足以建立"
    r")",
    re.IGNORECASE,
)

_MANUSCRIPT_BOUNDARY_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9])(?:one|single|only|limited|confined|local|site|facility|plant|dataset|"
    r"region|sample|case|system|task|condition|matrix|subfield|scenario|"
    r"short[- ]term|laborator(?:y|ies)|lab|pilot|bench[- ]scale|correlational|"
    r"descriptive|black[- ]box|performance[- ]only|outside|beyond|elsewhere|"
    r"cross[- ]site|external)(?![A-Za-z0-9])"
    r"|单一|单个|仅|只|局限|限于|本地|当地|场地|厂|设施|数据集|地区|区域|"
    r"样本|案例|系统|任务|条件|基质|子领域|场景|短期|实验室|中试|台架|"
    r"相关性|描述性|黑箱|性能指标|之外|超出|其他|跨场地|外部"
    r")",
    re.IGNORECASE,
)


class AssessmentValidationError(ValueError):
    """Raised when an LLM assessment cannot safely drive a decision.

    All detected errors are retained in ``errors`` so a caller can log one
    complete validation failure instead of repeatedly repairing one field at a
    time.
    """

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("Invalid editor assessment:\n- " + "\n- ".join(self.errors))


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalise_phrase(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^\w\u3400-\u9fff]+", " ", value)
    return " ".join(value.split())


def _is_generic_prestige_gap(value: str) -> bool:
    """Return True for an unsupported journal-prestige conclusion."""

    normalised = _normalise_phrase(value)
    exact_generic = {_normalise_phrase(phrase) for phrase in _GENERIC_GAP_PHRASES}
    if normalised in exact_generic or _GENERIC_PRESTIGE_GAP_RE.search(value):
        return True

    # Chinese variants are often written without word boundaries.  Treat them
    # as generic only when the same sentence fails to supply both concrete
    # ingredients; a detailed Chinese explanation is therefore not penalised
    # merely for containing words such as “未达到”.
    chinese_prestige = re.search(
        r"(?:不够|不足|不足以|缺乏).{0,8}(?:卓越|创新|影响力|显著|重大)"
        r"|(?:未达到|达不到).{0,8}(?:期刊|层级|档次|顶刊).{0,6}(?:门槛|要求|标准)?",
        value,
    )
    if chinese_prestige:
        return not (
            _MAGNITUDE_LANGUAGE_RE.search(value) and _MANUSCRIPT_BOUNDARY_RE.search(value)
        )
    return False


def _contains_forbidden_decision_key(value: Any, path: str = "assessment") -> list[str]:
    errors: list[str] = []
    if _is_mapping(value):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and key.casefold() in _FORBIDDEN_DECISION_KEYS:
                errors.append(
                    f"{child_path} is forbidden: the LLM must not supply or infer the decision"
                )
            errors.extend(_contains_forbidden_decision_key(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_contains_forbidden_decision_key(child, f"{path}[{index}]"))
    return errors


def _validate_novelty_block(axis: Mapping[str, Any], errors: list[str]) -> None:
    precedents = axis.get("direct_precedents")
    path = "novelty_increment.direct_precedents"
    if not isinstance(precedents, list) or not precedents:
        errors.append(
            f"{path} must contain at least one direct DOI precedent when verdict is block"
        )
        return

    valid_precedent_count = 0
    same_genre_count = 0
    for index, precedent in enumerate(precedents):
        item_path = f"{path}[{index}]"
        if not _is_mapping(precedent):
            errors.append(f"{item_path} must be an object")
            continue

        item_valid = True
        doi = precedent.get("doi")
        if not _is_nonempty_text(doi) or not _DOI_RE.fullmatch(doi.strip()):
            errors.append(f"{item_path}.doi must be a valid, explicit DOI beginning with 10.")
            item_valid = False
        if not _is_nonempty_text(precedent.get("evidence")):
            errors.append(
                f"{item_path}.evidence must state what the retrieved paper actually reports"
            )
            item_valid = False
        if not _is_nonempty_text(precedent.get("relationship")):
            errors.append(
                f"{item_path}.relationship must explain how the precedent covers the central claim"
            )
            item_valid = False
        genre_match = precedent.get("genre_match")
        if genre_match not in {"same_genre", "unknown"}:
            errors.append(
                f"{item_path}.genre_match must be same_genre or unknown"
            )
            item_valid = False
        if item_valid:
            valid_precedent_count += 1
            if genre_match == "same_genre":
                same_genre_count += 1

    if valid_precedent_count == 0:
        errors.append(
            f"{path} has no complete direct precedent; novelty cannot be blocked"
        )
    elif same_genre_count == 0:
        errors.append(
            f"{path} contains only unknown-genre comparators; at least one same_genre "
            "precedent is required to block novelty"
        )


def _validate_optional_comparators(
    axis: Mapping[str, Any], path: str, errors: list[str]
) -> None:
    """Prevent unknown-genre comparators from independently supporting a block.

    Blocking does not require comparator papers: the frozen bar and a manuscript-
    grounded positive finding are sufficient.  If the assessment does invoke
    comparator papers, however, their genre relation must be explicit and an
    unknown-only set cannot support the block.
    """

    if "comparators" not in axis:
        return
    comparators = axis.get("comparators")
    comparators_path = f"{path}.comparators"
    if not isinstance(comparators, list) or not comparators:
        errors.append(
            f"{comparators_path}, when supplied for a block, must be a non-empty list"
        )
        return

    same_genre_count = 0
    complete_count = 0
    for index, comparator in enumerate(comparators):
        item_path = f"{comparators_path}[{index}]"
        if not _is_mapping(comparator):
            errors.append(f"{item_path} must be an object")
            continue
        genre_match = comparator.get("genre_match")
        if genre_match not in {"same_genre", "unknown"}:
            errors.append(f"{item_path}.genre_match must be same_genre or unknown")
            continue
        if not _is_nonempty_text(comparator.get("evidence")):
            errors.append(f"{item_path}.evidence must explain the comparator's role")
            continue
        complete_count += 1
        if genre_match == "same_genre":
            same_genre_count += 1

    if complete_count and same_genre_count == 0:
        errors.append(
            f"{comparators_path} contains only unknown-genre comparators; those "
            "comparators cannot support a block"
        )


def _validate_novelty_magnitude_finding(
    finding: Any,
    index: int,
    errors: list[str],
) -> bool:
    path = f"novelty_magnitude.manuscript_findings[{index}]"
    if not _is_mapping(finding):
        errors.append(f"{path} must be an object")
        return False

    valid = True
    for field, explanation in (
        ("source_locator", "identify where the manuscript evidence appears"),
        ("evidence_quote", "quote or faithfully extract the manuscript evidence"),
        ("positive_finding", "state affirmatively what the manuscript actually contributes"),
        ("gap_to_bar", "state the specific magnitude gap between that contribution and the tier bar"),
    ):
        if not _is_nonempty_text(finding.get(field)):
            errors.append(f"{path}.{field} must {explanation}")
            valid = False

    positive = finding.get("positive_finding")
    if _is_nonempty_text(positive):
        if _NEGATIVE_FINDING_RE.search(positive):
            errors.append(
                f"{path}.positive_finding must describe what the manuscript does, not what it lacks"
            )
            valid = False
        elif len(_normalise_phrase(positive)) < 12:
            errors.append(
                f"{path}.positive_finding is too vague to ground a novelty-magnitude rejection"
            )
            valid = False

    gap = finding.get("gap_to_bar")
    if _is_nonempty_text(gap):
        if _is_generic_prestige_gap(gap):
            errors.append(
                f"{path}.gap_to_bar is only a generic prestige judgement; give a concrete magnitude gap"
            )
            valid = False
        if not _MAGNITUDE_LANGUAGE_RE.search(gap):
            errors.append(
                f"{path}.gap_to_bar must name the magnitude shortfall "
                "(for example incremental vs substantial, scope, transferability, or a single site/dataset)"
            )
            valid = False
        if not _MANUSCRIPT_BOUNDARY_RE.search(gap):
            errors.append(
                f"{path}.gap_to_bar must identify a demonstrated manuscript boundary "
                "(for example one site, one dataset, laboratory scale or a benchmark performance)"
            )
            valid = False

    return valid


def _validate_significance_finding(
    finding: Any,
    index: int,
    errors: list[str],
) -> bool:
    path = f"significance.manuscript_findings[{index}]"
    if not _is_mapping(finding):
        errors.append(f"{path} must be an object")
        return False

    valid = True
    for field, explanation in (
        ("source_locator", "identify where the manuscript evidence appears"),
        ("evidence_quote", "quote or faithfully extract the manuscript evidence"),
        ("positive_contribution", "state affirmatively what the manuscript's main contribution is"),
        ("gap_to_concern", "state the specific gap between the contribution and the journal's core concern"),
    ):
        if not _is_nonempty_text(finding.get(field)):
            errors.append(f"{path}.{field} must {explanation}")
            valid = False

    centrality = finding.get("centrality")
    if centrality not in ALLOWED_CENTRALITY:
        errors.append(
            f"{path}.centrality must be one of: {', '.join(sorted(ALLOWED_CENTRALITY))}"
        )
        valid = False

    positive = finding.get("positive_contribution")
    if _is_nonempty_text(positive):
        if _NEGATIVE_FINDING_RE.search(positive):
            errors.append(
                f"{path}.positive_contribution must describe what the manuscript contributes, "
                "not what it lacks"
            )
            valid = False
        elif len(_normalise_phrase(positive)) < 12:
            errors.append(
                f"{path}.positive_contribution is too vague to ground a significance rejection"
            )
            valid = False

    gap = finding.get("gap_to_concern")
    if _is_nonempty_text(gap) and _is_generic_prestige_gap(gap):
        errors.append(
            f"{path}.gap_to_concern is only a generic prestige judgement; give a concrete gap"
        )
        valid = False

    return valid


def _validate_novelty_magnitude_block(axis: Mapping[str, Any], errors: list[str]) -> None:
    tier_id = axis.get("tier_id")
    if tier_id not in ALLOWED_TIERS:
        errors.append("novelty_magnitude.tier_id must be one of T1, T2, T3 for a block")
    if not _is_nonempty_text(axis.get("required_bar")):
        errors.append(
            "novelty_magnitude.required_bar must quote or summarise the frozen tier requirement"
        )

    _validate_optional_comparators(axis, "novelty_magnitude", errors)

    findings = axis.get("manuscript_findings")
    if not isinstance(findings, list) or not findings:
        errors.append(
            "novelty_magnitude.manuscript_findings must contain at least one positive, "
            "manuscript-grounded finding when verdict is block"
        )
        return

    valid_findings = sum(
        _validate_novelty_magnitude_finding(finding, index, errors)
        for index, finding in enumerate(findings)
    )
    if valid_findings == 0:
        errors.append(
            "novelty_magnitude.manuscript_findings has no complete positive finding; "
            "novelty magnitude cannot be blocked"
        )


def _validate_significance_block(axis: Mapping[str, Any], errors: list[str]) -> None:
    if not _is_nonempty_text(axis.get("required_concern")):
        errors.append(
            "significance.required_concern must quote or summarise the journal's core concern"
        )

    _validate_optional_comparators(axis, "significance", errors)

    findings = axis.get("manuscript_findings")
    if not isinstance(findings, list) or not findings:
        errors.append(
            "significance.manuscript_findings must contain at least one positive, "
            "manuscript-grounded finding when verdict is block"
        )
        return

    valid_findings = sum(
        _validate_significance_finding(finding, index, errors)
        for index, finding in enumerate(findings)
    )
    if valid_findings == 0:
        errors.append(
            "significance.manuscript_findings has no complete positive finding; "
            "significance cannot be blocked"
        )
        return

    # A significance block must be carried by at least one finding that names a
    # non-central relation AND explains it with the decorativeness vocabulary.
    supportive = 0
    for index, finding in enumerate(findings):
        if not _is_mapping(finding):
            continue
        centrality = finding.get("centrality")
        gap = finding.get("gap_to_concern")
        if (
            centrality in {"secondary_demonstration", "supporting_discipline"}
            and _is_nonempty_text(gap)
            and _SIGNIFICANCE_DECORATIVE_LANGUAGE_RE.search(gap)
        ):
            supportive += 1
    if supportive == 0:
        errors.append(
            "significance block requires at least one finding with centrality "
            "secondary_demonstration/supporting_discipline and a gap_to_concern naming "
            "the secondary or decorative reason"
        )


def validate_assessment(assessment: Mapping[str, Any]) -> None:
    """Validate an LLM assessment or raise :class:`AssessmentValidationError`.

    Validation is strict at the top level: the model may return only the five
    assessment axes.  This makes an accidentally model-generated ``decision`` a
    hard error rather than a value the program might silently trust.
    """

    errors: list[str] = []
    if not _is_mapping(assessment):
        raise AssessmentValidationError(["assessment must be an object"])

    supplied = set(assessment.keys())
    expected = set(AXIS_PRECEDENCE)
    missing = sorted(expected - supplied)
    extra = sorted(str(key) for key in supplied - expected)
    if missing:
        errors.append("missing required axes: " + ", ".join(missing))
    if extra:
        errors.append("unknown top-level fields: " + ", ".join(extra))

    errors.extend(_contains_forbidden_decision_key(assessment))

    for axis_name in AXIS_PRECEDENCE:
        if axis_name not in assessment:
            continue
        axis = assessment[axis_name]
        if not _is_mapping(axis):
            errors.append(f"{axis_name} must be an object")
            continue

        verdict = axis.get("verdict")
        if verdict not in ALLOWED_VERDICTS[axis_name]:
            allowed = ", ".join(sorted(ALLOWED_VERDICTS[axis_name]))
            errors.append(f"{axis_name}.verdict must be one of: {allowed}")
        if not _is_nonempty_text(axis.get("rationale")):
            errors.append(f"{axis_name}.rationale must be non-empty")

        if axis_name == "novelty_increment" and verdict == "block":
            _validate_novelty_block(axis, errors)
        if axis_name == "significance" and verdict == "block":
            _validate_significance_block(axis, errors)
        if axis_name == "novelty_magnitude" and verdict == "block":
            _validate_novelty_magnitude_block(axis, errors)

    if errors:
        # Preserve order but avoid duplicate messages from layered checks.
        raise AssessmentValidationError(tuple(dict.fromkeys(errors)))


def derive_decision(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Validate five axes and deterministically derive the binary decision.

    ``warn`` never rejects.  If several axes block, all are recorded and the
    primary axis is the first in the fixed precedence order:
    scope > genre > novelty > significance > novelty_magnitude.
    """

    validate_assessment(assessment)

    verdicts = {
        axis_name: assessment[axis_name]["verdict"]
        for axis_name in AXIS_PRECEDENCE
    }
    blocking_axes = [
        axis_name for axis_name in AXIS_PRECEDENCE if verdicts[axis_name] == "block"
    ]
    warning_axes = [
        axis_name for axis_name in AXIS_PRECEDENCE if verdicts[axis_name] == "warn"
    ]

    primary = blocking_axes[0] if blocking_axes else None
    return {
        "decision": "拒稿" if blocking_axes else "送审",
        "primary_blocking_axis": primary,
        "blocking_axes": blocking_axes,
        "warning_axes": warning_axes,
        "axis_verdicts": verdicts,
    }
