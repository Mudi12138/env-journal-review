"""Unit tests for the deterministic v3 decision engine."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # the editor package
_sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the engine prints Chinese status lines
import copy
import itertools
import json
import unittest

from decision_engine import AssessmentValidationError, derive_decision, validate_assessment

AXIS_NAMES = (
    "scope_fit",
    "genre_fit",
    "novelty_increment",
    "significance",
    "novelty_magnitude",
)


def make_assessment(
    scope: str = "pass",
    genre: str = "pass",
    novelty: str = "pass",
    significance: str = "pass",
    magnitude: str = "pass",
) -> dict:
    assessment = {
        "scope_fit": {"verdict": scope, "rationale": "The official scope and manuscript align."},
        "genre_fit": {"verdict": genre, "rationale": "The submitted type is an Article."},
        "novelty_increment": {
            "verdict": novelty,
            "rationale": "The central claim was compared with the retrieved evidence.",
        },
        "significance": {
            "verdict": significance,
            "rationale": "The contribution's centrality to the core concern was assessed.",
        },
        "novelty_magnitude": {
            "verdict": magnitude,
            "rationale": "The identified increment was compared with the frozen tier bar.",
        },
    }
    if novelty == "block":
        assessment["novelty_increment"]["direct_precedents"] = [
            {
                "doi": "10.1016/j.watres.2025.123456",
                "evidence": "The precedent reports the same transfer-learning control claim.",
                "relationship": "It directly covers the manuscript's claimed central advance.",
                "genre_match": "same_genre",
            }
        ]
    if significance == "block":
        assessment["significance"].update(
            {
                "required_concern": (
                    "Environmental relevance must be central, not asserted only in "
                    "motivation or conclusion."
                ),
                "manuscript_findings": [
                    {
                        "source_locator": "Abstract, sentences 4-5",
                        "evidence_quote": "The model improves aeration control at one treatment plant.",
                        "positive_contribution": (
                            "The manuscript contributes a data-driven aeration control model."
                        ),
                        "centrality": "secondary_demonstration",
                        "gap_to_concern": (
                            "The water application is only a secondary demonstration of the "
                            "machine-learning method rather than the central contribution."
                        ),
                    }
                ],
            }
        )
    if magnitude == "block":
        assessment["novelty_magnitude"].update(
            {
                "tier_id": "T3",
                "required_bar": "A consequence extending beyond the narrow technical subfield.",
                "increment_summary": "A data-driven aeration control model applied at one plant.",
                "manuscript_findings": [
                    {
                        "source_locator": "Abstract, sentences 4-5",
                        "evidence_quote": "The model improves aeration control at one treatment plant.",
                        "positive_finding": "The manuscript improves aeration control at one plant.",
                        "demonstrated_scope_or_boundary": "one treatment plant",
                        "gap_to_bar": (
                            "The advance is confined to one treatment plant, so it is an "
                            "incremental rather than a substantial or transferable contribution."
                        ),
                    }
                ],
            }
        )
    return assessment


class DecisionCombinationTests(unittest.TestCase):
    def test_all_162_valid_verdict_combinations(self) -> None:
        spaces = (
            ("pass", "warn", "block"),
            ("pass", "block"),
            ("pass", "warn", "block"),
            ("pass", "warn", "block"),
            ("pass", "warn", "block"),
        )
        checked = 0
        for scope, genre, novelty, significance, magnitude in itertools.product(*spaces):
            assessment = make_assessment(scope, genre, novelty, significance, magnitude)
            result = derive_decision(assessment)
            verdicts = (scope, genre, novelty, significance, magnitude)
            expected_blocks = [
                axis
                for axis, verdict in zip(AXIS_NAMES, verdicts)
                if verdict == "block"
            ]
            expected_warnings = [
                axis
                for axis, verdict in zip(AXIS_NAMES, verdicts)
                if verdict == "warn"
            ]
            self.assertEqual(result["decision"], "拒稿" if expected_blocks else "送审")
            self.assertEqual(result["blocking_axes"], expected_blocks)
            self.assertEqual(
                result["primary_blocking_axis"],
                expected_blocks[0] if expected_blocks else None,
            )
            self.assertEqual(result["warning_axes"], expected_warnings)
            checked += 1
        self.assertEqual(checked, 162)

    def test_warns_alone_never_reject(self) -> None:
        result = derive_decision(
            make_assessment(scope="warn", novelty="warn", significance="warn", magnitude="warn")
        )
        self.assertEqual(result["decision"], "送审")
        self.assertEqual(result["blocking_axes"], [])

    def test_primary_precedence_and_all_blocks_are_recorded(self) -> None:
        result = derive_decision(
            make_assessment(
                scope="block",
                genre="block",
                novelty="block",
                significance="block",
                magnitude="block",
            )
        )
        self.assertEqual(result["primary_blocking_axis"], "scope_fit")
        self.assertEqual(result["blocking_axes"], list(AXIS_NAMES))

    def test_derive_does_not_mutate_assessment(self) -> None:
        assessment = make_assessment(
            novelty="block", significance="block", magnitude="block"
        )
        before = copy.deepcopy(assessment)
        derive_decision(assessment)
        self.assertEqual(assessment, before)

    def test_result_is_json_serialisable(self) -> None:
        json.dumps(derive_decision(make_assessment()), ensure_ascii=False)


class GeneralValidationTests(unittest.TestCase):
    def assertInvalid(self, assessment, contains: str) -> AssessmentValidationError:  # noqa: N802
        with self.assertRaises(AssessmentValidationError) as context:
            validate_assessment(assessment)
        self.assertIn(contains, str(context.exception))
        return context.exception

    def test_assessment_must_be_object(self) -> None:
        self.assertInvalid([], "assessment must be an object")

    def test_missing_axis_is_rejected(self) -> None:
        assessment = make_assessment()
        del assessment["scope_fit"]
        self.assertInvalid(assessment, "missing required axes: scope_fit")

    def test_unknown_top_level_field_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["comment"] = "extra"
        self.assertInvalid(assessment, "unknown top-level fields: comment")

    def test_llm_supplied_decision_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["decision"] = "送审"
        error = self.assertInvalid(assessment, "unknown top-level fields: decision")
        self.assertTrue(any("must not supply" in item for item in error.errors))

    def test_nested_decision_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["scope_fit"]["decision"] = "拒稿"
        self.assertInvalid(assessment, "must not supply or infer the decision")

    def test_nested_transfer_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["novelty_magnitude"]["transfer_target"] = "Another Journal"
        self.assertInvalid(assessment, "must not supply or infer the decision")

    def test_axis_must_be_object(self) -> None:
        assessment = make_assessment()
        assessment["genre_fit"] = "pass"
        self.assertInvalid(assessment, "genre_fit must be an object")

    def test_empty_rationale_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["scope_fit"]["rationale"] = "  "
        self.assertInvalid(assessment, "scope_fit.rationale must be non-empty")

    def test_invalid_scope_verdict_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["scope_fit"]["verdict"] = "maybe"
        self.assertInvalid(assessment, "scope_fit.verdict must be one of")

    def test_genre_warn_is_rejected(self) -> None:
        assessment = make_assessment()
        assessment["genre_fit"]["verdict"] = "warn"
        self.assertInvalid(assessment, "genre_fit.verdict must be one of: block, pass")

    def test_validation_reports_multiple_errors(self) -> None:
        assessment = make_assessment()
        assessment["scope_fit"]["rationale"] = ""
        assessment["genre_fit"]["verdict"] = "warn"
        error = self.assertInvalid(assessment, "scope_fit.rationale")
        self.assertGreaterEqual(len(error.errors), 2)


class NoveltyEvidenceTests(GeneralValidationTests):
    def test_nonblocking_novelty_does_not_need_precedent(self) -> None:
        validate_assessment(make_assessment(novelty="warn"))

    def test_block_requires_precedent_list(self) -> None:
        assessment = make_assessment(novelty="block")
        del assessment["novelty_increment"]["direct_precedents"]
        self.assertInvalid(assessment, "at least one direct DOI precedent")

    def test_block_rejects_empty_precedent_list(self) -> None:
        assessment = make_assessment(novelty="block")
        assessment["novelty_increment"]["direct_precedents"] = []
        self.assertInvalid(assessment, "at least one direct DOI precedent")

    def test_block_rejects_invalid_doi(self) -> None:
        assessment = make_assessment(novelty="block")
        assessment["novelty_increment"]["direct_precedents"][0]["doi"] = "watres-123"
        self.assertInvalid(assessment, "must be a valid, explicit DOI")

    def test_block_rejects_missing_evidence(self) -> None:
        assessment = make_assessment(novelty="block")
        assessment["novelty_increment"]["direct_precedents"][0]["evidence"] = ""
        self.assertInvalid(assessment, "must state what the retrieved paper actually reports")

    def test_block_rejects_missing_relationship(self) -> None:
        assessment = make_assessment(novelty="block")
        assessment["novelty_increment"]["direct_precedents"][0]["relationship"] = ""
        self.assertInvalid(assessment, "must explain how the precedent covers the central claim")

    def test_block_rejects_missing_genre_match(self) -> None:
        assessment = make_assessment(novelty="block")
        del assessment["novelty_increment"]["direct_precedents"][0]["genre_match"]
        self.assertInvalid(assessment, "genre_match must be same_genre or unknown")

    def test_unknown_genre_precedent_cannot_block_novelty(self) -> None:
        assessment = make_assessment(novelty="block")
        assessment["novelty_increment"]["direct_precedents"][0][
            "genre_match"
        ] = "unknown"
        self.assertInvalid(assessment, "only unknown-genre comparators")

    def test_complete_direct_precedent_is_accepted(self) -> None:
        validate_assessment(make_assessment(novelty="block"))


class SignificanceEvidenceTests(GeneralValidationTests):
    def test_nonblocking_significance_does_not_need_findings(self) -> None:
        validate_assessment(make_assessment(significance="warn"))

    def test_block_requires_required_concern(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["required_concern"] = ""
        self.assertInvalid(assessment, "required_concern must quote or summarise")

    def test_block_requires_manuscript_findings(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"] = []
        self.assertInvalid(assessment, "must contain at least one positive")

    def test_block_rejects_missing_source_locator(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["source_locator"] = ""
        self.assertInvalid(assessment, "source_locator must identify")

    def test_block_rejects_missing_evidence_quote(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["evidence_quote"] = ""
        self.assertInvalid(assessment, "evidence_quote must quote")

    def test_block_rejects_missing_positive_contribution(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["positive_contribution"] = ""
        self.assertInvalid(assessment, "positive_contribution must state")

    def test_block_rejects_negative_only_contribution(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0][
            "positive_contribution"
        ] = "The manuscript is not exceptional."
        self.assertInvalid(assessment, "must describe what the manuscript contributes")

    def test_block_rejects_invalid_centrality(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["centrality"] = "primary"
        self.assertInvalid(assessment, "centrality must be one of")

    def test_block_requires_non_central_centrality(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["centrality"] = "central"
        self.assertInvalid(assessment, "naming the secondary or decorative reason")

    def test_block_rejects_gap_without_decorativeness_vocabulary(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["gap_to_concern"] = (
            "The work is too specialized for the field."
        )
        self.assertInvalid(assessment, "naming the secondary or decorative reason")

    def test_block_rejects_generic_gap(self) -> None:
        assessment = make_assessment(significance="block")
        assessment["significance"]["manuscript_findings"][0]["gap_to_concern"] = (
            "Not exceptional."
        )
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_specific_significance_block_is_accepted(self) -> None:
        validate_assessment(make_assessment(significance="block"))


class NoveltyMagnitudeEvidenceTests(GeneralValidationTests):
    def test_nonblocking_magnitude_does_not_need_findings(self) -> None:
        validate_assessment(make_assessment(magnitude="warn"))

    def test_block_requires_tier_id(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["tier_id"] = "T4"
        self.assertInvalid(assessment, "tier_id must be one of T1, T2, T3")

    def test_block_requires_required_bar(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["required_bar"] = ""
        self.assertInvalid(assessment, "required_bar must quote or summarise")

    def test_block_requires_manuscript_findings(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"] = []
        self.assertInvalid(assessment, "must contain at least one positive")

    def test_block_rejects_missing_source_locator(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0]["source_locator"] = ""
        self.assertInvalid(assessment, "source_locator must identify")

    def test_block_rejects_missing_evidence_quote(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0]["evidence_quote"] = ""
        self.assertInvalid(assessment, "evidence_quote must quote")

    def test_block_rejects_missing_positive_finding(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0]["positive_finding"] = ""
        self.assertInvalid(assessment, "positive_finding must state")

    def test_block_rejects_negative_only_finding(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "positive_finding"
        ] = "The manuscript is not exceptional."
        self.assertInvalid(assessment, "must describe what the manuscript does")

    def test_block_rejects_generic_only_gap_in_english(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "Not exceptional."
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_generic_only_gap_in_chinese(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "未达到顶刊水平"
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_extended_not_exceptional_variant(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "This work is not exceptional enough for this journal."
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_extended_insufficient_impact_variant(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "The paper has insufficient impact for the target venue."
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_extended_not_enough_for_journal_variant(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "This manuscript is not enough for the journal."
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_does_not_meet_tier_bar_variant(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "The study does not meet the T3 journal bar."
        self.assertInvalid(assessment, "only a generic prestige judgement")

    def test_block_rejects_magnitude_gap_without_boundary(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "The advance is incremental rather than conceptual."
        self.assertInvalid(assessment, "must identify a demonstrated manuscript boundary")

    def test_block_rejects_boundary_without_magnitude(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "The result is demonstrated at a single treatment plant."
        self.assertInvalid(assessment, "must name the magnitude shortfall")

    def test_specific_chinese_gap_is_accepted(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0][
            "gap_to_bar"
        ] = "论文只在单个污水厂验证，属于增量改进而非实质性突破，可迁移性证据尚未覆盖其他设施。"
        validate_assessment(assessment)

    def test_block_rejects_vague_positive_finding(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["manuscript_findings"][0]["positive_finding"] = "A model"
        self.assertInvalid(assessment, "too vague")

    def test_specific_manuscript_grounded_block_is_accepted(self) -> None:
        validate_assessment(make_assessment(magnitude="block"))

    def test_unknown_only_optional_comparator_cannot_support_magnitude_block(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["comparators"] = [
            {"genre_match": "unknown", "evidence": "The abstract does not reveal article type."}
        ]
        self.assertInvalid(assessment, "only unknown-genre comparators")

    def test_same_genre_optional_comparator_is_accepted_for_magnitude_block(self) -> None:
        assessment = make_assessment(magnitude="block")
        assessment["novelty_magnitude"]["comparators"] = [
            {"genre_match": "same_genre", "evidence": "Both papers are primary research Articles."}
        ]
        validate_assessment(assessment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
