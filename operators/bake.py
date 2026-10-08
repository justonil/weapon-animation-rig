"""Operator: Bake Weapon Animation (plan §44, §45) -- Milestone 5.

Modes (plan §44): Bake New Action (default, never overwrites) or Bake
Current Action (explicit overwrite of the source action's weapon channels).
Range defaults to the scene frame range.
"""
import bpy

from ..animation import bake as bake_mod
from ..constants import WeaponRigError
from .rig import resolve_armature


class WPN_OT_bake(bpy.types.Operator):
    """Convert the control-rig result into plain animation keys (plan §44)"""
    bl_idname = "wpn.bake"
    bl_label = "Bake Weapon Animation"
    bl_options = {'REGISTER', 'UNDO'}

    frame_start: bpy.props.IntProperty(
        name="Start Frame",
        description="First frame to bake (-1 = scene frame start)",
        default=-1,
    )
    frame_end: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to bake (-1 = scene frame end)",
        default=-1,
    )
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('NEW_ACTION', "Bake New Action",
                "Create '<action>_Baked', source action untouched"),
               ('CURRENT_ACTION', "Bake Current Action",
                "Write baked keys into the current action")],
        default='NEW_ACTION',
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
        start = self.frame_start if self.frame_start >= 0 \
            else scene.frame_start
        end = self.frame_end if self.frame_end >= 0 else scene.frame_end
        try:
            result = bake_mod.bake_weapon_animation(
                armature, start, end, mode=self.mode)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        t, r = result["max_error"]
        self.report({'INFO'}, "Baked %d frames -> '%s' (max drift "
                    "%.6f / %.4f deg)" % (
                        result["frames"], result["action"], t, r))
        return {'FINISHED'}


CLASSES = (WPN_OT_bake,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
