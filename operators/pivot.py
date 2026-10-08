"""Operators: Set Pivot presets (plan §21, §22, §24) -- Milestone 3.

Keyframe policy (plan §31): pivot is a pure viewport operation -- NO keys
unless [Key] is checked or Blender's Auto Key is on (plan §22 step 8:
"optionally keyframe").
"""
import bpy

from ..constants import WeaponRigError
from ..weapon import focus as focus_mod
from ..weapon import pivot
from .rig import resolve_armature


def _effective_key(scene, explicit):
    if explicit:
        return True
    return bool(scene.tool_settings.use_keyframe_insert_auto)


class WPN_OT_select_pivot(bpy.types.Operator):
    """Select a pivot preset AND focus the viewport on it (plan §21).

    Besides storing scene.wpn_pivot for Set Pivot, the operator moves the
    3D cursor onto the point and switches transform pivot to 3D Cursor, so
    the hand can be rotated straight around it (R key). It also activates
    a custom "WPN_Weapon" orientation built from the weapon bone (axes of
    the weapon, not the hand), falling back to Normal when the UI context
    does not allow building it. Viewport state only -- never touches
    animation or the rig."""
    bl_idname = "wpn.select_pivot"
    bl_label = "Select Pivot"

    pivot: bpy.props.EnumProperty(
        name="Pivot",
        items=pivot.PIVOT_ITEMS,
        default='CENTER',
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.wpn_pivot = self.pivot
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            # No rig: preset is still stored, viewport focus is skipped.
            self.report({'WARNING'},
                        "Pivot preset set, focus skipped: %s" % exc)
            return {'FINISHED'}
        scene = context.scene
        custom = getattr(scene, "wpn_pivot_custom", (0.0, 0.0, 0.0))
        try:
            result = focus_mod.focus_on_point(armature, self.pivot,
                                              custom=custom)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            focus_mod.ensure_weapon_orientation(context, armature)
            oriented = "Weapon orientation"
        except WeaponRigError:
            oriented = "Normal orientation"
        p = result["point"]
        self.report({'INFO'}, "Focus %s at (%.3f, %.3f, %.3f) -- %s" % (
            self.pivot, p.x, p.y, p.z, oriented))
        return {'FINISHED'}


class WPN_OT_create_weapon_orientation(bpy.types.Operator):
    """Create (or refresh) the Weapon transform orientation.

    Builds a custom "WPN_Weapon" orientation from the weapon bone and
    activates it, so hand rotations use the weapon's axes whatever is
    selected. Loud errors (nothing silent): the exact failure reason is
    reported and the operator cancels."""
    bl_idname = "wpn.create_weapon_orientation"
    bl_label = "Create Orientation from Weapon"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            name = focus_mod.ensure_weapon_orientation(context, armature)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'},
                    "Orientation '%s' created from the weapon bone." % name)
        return {'FINISHED'}



class WPN_OT_set_pivot(bpy.types.Operator):
    """Move the weapon bone's origin onto a pivot preset without any jump
    (plan §21/§22)"""
    bl_idname = "wpn.set_pivot"
    bl_label = "Set Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    pivot: bpy.props.EnumProperty(
        name="Pivot",
        description="Pivot point preset",
        items=pivot.PIVOT_ITEMS,
        default='CENTER',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the changed channels (also implied by "
                    "Blender's Auto Key, plan §31)",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        scene = context.scene
        custom = getattr(scene, "wpn_pivot_custom", (0.0, 0.0, 0.0))
        try:
            result = pivot.set_pivot(
                armature, self.pivot, custom=custom,
                key=_effective_key(scene, self.key),
                frame=scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        p = result["pivot_world"]
        self.report({'INFO'}, "Pivot -> %s at (%.3f, %.3f, %.3f)"
                    % (self.pivot, p.x, p.y, p.z))
        return {'FINISHED'}


CLASSES = (
    WPN_OT_select_pivot,
    WPN_OT_set_pivot,
    WPN_OT_create_weapon_orientation,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
