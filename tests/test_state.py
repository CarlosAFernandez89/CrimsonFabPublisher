from pathlib import Path

from fabpublisher.dependencies import resubmit_set
from fabpublisher.discovery import discover_plugins
from fabpublisher.state import StateStore, compute_changes, hash_plugin_source


def test_hash_ignores_build_artifacts(suite: Path):
    common = suite / "Common"
    before = hash_plugin_source(common)
    # Dropping a Binaries file must not change the hash.
    (common / "Binaries").mkdir()
    (common / "Binaries" / "x.dll").write_text("junk")
    assert hash_plugin_source(common) == before


def test_hash_detects_source_edit(suite: Path):
    common = suite / "Common"
    before = hash_plugin_source(common)
    (common / "Source" / "Common" / "Common.cpp").write_text("// edited\n")
    assert hash_plugin_source(common) != before


def test_compute_changes_and_resubmit_flow(suite: Path, tmp_path: Path):
    plugins = discover_plugins(suite)
    store = StateStore(tmp_path / "state.json")

    # First scan: nothing built yet -> everything counts as changed.
    current, changed = compute_changes(plugins, store)
    assert changed == {"Common", "Ability", "Core"}

    # Mark all as built, persist, reload.
    for name, digest in current.items():
        store.mark_built(name, digest)
    store.save()
    store = StateStore(tmp_path / "state.json")

    # Nothing changed now.
    _, changed = compute_changes(plugins, store)
    assert changed == set()

    # Edit Common only.
    (suite / "Common" / "Source" / "Common" / "Common.cpp").write_text("// v2\n")
    _, changed = compute_changes(plugins, store)
    assert changed == {"Common"}

    # Resubmit impact fans out to dependents.
    impact = resubmit_set(plugins, changed)
    assert set(impact) == {"Common", "Ability", "Core"}
