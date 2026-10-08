"""Headless test suite: grip-point visualization + cursor placement.

Run:
    blender -b --factory-startup --python tests/run_milestone7_tests.py

The overlay draw callbacks need a real window and are NOT executed here
(they self-guard); what IS tested is everything a user depends on:
- collect_markers() returns the right points/labels and tracks the weapon
- grip_from_cursor lands points exactly on the cursor, touch nothing else
- the show toggle exists and draw callbacks survive headless no-UI calls
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import check, section, summary  # noqa: E402

war = common.register_addon()

from weapon_animation_rig.constants import TOL_TRANSLATION  # noqa: E402
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.ui import overlay as overlay_mod  # noqa: E402
from weapon_animation_rig.utils import constraints as con_util  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402


def test_collect_markers(arm):
    section("Marker collection tracks the weapon (pure, headless-safe)")
    markers = overlay_mod.collect_markers(arm)
    check("eight markers collected", len(markers) == 8, str(len(markers)))
    by_label = {label: (pos, color, size)
                for pos, label, color, size in markers}
    for label in ("Grip R", "Grip L", "Tip", "Guard L", "Guard R",
                  "Guard", "Pommel", "Center"):
        check("marker present: %s" % label, label in by_label)

    # The single Guard pivot marker sits exactly on the GUARD resolution.
    from weapon_animation_rig.weapon import pivot as pivot_mod
    guard_pivot = pivot_mod.compute_pivot_world(arm, 'GUARD')
    pos, _color, _size = by_label["Guard"]
    check("Guard marker == GUARD pivot resolution",
          (pos - guard_pivot).length <= TOL_TRANSLATION)

    # Stored points match the solver's own grip computation.
    gr = con_util.grip_world(arm, "R").translation
    pos, _color, _size = by_label["Grip R"]
    check("Grip R marker == grip solve position",
          (pos - gr).length <= TOL_TRANSLATION, "d=%.6f" % (pos - gr).length)

    # Move the weapon: markers must follow (they re-resolve every draw).
    before = {label: pos.copy() for pos, label, _, _
              in markers}
    wr = arm.pose.bones["weapon"]
    wr.matrix = (__import__("mathutils").Matrix.Translation(
        Vector((0.5, -0.3, 0.2)))) @ wr.matrix
    transforms.update_view_layer()
    after = {label: pos for pos, label, _, _
             in overlay_mod.collect_markers(arm)}
    moved = all((after[l] - before[l]).length > 1e-3 for l in before)
    check("markers follow weapon motion", moved)
    same_shape = True
    for label in before:
        if (after[label] - before[label]
                - (after["Grip R"] - before["Grip R"])).length > 1e-4:
            same_shape = False
    check("markers move rigidly (same delta)", same_shape)


def test_grip_from_cursor(arm):
    section("Grip-from-cursor placement")
    scene = bpy.context.scene
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    scene.wpn_armature = arm

    before_w = transforms.get_pose_bone_world_matrix(arm, "weapon").copy()
    # Verify each point landed exactly on the cursor, one by one.
    prop_of = {"GRIP_R": "grip_r", "GRIP_L": "grip_l",
               "GUARD_L": "guard_l", "GUARD_R": "guard_r",
               "POMMEL": "pommel", "CENTER": "center", "TIP": "tip"}
    for target in ("GRIP_R", "GRIP_L", "GUARD_L", "GUARD_R",
                   "POMMEL", "CENTER", "TIP"):
        scene.cursor.location = (1.0 + len(target), -2.0, 0.5 * len(target))
        res = bpy.ops.wpn.grip_from_cursor(target=target)
        if res != {'FINISHED'}:
            check("cursor op runs (%s)" % target, False, str(res))
            continue
        wmat = transforms.get_pose_bone_world_matrix(arm, "weapon")
        got = (wmat @ Vector(tuple(
            arm.data.bones["weapon"][prop_of[target]]))).copy()
        want = Vector(scene.cursor.location)
        check("point %s lands on cursor" % target,
              (got - want).length <= TOL_TRANSLATION,
              "d=%.6f" % (got - want).length)

    # Weapon itself never moved; no keys created by placement.
    after_w = transforms.get_pose_bone_world_matrix(arm, "weapon")
    t, _ = transforms.matrix_difference(before_w, after_w)
    check("weapon unmoved by placement", t <= TOL_TRANSLATION, "d=%.6f" % t)
    from weapon_animation_rig.animation import keyframes
    keyed = any(
        keyframes.find_fcurve(
            arm, 'pose.bones["weapon"].%s' % ch) is not None
        for ch in ("location", "rotation_quaternion", "scale"))
    check("placement creates no keys", not keyed)

    # Missing rig -> clean error, not a crash. NOTE: bpy.ops re-raises
    # an operator ERROR+CANCELLED as RuntimeError (Blender behavior) --
    # that IS the clean failure path.
    arm2_data = bpy.data.armatures.new("Bare2")
    arm2 = bpy.data.objects.new("Bare2", arm2_data)
    scene.collection.objects.link(arm2)
    scene.wpn_armature = arm2
    try:
        res = bpy.ops.wpn.grip_from_cursor(target='GRIP_R')
        check("cursor op errors cleanly without rig", False,
              "returned %s" % (res,))
    except RuntimeError as exc:
        check("cursor op errors cleanly without rig",
              "weapon is missing" in str(exc), str(exc))
    bpy.data.objects.remove(arm2, do_unlink=True)
    scene.wpn_armature = arm


def test_draw_guards():
    section("Draw callbacks survive headless no-UI calls")
    # In background mode there is no region/window: both callbacks must
    # return silently instead of raising.
    try:
        overlay_mod._draw_3d()
        overlay_mod._draw_2d()
        check("draw callbacks no-op headless", True)
    except Exception as exc:
        check("draw callbacks no-op headless", False,
              "%s: %s" % (type(exc).__name__, exc))
    check("show toggle defaults ON",
          bpy.context.scene.wpn_show_grips is True)


def main():
    print("=" * 70)
    print("MILESTONE 7 TEST SUITE: GRIP VISUALIZATION + CURSOR PICK")
    print("=" * 70)

    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.wpn_armature = arm

    test_collect_markers(arm)
    test_grip_from_cursor(arm)
    test_draw_guards()

    summary()


main()
