"""ScanService: the pipeline that used to live inside MainWindow.rescan()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher import scan_service as scan_service_module
from fabpublisher.models import EngineInfo, PluginStatus
from fabpublisher.scan_service import ScanService
from fabpublisher.state import StateStore, hash_plugin_source


def _service(tmp_path: Path) -> ScanService:
    return ScanService(StateStore(tmp_path / "state.json"))


def _fake_engine(tmp_path: Path, *builtins: str) -> EngineInfo:
    root = tmp_path / "UE_5.8"
    for name in builtins:
        d = root / "Engine" / "Plugins" / "Runtime" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.uplugin").write_text("{}")
    return EngineInfo(identifier="UE_5.8", version="5.8", root=root)


def test_missing_root_returns_empty_result(tmp_path: Path):
    result = _service(tmp_path).scan(tmp_path / "nope", None)
    assert result.plugins == []
    assert result.changed == set()
    assert result.cycle_error is None
    assert result.scanned is False


@pytest.mark.parametrize("root", ["", None])
def test_unset_root_does_not_scan_the_working_directory(root, tmp_path: Path):
    """Path("") is Path("."), so a falsy root must short-circuit."""
    result = _service(tmp_path).scan(root, None)
    assert result.scanned is False
    assert result.plugins == []


def test_valid_but_empty_folder_counts_as_scanned(tmp_path: Path):
    empty = tmp_path / "Plugins"
    empty.mkdir()
    result = _service(tmp_path).scan(empty, None)
    assert result.scanned is True
    assert result.plugins == []


def test_build_order_puts_dependencies_first(suite: Path, tmp_path: Path):
    result = _service(tmp_path).scan(suite, None)
    order = [p.name for p in result.plugins]
    assert order.index("Common") < order.index("Ability") < order.index("Core")
    assert [p.order for p in result.plugins] == sorted(p.order for p in result.plugins)


def test_first_scan_marks_everything_changed(suite: Path, tmp_path: Path):
    result = _service(tmp_path).scan(suite, None)
    assert result.changed == {"Common", "Ability", "Core"}
    assert set(result.hashes) == {"Common", "Ability", "Core"}


def test_external_dependency_outranks_changed(suite: Path, tmp_path: Path):
    """Ability declares ThirdParty, which resolves nowhere."""
    result = _service(tmp_path).scan(suite, None)
    by_name = {p.name: p for p in result.plugins}
    assert by_name["Ability"].status is PluginStatus.MISSING_DEP
    assert by_name["Common"].status is PluginStatus.CHANGED
    assert by_name["Core"].status is PluginStatus.CHANGED
    # Change state is still tracked even though the status reports the dep problem.
    assert "Ability" in result.changed


def test_up_to_date_after_marking_built(suite: Path, tmp_path: Path):
    service = _service(tmp_path)
    first = service.scan(suite, None)
    for name, digest in first.hashes.items():
        service.store.mark_built(name, digest)

    second = service.scan(suite, None)
    by_name = {p.name: p for p in second.plugins}
    assert second.changed == set()
    assert by_name["Common"].status is PluginStatus.UP_TO_DATE
    assert by_name["Core"].status is PluginStatus.UP_TO_DATE
    # Unresolvable dependency is not fixed by building.
    assert by_name["Ability"].status is PluginStatus.MISSING_DEP


def test_editing_a_dependency_cascades_to_dependents(suite: Path, tmp_path: Path):
    service = _service(tmp_path)
    first = service.scan(suite, None)
    for name, digest in first.hashes.items():
        service.store.mark_built(name, digest)

    (suite / "Common" / "Source" / "Common" / "Common.cpp").write_text("// edited\n")

    result = service.scan(suite, None)
    assert result.changed == {"Common"}
    assert result.impact["Common"] == "changed"
    assert result.impact["Ability"] == "dependency"
    assert result.impact["Core"] == "dependency"
    assert result.resubmit_only == ["Ability", "Core"]
    by_name = {p.name: p for p in result.plugins}
    assert by_name["Core"].status is PluginStatus.NEEDS_RESUBMIT


def test_validation_issues_are_returned_not_logged(suite: Path, tmp_path: Path):
    result = _service(tmp_path).scan(suite, None)
    messages = [i.message for i in result.issues["Ability"]]
    assert any("ThirdParty" in m for m in messages)
    # Core sets CanContainContent with no Content/ folder.
    assert any("CanContainContent" in i.message for i in result.issues["Core"])


def test_engine_builtins_resolve_and_suppress_the_warning(suite: Path, tmp_path: Path):
    engine = _fake_engine(tmp_path, "GameplayAbilities")
    result = _service(tmp_path).scan(suite, engine)
    messages = [i.message for i in result.issues["Ability"]]
    assert not any("GameplayAbilities" in m for m in messages)
    assert any("ThirdParty" in m for m in messages)


def test_engine_builtins_are_cached_per_engine_root(suite: Path, tmp_path: Path, monkeypatch):
    calls: list[Path] = []
    real = scan_service_module.engine_builtin_plugin_names

    def counting(root: Path) -> set[str]:
        calls.append(root)
        return real(root)

    monkeypatch.setattr(scan_service_module, "engine_builtin_plugin_names", counting)
    engine = _fake_engine(tmp_path, "GameplayAbilities")
    service = _service(tmp_path)
    service.scan(suite, engine)
    service.scan(suite, engine)
    assert len(calls) == 1


def test_dependency_cycle_reports_instead_of_raising(tmp_path: Path):
    root = tmp_path / "Plugins"
    for name, dep in (("A", "B"), ("B", "A")):
        d = root / name
        (d / "Source").mkdir(parents=True)
        (d / f"{name}.uplugin").write_text(
            json.dumps(
                {
                    "Modules": [{"Name": name, "Type": "Runtime", "LoadingPhase": "Default"}],
                    "Plugins": [{"Name": dep, "Enabled": True}],
                }
            )
        )

    result = _service(tmp_path).scan(root, None)
    assert result.cycle_error is not None
    assert {p.name for p in result.plugins} == {"A", "B"}
    assert all(p.order == 0 for p in result.plugins)


def test_hashes_match_the_domain_helper(suite: Path, tmp_path: Path):
    result = _service(tmp_path).scan(suite, None)
    assert result.hashes["Common"] == hash_plugin_source(suite / "Common")
