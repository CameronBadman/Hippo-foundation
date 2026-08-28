"""Deterministic evaluation quarantine compilation and matching."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .canonical import sha256_bytes
from .errors import QuarantineError, ValidationError

MINHASH_PERMUTATIONS = 128
MINHASH_SEED = "hippocampus-foundation-quarantine-v1"
MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
ALLOWED_RELATIONSHIPS = frozenset(
    {
        "revision_of",
        "page_family",
        "redirect_to",
        "title_alias",
        "sitelink",
        "incident_statement",
        "same_work",
        "story_family",
        "contract_family",
        "paper_family",
        "case_family",
        "claimant_family",
        "organisation_family",
        "publisher_family",
        "time_window",
        "generator_world",
        "generator_grammar",
        "generator_seed_family",
        "near_duplicate_cluster",
    }
)
DIRECTED_RELATIONSHIPS = frozenset({"incident_statement"})
FORBIDDEN_PUBLIC_FIELDS = frozenset(
    {"label", "labels", "answer", "answers", "target", "targets", "split", "membership"}
)


@dataclass(frozen=True, order=True)
class Identifier:
    namespace: str
    value: str
    source_version: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "namespace": self.namespace,
            "value": self.value,
            "source_version": self.source_version,
        }


def normalize_identifier(
    namespace: str, value: str, source_version: str | None = None
) -> Identifier:
    namespace = namespace.strip().lower()
    value = value.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", namespace):
        raise ValidationError(f"invalid identifier namespace: {namespace!r}")
    if namespace in {"wikipedia.page", "wikipedia.revision", "pmid"}:
        if not value.isascii() or not value.isdigit():
            raise ValidationError(f"{namespace} must be numeric")
        numeric_value = int(value)
        if numeric_value < 1:
            raise ValidationError(f"{namespace} must be positive")
        value = str(numeric_value)
    elif namespace == "wikidata.entity":
        value = value.upper()
        if not re.fullmatch(r"[QPL][1-9][0-9]*", value):
            raise ValidationError(f"invalid Wikidata identifier: {value!r}")
    elif namespace == "doi":
        value = re.sub(
            r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I
        )
        value = value.lower()
        if not value.startswith("10.") or "/" not in value:
            raise ValidationError(f"invalid DOI: {value!r}")
    elif namespace == "pmcid":
        value = value.upper()
        if not re.fullmatch(r"PMC[1-9][0-9]*", value):
            raise ValidationError(f"invalid PMCID: {value!r}")
    elif namespace == "url":
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValidationError(f"invalid URL identifier: {value!r}")
        hostname = parts.hostname.lower()
        port = parts.port
        if port and not (
            (parts.scheme.lower() == "http" and port == 80)
            or (parts.scheme.lower() == "https" and port == 443)
        ):
            hostname = f"{hostname}:{port}"
        path = parts.path.rstrip("/") or "/"
        value = urlunsplit((parts.scheme.lower(), hostname, path, parts.query, ""))
    if not value:
        raise ValidationError("identifier value cannot be empty")
    return Identifier(namespace=namespace, value=value, source_version=source_version)


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(value.split())


def normalized_text_sha256(text: str) -> str:
    return sha256_bytes(normalize_text(text).encode("utf-8"))


def _shingles(text: str) -> tuple[str, set[str]]:
    normalized = normalize_text(text)
    words = normalized.split()
    if len(words) < 50:
        compact = " ".join(words)
        return "character5", {
            compact[index : index + 5]
            for index in range(max(1, len(compact) - 4))
            if compact[index : index + 5]
        }
    return "word5", {
        " ".join(words[index : index + 5]) for index in range(len(words) - 4)
    }


def _hash_shingles(shingles: Iterable[str]) -> list[str]:
    return sorted(
        {hashlib.sha256(value.encode("utf-8")).hexdigest()[:32] for value in shingles}
    )


def _minhash(shingle_hashes: Iterable[str]) -> list[int]:
    values = list(shingle_hashes)
    if not values:
        values = [hashlib.sha256(b"").hexdigest()[:32]]
    signature: list[int] = []
    for permutation in range(MINHASH_PERMUTATIONS):
        salt = f"{MINHASH_SEED}:{permutation}:".encode()
        signature.append(
            min(
                # RFC 8785 canonical JSON uses the interoperable IEEE-754
                # integer domain. Keep the high 53 bits of the deterministic
                # 64-bit sketch instead of emitting an unsafe JSON integer.
                int.from_bytes(
                    hashlib.sha256(salt + value.encode("ascii")).digest()[:8],
                    "big",
                )
                >> 11
                for value in values
            )
        )
    return signature


def fingerprint_text(text: str, fingerprint_id: str) -> dict[str, Any]:
    kind, shingles = _shingles(text)
    hashes = _hash_shingles(shingles)
    return {
        "fingerprint_id": fingerprint_id,
        "kind": kind,
        "minhash": _minhash(hashes),
        "shingle_hashes": hashes,
    }


def minhash_similarity(left: list[int], right: list[int]) -> float:
    if len(left) != MINHASH_PERMUTATIONS or len(right) != MINHASH_PERMUTATIONS:
        raise QuarantineError("MinHash signatures must contain exactly 128 values")
    return sum(a == b for a, b in zip(left, right, strict=True)) / MINHASH_PERMUTATIONS


def jaccard_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _reject_forbidden_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_PUBLIC_FIELDS:
                raise QuarantineError(
                    f"label-bearing field forbidden in public index: {path}/{key}"
                )
            _reject_forbidden_fields(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{path}/{index}")


def dependency_closure(
    seeds: Iterable[Identifier],
    relationships: Iterable[tuple[Identifier, str, Identifier]],
) -> set[Identifier]:
    adjacency: dict[Identifier, list[tuple[str, Identifier]]] = defaultdict(list)
    for source, relation, destination in relationships:
        if relation not in ALLOWED_RELATIONSHIPS:
            raise QuarantineError(f"unregistered closure relationship: {relation}")
        adjacency[source].append((relation, destination))
        # An entity seeds its incident statements, but a statement must not seed
        # its entity (and thereby every sibling statement on that entity).
        if relation not in DIRECTED_RELATIONSHIPS:
            adjacency[destination].append((relation, source))
    closed = set(seeds)
    queue = deque(sorted(closed))
    while queue:
        current = queue.popleft()
        for _relation, neighbour in sorted(adjacency.get(current, [])):
            if neighbour not in closed:
                closed.add(neighbour)
                queue.append(neighbour)
    return closed


def compile_public_index(
    *,
    index_id: str,
    bundles: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    all_identifiers: set[Identifier] = set()
    all_raw_hashes: set[str] = set()
    all_normalized_hashes: set[str] = set()
    fingerprint_values: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    seen_seals: set[str] = set()
    for bundle in bundles:
        seal_id = bundle["seal_id"]
        if not isinstance(seal_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_.-]+", seal_id
        ):
            raise QuarantineError(f"invalid quarantine seal_id: {seal_id!r}")
        if seal_id in seen_seals:
            raise QuarantineError(
                f"duplicate seal_id in quarantine specification: {seal_id}"
            )
        seen_seals.add(seal_id)
        record_count = bundle["sealed_record_count"]
        if (
            not isinstance(record_count, int)
            or isinstance(record_count, bool)
            or record_count < 1
        ):
            raise QuarantineError(f"sealed_record_count is unresolved for {seal_id}")
        seeds = list(bundle.get("seeds", []))
        relationships = list(bundle.get("relationships", []))
        raw_hashes = set(bundle.get("raw_hashes", []))
        normalized_hashes = set(bundle.get("normalized_hashes", []))
        fingerprints = list(bundle.get("fingerprints", []))
        if not (seeds or raw_hashes or normalized_hashes or fingerprints):
            raise QuarantineError(f"quarantine bundle has no selectors: {seal_id}")
        closed = dependency_closure(seeds, relationships)
        all_identifiers.update(closed)
        all_raw_hashes.update(raw_hashes)
        all_normalized_hashes.update(normalized_hashes)
        fingerprint_values.extend(fingerprints)
        coverage.append(
            {
                "seal_id": seal_id,
                "sealed_record_count": record_count,
                "seed_identifier_count": len(set(seeds)),
                "closure_identifier_count": len(closed),
                "relationship_count": len(relationships),
                "raw_hash_count": len(raw_hashes),
                "normalized_hash_count": len(normalized_hashes),
                "fingerprint_count": len(fingerprints),
                "closure_complete": True,
            }
        )
    if not coverage:
        raise QuarantineError("quarantine specification contains no sealed bundles")
    fingerprint_ids = [item.get("fingerprint_id") for item in fingerprint_values]
    if len(fingerprint_ids) != len(set(fingerprint_ids)):
        raise QuarantineError("duplicate fingerprint_id in public index")
    result = {
        "schema_version": "1.0.0",
        "index_id": index_id,
        "closure_policy_id": "quarantine-closure-v1",
        "source_seal_ids": sorted(seen_seals),
        "coverage": sorted(coverage, key=lambda item: item["seal_id"]),
        "identifiers": [item.as_dict() for item in sorted(all_identifiers)],
        "raw_hashes": sorted(all_raw_hashes),
        "normalized_hashes": sorted(all_normalized_hashes),
        "fingerprints": sorted(
            fingerprint_values, key=lambda item: item["fingerprint_id"]
        ),
    }
    _reject_forbidden_fields(result)
    return result


def match_record(descriptor: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    reasons: set[str] = set()
    required = {"identifiers", "raw_sha256", "normalized_sha256", "fingerprint"}
    missing = sorted(required - descriptor.keys())
    if missing:
        return {
            "decision": "undetermined",
            "reasons": [f"missing:{name}" for name in missing],
        }

    indexed_ids = {
        normalize_identifier(
            item["namespace"], item["value"], item.get("source_version")
        )
        for item in index["identifiers"]
    }
    record_ids = {
        normalize_identifier(
            item["namespace"], item["value"], item.get("source_version")
        )
        for item in descriptor["identifiers"]
    }
    if indexed_ids & record_ids:
        reasons.add("exact_identifier")
    if descriptor["raw_sha256"] in set(index["raw_hashes"]):
        reasons.add("raw_hash")
    if descriptor["normalized_sha256"] in set(index["normalized_hashes"]):
        reasons.add("normalized_hash")

    candidate = descriptor["fingerprint"]
    for reference in index["fingerprints"]:
        if candidate["kind"] != reference["kind"]:
            continue
        # MinHash is retained for deterministic indexing/ranking, but it cannot
        # veto exact comparison: a stochastic estimate must never create a
        # contamination false negative.
        minhash_similarity(candidate["minhash"], reference["minhash"])
        threshold = 0.9 if candidate["kind"] == "character5" else 0.85
        exact = jaccard_similarity(
            candidate["shingle_hashes"], reference["shingle_hashes"]
        )
        if exact >= threshold:
            reasons.add(f"near_duplicate:{reference['fingerprint_id']}")
    if reasons:
        return {"decision": "excluded", "reasons": sorted(reasons)}
    return {"decision": "clear", "reasons": []}
