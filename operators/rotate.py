"""Operators: rotate weapon about a pivot (user-requested feature).

- ``wpn.rotate_to_cursor``: one-shot solve toward the 3D cursor.
- ``wpn.rotate_drag``: modal mouse interaction -- grab a weapon point and
  drag it around the fixed pivot in real time (LMB confirm, RMB/Esc cancel
  with restore). All solving goes through weapon/rotate.py (headless
  tested); the modal layer only converts mouse motion to target points.
"""
import bpy
from mathutils import Vector

from ..constants import WeaponRigError
from ..weapon import pivot as pivot_presets
from ..weapon import rotate as rotate_mod
from .rig import resolve_armature


def _effective_key(scene, explicit):
    if explicit:
        return True
    return bool(scene.tool_settings.use_keyframe_insert_auto)


class WPN_OT_rotate_to_cursor(bpy.types.Operator):
    """Rotate the weapon about the pivot toward the 3D cursor"""
    bl_idname = "wpn.rotate_to_cursor"
    bl_label = "Rotate to Cursor"
    bl_options = {'REGISTER', 'UNDO'}

    pivot: bpy.props.EnumProperty(
        name="Pivot",
        description="Fixed pivot point (stays locked)",
        items=pivot_presets.PIVOT_ITEMS,
        default='POMMEL',
    )
    drag: bpy.props.EnumProperty(
        name="Drag",
        description="Weapon point being aimed",
        items=[('TIP', "Tip", ""),
               ('GUARD_L', "Guard L", ""),
               ('GUARD_R', "Guard R", ""),
               ('GRIP_R', "Grip R", ""),
               ('GRIP_L', "Grip L", ""),
               ('POMMEL', "Pommel", ""),
               ('CENTER', "Center", "")],
        default='TIP',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe weapon channels (also implied by Auto Key)",
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
            scene = context.scene
            result = rotate_mod.rotate_toward(
                armature, self.pivot, self.drag,
                Vector(scene.cursor.location),
                key=_effective_key(scene, self.key),
                frame=scene.frame_current,
                custom=getattr(scene, "wpn_pivot_custom",
                               (0.0, 0.0, 0.0)))
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Rotated about %s (off %.4f deg)"
                    % (self.pivot, result["angle_error_deg"]))
        return {'FINISHED'}


