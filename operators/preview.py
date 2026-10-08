"""Operators: assign / clear the preview weapon mesh (plan §16)."""
import bpy

from ..constants import WeaponRigError
from ..weapon import preview
from .rig import resolve_armature


class WPN_OT_set_preview_mesh(bpy.types.Operator):
    """Preview a mesh on the weapon bone (active mesh object, plan §16)"""
    bl_idname = "wpn.set_preview_mesh"
    bl_label = "Set Preview Mesh"
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
        obj = context.view_layer.objects.active
        if obj is not None and obj.type != 'MESH':
            # Fall back to the first selected mesh.
            meshes = [o for o in context.selected_objects
                      if o.type == 'MESH' and o is not armature]
            obj = meshes[0] if meshes else None
        try:
            preview.set_preview_mesh(armature, obj)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Preview mesh: %s" % obj.name)
        return {'FINISHED'}


class WPN_OT_clear_preview_mesh(bpy.types.Operator):
    """Remove the preview mesh assignment (keeps its transform)"""
    bl_idname = "wpn.clear_preview_mesh"
    bl_label = "Clear Preview Mesh"
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
            obj = preview.clear_preview_mesh(armature)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Preview cleared (%s)" % obj.name)
        return {'FINISHED'}


CLASSES = (
    WPN_OT_set_preview_mesh,
    WPN_OT_clear_preview_mesh,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
