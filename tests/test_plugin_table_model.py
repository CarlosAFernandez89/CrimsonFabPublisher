"""Status/reason bookkeeping in the table model."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from fabpublisher.models import PluginInfo, PluginStatus  # noqa: E402
from fabpublisher.ui.plugin_table_model import (  # noqa: E402
    COL_STATUS,
    PluginTableModel,
    ReasonRole,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _plugin(status: PluginStatus = PluginStatus.UNKNOWN) -> PluginInfo:
    return PluginInfo(
        name="CrimsonCombatText",
        path=Path("Plugins/CrimsonCombatText"),
        uplugin_path=Path("Plugins/CrimsonCombatText/CrimsonCombatText.uplugin"),
        status=status,
    )


def _reason(model: PluginTableModel) -> str:
    return model.data(model.index(0, COL_STATUS), ReasonRole)


def test_success_clears_the_previous_failure_reason(qapp):
    model = PluginTableModel()
    model.set_plugins([_plugin()])

    model.set_status("CrimsonCombatText", PluginStatus.FAILED, "Build failed (exit code 6)")
    assert _reason(model) == "Build failed (exit code 6)"

    model.set_status("CrimsonCombatText", PluginStatus.SUCCESS, "")
    assert _reason(model) == ""


def test_rescan_drops_reasons_from_the_previous_build(qapp):
    model = PluginTableModel()
    model.set_plugins([_plugin()])
    model.set_status("CrimsonCombatText", PluginStatus.FAILED, "Build failed (exit code 6)")

    model.set_plugins([_plugin(PluginStatus.UP_TO_DATE)])
    assert _reason(model) == ""
