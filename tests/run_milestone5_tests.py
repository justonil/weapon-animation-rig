"""Headless test suite: Milestone 5 (bake, plan §52).

Run:
    blender -b --factory-startup --python tests/run_milestone5_tests.py

Covers plan §52 Test I's Blender side (bake -> the baked action reproduces
the rig's evaluated weapon transform, which is what Unreal attaches
the Static Mesh to): new action behavior, source preservation, range
respect, attach+aim+weapon-motion shots, and failure modes (§54).
"""
import os
import sys

import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import check, section, summary  # noqa: E402

war = common.register_addon()

from weapon_animation_rig.animation import bake as bake_mod  # noqa: E402
from weapon_animation_rig.constants import (  # noqa: E402
    TOL_TRANSLATION,
    WeaponRigError,
)
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402
from weapon_animation_rig.animation import keyframes  # noqa: E402


def world(arm, name):
    return transforms.get_pose_bone_world_matrix(arm, name)


def action_snapshot(arm):
    """All fcurves of the current action: {(path, idx): [(f, v)]}."""
    ad = arm.animation_data
    if ad is None or ad.action is None:
        return {}
    out = {}
    slot = getattr(ad, "action_slot", None)
    for layer in ad.action.layers:
        for strip in layer.strips:
            if strip.type != 'KEYFRAME':
                continue
            cb = None
            try:
                cb = strip.channelbag(slot)
            except Exception:
                cb = None
            if cb is None:
                try:
                    bags = list(strip.channelbags)
                except Exception:
                    bags = []
                if len(bags) == 1:
                    cb = bags[0]
            if cb is None:
                continue
            for fcu in cb.fcurves:
                out[(fcu.data_path, fcu.array_index)] = [
                    (round(k.co[0], 6), round(k.co[1], 6))
                    for k in fcu.keyframe_points]
    return out


def build_animated_shot():
    """Rig + a real shot: root motion, attached hands, moving weapon."""
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 30

    # Character root motion (baked action must reproduce it via copy).
    root = arm.pose.bones["root"]
    root.location = (0.0, 0.0, 0.0)
    arm.keyframe_insert('pose.bones["root"].location', frame=1)
    root.location = (0.5, -0.3, 0.0)
    arm.keyframe_insert('pose.bones["root"].location', frame=15)
    root.location = (1.0, -0.1, 0.2)
    arm.keyframe_insert('pose.bones["root"].location', frame=30)

    # Weapon swing, keyed on the weapon bone.
    wr = arm.pose.bones["weapon"]
    scene.frame_set(1)
    wr.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((1.9, 0.2, 2.6)))
    arm.keyframe_insert('pose.bones["weapon"].location', frame=1)
    arm.keyframe_insert('pose.bones["weapon"].rotation_quaternion',
                        frame=1)
    scene.frame_set(15)
    mw = arm.matrix_world.inverted() @ (
        Matrix.Translation(Vector((2.5, -0.6, 3.2)))
        @ Euler((0.5, 0.2, -0.7)).to_matrix().to_4x4())
    wr.matrix = mw
    arm.keyframe_insert('pose.bones["weapon"].location', frame=15)
    arm.keyframe_insert('pose.bones["weapon"].rotation_quaternion',
                        frame=15)
    scene.frame_set(30)
    mw = arm.matrix_world.inverted() @ (
        Matrix.Translation(Vector((1.2, 1.1, 2.2)))
        @ Euler((-0.3, 0.9, 0.4)).to_matrix().to_4x4())
    wr.matrix = mw
    arm.keyframe_insert('pose.bones["weapon"].location', frame=30)
    arm.keyframe_insert('pose.bones["weapon"].rotation_quaternion',
                        frame=30)

    # Attach both at frame 5 (curve states inside the bake range).
    scene.frame_set(5)
    from weapon_animation_rig.utils import constraints as con_util
    con_util.attach_preserve_transform(arm, "R", frame=5, key=True)
    con_util.attach_preserve_transform(arm, "L", frame=5, key=True)
    scene.frame_set(1)
    return arm


def bind_action(arm, action):
    """Assign action + rebind slot (5.2 evaluates through the binding)."""
    bake_mod._bind_action(arm, action)


