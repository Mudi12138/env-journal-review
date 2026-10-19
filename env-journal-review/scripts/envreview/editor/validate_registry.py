"""Validate the v3 journal, tier, and versioned official-source registries."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
EXPECTED_DATE = "2026-09-22"
# tier bars were recalibrated separately (see tier_bars.json revision_note)
EXPECTED_TIER_DATE = "2026-10-15"
EXPECTED_JOURNALS = {
    "nature_water",
    "nature_sustainability",
    "nature_climate_change",
    "nature_geoscience",
    "one_earth",
    "environmental_science_technology",
    "water_research",
}
EXPECTED_TIER_COUNTS = {"T3": 5, "T2": 1, "T1": 1}
OFFICIAL_HOSTS = {
    "www.nature.com",
    "researcher-resources.acs.org",
    "shop.elsevier.com",
    "www.cell.com",
    "info.cell.com",
    "www.sciencedirect.com",
}
FORBIDDEN_KEYS = {"transfer", "transfer_target", "profile", "profile_statistics"}
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


class ValidationError(Exception):
    """Raised when a registry invariant is violated."""


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Top-level JSON value must be an object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def count_official_excerpt_words(
    path: Path,
    section_name: str,
    section: dict,
    source_ids: set[str],
    totals: defaultdict[str, int],
) -> None:
    excerpts = section.get("official_excerpts")
    require(isinstance(excerpts, list) and excerpts, f"Missing {section_name} official excerpts: {path}")
    for excerpt in excerpts:
        require(isinstance(excerpt, dict), f"{section_name} excerpt must be an object: {path}")
        source_ref = excerpt.get("source_ref")
        text = excerpt.get("text")
        require(source_ref in source_ids, f"{section_name} excerpt has unknown source_ref {source_ref}: {path}")
        require(isinstance(text, str) and text.strip(), f"Empty {section_name} official excerpt: {path}")
        totals[source_ref] += len(WORD_RE.findall(text))


def validate_snapshot(path: Path, journal: dict) -> None:
    snapshot = load_json(path)
    journal_id = journal["journal_id"]
    require(snapshot.get("journal_id") == journal_id, f"Snapshot ID mismatch: {path}")
    require(snapshot.get("display_name") == journal["display_name"], f"Display-name mismatch: {path}")
    require(snapshot.get("retrieved_at") == EXPECTED_DATE, f"Unexpected snapshot date: {path}")

    forbidden = FORBIDDEN_KEYS.intersection(walk_keys(snapshot))
    require(not forbidden, f"Forbidden keys in {path}: {sorted(forbidden)}")

    scope = snapshot.get("scope")
    require(isinstance(scope, dict), f"Missing scope object: {path}")
    scope_text = scope.get("text")
    require(isinstance(scope_text, str) and scope_text.strip(), f"Missing scope text: {path}")
    expected_hash = hashlib.sha256(scope_text.encode("utf-8")).hexdigest()
    require(scope.get("text_sha256") == expected_hash, f"Scope hash mismatch: {path}")

    sources = snapshot.get("sources")
    require(isinstance(sources, list) and sources, f"Missing official sources: {path}")
    source_ids: set[str] = set()
    for source in sources:
        require(isinstance(source, dict), f"Source must be an object: {path}")
        source_id = source.get("source_id")
        require(isinstance(source_id, str) and source_id, f"Source without source_id: {path}")
        require(source_id not in source_ids, f"Duplicate source_id {source_id}: {path}")
        source_ids.add(source_id)
        require(source.get("retrieved_at") == EXPECTED_DATE, f"Unexpected source date: {path}#{source_id}")
        url = source.get("url")
        require(isinstance(url, str) and url.startswith("https://"), f"Non-HTTPS source: {path}#{source_id}")
        host = (urlparse(url).hostname or "").lower()
        require(host in OFFICIAL_HOSTS, f"Non-official source host {host}: {path}#{source_id}")
        declared_domain = source.get("publisher_domain")
        require(
            isinstance(declared_domain, str) and (host == declared_domain or host.endswith("." + declared_domain)),
            f"publisher_domain does not match URL host: {path}#{source_id}",
        )

    for section_name in ("scope", "content_types"):
        refs = snapshot.get(section_name, {}).get("source_refs")
        require(isinstance(refs, list) and refs, f"Missing {section_name}.source_refs: {path}")
        unknown = set(refs) - source_ids
        require(not unknown, f"Unknown {section_name} source refs {sorted(unknown)}: {path}")

    content_types = snapshot.get("content_types")
    require(isinstance(content_types, dict), f"Missing content_types object: {path}")
    primary = content_types.get("primary_research")
    require(isinstance(primary, list) and primary, f"No verified primary-research type: {path}")
    completeness = content_types.get("capture_completeness")
    require(completeness in {"full", "partial"}, f"Invalid content-type capture completeness: {path}")
    absence_is_not_exclusion = content_types.get("absence_is_not_exclusion")
    require(isinstance(absence_is_not_exclusion, bool), f"Missing absence_is_not_exclusion: {path}")
    if completeness == "partial":
        require(absence_is_not_exclusion is True, f"Partial capture must not treat absence as exclusion: {path}")
        require(
            isinstance(content_types.get("capture_status"), str) and content_types["capture_status"].strip(),
            f"Partial capture requires an explicit capture_status: {path}",
        )
    else:
        require(absence_is_not_exclusion is False, f"Full capture should set absence_is_not_exclusion=false: {path}")

    excerpt_words: defaultdict[str, int] = defaultdict(int)
    count_official_excerpt_words(path, "scope", scope, source_ids, excerpt_words)
    count_official_excerpt_words(path, "content_types", content_types, source_ids, excerpt_words)
    for source_ref, word_count in excerpt_words.items():
        require(
            word_count <= 25,
            f"Combined official excerpts exceed 25 words for {source_ref} ({word_count}): {path}",
        )


def validate() -> None:
    registry = load_json(ROOT / "journal_registry.json")
    tiers = load_json(ROOT / "tier_bars.json")
    require(registry.get("effective_date") == EXPECTED_DATE, "Unexpected registry date")
    require(tiers.get("effective_date") == EXPECTED_TIER_DATE, "Unexpected tier-registry date")
    require(tiers.get("order_high_to_low") == ["T3", "T2", "T1"], "Tier order must be T3 > T2 > T1")

    tier_records = tiers.get("tiers")
    require(isinstance(tier_records, dict), "Missing tiers object")
    valid_tiers = set(tier_records)
    require(valid_tiers == {"T3", "T2", "T1"}, f"Unexpected tier IDs: {sorted(valid_tiers)}")

    journals = registry.get("journals")
    require(isinstance(journals, list) and len(journals) == 7, "Registry must contain exactly seven journals")
    journal_ids = [journal.get("journal_id") for journal in journals]
    require(len(set(journal_ids)) == len(journal_ids), "journal_id values must be unique")
    require(set(journal_ids) == EXPECTED_JOURNALS, f"Unexpected journal set: {sorted(set(journal_ids))}")

    tiers_seen: Counter[str] = Counter()
    for journal in journals:
        tier_id = journal.get("tier_id")
        require(tier_id in valid_tiers, f"Invalid tier_id for {journal.get('journal_id')}: {tier_id}")
        tiers_seen[tier_id] += 1
        snapshot_rel = journal.get("snapshot")
        require(isinstance(snapshot_rel, str) and snapshot_rel, f"Missing snapshot path: {journal.get('journal_id')}")
        snapshot_path = (ROOT / snapshot_rel).resolve()
        require(ROOT.resolve() in snapshot_path.parents, f"Snapshot escapes v3 directory: {snapshot_rel}")
        require(snapshot_path.is_file(), f"Missing snapshot file: {snapshot_path}")
        validate_snapshot(snapshot_path, journal)

        members = tier_records[tier_id].get("member_journals")
        require(isinstance(members, list), f"Missing member_journals for {tier_id}")
        require(journal["journal_id"] in members, f"Tier registry omits {journal['journal_id']} from {tier_id}")

    require(dict(tiers_seen) == EXPECTED_TIER_COUNTS, f"Tier distribution mismatch: {dict(tiers_seen)}")
    all_members = [member for tier in tier_records.values() for member in tier.get("member_journals", [])]
    require(len(all_members) == len(set(all_members)), "A journal appears in more than one tier")
    require(set(all_members) == EXPECTED_JOURNALS, "Tier members and journal registry do not match")

    forbidden = FORBIDDEN_KEYS.intersection(walk_keys(registry))
    forbidden.update(FORBIDDEN_KEYS.intersection(walk_keys(tiers)))
    require(not forbidden, f"Forbidden keys in registries: {sorted(forbidden)}")


def main() -> int:
    try:
        validate()
    except ValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print("VALID: 7 journals; tiers T3=5, T2=1, T1=1; official sources, excerpts, and hashes verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
