"""Independent signed-Horn policy oracles for procedural worlds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256

from .errors import Phase2OracleDisagreement, Phase2ValidationError

AtomKey = tuple[str, str, tuple[str, ...]]


@dataclass(frozen=True)
class OracleResult:
    action: str
    payload: dict[str, bool] | None
    positive: bool
    negative: bool
    positive_proofs: tuple[tuple[str, ...], ...]
    negative_proofs: tuple[tuple[str, ...], ...]
    useful_frontier_candidate_ids: tuple[str, ...]


def atom_key(atom: dict[str, Any]) -> AtomKey:
    return atom["polarity"], atom["predicate"], tuple(atom["arguments"])


def complement(key: AtomKey) -> AtomKey:
    polarity, predicate, arguments = key
    return (
        "negative" if polarity == "positive" else "positive",
        predicate,
        arguments,
    )


def _proof_object(steps: tuple[str, ...]) -> dict[str, Any]:
    proof_id = canonical_sha256({"steps": list(steps)})
    return {
        "proof_id": f"proof:{proof_id.removeprefix('sha256:')}",
        "steps": list(steps),
    }


def render_evidence(result: OracleResult) -> dict[str, Any]:
    return {
        "positive_proofs": [_proof_object(steps) for steps in result.positive_proofs],
        "negative_proofs": [_proof_object(steps) for steps in result.negative_proofs],
        "useful_frontier_candidate_ids": list(result.useful_frontier_candidate_ids),
    }


def _agenda_closure(
    world: dict[str, Any],
    *,
    extra_fact: tuple[str, AtomKey] | None,
    max_rule_firings: int,
) -> dict[AtomKey, tuple[str, ...]]:
    """Oracle A: monotone agenda closure, retaining first sorted derivation."""

    proofs: dict[AtomKey, tuple[str, ...]] = {}
    for fact in sorted(world["facts"], key=lambda item: item["fact_id"]):
        proofs.setdefault(atom_key(fact["atom"]), (fact["fact_id"],))
    if extra_fact is not None:
        fact_id, key = extra_fact
        proofs.setdefault(key, (fact_id,))

    firings = 0
    rules = sorted(world["rules"], key=lambda item: item["rule_id"])
    changed = True
    while changed:
        changed = False
        for rule in rules:
            consequent = atom_key(rule["consequent"])
            if consequent in proofs:
                continue
            antecedents = [atom_key(item) for item in rule["antecedents"]]
            if not all(item in proofs for item in antecedents):
                continue
            steps: list[str] = []
            for antecedent in antecedents:
                for step in proofs[antecedent]:
                    if step not in steps:
                        steps.append(step)
            if rule["rule_id"] not in steps:
                steps.append(rule["rule_id"])
            proofs[consequent] = tuple(steps)
            firings += 1
            if firings > max_rule_firings:
                raise Phase2ValidationError("forward oracle exceeded max_rule_firings")
            changed = True
    return proofs


def evaluate_forward(
    world: dict[str, Any],
    query: dict[str, Any],
    *,
    max_rule_firings: int,
) -> OracleResult:
    query_key = atom_key(query)
    opposite = complement(query_key)
    closure = _agenda_closure(world, extra_fact=None, max_rule_firings=max_rule_firings)
    positive = query_key in closure
    negative = opposite in closure
    useful: list[str] = []
    if not positive and not negative:
        for candidate in sorted(
            world["frontier"], key=lambda item: item["candidate_id"]
        ):
            candidate_closure = _agenda_closure(
                world,
                extra_fact=(
                    candidate["candidate_id"],
                    atom_key(candidate["observation"]),
                ),
                max_rule_firings=max_rule_firings,
            )
            if query_key in candidate_closure or opposite in candidate_closure:
                useful.append(candidate["candidate_id"])

    if positive and negative:
        action, payload = "abstain_conflict", None
    elif positive:
        action, payload = "return", {"truth": True}
    elif negative:
        action, payload = "return", {"truth": False}
    elif useful:
        action, payload = "continue", None
    elif world["frontier"]:
        action, payload = "stop_irrelevant", None
    else:
        action, payload = "abstain_unknown", None
    return OracleResult(
        action=action,
        payload=payload,
        positive=positive,
        negative=negative,
        positive_proofs=(closure[query_key],) if positive else (),
        negative_proofs=(closure[opposite],) if negative else (),
        useful_frontier_candidate_ids=tuple(useful),
    )


class _ProofTreeOracle:
    """Oracle B: depth-bounded recursive proof enumeration with path cycles."""

    def __init__(
        self,
        world: dict[str, Any],
        *,
        extra_fact: tuple[str, AtomKey] | None,
        max_depth: int,
        max_expansions: int,
    ) -> None:
        self.max_depth = max_depth
        self.max_expansions = max_expansions
        self.expansions = 0
        self.facts: dict[AtomKey, list[str]] = {}
        for fact in world["facts"]:
            self.facts.setdefault(atom_key(fact["atom"]), []).append(fact["fact_id"])
        if extra_fact is not None:
            fact_id, key = extra_fact
            self.facts.setdefault(key, []).append(fact_id)
        self.rules: dict[AtomKey, list[tuple[str, tuple[AtomKey, ...]]]] = {}
        for rule in world["rules"]:
            consequent = atom_key(rule["consequent"])
            antecedents = tuple(atom_key(item) for item in rule["antecedents"])
            self.rules.setdefault(consequent, []).append((rule["rule_id"], antecedents))
        for values in self.facts.values():
            values.sort()
        for values in self.rules.values():
            values.sort()

    def prove(
        self,
        target: AtomKey,
        *,
        depth: int = 0,
        active: frozenset[AtomKey] = frozenset(),
    ) -> tuple[tuple[str, ...], ...]:
        if depth > self.max_depth or target in active:
            return ()
        proofs: set[tuple[str, ...]] = {
            (fact_id,) for fact_id in self.facts.get(target, [])
        }
        next_active = active | {target}
        for rule_id, antecedents in self.rules.get(target, []):
            self.expansions += 1
            if self.expansions > self.max_expansions:
                raise Phase2ValidationError(
                    "proof-tree oracle exceeded max_rule_firings"
                )
            combinations: list[tuple[str, ...]] = [()]
            for antecedent in antecedents:
                child_proofs = self.prove(
                    antecedent, depth=depth + 1, active=next_active
                )
                if not child_proofs:
                    combinations = []
                    break
                expanded: list[tuple[str, ...]] = []
                for prefix in combinations:
                    for child in child_proofs:
                        merged = list(prefix)
                        for step in child:
                            if step not in merged:
                                merged.append(step)
                        expanded.append(tuple(merged))
                        if len(expanded) > self.max_expansions:
                            raise Phase2ValidationError(
                                "proof-tree oracle exceeded derivation-path bound"
                            )
                combinations = expanded
            for prefix in combinations:
                steps = list(prefix)
                if rule_id not in steps:
                    steps.append(rule_id)
                proofs.add(tuple(steps))
        return tuple(sorted(proofs))


def evaluate_proof_tree(
    world: dict[str, Any],
    query: dict[str, Any],
    *,
    max_depth: int,
    max_expansions: int,
) -> OracleResult:
    query_key = atom_key(query)
    opposite = complement(query_key)
    oracle = _ProofTreeOracle(
        world,
        extra_fact=None,
        max_depth=max_depth,
        max_expansions=max_expansions,
    )
    positive_proofs = oracle.prove(query_key)
    negative_proofs = oracle.prove(opposite)
    positive = bool(positive_proofs)
    negative = bool(negative_proofs)
    useful: list[str] = []
    if not positive and not negative:
        for candidate in sorted(
            world["frontier"], key=lambda item: item["candidate_id"]
        ):
            candidate_oracle = _ProofTreeOracle(
                world,
                extra_fact=(
                    candidate["candidate_id"],
                    atom_key(candidate["observation"]),
                ),
                max_depth=max_depth,
                max_expansions=max_expansions,
            )
            if candidate_oracle.prove(query_key) or candidate_oracle.prove(opposite):
                useful.append(candidate["candidate_id"])

    if positive:
        if negative:
            action = "abstain_conflict"
            payload = None
        else:
            action = "return"
            payload = {"truth": True}
    elif negative:
        action = "return"
        payload = {"truth": False}
    elif len(useful) > 0:
        action = "continue"
        payload = None
    elif len(world["frontier"]) > 0:
        action = "stop_irrelevant"
        payload = None
    else:
        action = "abstain_unknown"
        payload = None
    return OracleResult(
        action=action,
        payload=payload,
        positive=positive,
        negative=negative,
        positive_proofs=positive_proofs,
        negative_proofs=negative_proofs,
        useful_frontier_candidate_ids=tuple(useful),
    )


def compare_oracles(
    world: dict[str, Any],
    query: dict[str, Any],
    *,
    max_rule_firings: int,
    max_depth: int,
) -> tuple[OracleResult, OracleResult]:
    forward = evaluate_forward(world, query, max_rule_firings=max_rule_firings)
    proof_tree = evaluate_proof_tree(
        world,
        query,
        max_depth=max_depth,
        max_expansions=max_rule_firings,
    )
    forward_decision = (
        forward.action,
        forward.payload,
        forward.positive,
        forward.negative,
        forward.useful_frontier_candidate_ids,
    )
    proof_tree_decision = (
        proof_tree.action,
        proof_tree.payload,
        proof_tree.positive,
        proof_tree.negative,
        proof_tree.useful_frontier_candidate_ids,
    )
    if forward_decision != proof_tree_decision:
        raise Phase2OracleDisagreement(
            "independent oracles disagree: "
            f"forward={forward_decision!r}, proof_tree={proof_tree_decision!r}"
        )
    return forward, proof_tree