class WPN_OT_rotate_drag(bpy.types.Operator):
    """Drag a weapon point around a fixed pivot with the mouse.

    LMB confirms, RMB/Esc cancels and restores the pre-drag pose.
    """
    bl_idname = "wpn.rotate_drag"
    bl_label = "Drag Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    pivot: bpy.props.EnumProperty(
        name="Pivot",
        description="Fixed pivot point (stays locked)",
        items=pivot_presets.PIVOT_ITEMS,
        default='POMMEL',
    )
    drag: bpy.props.EnumProperty(
        name="Drag",
        description="Weapon point being dragged",
        items=[('TIP', "Tip", ""),
               ('GUARD_L', "Guard L", ""),
               ('GUARD_R', "Guard R", ""),
               ('GRIP_R', "Grip R", ""),
               ('GRIP_L', "Grip L", ""),
               ('POMMEL', "Pommel", ""),
               ('CENTER', "Center", "")],
        default='TIP',
    )
    key: bpy.props.BoolProperty(
        name="Key",
        description="Keyframe on confirm (also implied by Auto Key)",
        default=False,
    )

    _armature = None
    _pivot_world = None
    _plane_normal = None
    _weapon_before = None
    _old_channels = None
    _custom = (0.0, 0.0, 0.0)

    @classmethod
    def poll(cls, context):
        # A real 3D view is required (region/rv3d for ray unprojection);
        # headless/background contexts are refused cleanly instead of
        # crashing mid-gesture.
        area = context.area
        return (area is not None and area.type == 'VIEW_3D'
                and context.region is not None
                and context.region_data is not None)

    def invoke(self, context, event):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        from ..utils import transforms
        from ..weapon import pivot as pivot_mod
        self._custom = tuple(getattr(context.scene, "wpn_pivot_custom",
                                      (0.0, 0.0, 0.0)))
        try:
            pivot_world = pivot_mod.compute_pivot_world(
                armature, self.pivot, self._custom)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        from ..animation import keyframes
        from ..utils import constraints as con_util
        weapon = con_util.get_weapon_bone(armature)

        self._armature = armature
        self._pivot_world = pivot_world.copy()
        rv3d = context.region_data
        self._plane_normal = (rv3d.view_rotation
                              @ Vector((0.0, 0.0, -1.0))).normalized()
        self._weapon_before = (
            transforms.get_pose_bone_world_matrix(armature, weapon).copy())
        self._old_channels = keyframes.capture_channels(armature, weapon)
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(
            "Drag Rotate: move mouse to rotate about %s -- "
            "LMB confirm, RMB/Esc cancel" % self.pivot)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish_header(context, None)
            self._restore()
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._finish_header(context, "Rotated about %s" % self.pivot)
            self._finish_keys(context)
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            self._solve_at_mouse(context, event)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # -- internals (thin glue over the tested core) ---------------------

    def _finish_header(self, context, text):
        try:
            context.area.header_text_set(None)
            if text is not None:
                self.report({'INFO'}, text)
        except (AttributeError, ReferenceError):
            pass

    def _restore(self):
        try:
            from ..utils import transforms
            from ..utils import constraints as con_util
            arm = self._armature
            weapon = con_util.get_weapon_bone(arm)
            transforms.set_pose_bone_arm_matrix(
                arm, weapon, arm.matrix_world.inverted()
                @ self._weapon_before)
            transforms.update_view_layer()
        except (AttributeError, ReferenceError, WeaponRigError):
            pass

    def _finish_keys(self, context):
        from ..animation import keyframes
        from ..utils import constraints as con_util
        if not _effective_key(context.scene, self.key):
            return
        arm = self._armature
        try:
            weapon = con_util.get_weapon_bone(arm)
            keyframes.key_changed_channels(
                arm, weapon, context.scene.frame_current,
                self._old_channels)
        except (AttributeError, ReferenceError, WeaponRigError) as exc:
            self.report({'WARNING'}, "Keyframing failed: %s" % exc)

    def _solve_at_mouse(self, context, event):
        from bpy_extras.view3d_utils import (
            region_2d_to_origin_3d,
            region_2d_to_vector_3d,
        )
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            origin = region_2d_to_origin_3d(region, rv3d, coord)
            direction = region_2d_to_vector_3d(region, rv3d, coord)
        except (AttributeError, ReferenceError):
            return
        target = rotate_mod.ray_plane_target(
            origin, direction, self._pivot_world, self._plane_normal)
        if target is None:
            return  # ray parallel to the drag plane: keep last good pose
        try:
            rotate_mod.rotate_toward(
                self._armature, self.pivot, self.drag, target,
                key=False, custom=self._custom)
        except (WeaponRigError, AttributeError, ReferenceError):
            pass  # transient degenerate geometry mid-drag: hold pose
        try:
            context.area.tag_redraw()
        except (AttributeError, ReferenceError):
            pass


CLASSES = (
    WPN_OT_rotate_to_cursor,
    WPN_OT_rotate_drag,
)


class WPN_OT_handle_create(bpy.types.Operator):
    """Create (or re-place) the Empty rotate handle on the drag point.

    Move the Empty with Blender's own tools (G/R/gizmo/snap/numeric) --
    the weapon rotates live to aim its drag point at it, around the
    currently selected pivot.
    """
    bl_idname = "wpn.handle_create"
    bl_label = "Create Rotate Handle"
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
        scene = context.scene
        try:
            obj = rotate_mod.create_handle(
                armature, scene.wpn_pivot, scene.wpn_drag,
                custom=getattr(scene, "wpn_pivot_custom",
                               (0.0, 0.0, 0.0)))
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'},
                    "Handle '%s' ready -- move it to rotate about %s"
                    % (obj.name, scene.wpn_pivot))
        return {'FINISHED'}


class WPN_OT_handle_remove(bpy.types.Operator):
    """Remove the Empty rotate handle (weapon keeps its pose)"""
    bl_idname = "wpn.handle_remove"
    bl_label = "Remove Rotate Handle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        rotate_mod.remove_handle(context.scene)
        return {'FINISHED'}


CLASSES = (
    WPN_OT_rotate_to_cursor,
    WPN_OT_rotate_drag,
    WPN_OT_handle_create,
    WPN_OT_handle_remove,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    # Live follow is installed for the whole addon lifetime; it no-ops
    # until a handle exists (cheap matrix compare).
    rotate_mod.start_handler()


def unregister():
    rotate_mod.stop_handler()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
