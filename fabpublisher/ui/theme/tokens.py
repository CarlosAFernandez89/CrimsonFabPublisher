"""Design tokens. Every colour in the app resolves here and nowhere else.

Contrast ratios in the comments are measured against `surface` (#16181C).
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Tokens:
    name: str

    # -- surfaces ---------------------------------------------------------
    surface_sunken: str  # log body, table viewport
    surface: str  # window background
    surface_raised: str  # cards, sidebar, status strip
    surface_overlay: str  # hover, tooltips, menus
    border: str  # dividers, card outlines
    border_strong: str  # input borders, splitter handles

    # -- text -------------------------------------------------------------
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_accent: str

    # -- accent: crimson means "live", never decoration -------------------
    accent: str  # fills only — too dark to write words in
    accent_hover: str
    accent_pressed: str
    accent_text: str  # the crimson that is legible as text
    accent_subtle: str  # active nav item / selected row background
    focus_ring: str

    # -- semantic ---------------------------------------------------------
    success: str
    warning: str
    resubmit: str
    danger: str
    info: str
    neutral: str

    def as_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


CRIMSON_DARK = Tokens(
    name="crimson-dark",
    surface_sunken="#101114",
    surface="#16181C",
    surface_raised="#1D2026",
    surface_overlay="#24272E",
    border="#2B2F37",
    border_strong="#3A3F49",
    text_primary="#E6E8EC",  # 14.6:1
    text_secondary="#A8AEB9",  # 8.2:1
    text_muted="#7D8492",  # 4.8:1
    text_on_accent="#FFFFFF",  # 5.9:1 on accent
    accent="#C8102E",
    accent_hover="#E01B3D",
    accent_pressed="#A20D25",
    accent_text="#FF6B81",  # 6.6:1
    accent_subtle="#2A1219",
    focus_ring="#FF4D6A",
    success="#4ADE80",  # 10.3:1
    warning="#F5B841",  # 10.1:1
    resubmit="#F0883E",  # 7.1:1
    danger="#FF6B6B",  # 6.5:1
    info="#5EA9F0",  # 7.2:1
    neutral="#8A919C",  # 5.6:1
)

#: The active token set. Only one theme exists; a second would go here.
ACTIVE = CRIMSON_DARK