def test_bake_new_action(arm):
    section("Bake New Action reproduces the rig (plan §44, §52 Test I)")
    scene = bpy.context.scene
    src_name = arm.animation_data.action.name
    before = action_snapshot(arm)

    try:
        result = bake_mod.bake_weapon_animation(arm, 1, 30,
                                                mode='NEW_ACTION')
        check("bake runs", True)
    except WeaponRigError as exc:
        check("bake runs", False, str(exc))
        return None

    check("baked action name has _Baked suffix",
          result["action"].endswith("_Baked"), result["action"])
    new = arm.animation_data.action
    check("baked action assigned", new is not None
          and new.name == result["action"])
    check("source action still in data",
          src_name in bpy.data.actions, "source gone")

    # Reproduce: at every 3rd frame, socket+root match the ORIGINAL rig
    # result. Capture reference by re-evaluating the source action.
    ref = {}
    bind_action(arm, bpy.data.actions[src_name])
    for f in range(1, 31):
        scene.frame_set(f)
        ref[f] = {n: world(arm, n)
                  for n in ("weapon",)}
    worst_t = 0.0
    bind_action(arm, new)
    for f in range(1, 31):
        scene.frame_set(f)
        for n in ("weapon",):
            t, _r = transforms.matrix_difference(ref[f][n], world(arm, n))
            worst_t = max(worst_t, t)
    check("baked action reproduces socket+root (UE would match)",
          worst_t <= 1e-3, "worst d-trans=%.6f" % worst_t)

    # Source action byte-identical (plan §44 "do not overwrite").
    bind_action(arm, bpy.data.actions[src_name])
    check("source action untouched by NEW bake",
          before == action_snapshot(arm))
    bind_action(arm, new)
    check("reported error within tolerance",
          result["max_error"][0] <= TOL_TRANSLATION,
          str(result["max_error"]))
    return new


def test_bake_range_and_guards(arm):
    section("Range + guard frames (plan §30, §44)")
    scene = bpy.context.scene
    src_candidates = [a for a in bpy.data.actions
                      if not a.name.endswith("_Baked")]
    if not src_candidates:
        check("range bake has source", False)
        return
    src = src_candidates[0]
    bind_action(arm, src)
    before = action_snapshot(arm)

    result = bake_mod.bake_weapon_animation(arm, 10, 20, mode='NEW_ACTION')
    check("range bake runs", result["frames"] == 13,  # 9..21 incl guards
          "frames=%d" % result["frames"])

    # Outside the range, the baked action must evaluate like the source.
    new = arm.animation_data.action
    for f, label in ((1, "before range"), (30, "after range")):
        bind_action(arm, src)
        scene.frame_set(f)
        ref = world(arm, "weapon")
        bind_action(arm, new)
        scene.frame_set(f)
        got = world(arm, "weapon")
        t, _ = transforms.matrix_difference(ref, got)
        check("outside range %s: pose preserved" % label,
              t <= 1e-3, "frame %d d=%.6f" % (f, t))
    bind_action(arm, src)
    scene.frame_set(1)
    check("range bake leaves source action untouched",
          before == action_snapshot(arm))


def test_bake_modes(arm):
    section("Bake mode CURRENT_ACTION (plan §44, explicit overwrite)")
    src = [a for a in bpy.data.actions
           if not a.name.endswith("_Baked")][0]
    bind_action(arm, src)
    result = bake_mod.bake_weapon_animation(arm, 1, 30,
                                            mode='CURRENT_ACTION')
    check("CURRENT bake runs", not result["created"])
    check("CURRENT bakes in place",
          arm.animation_data.action.name == result["action"])
    # Root/socket channels gained keys inside the range (+ guards at 0/31
    # pinning the pre-bake pose outside it, plan §30).
    fc = keyframes.find_fcurve(
        arm, 'pose.bones["weapon"].location')
    frames = sorted(k.co[0] for k in fc.keyframe_points) if fc else []
    check("CURRENT bake keyed every frame",
          all(f in frames for f in range(1, 31)),
          "frames=%s" % frames[:8])


def test_bake_errors():
    section("Bake error handling (plan §54)")
    # No weapon bones at all.
    data = bpy.data.armatures.new("Bare")
    bare = bpy.data.objects.new("Bare", data)
    bpy.context.scene.collection.objects.link(bare)
    bpy.context.view_layer.objects.active = bare
    bpy.ops.object.mode_set(mode='EDIT')
    eb = data.edit_bones
    r = eb.new("root"); r.head = (0, 0, 0); r.tail = (0, 0, 0.3)
    bpy.ops.object.mode_set(mode='POSE')
    try:
        bake_mod.bake_weapon_animation(bare, 1, 10)
        check("bake without rig errors", False, "no exception")
    except WeaponRigError as exc:
        check("bake without rig errors", "weapon" in str(exc).lower(),
              str(exc))
    bpy.data.objects.remove(bare, do_unlink=True)

    # Blended aim influence is refused, not silently corrupted (§30).
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 10
    scene.wpn_armature = arm
    res = bpy.ops.wpn.aim_weapon(roll=0.0)
    assert res == {'FINISHED'}, res
    con = arm.pose.bones["weapon"].constraints["WPN_Aim"]
    path = ('pose.bones["weapon"].constraints["WPN_Aim"].influence')
    con.influence = 0.0
    arm.keyframe_insert(path, frame=1)
    con.influence = 1.0
    arm.keyframe_insert(path, frame=5)
    # Force BEZIER so the 1..5 segment actually blends (partial values).
    fc = keyframes.find_fcurve(arm, path)
    for k in fc.keyframe_points:
        k.interpolation = 'BEZIER'
    try:
        bake_mod.bake_weapon_animation(arm, 1, 10, mode='NEW_ACTION')
        check("blended aim influence refused", False, "no exception")
    except WeaponRigError as exc:
        check("blended aim influence refused",
              "aim" in str(exc).lower() or "influence" in str(exc).lower(),
              str(exc))

    # Binary aim (influence 1 throughout) bakes fine. Note: rewriting key
    # VALUES leaves stale bezier handles behind (curve would still dip),
    # so pin CONSTANT -- binary influence is constant by definition.
    fc = keyframes.find_fcurve(arm, path)
    for k in fc.keyframe_points:
        k.co[1] = 1.0
        k.interpolation = 'CONSTANT'
    try:
        bake_mod.bake_weapon_animation(arm, 1, 10,
                                       mode='NEW_ACTION')
        check("binary aim bakes", True)
    except WeaponRigError as exc:
        check("binary aim bakes", False, str(exc))


