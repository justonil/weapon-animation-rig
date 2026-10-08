"""Operators: Aim Weapon, Point Blade At, Roll (plan §25, §26, §27).

Keyframe policy (plan §31): pure viewport ops -- no keys unless [Key] is
checked or Blender's Auto Key is on.
"""
import bpy

from ..constants import WeaponRigError
from ..weapon import aim
from .rig import resolve_armature


def _effective_key(scene, explicit):
    if explicit:
        return True
    return bool(scene.tool_settings.use_keyframe_insert_auto)


class _AimBase:
    @classmethod
    def poll(cls, context):
        return True

    def _armature_or_report(self, context):
        try:
            return resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return None


class WPN_OT_point_blade_at(_AimBase, bpy.types.Operator):
    """Orient the blade axis at the aim target, one shot (plan §26)"""
    bl_idname = "wpn.point_blade_at"
    bl_label = "Point Blade At"
    bl_options = {'REGISTER', 'UNDO'}

    roll: bpy.props.FloatProperty(
        name="Roll",
        description="Extra roll about the blade axis, degrees (plan §27)",
        default=0.0,
        unit='ROTATION',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the weapon bone (also implied by Auto Key)",
        default=False,
    )

    def execute(self, context):
        armature = self._armature_or_report(context)
        if armature is None:
            return {'CANCELLED'}
        try:
            result = aim.point_blade_at(
                armature, roll_degrees=self.roll,
                key=_effective_key(context.scene, self.key),
                frame=context.scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Blade points at aim (off %.4f deg)"
                    % result["angle_error_deg"])
        return {'FINISHED'}


class WPN_OT_aim_weapon(_AimBase, bpy.types.Operator):
    """Enable live aim (Damped Track) with absolute roll (plan §25, §27)"""
    bl_idname = "wpn.aim_weapon"
    bl_label = "Aim Weapon"
    bl_options = {'REGISTER', 'UNDO'}

    roll: bpy.props.FloatProperty(
        name="Roll",
        description="Roll about the blade axis, degrees (plan §27)",
        default=0.0,
        unit='ROTATION',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the weapon bone + aim influence (also implied "
                    "by Auto Key)",
        default=False,
    )

    def execute(self, context):
        armature = self._armature_or_report(context)
        if armature is None:
            return {'CANCELLED'}
        try:
            result = aim.aim_weapon(
                armature, roll_degrees=self.roll,
                key=_effective_key(context.scene, self.key),
                frame=context.scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Aim live toward weapon_aim (off %.4f deg, "
                    "roll %.1f deg)"
                    % (result["angle_error_deg"], result["roll_degrees"]))
        return {'FINISHED'}


class WPN_OT_stop_aim(_AimBase, bpy.types.Operator):
    """Disable live aim (influence 0), pose untouched"""
    bl_idname = "wpn.stop_aim"
    bl_label = "Stop Aim"
    bl_options = {'REGISTER', 'UNDO'}

    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe aim influence (also implied by Auto Key)",
        default=False,
    )

    def execute(self, context):
        armature = self._armature_or_report(context)
        if armature is None:
            return {'CANCELLED'}
        result = aim.stop_aim(
            armature, key=_effective_key(context.scene, self.key),
            frame=context.scene.frame_current)
        if not result["stopped"]:
            self.report({'INFO'}, "Aim was not active")
        else:
            self.report({'INFO'}, "Aim stopped")
        return {'FINISHED'}


class WPN_OT_set_roll(_AimBase, bpy.types.Operator):
    """Relative roll about the current blade axis (plan §27)"""
    bl_idname = "wpn.set_roll"
    bl_label = "Apply Roll"
    bl_options = {'REGISTER', 'UNDO'}

    roll: bpy.props.FloatProperty(
        name="Roll",
        description="Roll to apply about the blade axis, degrees",
        default=0.0,
        unit='ROTATION',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe the weapon bone (also implied by Auto Key)",
        default=False,
    )

    def execute(self, context):
        armature = self._armature_or_report(context)
        if armature is None:
            return {'CANCELLED'}
        try:
            aim.set_roll(armature, self.roll,
                         key=_effective_key(context.scene, self.key),
                         frame=context.scene.frame_current)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Rolled %.1f deg" % self.roll)
        return {'FINISHED'}


CLASSES = (
    WPN_OT_point_blade_at,
    WPN_OT_aim_weapon,
    WPN_OT_stop_aim,
    WPN_OT_set_roll,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
