"""The Track O walk, pinned exactly, so an optimisation cannot change it silently.

Track O's result is the walk: which edges it examined, which routes it emitted,
when it stopped. The optimisation pass rewrites how features are built and how
work is batched, and none of that may move those decisions. Logits may drift by
float reassociation and are held to a tolerance; **the walk decisions are held
exactly**, because the frontier tie-break sums two detached float32 values in
Python and a near-tie can flip.

Regenerate the fixture with `scripts/read_run_track_o_golden.py` only when a
change is *intended* to alter behaviour, and say so in the commit message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/track_o_golden.json"
LOGIT_TOLERANCE = 1e-4  # the v1 precedent, tests/test_read_run.py


def _torch():
    return pytest.importorskip("torch")


@pytest.fixture(scope="module")
def fixture() -> dict:
    if not FIXTURE_PATH.exists():
        pytest.fail(
            "golden fixture missing; regenerate with scripts/read_run_track_o_golden.py"
        )
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture(scope="module")
def golden_module():
    import importlib.util

    path = ROOT / "scripts" / "read_run_track_o_golden.py"
    spec = importlib.util.spec_from_file_location("read_run_track_o_golden", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rebuild(torch, golden_module, fixture):
    from hippocampus_foundation.read_run.model_v2 import build_read_model_v2

    config = json.loads((ROOT / fixture["config"]).read_text())
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(fixture["model_seed"])
    model = build_read_model_v2(config)
    model.eval()
    return model


@pytest.mark.parametrize("cell", ("deg3_len6_v8", "deg6_len8_v4_rep"))
@pytest.mark.parametrize("mode", ("on_policy", "gold", "walker"))
def test_walk_decisions_match_the_golden_fixture(
    fixture, golden_module, cell: str, mode: str
) -> None:
    torch = _torch()
    model = _rebuild(torch, golden_module, fixture)
    episodes = golden_module.episodes_for(cell)
    recorded = fixture["cells"][cell]
    assert [e.episode_id for e in episodes] == recorded["episode_ids"], (
        "fixture episodes drifted; the generator changed"
    )
    expected = recorded["modes"][mode]
    actual = golden_module.record(torch, model, episodes, mode=mode)

    # Exact: these are the walk's decisions and Track O's result rests on them.
    # Compared as digests so no per-episode route data lives in a tracked file.
    assert actual["edge_ids_sha256"] == expected["edge_ids_sha256"]
    assert actual["prefixes_sha256"] == expected["prefixes_sha256"]
    assert actual["routes_sha256"] == expected["routes_sha256"]
    assert actual["stop_reason"] == expected["stop_reason"]
    assert actual["examined_count"] == expected["examined_count"]
    assert actual["expansion_count"] == expected["expansion_count"]

    # Tolerance: float reassociation is permitted, a different answer is not.
    got = torch.tensor(actual["logits"])
    want = torch.tensor(expected["logits"])
    assert torch.allclose(got, want, atol=LOGIT_TOLERANCE), (
        f"logits drifted beyond {LOGIT_TOLERANCE}"
    )
    assert torch.equal(got.argmax(dim=-1), want.argmax(dim=-1))


@pytest.mark.parametrize("cell", ("deg3_len6_v8", "deg6_len8_v4_rep"))
def test_feature_vectors_match_the_golden_fixture(
    fixture, golden_module, cell: str
) -> None:
    """The featurisers, pinned elementwise and independently of any weights.

    The walk-decision assertions above are an insensitive detector on their own:
    with a randomly initialised scorer a sign flip on the similarity feature left
    every examined set identical. Since the optimisation pass rewrites exactly
    these functions, they are compared directly.
    """

    _torch()
    episodes = golden_module.episodes_for(cell)
    expected = fixture["cells"][cell]["features"]
    actual = golden_module.feature_rows(episodes)
    assert set(actual) == set(expected)
    for episode_id, blocks in expected.items():
        assert set(actual[episode_id]) == set(blocks), episode_id
        for name, rows in blocks.items():
            assert actual[episode_id][name] == rows, f"{episode_id}/{name}"


def test_the_feature_fixture_would_catch_a_perturbation(fixture, golden_module) -> None:
    """A fixture that cannot fail is worthless; prove this one can."""

    _torch()

    cell = "deg6_len8_v4_rep"
    episodes = golden_module.episodes_for(cell)
    expected = fixture["cells"][cell]["features"]
    # Patch the name the recorder actually calls: the script imported it, so it
    # holds its own reference and patching the defining module would miss.
    original = golden_module.pair_features
    try:

        def zeroed_adjacency(index, candidate, context):
            row = original(index, candidate, context)
            row[1:6] = [0.0] * 5
            return row

        golden_module.pair_features = zeroed_adjacency
        perturbed = golden_module.feature_rows(episodes)
    finally:
        golden_module.pair_features = original
    assert any(
        perturbed[episode_id]["pair"] != blocks["pair"]
        for episode_id, blocks in expected.items()
    ), "zeroing the adjacency bits did not change the recorded features"


def test_the_fixture_pins_the_config_it_was_generated_from(fixture) -> None:
    import hashlib

    digest = hashlib.sha256((ROOT / fixture["config"]).read_bytes()).hexdigest()
    assert fixture["config_sha256"] == f"sha256:{digest}", (
        "the training config changed after the fixture was recorded; "
        "regenerate the fixture deliberately"
    )


@pytest.mark.parametrize("cell", ("deg3_len6_v8", "deg6_len8_v4_rep"))
def test_walk_is_identical_under_bfloat16_autocast(
    fixture, golden_module, cell: str
) -> None:
    """v1 shipped a dtype fault to a whole sweep behind an fp32-only check.

    Autocast may move the logits; it must not move the walk.
    """

    torch = _torch()
    if not torch.cuda.is_available():
        pytest.skip("autocast equivalence needs CUDA")
    from hippocampus_foundation.read_run.model_v2 import build_read_model_v2

    config = json.loads((ROOT / fixture["config"]).read_text())
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(fixture["model_seed"])
    model = build_read_model_v2(config).cuda().eval()
    episodes = golden_module.episodes_for(cell)
    visible = [e.visible for e in episodes]
    with torch.no_grad():
        plain = model(visible, budget=golden_module.BUDGET)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            cast = model(visible, budget=golden_module.BUDGET)
    assert cast["edge_ids"] == plain["edge_ids"]
    assert cast["routes"] == plain["routes"]
    assert cast["stop_reason"] == plain["stop_reason"]
    assert cast["expansion_count"] == plain["expansion_count"]