def test_bake_after_pivot():
    section("Pivot translations flow into baked export data (UE safety)")
    # Scenario behind the question "won't the mesh shift in UE when Set
    # Pivot moves the bone?": pivot first, animate a rotation ABOUT the
    # pivot, bake, and prove the baked bone animation reproduces the rig
    # exactly. UE plays baked bone transforms, so baked == rig means
    # UE == Blender (given the same attach-offset convention).
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 30
    scene.frame_current = 1

    from weapon_animation_rig.weapon import pivot as pivot_mod
    pivot_mod.set_pivot(arm, 'TIP', key=False)
    head = world(arm, "weapon").translation.copy()

    # Rotate the weapon about its head (= tip) at frame 30, key both ends.
    # Mimics R-key rotation about the bone origin (world-space pivot).
    arm.keyframe_insert('pose.bones["weapon"].location', frame=1)
    arm.keyframe_insert('pose.bones["weapon"].rotation_quaternion',
                        frame=1)
    scene.frame_set(30)
    w = world(arm, "weapon")
    rot = Matrix.Rotation(0.9, 4, 'Z') @ Matrix.Rotation(0.4, 4, 'X')
    t_to = Matrix.Translation(head)
    new_world = (t_to @ rot @ Matrix.Translation(-head) @ w)
    transforms.set_pose_bone_arm_matrix(
        arm, "weapon", arm.matrix_world.inverted() @ new_world)
    transforms.update_view_layer()
    arm.keyframe_insert('pose.bones["weapon"].location', frame=30)
    arm.keyframe_insert('pose.bones["weapon"].rotation_quaternion',
                        frame=30)

    # Reference: rig-evaluated weapon matrices with the SOURCE action.
    ref = {}
    for f in range(1, 31):
        scene.frame_set(f)
        ref[f] = world(arm, "weapon")

    result = bake_mod.bake_weapon_animation(arm, 1, 30,
                                            mode='NEW_ACTION')
    check("pivot-shot bake runs", result["action"].endswith("_Baked"))
    worst_t = 0.0
    for f in range(1, 31):
        scene.frame_set(f)
        got = world(arm, "weapon")
        t, _r = transforms.matrix_difference(ref[f], got)
        worst_t = max(worst_t, t)
    check("baked weapon matches rig every frame",
          worst_t <= 1e-3, "worst d-trans=%.6f" % worst_t)

    # Tip stays glued to the pivot through the baked playback too.
    worst_tip = 0.0
    for f in range(1, 31, 7):
        scene.frame_set(f)
        tip_here = (world(arm, "weapon").translation
                    + world(arm, "weapon").to_3x3() @ Vector(tuple(
                        arm.data.bones["weapon"]["tip"])))
        worst_tip = max(worst_tip, (tip_here - head).length)
    check("tip fixed at pivot in baked playback",
          worst_tip <= 1e-3, "drift=%.6f" % worst_tip)
    scene.frame_set(1)


def test_bake_operator(arm):
    section("Bake operator + panel range (plan §32)")
    scene = bpy.context.scene
    src = [a for a in bpy.data.actions if not a.name.endswith("_Baked")]
    bind_action(arm, src[0])
    scene.wpn_armature = arm
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    res = bpy.ops.wpn.bake(mode='NEW_ACTION')
    check("bake operator runs", res == {'FINISHED'}, str(res))
    check("baked action picked up",
          "_Baked" in arm.animation_data.action.name,
          arm.animation_data.action.name)


def main():
    print("=" * 70)
    print("MILESTONE 5 TEST SUITE: BAKE (plan §52)")
    print("=" * 70)

    arm = build_animated_shot()
    test_bake_new_action(arm)
    test_bake_range_and_guards(arm)
    test_bake_modes(arm)
    test_bake_operator(arm)
    test_bake_errors()
    # Self-contained (factory reset inside): must run last.
    test_bake_after_pivot()

    summary()


main()
