"""Operators: attach/detach hands and attachment modes (plan §13, §32).

Every operator resolves the armature the same way as the rig operators,
delegates to the transform-preserving core in utils/constraints.py, and
turns WeaponRigError into a user-visible error (plan §54).
"""
import bpy

from ..constants import (
    GRIP_DISTANCE_WARN,
    MODES,
    SIDES,
    WeaponRigError,
)
from ..utils import constraints as con_util
from .rig import resolve_armature


def _frame(context):
    return context.scene.frame_current


class _WPN_AttachDetachBase:
    """Shared execute: run the op, report failures, summarize successes."""

    sides = SIDES  # overridden
    action = "attach"  # overridden

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        try:
            if self.action == "attach":
                results = [con_util.attach_preserve_transform(
                    armature, s, frame=_frame(context), key=True)
                    for s in self.sides]
            else:
                results = [con_util.detach_preserve_transform(
                    armature, s, frame=_frame(context), key=True)
                    for s in self.sides]
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        changed = [r["side"] for r in results if r.get("changed", True)]
        if changed:
            self.report({'INFO'}, "%s %s: pose preserved"
                        % (self.action.capitalize(),
                           "/".join(changed)))
        else:
            self.report({'INFO'}, "Already %sd -- no change"
                        % self.action)
        if self.action == "attach":
            segs = [(r["side"], r.get("segment")) for r in results
                    if r.get("segment")]
            if segs:
                self.report(
                    {'INFO'},
                    "Earlier holds kept on %s (re-attach with a new "
                    "offset)." % ", ".join("%s->%s" % item
                                          for item in segs))
        if self.action == "attach":
            kept = [r["side"] for r in results
                    if r.get("native_kept_warn")]
            if kept:
                self.report(
                    {'WARNING'},
                    "Kept the stored offset on %s: a native follow next "
                    "to the weapon follow makes a re-aim unverifiable "
                    "here. Playback and history untouched." % ", ".join(kept))
        if self.action == "attach":
            far = [(r["side"], r.get("grip_distance", 0.0))
                   for r in results
                   if r.get("grip_distance", 0.0) > GRIP_DISTANCE_WARN]
            if far:
                self.report(
                    {'WARNING'},
                    "Attached %s -- but the hand is far from the grip. "
                    "Attach glues in place, it never moves the hand onto "
                    "the weapon: move the hand closer (or Snap Weapon) "
                    "first." % ", ".join("%s (%.2f m)" % item
                                          for item in far))
        # Keep scene mode enum in sync for the panel display.
        _sync_mode_enum(armature, context)
        return {'FINISHED'}


def _sync_mode_enum(armature, context):
    """Update the scene mode dropdown to reflect actual constraint state."""
    states = {}
    for side in SIDES:
        states[side] = bool(con_util.is_hand_attached(armature, side))
    for mode, want in MODES.items():
        if want == states:
            context.scene.wpn_mode = mode
            return


class WPN_OT_attach(_WPN_AttachDetachBase, bpy.types.Operator):
    """Attach hand(s) to the weapon grip without any visible jump (plan §10)"""
    bl_idname = "wpn.attach"
    bl_label = "Attach"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.EnumProperty(
        name="Side",
        items=[('R', "Right", "Right hand only"),
               ('L', "Left", "Left hand only"),
               ('BOTH', "Both", "Both hands")],
        default='BOTH',
    )
    action = "attach"

    @classmethod
    def poll(cls, context):
        return True

    @property
    def sides(self):  # type: ignore[override]
        return SIDES if self.side == 'BOTH' else (self.side,)


class WPN_OT_detach(_WPN_AttachDetachBase, bpy.types.Operator):
    """Detach hand(s) from the weapon grip without any visible jump (plan §11)"""
    bl_idname = "wpn.detach"
    bl_label = "Detach"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.EnumProperty(
        name="Side",
        items=[('R', "Right", "Right hand only"),
               ('L', "Left", "Left hand only"),
               ('BOTH', "Both", "Both hands")],
        default='BOTH',
    )
    action = "detach"

    @classmethod
    def poll(cls, context):
        return True

    @property
    def sides(self):  # type: ignore[override]
        return SIDES if self.side == 'BOTH' else (self.side,)


class WPN_OT_set_mode(_WPN_AttachDetachBase, bpy.types.Operator):
    """Switch to a logical attachment mode (plan §13):
    FREE / RIGHT / LEFT / BOTH by toggling each side as needed."""
    bl_idname = "wpn.set_mode"
    bl_label = "Set Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('FREE', "Free", "No hands attached"),
               ('RIGHT', "Right", "Right hand only"),
               ('LEFT', "Left", "Left hand only"),
               ('BOTH', "Both", "Both hands")],
        default='BOTH',
    )
    action = "mode"

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            armature = resolve_armature(context)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        want = MODES[self.mode]
        try:
            for side in SIDES:
                attached = con_util.is_hand_attached(armature, side)
                if want[side] and not attached:
                    con_util.attach_preserve_transform(
                        armature, side, frame=_frame(context), key=True)
                elif not want[side] and attached:
                    con_util.detach_preserve_transform(
                        armature, side, frame=_frame(context), key=True)
        except WeaponRigError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.wpn_mode = self.mode
        self.report({'INFO'}, "Mode: %s" % self.mode.capitalize())
        return {'FINISHED'}


CLASSES = (
    WPN_OT_attach,
    WPN_OT_detach,
    WPN_OT_set_mode,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
