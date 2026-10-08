"""Weapon presets: per-weapon configuration as data (plan §17).

A preset captures the weapon-specific layout that must NOT be hard-coded
(plan §17: "Do not hard-code sword-specific coordinates into the add-on"):
grip/tip reference points (weapon-bone LOCAL vectors), the blade axis
(plan §47), and the preview mesh pointer (plan §16).

Save reads the CURRENT rig (custom props + blade axis, pure reads);
Apply writes them back. No edit mode, no rest-pose changes -- unlike the
pre-rework bone-position presets. Pose animation is untouched by either
direction (save reads props, apply writes props; channels unchanged).
"""
import bpy

from ..constants import (
    BLADE_AXES,
    BONE_WEAPON,
    CONFIG_PROPS,
    DEFAULT_GRIP_OFFSETS,
    WeaponRigError,
)
from ..utils import transforms
from ..weapon.preview import PREVIEW_PROP

# Preset-owned weapon reference points (weapon-local vectors).
PRESET_PROPS = CONFIG_PROPS


def _require_current_rig(armature):
    """Presets are new-format config: legacy rigs must migrate first.

    (Unlike attach/snap/pivot/aim/bake, which resolve the legacy root
    transparently, presets STORE the new layout -- capturing from a legacy
    rig would silently bless stale data, so this is an explicit error
    pointing at Create-to-migrate.)
    """
    from ..constants import LEGACY_NAMES
    if BONE_WEAPON not in armature.data.bones:
        legacy = [n for n in LEGACY_NAMES if n in armature.data.bones]
        hint = (" Pre-rework bones present (%s) -- run Create Weapon Rig "
                "to migrate first." % ", ".join(legacy)) if legacy else ""
        raise WeaponRigError(
            "Cannot work with presets: '%s' is missing.%s"
            % (BONE_WEAPON, hint))
    return armature.data.bones[BONE_WEAPON]


def capture_preset(armature):
    """Read the rig's weapon configuration into a plain dict (pure reads)."""
    bone = _require_current_rig(armature)
    layout = {}
    for prop in PRESET_PROPS:
        if prop in bone:
            layout[prop] = tuple(bone[prop])
        else:
            layout[prop] = DEFAULT_GRIP_OFFSETS[prop]
    blade = bone.get("blade_axis", "+Y")
    if blade not in BLADE_AXES:
        blade = "+Y"
    layout["blade_axis"] = blade
    layout["preview_mesh"] = armature.get(PREVIEW_PROP, "")
    return layout


def apply_preset(armature, layout, reparent_preview=True):
    """Write a captured layout into the rig (custom props only).

    Returns the list of props written. Never touches channels, keys, or
    rest pose -- the values take effect on the next snap/pivot/aim solve.
    """
    bone = _require_current_rig(armature)
    written = []
    for prop in PRESET_PROPS:
        if prop in layout:
            bone[prop] = tuple(layout[prop])[:3]
            written.append(prop)
    if layout.get("blade_axis") in BLADE_AXES:
        bone["blade_axis"] = layout["blade_axis"]
        written.append("blade_axis")

    preview_name = layout.get("preview_mesh", "")
    if preview_name:
        armature[PREVIEW_PROP] = preview_name
        if reparent_preview:
            from ..weapon.preview import set_preview_mesh
            obj = bpy.data.objects.get(preview_name)
            if obj is not None and obj.type == 'MESH':
                try:
                    set_preview_mesh(armature, obj)
                except WeaponRigError:
                    pass  # pointer stored; parenting left to the operator

    transforms.update_view_layer()
    return written
