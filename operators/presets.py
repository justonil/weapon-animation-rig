"""Operators: save/apply weapon presets (plan §17).

A preset captures the weapon-specific layout as DATA (grip/tip local
vectors, blade axis, preview mesh) so swords, bows, spears, ... can share
the same framework without hard-coded coordinates (plan §11).
"""
import bpy

from ..constants import WeaponRigError
from ..weapon import presets
from .rig import resolve_armature


def _active_preset(scene):
    if not scene.wpn_presets:
        return None
    idx = max(0, min(scene.wpn_preset_index, len(scene.wpn_presets) - 1))
    return scene.wpn_presets[idx]


class WPN_OT_save_preset(bpy.types.Operator):
    """Save the current rig layout as a named weapon preset (plan §17)"""
    bl_idname = "wpn.save_preset"
    bl_label = "Save Preset"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(
        name="Preset Name",
        description="Name for the weapon preset",
        default="Weapon",
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
            layout = presets.capture_preset(armature)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        scene = context.scene
        existing = None
        for preset in scene.wpn_presets:
            if preset.name == self.name:
                existing = preset
                break
        target = existing or scene.wpn_presets.add()
        target.name = self.name
        for prop in presets.PRESET_PROPS:
            setattr(target, prop, layout[prop])
        tag = layout["blade_axis"]
        target.blade_axis = tag.replace('+', 'P').replace('-', 'N')
        preview_name = layout["preview_mesh"]
        target.preview_mesh = (bpy.data.objects.get(preview_name)
                               if preview_name else None)
        scene.wpn_preset_index = list(scene.wpn_presets).index(target)
        self.report({'INFO'}, "Saved preset '%s'" % target.name)
        return {'FINISHED'}


class WPN_OT_apply_preset(bpy.types.Operator):
    """Apply the selected weapon preset to the rig (plan §17)"""
    bl_idname = "wpn.apply_preset"
    bl_label = "Apply Preset"
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
        preset = _active_preset(context.scene)
        if preset is None:
            self.report({'ERROR'}, "No weapon presets saved yet.")
            return {'CANCELLED'}
        layout = {prop: tuple(getattr(preset, prop))
                  for prop in presets.PRESET_PROPS}
        layout["blade_axis"] = _decode_axis(preset.blade_axis)
        layout["preview_mesh"] = (preset.preview_mesh.name
                                  if preset.preview_mesh else "")
        try:
            written = presets.apply_preset(armature, layout,
                                           reparent_preview=True)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Applied preset '%s' (%s)"
                    % (preset.name, ", ".join(written)))
        return {'FINISHED'}


def _decode_axis(token):
    """Property-identifier form ('PY', 'NX', ...) back to config form."""
    table = {'PX': '+X', 'NX': '-X', 'PY': '+Y', 'NY': '-Y',
             'PZ': '+Z', 'NZ': '-Z'}
    return table.get(token, '+Y')


class WPN_OT_grip_from_cursor(bpy.types.Operator):
    """Place a grip/tip point at the 3D cursor (viewport configuration).

    Solves the weapon-local offset so the chosen reference point lands
    exactly on the cursor, then stores it. No channels, keys or animation
    touched -- this edits weapon CONFIGURATION (what presets store).
    """
    bl_idname = "wpn.grip_from_cursor"
    bl_label = "Grip From Cursor"
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.EnumProperty(
        name="Point",
        items=[('GRIP_R', "Grip R", ""),
               ('GRIP_L', "Grip L", ""),
               ('GUARD_L', "Guard L", ""),
               ('GUARD_R', "Guard R", ""),
               ('POMMEL', "Pommel", ""),
               ('CENTER', "Center", ""),
               ('TIP', "Tip", "")],
        default='GRIP_R',
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        from ..constants import (CENTER_PROP, GUARD_PROP_L, GUARD_PROP_R,
                                 POMMEL_PROP, TIP_PROP, GRIP_PROPS)
        from ..utils import constraints as con_util
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        prop = {'TIP': TIP_PROP, 'GUARD_L': GUARD_PROP_L,
                'GUARD_R': GUARD_PROP_R, 'POMMEL': POMMEL_PROP,
                'CENTER': CENTER_PROP}.get(
                    self.target,
                    GRIP_PROPS['R' if self.target == 'GRIP_R' else 'L'])
        try:
            con_util.set_grip_from_world(
                armature, prop, context.scene.cursor.location)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "%s placed at 3D cursor"
                    % self.target.replace('_', ' '))
        return {'FINISHED'}


CLASSES = (
    WPN_OT_save_preset,
    WPN_OT_apply_preset,
    WPN_OT_grip_from_cursor,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
