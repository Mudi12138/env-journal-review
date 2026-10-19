"""Zero-cost fixture tests for the v3 editor runner."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # the editor package
_sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the engine prints Chinese status lines
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import editor_v3


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class EditorV3Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        scope_text = "The journal publishes water research with a direct water-system connection."
        scope_hash = hashlib.sha256(scope_text.encode("utf-8")).hexdigest()

        def snapshot(journal_id: str, display_name: str) -> dict:
            return {
                "schema_version": "1.0",
                "journal_id": journal_id,
                "display_name": display_name,
                "retrieved_at": "2026-09-22",
                "scope": {
                    "text": scope_text,
                    "text_sha256": scope_hash,
                    "official_excerpts": [
                        {
                            "source_ref": "aims_scope",
                            "text": "publishes water research with a direct water-system connection",
                        }
                    ],
                    "source_refs": ["aims_scope"],
                },
                "content_types": {
                    "capture_completeness": "partial",
                    "absence_is_not_exclusion": True,
                    "primary_research": ["Article"],
                    "non_primary_or_commentary": ["Review"],
                    "submission_notes": ["Articles report original research."],
                    "official_excerpts": [
                        {
                            "source_ref": "content_types",
                            "text": "Articles report original research.",
                        }
                    ],
                    "source_refs": ["content_types"],
                    "capture_status": (
                        "Conservative subset only: detailed article-types page was "
                        "access-restricted during capture."
                    ),
                },
                "sources": [
                    {
                        "source_id": "aims_scope",
                        "url": "https://official.example/aims",
                        "retrieved_at": "2026-09-22",
                    },
                    {
                        "source_id": "content_types",
                        "url": "https://official.example/content",
                        "retrieved_at": "2026-09-22",
                    },
                ],
            }

        registry = {
            "schema_version": "1.0",
            "journals": [
                {
                    "journal_id": "journal_a",
                    "display_name": "Journal A",
                    "tier_id": "T1",
                    "snapshot": "official_scope/journal_a.json",
                },
                {
                    "journal_id": "journal_b",
                    "display_name": "Journal B",
                    "tier_id": "T2",
                    "snapshot": "official_scope/journal_b.json",
                },
            ],
        }
        tiers = {
            "order_high_to_low": ["T3", "T2", "T1"],
            "tiers": {
                "T3": {
                    "significance": {
                        "bar": "The main conclusions must matter beyond a narrow specialist subfield."
                    },
                    "novelty_magnitude": {
                        "bar": "A substantial or conceptual advance beyond a leading specialist journal."
                    },
                    "member_journals": [],
                },
                "T1": {
                    "significance": {
                        "bar": "The paper must be fundamentally a water-research contribution."
                    },
                    "novelty_magnitude": {
                        "bar": (
                            "A clear water-engineering increment with transferability or "
                            "an explicit applicability boundary."
                        ),
                    },
                    "member_journals": ["journal_a"],
                },
                "T2": {
                    "significance": {
                        "bar": "Environmental relevance must be central and explicit."
                    },
                    "novelty_magnitude": {
                        "bar": "A significant and generalizable advance."
                    },
                    "member_journals": ["journal_b"],
                },
            },
        }
        self.registry_path = self.root / "journal_registry.json"
        self.tier_path = self.root / "tier_bars.json"
        _write_json(self.registry_path, registry)
        _write_json(self.tier_path, tiers)
        _write_json(
            self.root / "official_scope" / "journal_a.json",
            snapshot("journal_a", "Journal A"),
        )
        _write_json(
            self.root / "official_scope" / "journal_b.json",
            snapshot("journal_b", "Journal B"),
        )
        self.pack = {
            "id": "MS-fixture",
            "title": "Water treatment control with adaptive learning",
            "abstract": (
                "We report an adaptive controller for water treatment and test it at "
                "three full-scale plants."
            ),
            "cutoff_year": 2025,
            "excluded_self": ["10.9999/self"],
            "hits": [
                {
                    "doi": "10.1000/a",
                    "year": "2024",
                    "journal": "Journal A",
                    "category": "control",
                    "title": "Adaptive water treatment control",
                    "abstract": "A full research article on adaptive plant control.",
                    "why_retrieved": "emb:q1#1",
                },
                {
                    "doi": "10.1000/b",
                    "year": "2023",
                    "journal": "Journal B",
                    "category": "review",
                    "title": "A review of water control",
                    "abstract": "This review summarizes control methods.",
                    "why_retrieved": "bm25:q1#2",
                },
            ],
        }
        self.journals = editor_v3.load_journal_registry(self.registry_path)
        self.tiers = editor_v3.load_tier_bars(self.tier_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def valid_assessment(self, journal_id: str = "journal_a") -> dict:
        journal = self.journals[journal_id]
        tier = self.tiers[journal["tier_id"]]
        return {
            "scope_fit": {
                "verdict": "pass",
                "rationale": "核心对象是水处理。",
                "official_basis": [
                    {
                        "source_id": "aims_scope",
                        "official_quote": (
                            "publishes water research with a direct water-system connection"
                        ),
                    }
                ],
                "manuscript_basis": [
                    {
                        "source_locator": "abstract",
                        "evidence_quote": "adaptive controller for water treatment",
                    }
                ],
            },
            "genre_fit": {
                "verdict": "pass",
                "rationale": "稿件报告原创研究。",
                "inferred_manuscript_genre": "primary research Article",
                "official_basis": [
                    {
                        "source_id": "content_types",
                        "official_quote": "Articles report original research.",
                    }
                ],
                "manuscript_basis": [
                    {
                        "source_locator": "abstract",
                        "evidence_quote": "test it at three full-scale plants",
                    }
                ],
            },
            "novelty_increment": {
                "verdict": "warn",
                "rationale": "检索集存在同类工作，但增量尚未被完全覆盖。",
                "central_claim": "自适应水处理控制。",
                "manuscript_increment": "在三个全规模厂验证。",
                "direct_precedents": [],
                "nearest_same_genre_precedents": [
                    {
                        "doi": "10.1000/a",
                        "manuscript_genre": "computational_or_method",
                        "precedent_genre": "computational_or_method",
                        "genre_match": "same",
                        "manuscript_genre_evidence": "adaptive controller",
                        "genre_evidence": "Adaptive water treatment control",
                        "what_it_already_did": "报告自适应控制。",
                        "what_the_manuscript_adds": "三个全规模厂验证。",
                        "delta_type": "site_or_dataset",
                    }
                ],
            },
            "significance": {
                "verdict": "pass",
                "rationale": "水处理控制是核心贡献。",
                "required_concern": tier["_required_concern"],
                "manuscript_findings": [
                    {
                        "source_locator": "abstract",
                        "evidence_quote": "adaptive controller for water treatment",
                        "positive_contribution": "稿件贡献自适应水处理控制器。",
                        "centrality": "central",
                        "gap_to_concern": "无核心关切缺口。",
                    }
                ],
            },
            "novelty_magnitude": {
                "verdict": "pass",
                "rationale": "增量达到该层级。",
                "tier_id": journal["tier_id"],
                "required_bar": tier["_required_bar"],
                "increment_summary": "多厂验证。",
                "manuscript_findings": [
                    {
                        "source_locator": "abstract",
                        "evidence_quote": "test it at three full-scale plants",
                        "positive_finding": "完成三个全规模厂验证。",
                        "demonstrated_scope_or_boundary": "摘要展示三个全规模水处理厂。",
                        "gap_to_bar": "无决定性缺口。",
                    }
                ],
            },
        }


class TestEditorV3(EditorV3Fixture):
    def test_schema_exposes_only_five_axes(self) -> None:
        properties = editor_v3.ASSESSMENT_SCHEMA["schema"]["properties"]
        self.assertEqual(set(properties), set(editor_v3.AXIS_KEYS))
        serialized = json.dumps(properties)
        self.assertNotIn('"decision"', serialized)
        self.assertNotIn('"transfer_target"', serialized)
        self.assertNotIn('"转投"', serialized)
        self.assertNotIn('"profile', serialized)

    def test_same_global_pack_reaches_every_journal(self) -> None:
        prompts = []
        hashes = set()
        for journal in self.journals.values():
            messages, metadata = editor_v3.build_decision_messages(
                self.pack, journal, self.tiers[journal["tier_id"]]
            )
            prompts.append(messages[1]["content"])
            hashes.add(metadata["retrieval_pack_sha256"])
        self.assertEqual(len(hashes), 1)
        for prompt in prompts:
            self.assertIn("10.1000/a", prompt)
            self.assertIn("10.1000/b", prompt)
            self.assertNotIn("TOPIC PROFILE", prompt)

    def test_valid_assessment_derives_binary_decision(self) -> None:
        assessment = self.valid_assessment()
        journal = self.journals["journal_a"]
        tier = self.tiers["T1"]
        editor_v3.validate_assessment(assessment, self.pack, journal, tier)
        decision = editor_v3.derive_decision(assessment)
        self.assertEqual(decision["decision"], "送审")
        self.assertNotIn(decision["decision"], {"转投"})

    def test_novelty_block_needs_pack_doi_and_same_genre(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["verdict"] = "block"
        assessment["novelty_increment"]["direct_precedents"] = [
            {
                "doi": "10.9999/not-in-pack",
                "evidence_quote": "claims the same controller",
                "evidence": "claims the same controller",
                "relationship": "covers the central claim",
                "genre_match": "unknown",
            }
        ]
        with self.assertRaisesRegex(ValueError, "outside retrieval pack"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_assessment_rejects_nested_editorial_action_language(self) -> None:
        assessment = self.valid_assessment()
        assessment["scope_fit"]["rationale"] = "因此建议送审。"
        with self.assertRaisesRegex(ValueError, "forbidden decision/action language"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_chinese_editorial_action_synonyms_are_rejected(self) -> None:
        for phrase in (
            "该稿应直接退稿。",
            "可另投 Water Research。",
            "稿件可以进入同行评议。",
            "该工作不宜进入审稿流程。",
        ):
            with self.subTest(phrase=phrase):
                assessment = self.valid_assessment()
                assessment["scope_fit"]["rationale"] = phrase
                with self.assertRaisesRegex(ValueError, "forbidden decision/action language"):
                    editor_v3.validate_assessment(
                        assessment,
                        self.pack,
                        self.journals["journal_a"],
                        self.tiers["T1"],
                    )

    def test_policy_recommendation_narrative_is_not_editorial_action(self) -> None:
        assessment = self.valid_assessment()
        comparison = assessment["novelty_increment"]["nearest_same_genre_precedents"][0]
        comparison["what_the_manuscript_adds"] = (
            "形成政策建议。The study recommends publication of national water-reuse "
            "policy guidance."
        )
        editor_v3.validate_assessment(
            assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
        )
        comparison["what_the_manuscript_adds"] = (
            "We recommend this manuscript for peer review."
        )
        with self.assertRaisesRegex(ValueError, "forbidden decision/action language"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_verbatim_policy_recommendation_quote_is_not_mistaken_for_decision(self) -> None:
        pack = deepcopy(self.pack)
        pack["hits"][0]["abstract"] += (
            " It supports policy recommendations and operational decision-making."
        )
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["direct_precedents"] = [
            {
                "doi": "10.1000/a",
                "evidence_quote": (
                    "supports policy recommendations and operational decision-making"
                ),
                "evidence": "该文报告政策与运行用途。",
                "relationship": "与控制方法应用相关。",
                "genre_match": "same_genre",
            }
        ]
        editor_v3.validate_assessment(
            assessment, pack, self.journals["journal_a"], self.tiers["T1"]
        )

    def test_direct_precedent_quote_must_come_from_same_doi(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["direct_precedents"] = [
            {
                "doi": "10.1000/a",
                "evidence_quote": "This review summarizes control methods",
                "evidence": "该文覆盖控制方法。",
                "relationship": "与中心主张相关。",
                "genre_match": "same_genre",
            }
        ]
        with self.assertRaisesRegex(ValueError, "not from that DOI"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_direct_precedent_one_word_quote_is_not_sufficient(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["direct_precedents"] = [
            {
                "doi": "10.1000/a",
                "evidence_quote": "control",
                "evidence": "该文涉及控制。",
                "relationship": "与中心方法相关。",
                "genre_match": "same_genre",
            }
        ]
        with self.assertRaisesRegex(ValueError, "too short or general"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_nearest_genre_quote_must_come_from_same_doi(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["nearest_same_genre_precedents"][0][
            "genre_evidence"
        ] = "This review summarizes control methods"
        with self.assertRaisesRegex(ValueError, "genre_evidence is not from that DOI"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_novelty_block_direct_doi_must_match_same_comparison(self) -> None:
        assessment = self.valid_assessment()
        novelty = assessment["novelty_increment"]
        novelty["verdict"] = "block"
        novelty["direct_precedents"] = [
            {
                "doi": "10.1000/b",
                "evidence_quote": "This review summarizes control methods",
                "evidence": "该综述总结控制方法。",
                "relationship": "覆盖稿件中心方法类别。",
                "genre_match": "same_genre",
            }
        ]
        with self.assertRaisesRegex(ValueError, "match a same-genre comparison by DOI"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_novelty_pass_forbidden_by_limited_delta(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_increment"]["verdict"] = "pass"
        # The default comparison has delta_type "site_or_dataset" (limited), so a
        # near-duplicate in the pack must forbid a `pass` on novelty.
        with self.assertRaisesRegex(ValueError, "cannot be pass"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )
        # A substantial delta lifts the restriction.
        assessment["novelty_increment"]["nearest_same_genre_precedents"][0][
            "delta_type"
        ] = "reframe"
        editor_v3.validate_assessment(
            assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
        )

    def test_novelty_block_requires_limited_delta(self) -> None:
        assessment = self.valid_assessment()
        novelty = assessment["novelty_increment"]
        novelty["verdict"] = "block"
        novelty["direct_precedents"] = [
            {
                "doi": "10.1000/a",
                "evidence_quote": "A full research article on adaptive plant control",
                "evidence": "该文报告自适应水处理控制。",
                "relationship": "直接覆盖稿件中心主张。",
                "genre_match": "same_genre",
            }
        ]
        # A block cannot stand on a substantial delta: it must name a limited one.
        novelty["nearest_same_genre_precedents"][0]["delta_type"] = "reframe"
        with self.assertRaisesRegex(ValueError, "block must be grounded"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )
        # A limited but real increment (new site, configuration, method transfer) is not a
        # novelty block any more: its sufficiency belongs to novelty_magnitude.
        novelty["nearest_same_genre_precedents"][0]["delta_type"] = "site_or_dataset"
        with self.assertRaisesRegex(ValueError, "validation_only"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )
        # Only "already done" grounds a novelty block.
        novelty["nearest_same_genre_precedents"][0]["delta_type"] = "validation_only"
        editor_v3.validate_assessment(
            assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
        )
        self.assertEqual(editor_v3.derive_decision(assessment)["decision"], "拒稿")

    def test_review_cannot_be_relabelled_as_computational_same_genre(self) -> None:
        assessment = self.valid_assessment()
        comparison = assessment["novelty_increment"]["nearest_same_genre_precedents"][0]
        comparison.update(
            {
                "doi": "10.1000/b",
                "precedent_genre": "computational_or_method",
                "genre_match": "same",
                "genre_evidence": "This review summarizes control methods",
            }
        )
        with self.assertRaisesRegex(ValueError, "clearly synthesis_or_review"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_perspectives_title_cannot_be_relabelled_as_computational(self) -> None:
        pack = deepcopy(self.pack)
        pack["hits"][1]["title"] = "Perspectives on adaptive water control"
        pack["hits"][1]["abstract"] = "Control methods and future directions are discussed."
        assessment = self.valid_assessment()
        comparison = assessment["novelty_increment"]["nearest_same_genre_precedents"][0]
        comparison.update(
            {
                "doi": "10.1000/b",
                "precedent_genre": "computational_or_method",
                "genre_match": "same",
                "genre_evidence": "Perspectives on adaptive water control",
            }
        )
        with self.assertRaisesRegex(ValueError, "clearly synthesis_or_review"):
            editor_v3.validate_assessment(
                assessment, pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_viewpoint_abstract_cannot_be_relabelled_as_computational(self) -> None:
        pack = deepcopy(self.pack)
        pack["hits"][1]["title"] = "Adaptive water control"
        pack["hits"][1]["abstract"] = (
            "This viewpoint discusses controller design and future directions."
        )
        assessment = self.valid_assessment()
        comparison = assessment["novelty_increment"]["nearest_same_genre_precedents"][0]
        comparison.update(
            {
                "doi": "10.1000/b",
                "precedent_genre": "computational_or_method",
                "genre_match": "same",
                "genre_evidence": "This viewpoint discusses controller design",
            }
        )
        with self.assertRaisesRegex(ValueError, "clearly synthesis_or_review"):
            editor_v3.validate_assessment(
                assessment, pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_review_wording_in_manuscript_full_text_does_not_force_review_label(self) -> None:
        # Research papers cite reviews in their full text; only title + abstract decide.
        pack = deepcopy(self.pack)
        pack["fulltext"] = (
            pack["abstract"] + " Introduction. A comprehensive review of plant control "
            "strategies is given elsewhere."
        )
        editor_v3.validate_assessment(
            self.valid_assessment(), pack, self.journals["journal_a"], self.tiers["T1"]
        )

    def test_generic_novelty_magnitude_exceptionality_cannot_block(self) -> None:
        assessment = self.valid_assessment()
        axis = assessment["novelty_magnitude"]
        axis["verdict"] = "block"
        finding = axis["manuscript_findings"][0]
        finding["positive_finding"] = "稿件在三个全规模水处理厂完成自适应控制器验证。"
        finding["demonstrated_scope_or_boundary"] = "摘要仅展示三个全规模水处理厂。"
        finding["gap_to_bar"] = "This work is not exceptional enough for this journal."
        with self.assertRaisesRegex(ValueError, "only a generic prestige judgement"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_generic_significance_exceptionality_cannot_block(self) -> None:
        assessment = self.valid_assessment()
        axis = assessment["significance"]
        axis["verdict"] = "block"
        finding = axis["manuscript_findings"][0]
        finding["centrality"] = "secondary_demonstration"
        finding["gap_to_concern"] = "Not exceptional."
        with self.assertRaisesRegex(ValueError, "only a generic prestige judgement"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_significance_block_requires_non_central_centrality(self) -> None:
        assessment = self.valid_assessment()
        axis = assessment["significance"]
        axis["verdict"] = "block"
        finding = axis["manuscript_findings"][0]
        finding["centrality"] = "central"
        finding["gap_to_concern"] = "水应用只是方法的次要演示。"
        with self.assertRaisesRegex(ValueError, "naming the secondary or decorative reason"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_specific_novelty_magnitude_gap_can_block(self) -> None:
        assessment = self.valid_assessment()
        axis = assessment["novelty_magnitude"]
        axis["verdict"] = "block"
        finding = axis["manuscript_findings"][0]
        finding["positive_finding"] = "稿件在三个全规模水处理厂完成自适应控制器验证。"
        finding["demonstrated_scope_or_boundary"] = "摘要仅展示三个全规模水处理厂。"
        finding["gap_to_bar"] = "可迁移性仅在三个水处理厂展示，未覆盖其他水系统。"
        editor_v3.validate_assessment(
            assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
        )
        self.assertEqual(editor_v3.derive_decision(assessment)["decision"], "拒稿")

    def test_specific_significance_gap_can_block(self) -> None:
        assessment = self.valid_assessment()
        axis = assessment["significance"]
        axis["verdict"] = "block"
        finding = axis["manuscript_findings"][0]
        finding["centrality"] = "supporting_discipline"
        finding["gap_to_concern"] = (
            "水处理应用只是机器学习方法的次要演示，未建立与水研究核心的强联系。"
        )
        editor_v3.validate_assessment(
            assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
        )
        self.assertEqual(editor_v3.derive_decision(assessment)["decision"], "拒稿")

    def test_scope_quality_words_alone_cannot_block(self) -> None:
        assessment = self.valid_assessment()
        assessment["scope_fit"]["verdict"] = "block"
        assessment["scope_fit"]["official_basis"][0]["official_quote"] = (
            "significant, broadly relevant, and generalizable research"
        )
        journal = deepcopy(self.journals["journal_a"])
        journal["_official_excerpts"] = [
            {
                "source_ref": "aims_scope",
                "text": "significant, broadly relevant, and generalizable research",
            }
        ]
        with self.assertRaisesRegex(ValueError, "quality language alone"):
            editor_v3.validate_assessment(
                assessment, self.pack, journal, self.tiers["T1"]
            )

    def test_fixed_tier_id_cannot_drift(self) -> None:
        assessment = self.valid_assessment()
        assessment["novelty_magnitude"]["tier_id"] = "T3"
        with self.assertRaisesRegex(ValueError, "expected T1"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_genre_quote_must_come_from_captured_rules(self) -> None:
        assessment = self.valid_assessment()
        assessment["genre_fit"]["official_basis"][0]["official_quote"] = (
            "The journal categorically rejects all reviews."
        )
        with self.assertRaisesRegex(ValueError, "captured content-type evidence"):
            editor_v3.validate_assessment(
                assessment, self.pack, self.journals["journal_a"], self.tiers["T1"]
            )

    def test_partial_capture_instruction_defaults_away_from_block(self) -> None:
        journal = self.journals["journal_a"]
        messages, _ = editor_v3.build_decision_messages(
            self.pack, journal, self.tiers["T1"]
        )
        self.assertIn("absence from the captured list does NOT mean", messages[0]["content"])
        self.assertIn("Conservative subset only", messages[1]["content"])
        assessment = self.valid_assessment()
        assessment["genre_fit"]["verdict"] = "block"
        with self.assertRaisesRegex(ValueError, "partial conservative capture"):
            editor_v3.validate_assessment(
                assessment, self.pack, journal, self.tiers["T1"]
            )

    def test_dry_run_makes_zero_calls(self) -> None:
        report = editor_v3.dry_run(
            {self.pack["id"]: self.pack}, self.journals, self.tiers, raw_profiles=None
        )
        self.assertEqual(report["paid_api_calls"], 0)
        self.assertEqual(report["decision_jobs"], 2)
        self.assertEqual(report["schema_top_level"], list(editor_v3.AXIS_KEYS))

    def test_registry_tier_membership_is_consistent(self) -> None:
        editor_v3.validate_journal_tier_membership(
            self.journals, self.tiers, self.tier_path
        )
        broken = deepcopy(self.tiers)
        broken["T2"]["member_journals"].append("journal_a")
        with self.assertRaisesRegex(ValueError, "exactly once"):
            editor_v3.validate_journal_tier_membership(
                self.journals, broken, self.tier_path
            )

    def test_bad_snapshot_hash_fails_closed(self) -> None:
        path = self.root / "official_scope" / "journal_a.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["scope"]["text_sha256"] = "0" * 64
        _write_json(path, snapshot)
        with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
            editor_v3.load_journal_registry(self.registry_path)

    def test_profile_pass_is_separate_and_reference_only(self) -> None:
        messages = editor_v3.build_profile_messages(
            self.pack,
            self.journals["journal_a"],
            {"recent_density": "high", "historical_citation": "median"},
        )
        self.assertIn("仅供参考", messages[0]["content"])
        self.assertNotIn("Axis verdicts", messages[1]["content"])
        self.assertNotIn("Primary blocking axis", messages[1]["content"])
        profile_prompt = "\n".join(message["content"] for message in messages)
        self.assertNotIn("送审", profile_prompt)
        self.assertNotIn("拒稿", profile_prompt)
        self.assertEqual(
            editor_v3.PROFILE_UI_LABEL,
            "仅供参考，不参与送审/拒稿决定",
        )

        editor_v3.validate_profile_note(
            {
                "profile_note": (
                    "近期发文密度较高；The study recommends publication of national "
                    "water-reuse policy guidance."
                ),
                "review_attention": "可进一步核查相似工作中的增量。",
                "reference_only_acknowledged": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "forbidden decision language"):
            editor_v3.validate_profile_note(
                {
                    "profile_note": "这个背景说明稿件应拒稿。",
                    "review_attention": "仅供参考。",
                    "reference_only_acknowledged": True,
                }
            )
        for phrase in ("直接退稿", "另投 Water Research", "进入同行评议", "不宜进入审稿流程"):
            with self.subTest(profile_phrase=phrase):
                with self.assertRaisesRegex(ValueError, "forbidden decision language"):
                    editor_v3.validate_profile_note(
                        {
                            "profile_note": phrase,
                            "review_attention": "仅供参考。",
                            "reference_only_acknowledged": True,
                        }
                    )

    def test_profiles_are_resolved_by_manuscript_and_journal(self) -> None:
        raw = {
            "profiles": {
                "MS-one": {
                    "journal_a": {"topic_id": "A1", "recent_density": "high"},
                    "journal_b": {"topic_id": "A1", "recent_density": "low"},
                },
                "MS-two||journal_a": {
                    "topic_id": "B2",
                    "recent_density": "medium",
                },
                "MS-two||journal_b": {
                    "topic_id": "B2",
                    "recent_density": "high",
                },
            }
        }
        first = editor_v3._profile_for(raw, "MS-one", self.journals["journal_a"])
        second = editor_v3._profile_for(raw, "MS-two", self.journals["journal_a"])
        self.assertEqual(first["topic_id"], "A1")
        self.assertEqual(second["topic_id"], "B2")
        self.assertNotEqual(first, second)
        packs = {}
        for manuscript_id in ("MS-one", "MS-two"):
            pack = deepcopy(self.pack)
            pack["id"] = manuscript_id
            packs[manuscript_id] = pack
        report = editor_v3.dry_run(
            packs, self.journals, self.tiers, raw_profiles=raw
        )
        self.assertEqual(report["profile_jobs"], 4)
        self.assertEqual(report["paid_api_calls"], 0)
        with self.assertRaisesRegex(KeyError, "No exact profile"):
            editor_v3._profile_for(
                {"profiles": {"journal_a": {"topic_id": "legacy"}}},
                "MS-one",
                self.journals["journal_a"],
            )
        with self.assertRaisesRegex(KeyError, "No exact profile"):
            editor_v3._profile_for(
                {"profiles": {"MS-one": {"Journal A": {"topic_id": "display-name"}}}},
                "MS-one",
                self.journals["journal_a"],
            )
        with self.assertRaisesRegex(ValueError, "forbidden decision language"):
            editor_v3.validate_profile_note(
                {
                    "profile_note": "不建议进入外审。",
                    "review_attention": "仅供参考。",
                    "reference_only_acknowledged": True,
                }
            )


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.refusal = None


class _FakeResponse:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": _FakeMessage(content), "finish_reason": "stop"})()]
        self.usage = None


class _FakeClient:
    """Stands in for openai.OpenAI. `script` maps a prompt marker -> payload or Exception."""

    def __init__(self, script):
        self.script = script
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls += 1
                prompt = kwargs["messages"][1]["content"]
                for journal_id, payload in outer.script.items():
                    if journal_id in prompt:
                        if isinstance(payload, Exception):
                            raise payload
                        return _FakeResponse(payload)
                raise AssertionError("no scripted answer")

        self.chat = type("Chat", (), {"completions": _Completions()})()


class TestRunRobustness(EditorV3Fixture):
    def _patch_client(self, client):
        import sys
        import types
        fake = types.ModuleType("openai")
        fake.OpenAI = lambda **kwargs: client
        self._saved = sys.modules.get("openai")
        sys.modules["openai"] = fake
        self.addCleanup(lambda: sys.modules.__setitem__("openai", self._saved)
                        if self._saved else sys.modules.pop("openai", None))
        import os
        os.environ.setdefault("OPENAI_API_KEY_default", "test-key")

    def test_empty_response_is_a_clear_error(self) -> None:
        client = _FakeClient({"": None})
        with self.assertRaises(editor_v3.EmptyResponseError):
            editor_v3._call_structured(
                client, "m", "high",
                [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}],
                editor_v3.ASSESSMENT_SCHEMA)

    def test_response_without_choices_is_retried_then_reported(self) -> None:
        calls = []

        class _NoChoices:
            choices = None
            usage = None

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        calls.append(1)
                        return _NoChoices()

        import unittest.mock as mock
        with mock.patch.object(editor_v3.time, "sleep"):
            with self.assertRaises(editor_v3.ProviderOverloadedError):
                editor_v3._call_structured(
                    _Client(), "deepseek-flash", "high",
                    [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}],
                    editor_v3.ASSESSMENT_SCHEMA, "deepseek")
        self.assertEqual(len(calls), 4)

    def test_json_mode_provider_checks_the_schema_and_sends_it_in_the_prompt(self) -> None:
        seen = {}

        class _Spy(_FakeClient):
            pass

        client = _FakeClient({"": json.dumps({"scope_fit": {}})})
        orig = client.chat.completions.create

        def create(**kwargs):
            seen.update(kwargs)
            return orig(**kwargs)

        client.chat.completions.create = create
        with self.assertRaises(editor_v3.SchemaMismatchError):
            editor_v3._call_structured(
                client, "deepseek-v4-pro", "high",
                [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}],
                editor_v3.ASSESSMENT_SCHEMA, "deepseek")
        self.assertEqual(seen["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", seen)
        self.assertIn("JSON Schema", seen["messages"][-1]["content"])
        self.assertEqual(editor_v3.provider_for("deepseek-flash"), "deepseek")
        self.assertEqual(editor_v3.provider_for("gpt-5.6-sol"), "openai")

    def test_one_failing_job_does_not_lose_the_others_and_resume_skips_them(self) -> None:
        ids = list(self.journals)
        good = json.dumps(self.valid_assessment(ids[0]), ensure_ascii=False)
        mark = {i: f"{self.journals[i]['display_name']} ({i})" for i in ids}
        client = _FakeClient({mark[ids[0]]: good, mark[ids[1]]: RuntimeError("API down")})
        self._patch_client(client)
        run_dir = self.root / "run"
        out = editor_v3.execute({"MSX": self.pack}, {i: self.journals[i] for i in ids[:2]},
                                self.tiers, "m", "high", 1, None, run_dir)
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(len(out["errors"]), 1)
        saved = list((run_dir / "decisions").glob("*.json"))
        self.assertEqual(len(saved), 1)

        calls_before = client.calls
        client.script[mark[ids[1]]] = json.dumps(
            self.valid_assessment(ids[1]), ensure_ascii=False)
        out = editor_v3.execute({"MSX": self.pack}, {i: self.journals[i] for i in ids[:2]},
                                self.tiers, "m", "high", 1, None, run_dir)
        # the finished job came from disk; only the failed one was paid for again
        self.assertEqual(client.calls - calls_before, 1)
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["errors"], {})
        self.assertEqual(len(list((run_dir / "decisions").glob("*.json"))), 2)

    def test_main_refuses_to_overwrite_an_existing_results_file(self) -> None:
        existing = self.root / "editor_results_v3.json"
        existing.write_text("{}", encoding="utf-8")
        _write_json(self.root / "pack_MSX.json", self.pack)
        with self.assertRaises(FileExistsError):
            editor_v3.main(["--execute", "--registry", str(self.registry_path),
                            "--tiers", str(self.tier_path), "--pack-dir", str(self.root),
                            "--output", str(existing), "--run-dir", str(self.root / "r")])
        self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
