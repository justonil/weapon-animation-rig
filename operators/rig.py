"""Operators: rig detection, creation, validation (plan §32, §35, §36)."""
import bpy

from ..constants import WeaponRigError
from ..constants import ALL_WEAPON_BONES
from ..rig import create as rig_create
from ..rig import validate as rig_validate
from ..utils import armature as arm_util


def resolve_armature(context):
    """Armature the panel works on: scene selection first, then auto-detect.

    The scene property wins when set (that's what Auto Detect fills and the
    panel displays); otherwise fall back to detection from context so the
    operators are usable without ever pressing Auto Detect.
    """
    obj = context.scene.wpn_armature
    if obj is not None and obj.type == 'ARMATURE':
        return obj
    return arm_util.find_generated_rig(context)


class WPN_OT_auto_detect(bpy.types.Operator):
    """Find the generated Auto-Rig Pro armature (plan §32 'Auto Detect')"""
    bl_idname = "wpn.auto_detect"
    bl_label = "Auto Detect"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            armature = arm_util.find_generated_rig(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_armature = armature
        self.report({'INFO'}, "Found ARP armature: %s" % armature.name)
        return {'FINISHED'}


class WPN_OT_create_rig(bpy.types.Operator):
    """Create the weapon bone hierarchy on the ARP rig (plan §35)"""
    bl_idname = "wpn.create_rig"
    bl_label = "Create Weapon Rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            ok, lines = rig_create.create_weapon_rig(context, armature)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_armature = armature
        context.scene.wpn_report = "\n".join(lines)
        # Echo the full checklist to the Info log (plan §36: human-readable).
        for line in lines:
            print(line)
        self.report({'INFO'}, "Weapon rig created on %s (%s)"
                    % (armature.name, "valid" if ok else "INVALID -- "
                       "see report"))
        return {'FINISHED'}


class WPN_OT_validate_rig(bpy.types.Operator):
    """Validate the weapon rig (plan §36 'Validate Rig')"""
    bl_idname = "wpn.validate_rig"
    bl_label = "Validate Rig"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        ok, lines = rig_validate.validate_weapon_rig(armature)
        context.scene.wpn_report = "\n".join(lines)
        for line in lines:
            print(line)
        if ok:
            self.report({'INFO'}, "Weapon rig: VALID")
            return {'FINISHED'}
        self.report({'WARNING'},
                    "Weapon rig: INVALID -- see report (Sidebar > Weapon)")
        return {'FINISHED'}


class WPN_OT_toggle_rig_visibility(bpy.types.Operator):
    """Show / hide all weapon bones in the viewport (plan §34)"""
    bl_idname = "wpn.toggle_rig_visibility"
    bl_label = "Show Weapon Rig"
    bl_options = {'REGISTER', 'UNDO'}

    show: bpy.props.BoolProperty(
        name="Show",
        description="Show the weapon bones (off hides them)",
        default=True,
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
        shown = []
        for name in ALL_WEAPON_BONES:
            bone = armature.data.bones.get(name)
            if bone is not None:
                bone.hide = not self.show
                shown.append(name)
        if not shown:
            self.report({'WARNING'}, "No weapon bones to toggle")
            return {'CANCELLED'}
        self.report({'INFO'}, "Weapon rig %s"
                    % ("shown" if self.show else "hidden"))
        return {'FINISHED'}


class WPN_OT_reparent_weapon(bpy.types.Operator):
    """Move weapon (+aim) under another bone, keeping the world pose."""
    bl_idname = "wpn.reparent_weapon"
    bl_label = "Reparent Weapon (Keep Transform)"
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.EnumProperty(
        name="Parent Under",
        description="New parent: active pose bone, resolved root, "
                    "or armature level (no bone parent).",
        items=[("AUTO", "Auto (active bone, else root)", ""),
               ("ACTIVE", "Active Pose Bone", ""),
               ("ROOT", "Character Root", ""),
               ("ARMATURE", "Armature Level (no parent)", "")],
        default="AUTO",
    )

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        want = self.target
        if want in ("AUTO", "ACTIVE"):
            active = context.active_pose_bone
            if active is not None:
                target = active.name
            elif want == "ACTIVE":
                self.report({'ERROR'}, "No active pose bone selected.")
                return {'CANCELLED'}
            else:
                target, _status = arm_util.resolve_character_root(
                    armature)
        elif want == "ROOT":
            target, _status = arm_util.resolve_character_root(armature)
        else:
            target = None
        if target is None and want != "ARMATURE":
            self.report(
                {'ERROR'},
                "No target: select a bone first (active bone), or "
                "create a root bone. Root-like: %s."
                % ", ".join(arm_util.root_like_candidates(armature)))
            return {'CANCELLED'}
        try:
            from ..rig import reparent as rig_reparent
            lines, moved = rig_reparent.reparent_weapon_bones(
                armature, target)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_report = "\n".join(lines)
        for line in lines:
            print(line)
        if not moved:
            self.report({'INFO'}, "; ".join(lines))
        else:
            self.report({'INFO'}, "Weapon rig reparented under '%s' "
                        "(pose + keys preserved)"
                        % (target if target is not None else "(armature)"))
        return {'FINISHED'}


class WPN_OT_create_hand_socket(bpy.types.Operator):
    """Seat a static engine socket bone under a hand (mesh origin)."""
    bl_idname = "wpn.create_hand_socket"
    bl_label = "Create Hand Socket"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.EnumProperty(
        name="Side",
        items=[("R", "Right", ""), ("L", "Left", "")],
        default="R",
    )

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            from ..rig import socket as rig_socket
            lines, name = rig_socket.create_hand_socket(
                armature, self.side)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_report = "\n".join(lines)
        for line in lines:
            print(line)
            if line.startswith("WARNING"):
                self.report({'WARNING'}, line)
        self.report({'INFO'}, "Socket '%s' ready (bind at current "
                    "frame)" % name)
        return {'FINISHED'}


class WPN_OT_bake_socket(bpy.types.Operator):
    """Bake authored weapon motion into the hand socket's keys."""
    bl_idname = "wpn.bake_socket"
    bl_label = "Bake Socket Follow"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.EnumProperty(
        name="Side",
        items=[("R", "Right", ""), ("L", "Left", "")],
        default="R",
    )

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            from ..rig import socket as rig_socket
            lines, _gap = rig_socket.bake_socket_follow(
                armature, self.side)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_report = "\n".join(lines)
        for line in lines:
            print(line)
        self.report({'INFO'}, "; ".join(lines))
        return {'FINISHED'}


CLASSES = (
    WPN_OT_auto_detect,
    WPN_OT_create_rig,
    WPN_OT_validate_rig,
    WPN_OT_toggle_rig_visibility,
    WPN_OT_reparent_weapon,
    WPN_OT_create_hand_socket,
    WPN_OT_bake_socket,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
