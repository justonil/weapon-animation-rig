"""Scene-level properties for the add-on UI (plan §32).

Keep these minimal for Milestone 1: which armature the panel operates on,
the last validation report (for display), and the mode selector.
"""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)

from .constants import BLADE_AXES


class WPN_Preset(bpy.types.PropertyGroup):
    """One named per-weapon configuration (plan §17).

    Stores weapon-bone LOCAL grip/tip reference vectors (no edit mode
    needed to save or apply), the blade axis (plan §47), and the preview
    mesh reference (plan §16).
    """
    blade_axis: EnumProperty(
        name="Blade Axis",
        description="Bone-local axis pointing toward the tip (plan §47)",
        items=[(tag.replace('+', 'P').replace('-', 'N'), tag, "")
               for tag in sorted(BLADE_AXES)],
        default='PY',
    )
    grip_r: FloatVectorProperty(
        name="Grip R",
        description="Right grip point, weapon-bone local",
        size=3, default=(0.0, 0.0, 0.0),
    )
    grip_l: FloatVectorProperty(
        name="Grip L",
        description="Left grip point, weapon-bone local",
        size=3, default=(0.0, 0.15, 0.0),
    )
    guard_l: FloatVectorProperty(
        name="Guard L",
        description="Left quillon end, weapon-bone local",
        size=3, default=(-0.07, 0.19, 0.0),
    )
    guard_r: FloatVectorProperty(
        name="Guard R",
        description="Right quillon end, weapon-bone local",
        size=3, default=(0.07, 0.19, 0.0),
    )
    pommel: FloatVectorProperty(
        name="Pommel",
        description="Pommel point, weapon-bone local",
        size=3, default=(0.0, -0.06, 0.0),
    )
    center: FloatVectorProperty(
        name="Center",
        description="Weapon center, weapon-bone local",
        size=3, default=(0.0, 0.52, 0.0),
    )
    tip: FloatVectorProperty(
        name="Tip",
        description="Blade-tip point, weapon-bone local",
        size=3, default=(0.0, 1.10, 0.0),
    )
    preview_mesh: PointerProperty(
        name="Preview Mesh",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj.type == 'MESH',
    )


def _poll_armature(self, obj):
    if obj is None:
        return True  # allow clearing
    return obj.type == 'ARMATURE'


def _update_armature(self, context):
    pass  # panel re-reads each draw; nothing to cache


def _pivot_items():
    """Single source of truth lives in weapon/pivot.py (avoids drift
    between the scene enum, the operator enum and the panel)."""
    from .weapon.pivot import PIVOT_ITEMS
    return list(PIVOT_ITEMS)


def register():
    bpy.utils.register_class(WPN_Preset)
    bpy.types.Scene.wpn_armature = PointerProperty(
        name="Character",
        description="Auto-Rig Pro character armature the weapon rig is "
                    "attached to (Auto Detect fills this)",
        type=bpy.types.Object,
        poll=_poll_armature,
        update=_update_armature,
    )
    bpy.types.Scene.wpn_report = StringProperty(
        name="Last Report",
        description="Last validation/operation report",
        default="",
    )
    bpy.types.Scene.wpn_mode = EnumProperty(
        name="Mode",
        description="Hand attachment mode (plan §13)",
        items=[
            ('FREE', "Free", "No hands attached to the weapon"),
            ('RIGHT', "Right", "Right hand attached only"),
            ('LEFT', "Left", "Left hand attached only"),
            ('BOTH', "Both", "Both hands attached"),
        ],
        default='BOTH',
    )
    bpy.types.Scene.wpn_pivot = EnumProperty(
        name="Pivot",
        description="Weapon pivot preset (plan §21)",
        items=_pivot_items(),
        default='CENTER',
    )
    bpy.types.Scene.wpn_pivot_custom = FloatVectorProperty(
        name="Custom Pivot",
        description="Stored pivot position, world space (plan §21)",
        subtype='XYZ',
        default=(0.0, 0.0, 0.0),
    )
    bpy.types.Scene.wpn_roll = FloatProperty(
        name="Roll",
        description="Weapon roll about the blade axis, degrees (plan §27)",
        default=0.0,
        unit='ROTATION',
    )
    bpy.types.Scene.wpn_drag = EnumProperty(
        name="Drag Point",
        description="Weapon point aimed by rotate interactions",
        items=[
            ('TIP', "Tip", "Blade tip"),
            ('GUARD_L', "Guard L", "Left quillon end"),
            ('GUARD_R', "Guard R", "Right quillon end"),
            ('GRIP_R', "Grip R", "Right hand grip point"),
            ('GRIP_L', "Grip L", "Left hand grip point"),
            ('POMMEL', "Pommel", "Pommel point"),
            ('CENTER', "Center", "Weapon center"),
        ],
        default='TIP',
    )
    bpy.types.Scene.wpn_rot_handle = StringProperty(
        name="Rotate Handle",
        description="Name of the Empty used as the live rotate target "
                    "(empty = no handle)",
        default="",
    )
    bpy.types.Scene.wpn_presets = CollectionProperty(type=WPN_Preset)
    bpy.types.Scene.wpn_preset_index = IntProperty(
        name="Weapon Preset",
        description="Active per-weapon configuration (plan §17)",
        default=0,
    )
    bpy.types.Scene.wpn_preset_name = StringProperty(
        name="Preset Name",
        description="Name for the next saved weapon preset",
        default="Greatsword",
    )
    bpy.types.Scene.wpn_show_grips = BoolProperty(
        name="Show Grip Points",
        description="Viewport markers for grip/tip/pivot points "
                    "(display only, never exported)",
        default=True,
    )
    bpy.types.Scene.wpn_show_direct_snaps = BoolProperty(
        name="Direct Snaps",
        description="Show one-shot direct snaps (weapon to hand and "
                    "hand to weapon). Only needed for the initial "
                    "placement; daily work uses the Home slots",
        default=False,
    )


def unregister():
    del bpy.types.Scene.wpn_armature
    del bpy.types.Scene.wpn_report
    del bpy.types.Scene.wpn_mode
    del bpy.types.Scene.wpn_pivot
    del bpy.types.Scene.wpn_pivot_custom
    del bpy.types.Scene.wpn_roll
    del bpy.types.Scene.wpn_drag
    del bpy.types.Scene.wpn_rot_handle
    del bpy.types.Scene.wpn_presets
    del bpy.types.Scene.wpn_preset_index
    del bpy.types.Scene.wpn_preset_name
    del bpy.types.Scene.wpn_show_grips
    del bpy.types.Scene.wpn_show_direct_snaps
    bpy.utils.unregister_class(WPN_Preset)
