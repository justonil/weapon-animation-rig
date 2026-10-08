"""Operator: Snap Weapon -> Right / Left / Both hands (plan §18-20, §32).

Keyframe policy (plan §31): the [Key] checkbox defaults to OFF and Blender's
Auto Key state is honored -- if the scene's Auto Keying is enabled the snap
keys the weapon bone as well. No keys are created otherwise.
"""
import bpy

from ..constants import WeaponRigError
from ..weapon import snap
from .rig import resolve_armature


def _effective_key(scene, explicit):
    if explicit:
        return True
    # Respect Blender's current Auto Keying state (plan §31).
    return bool(scene.tool_settings.use_keyframe_insert_auto)


class WPN_OT_snap_to_hand(bpy.types.Operator):
    """Snap the weapon so a grip lands on a hand controller (plan §18/§19)"""
    bl_idname = "wpn.snap_to_hand"
    bl_label = "Snap Weapon to Hand"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.EnumProperty(
        name="Side",
        items=[('R', "Right", "Align the right grip point to the right hand"),
               ('L', "Left", "Align the left grip point to the left hand")],
        default='R',
    )
    align_orientation: bpy.props.BoolProperty(
        name="Align Orientation",
        description="Also match the grip's orientation to the hand "
                    "(default: position only, grip orientation preserved)",
        default=False,
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the weapon bone (also implied by Blender's "
                    "Auto Key, plan §31)",
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
        try:
            result = snap.snap_weapon_to_hand(
                armature, self.side,
                align_orientation=self.align_orientation,
                key=_effective_key(context.scene, self.key),
                frame=context.scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if result["warning"]:
            self.report({'WARNING'}, result["warning"])
        msg = "Snapped weapon -> %s hand (grip error %.6f)" % (
            "right" if self.side == 'R' else "left", result["grip_error_r"])
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class WPN_OT_snap_to_both(bpy.types.Operator):
    """Solve the weapon transform from both hand positions (plan §20)"""
    bl_idname = "wpn.snap_to_both"
    bl_label = "Snap Weapon to Both Hands"
    bl_options = {'REGISTER', 'UNDO'}

    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the weapon bone (also implied by Blender's "
                    "Auto Key, plan §31)",
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
        try:
            result = snap.snap_weapon_to_both(
                armature,
                key=_effective_key(context.scene, self.key),
                frame=context.scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if result["warning"]:
            self.report({'WARNING'}, result["warning"])
        msg = "Snapped weapon -> both hands (R err %.6f, L err %.6f)" % (
            result["grip_error_r"], result["grip_error_l"])
        self.report({'INFO'}, msg)
        return {'FINISHED'}


CLASSES = (
    WPN_OT_snap_to_hand,
    WPN_OT_snap_to_both,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
