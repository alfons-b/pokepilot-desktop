"""Catalog of PGSharp user-facing features PokePilot can map.

Nothing here claims a feature exists. Availability depends on the installed PGSharp version and
edition (free/premium) and is recorded per user after checking the real UI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureInfo:
    id: str
    name: str
    description: str
    toggleable: bool  # has an on/off switch in the UI


FEATURE_CATALOG: tuple[FeatureInfo, ...] = (
    FeatureInfo("joystick", "Joystick", "On-screen joystick for walking.", True),
    FeatureInfo("teleport", "Teleport", "Jump to coordinates entered in PGSharp's teleport dialog.", False),
    FeatureInfo("autowalk", "Autowalk", "Walk automatically to a destination.", True),
    FeatureInfo("custom_gpx", "Custom GPX", "Follow a route from a GPX file.", False),
    FeatureInfo("nearby_radar", "Nearby Radar", "List nearby Pokémon.", True),
    FeatureInfo("quick_catch", "Quick Catch", "Shortened catch flow.", True),
    FeatureInfo("virtual_go_plus", "Virtual GO Plus", "Virtual Pokémon GO Plus device.", True),
    FeatureInfo("auto_transfer", "Auto Transfer", "Transfer after catching.", True),
    FeatureInfo("auto_discard", "Auto Discard", "Discard excess items.", True),
    FeatureInfo("auto_incubator", "Auto Incubator", "Put eggs into incubators automatically.", True),
)

FEATURES_BY_ID = {f.id: f for f in FEATURE_CATALOG}
