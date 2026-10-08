"""Headless test suite for Milestone 2: Snap Weapon -> Hands (plan §49).

Run:
    blender -b --factory-startup --python tests/run_milestone2_tests.py

Covers plan §53 Test H (two-hand snap) plus §18 (single-hand snap: no
character movement, no hand animation touched, no keys unless requested),
§20 (solver accuracy), §55 (edge cases: hands too close -> warning +
fallback, no unstable quaternions), §31 (key policy).
"""
import os
import sys

import bpy
from mathutils import Euler, Matrix, Vector

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(ADDON_DIR))

import weapon_animation_rig as war  # noqa: E402
war.register()

from weapon_animation_rig.constants import (  # noqa: E402
    TOL_TRANSLATION,
    WeaponRigError,
)
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402
from weapon_animation_rig.weapon import snap  # noqa: E402
from weapon_animation_rig.animation import keyframes  # noqa: E402

PASS = []
FAIL = []


def check(name, ok, detail=""):
    if ok:
        PASS.append(name)
        print("  PASS  %s" % name)
    else:
        FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def section(title):
    print("\n--- %s ---" % title)


def world(arm, name):
    return transforms.get_pose_bone_world_matrix(arm, name)


def grip_world(arm, side):
    """Grip reference frame (rework: prop-based, not a bone)."""
    from weapon_animation_rig.utils import constraints as con_util
    return con_util.grip_world(arm, side)


def build_rig():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 100
    scene.frame_current = 1
    scene.tool_settings.use_keyframe_insert_auto = False  # plan §31

    arm_data = bpy.data.armatures.new("MockARP")
    arm = bpy.data.objects.new("MockARP", arm_data)
    scene.collection.objects.link(arm)
    arm.location = (1.3, -0.7, 2.1)  # non-identity: catches space bugs
    arm.rotation_euler = Euler((0.23, -0.61, 0.42), 'XYZ')

    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones

    def mk(name, head, tail, parent=None):
        b = eb.new(name)
        b.head, b.tail = head, tail
        b.parent = parent
        return b

    root = mk("root", (0, 0, 0), (0, 0, 0.3))
    spine = mk("spine_01", (0, 0, 1.0), (0, 0.15, 1.0), root)
    mk("c_hand_ik.r", (0.6, 0.0, 1.3), (0.6, 0.18, 1.3), spine)
    mk("c_hand_ik.l", (-0.6, 0.0, 1.3), (-0.6, 0.18, 1.3), spine)
    bpy.ops.object.mode_set(mode='POSE')

    rig_create.create_weapon_rig(bpy.context, arm)
    return arm


def pose_hand(arm, side, world_matrix):
    """Place a hand IK bone at an exact world matrix (arm-space write)."""
    arm_space = arm.matrix_world.inverted() @ world_matrix
    transforms.set_pose_bone_arm_matrix(
        arm, "c_hand_ik." + side.lower(), arm_space)
    transforms.update_view_layer()


def weapon_root_channels_keyed(arm):
    for path in keyframes.channel_data_paths(arm.pose.bones["weapon"]):
        if keyframes.find_fcurve(arm, path) is not None:
            return True, path
    return False, None


# ---------------------------------------------------------------------------
# Test H (plan §53): two-hand snap
# ---------------------------------------------------------------------------

def test_snap_both(arm):
    section("Test H: snap weapon -> both hands (plan §53 H, §20)")
    scene = bpy.context.scene
    scene.frame_current = 10

    # Pose both hands to a known configuration in world space:
    # right hand at P, left hand 0.25m to the left, both with rotation.
    p_r = Vector((1.5, 0.4, 1.6))
    p_l = Vector((1.0, 0.7, 1.6))  # distance ~0.583
    hr = Matrix.Translation(p_r) @ Euler((0.4, 0.2, 0.9)).to_matrix().to_4x4()
    hl = Matrix.Translation(p_l) @ Euler((-0.3, 0.7, -0.4)).to_matrix().to_4x4()
    pose_hand(arm, "R", hr)
    pose_hand(arm, "L", hl)

    hands_before = (world(arm, "c_hand_ik.r").copy(),
                    world(arm, "c_hand_ik.l").copy())

    try:
        result = snap.snap_weapon_to_both(arm, key=False)
        check("snap both runs", True)
    except WeaponRigError as exc:
        check("snap both runs", False, str(exc))
        return

    grip_r = grip_world(arm, "R")
    grip_l = grip_world(arm, "L")
    err_r = (grip_r.translation - p_r).length
    check("grip_r lands on right hand", err_r <= TOL_TRANSLATION,
          "err=%.6f" % err_r)

    # grip_l: rigid spacing differs from hand spacing -> must miss by at
    # most the spacing gap (plan §20 step 7 / solver's own guarantee).
    hand_spacing = (p_l - p_r).length
    grip_spacing = (grip_world(arm, "L").translation
                    - grip_world(arm, "R").translation).length
    # Actually grip spacing is preserved by rigid motion; compare against
    # the pre-snap grip spacing.
    err_l = (grip_l.translation - p_l).length
    spacing_gap = abs(hand_spacing - grip_spacing)
    check("grip_l error within spacing gap", err_l <= spacing_gap + 1e-4,
          "err_l=%.6f gap=%.6f" % (err_l, spacing_gap))

    # Both grip positions must lie ON the line between the hands (direction
    # alignment, plan §20 step 3): grip_r is anchored to right hand, so the
    # grip vector must be parallel to the hand vector.
    grip_vec = grip_l.translation - grip_r.translation
    hand_vec = p_l - p_r
    grip_dir = grip_vec.normalized()
    hand_dir = hand_vec.normalized()
    align_err = (grip_dir - hand_dir).length
    check("grip vector aligned with hand vector", align_err <= 1e-4,
          "align=%.8f" % align_err)

    # Hands must not move (they are not attached, plan §18).
    t_r, _ = transforms.matrix_difference(
        hands_before[0], world(arm, "c_hand_ik.r"))
    t_l, _ = transforms.matrix_difference(
        hands_before[1], world(arm, "c_hand_ik.l"))
    check("right hand unmoved by snap", t_r <= TOL_TRANSLATION, "d=%.6f" % t_r)
    check("left hand unmoved by snap", t_l <= TOL_TRANSLATION, "d=%.6f" % t_l)

    # No keys unless requested (plan §31).
    keyed, path = weapon_root_channels_keyed(arm)
    check("no weapon_root keys without key=True", not keyed,
          "unexpected fcurve: %s" % path)

    # Re-running is stable (idempotent within tolerance).
    err_r2 = 0.0
    try:
        snap.snap_weapon_to_both(arm, key=False)
        err_r2 = (grip_world(arm, "R").translation - p_r).length
    except WeaponRigError as exc:
        check("snap both idempotent", False, str(exc))
        return
    check("snap both idempotent", err_r2 <= TOL_TRANSLATION,
          "err=%.6f" % err_r2)
    return result


def test_snap_both_matched_spacing(arm):
    """With |hand spacing| == |grip spacing| BOTH grips must land exactly
    (plan §20: 'match both grip positions as accurately as possible')."""
    section("Test H2: matched spacing -> both grips exact (plan §20)")
    scene = bpy.context.scene
    scene.frame_current = 20

    # Read current grip spacing from the weapon (rigid).
    gr = grip_world(arm, "R").translation
    gl = grip_world(arm, "L").translation
    grip_spacing = (gl - gr).length
    check("grip spacing non-degenerate", grip_spacing > 0.01,
          "spacing=%.6f" % grip_spacing)

    # Place hands exactly grip_spacing apart along a chosen direction.
    p_r = Vector((1.7, -0.3, 1.5))
    direction = Vector((0.3, 0.8, 0.1)).normalized()
    p_l = p_r + direction * grip_spacing
    hr = Matrix.Translation(p_r) @ Euler((0.1, -0.5, 0.3)).to_matrix().to_4x4()
    hl = Matrix.Translation(p_l) @ Euler((0.6, 0.2, -0.8)).to_matrix().to_4x4()
    pose_hand(arm, "R", hr)
    pose_hand(arm, "L", hl)

    try:
        result = snap.snap_weapon_to_both(arm, key=False)
    except WeaponRigError as exc:
        check("snap both (matched spacing)", False, str(exc))
        return
    err_r = (grip_world(arm, "R").translation - p_r).length
    err_l = (grip_world(arm, "L").translation - p_l).length
    check("matched spacing: grip_r exact", err_r <= TOL_TRANSLATION,
          "err=%.6f" % err_r)
    check("matched spacing: grip_l exact", err_l <= TOL_TRANSLATION,
          "err=%.6f" % err_l)
    check("matched spacing: no warning", result["warning"] is None,
          str(result["warning"]))


# ---------------------------------------------------------------------------
# Single-hand snap (plan §18/§19)
# ---------------------------------------------------------------------------

def test_snap_single(arm):
    section("Snap -> right hand only (plan §18)")
    scene = bpy.context.scene
    scene.frame_current = 30

    p_r = Vector((1.2, 0.9, 2.0))
    hr = Matrix.Translation(p_r) @ Euler((0.9, -0.2, 0.5)).to_matrix().to_4x4()
    pose_hand(arm, "R", hr)
    pose_hand(arm, "L", Matrix.Translation(Vector((-1.0, 0.5, 1.0))))

    hands_before = (world(arm, "c_hand_ik.r").copy(),
                    world(arm, "c_hand_ik.l").copy())
    grip_rot_before = grip_world(arm, "R").to_quaternion()

    try:
        snap.snap_weapon_to_hand(arm, "R", align_orientation=False,
                                 key=False)
        check("snap -> R runs", True)
    except WeaponRigError as exc:
        check("snap -> R runs", False, str(exc))
        return

    err = (grip_world(arm, "R").translation - p_r).length
    check("grip_r lands on right hand (single)", err <= TOL_TRANSLATION,
          "err=%.6f" % err)

    # Default = position only: grip ORIENTATION preserved (plan §18).
    grip_rot_after = grip_world(arm, "R").to_quaternion()
    angle = abs(grip_rot_before.rotation_difference(grip_rot_after).angle)
    check("grip orientation preserved (position-only snap)",
          angle * 57.2957795 <= 0.01, "angle=%.6f deg" % (angle * 57.2957795))

    # Both hands unmoved.
    for label, before, name in (("R", hands_before[0], "c_hand_ik.r"),
                                ("L", hands_before[1], "c_hand_ik.l")):
        d, _ = transforms.matrix_difference(before, world(arm, name))
        check("hand %s unmoved by single snap" % label,
              d <= TOL_TRANSLATION, "d=%.6f" % d)

    # align_orientation=True matches the hand frame too.
    try:
        snap.snap_weapon_to_hand(arm, "R", align_orientation=True, key=False)
        check("snap -> R with orientation runs", True)
    except WeaponRigError as exc:
        check("snap -> R with orientation runs", False, str(exc))
        return
    grip = grip_world(arm, "R")
    trans, rot = transforms.matrix_difference(grip, world(arm, "c_hand_ik.r"))
    check("orientation snap: grip frame == hand frame",
          trans <= TOL_TRANSLATION and rot <= 0.01,
          "trans=%.6f rot=%.4f" % (trans, rot))

    # Left hand snap.
    p_l = Vector((0.8, -0.6, 1.7))
    hl = Matrix.Translation(p_l) @ Euler((-0.7, 0.1, 0.2)).to_matrix().to_4x4()
    pose_hand(arm, "L", hl)
    try:
        snap.snap_weapon_to_hand(arm, "L", key=False)
        check("snap -> L runs", True)
    except WeaponRigError as exc:
        check("snap -> L runs", False, str(exc))
        return
    err = (grip_world(arm, "L").translation - p_l).length
    check("grip_l lands on left hand", err <= TOL_TRANSLATION,
          "err=%.6f" % err)


# ---------------------------------------------------------------------------
# Keyframe policy (plan §31)
# ---------------------------------------------------------------------------

def test_snap_key_policy(arm):
    section("Snap key policy (plan §31)")
    scene = bpy.context.scene
    scene.frame_current = 40

    p_r = Vector((1.4, 0.2, 1.8))
    pose_hand(arm, "R", Matrix.Translation(p_r))

    # key=False: no keys.
    snap.snap_weapon_to_hand(arm, "R", key=False)
    keyed, path = weapon_root_channels_keyed(arm)
    check("key=False creates no keys", not keyed, "fcurve: %s" % path)

    # key=True: keys created at frame 40, value = current pose.
    # Move the hand first so the snap actually CHANGES weapon_root --
    # per plan §31 a no-op operation must not create keys.
    scene.frame_current = 40
    p_r2 = Vector((1.4, 0.2, 1.8))
    pose_hand(arm, "R", Matrix.Translation(p_r2 + Vector((0.3, -0.4, 0.2))))
    snap.snap_weapon_to_hand(arm, "R", key=True, frame=40)
    keyed, path = weapon_root_channels_keyed(arm)
    check("key=True keys weapon_root", keyed)
    if not keyed:
        return
    loc_path = 'pose.bones["weapon"].location'
    fc = keyframes.find_fcurve(arm, loc_path)
    check("location key at frame 40", fc is not None
          and any(abs(k.co[0] - 40) < 1e-6 for k in fc.keyframe_points),
          str([(k.co[0], k.co[1]) for k in fc.keyframe_points])
          if fc else "no fcurve")

    # Guard: with no prior keys, key_changed_channels writes a guard at
    # frame-39 with the OLD value so earlier frames keep their pose (§30).
    frames = sorted(k.co[0] for k in fc.keyframe_points)
    check("guard key at frame-1 exists", frames and frames[0] == 39.0,
          "frames=%s" % frames)

    # Auto Key respected (plan §31).
    scene.frame_current = 41
    p_r2 = Vector((1.1, 0.5, 1.9))
    pose_hand(arm, "R", Matrix.Translation(p_r2))
    scene.tool_settings.use_keyframe_insert_auto = True
    result = snap.snap_weapon_to_hand(arm, "R", key=False, frame=41)
    scene.tool_settings.use_keyframe_insert_auto = False
    # snap core doesn't read Auto Key itself (operator does) -- operator
    # test below covers that. Here just ensure core still ran clean.
    check("snap with Auto Key on runs", result is not None)


def test_snap_operator_key(arm):
    """Operator must fold scene Auto Key into its key decision (§31)."""
    section("Snap operator Auto Key handling (plan §31)")
    scene = bpy.context.scene
    scene.frame_current = 45
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    scene.wpn_armature = arm

    # Clean weapon_root animation from previous test.
    arm.animation_data_clear()

    pose_hand(arm, "R", Matrix.Translation(Vector((1.6, 0.1, 1.7))))
    scene.tool_settings.use_keyframe_insert_auto = True
    res = bpy.ops.wpn.snap_to_hand(side='R', key=False)
    scene.tool_settings.use_keyframe_insert_auto = False
    check("operator snap runs", res == {'FINISHED'}, str(res))
    keyed, path = weapon_root_channels_keyed(arm)
    check("operator keys with scene Auto Key ON", keyed,
          "no fcurve created")

    # Auto Key off + key=False: no new keys after clearing.
    arm.animation_data_clear()
    pose_hand(arm, "R", Matrix.Translation(Vector((1.3, 0.6, 1.2))))
    scene.tool_settings.use_keyframe_insert_auto = False
    res = bpy.ops.wpn.snap_to_hand(side='R', key=False)
    check("operator snap runs (auto-key off)", res == {'FINISHED'}, str(res))
    keyed, path = weapon_root_channels_keyed(arm)
    check("operator creates no keys with Auto Key OFF", not keyed,
          "fcurve: %s" % path)

    res = bpy.ops.wpn.snap_to_both(key=False)
    check("operator snap both runs", res == {'FINISHED'}, str(res))


# ---------------------------------------------------------------------------
# Edge cases (plan §55)
# ---------------------------------------------------------------------------

def test_degenerate_hands(arm):
    section("Degenerate hand distance (plan §55)")
    scene = bpy.context.scene
    scene.frame_current = 60

    p = Vector((1.5, 0.3, 1.6))
    pose_hand(arm, "R", Matrix.Translation(p))
    pose_hand(arm, "L", Matrix.Translation(p))  # hands coincide

    try:
        result = snap.snap_weapon_to_both(arm, key=False)
        check("degenerate hands: no crash", True)
    except WeaponRigError as exc:
        check("degenerate hands: no crash", False, str(exc))
        return
    check("degenerate hands: warning reported",
          result["warning"] is not None and "ambiguous" in result["warning"],
          str(result["warning"]))
    check("degenerate hands: fallback anchored grip_r to right hand",
          (grip_world(arm, "R").translation - p).length
          <= TOL_TRANSLATION)
    # No NaN/inf in the resulting matrix (no unstable quaternion).
    w_after = world(arm, "weapon")
    vals = [w_after[i][j] for i in range(4) for j in range(4)]
    check("degenerate hands: result matrix finite",
          all(v == v and abs(v) != float("inf") for v in vals),
          str(vals))
    # Roll check: weapon rotation should be finite + grip_r orientation
    # derived from right hand aim (fallback path).
    check("degenerate hands: fallback mode", result["mode"] == "fallback",
          result["mode"])


def test_near_180_alignment(arm):
    """Grip vector and hand vector anti-parallel -> frame solver must still
    produce a valid rotation (plan §55 'near-180-degree vector alignment')."""
    section("Near-180 alignment (plan §55)")
    scene = bpy.context.scene
    scene.frame_current = 70

    # First orient the weapon so grips run along +X-ish in world, then put
    # hands along -X (anti-parallel).
    # Put hands along a direction, snap, then flip and snap again.
    gr = grip_world(arm, "R").translation
    gl = grip_world(arm, "L").translation
    spacing = (gl - gr).length

    p_r = Vector((1.6, 0.5, 1.5))
    # hands along the NEGATIVE of the current grip direction
    grip_dir = (gl - gr).normalized()
    p_l = p_r - grip_dir * spacing  # anti-parallel arrangement
    pose_hand(arm, "R", Matrix.Translation(p_r))
    pose_hand(arm, "L", Matrix.Translation(p_l))

    try:
        snap.snap_weapon_to_both(arm, key=False)
        check("anti-parallel snap runs", True)
    except WeaponRigError as exc:
        check("anti-parallel snap runs", False, str(exc))
        return
    err_r = (grip_world(arm, "R").translation - p_r).length
    check("anti-parallel: grip_r exact", err_r <= TOL_TRANSLATION,
          "err=%.6f" % err_r)
    # grip vector must now point along the hand vector (flipped).
    grip_dir2 = ((grip_world(arm, "L").translation
                  - grip_world(arm, "R").translation).normalized())
    hand_dir = (p_l - p_r).normalized()
    check("anti-parallel: direction flipped correctly",
          (grip_dir2 - hand_dir).length <= 1e-4,
          "d=%.8f" % (grip_dir2 - hand_dir).length)
    w = world(arm, "weapon")
    vals = [w[i][j] for i in range(4) for j in range(4)]
    check("anti-parallel: matrix finite",
          all(v == v and abs(v) != float("inf") for v in vals))


def test_snap_does_not_touch_animation(arm):
    """plan §49: 'Test especially: existing character pose, existing hand
    animation, existing weapon animation. The snapping operation must not
    unexpectedly modify the character.'"""
    section("Existing animation untouched by snap (plan §49)")

    # Fresh rig with animation on hand + spine.
    arm2_data = bpy.data.armatures.new("MockAnim")
    arm2 = bpy.data.objects.new("MockAnim", arm2_data)
    bpy.context.scene.collection.objects.link(arm2)
    bpy.context.view_layer.objects.active = arm2
    arm2.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm2.data.edit_bones
    root = eb.new("root"); root.head = (0, 0, 0); root.tail = (0, 0, 0.3)
    spine = eb.new("spine_01")
    spine.head, spine.tail, spine.parent = (0, 0, 1.0), (0, 0.15, 1.0), root
    h_r = eb.new("c_hand_ik.r")
    h_r.head, h_r.tail, h_r.parent = (0.6, 0, 1.3), (0.6, 0.18, 1.3), spine
    h_l = eb.new("c_hand_ik.l")
    h_l.head, h_l.tail, h_l.parent = (-0.6, 0, 1.3), (-0.6, 0.18, 1.3), spine
    bpy.ops.object.mode_set(mode='POSE')
    rig_create.create_weapon_rig(bpy.context, arm2)

    # Animate hand + spine.
    hr = arm2.pose.bones["c_hand_ik.r"]
    hr.location = (0, 0, 0)
    arm2.keyframe_insert('pose.bones["c_hand_ik.r"].location', frame=1)
    hr.location = (0.3, 0.1, -0.2)
    arm2.keyframe_insert('pose.bones["c_hand_ik.r"].location', frame=50)
    sp = arm2.pose.bones["spine_01"]
    sp.rotation_mode = 'XYZ'
    sp.rotation_euler = (0.1, 0, 0)
    arm2.keyframe_insert('pose.bones["spine_01"].rotation_euler', frame=1)
    sp.rotation_euler = (0.5, 0.2, 0)
    arm2.keyframe_insert('pose.bones["spine_01"].rotation_euler', frame=50)

    def snap_keys(a):
        ad = a.animation_data
        out = {}
        if ad is None or ad.action is None:
            return out
        slot = getattr(ad, "action_slot", None)
        for layer in ad.action.layers:
            for strip in layer.strips:
                if strip.type != 'KEYFRAME':
                    continue
                cb = strip.channelbag(slot)
                if cb is None:
                    continue
                for fcu in cb.fcurves:
                    out[(fcu.data_path, fcu.array_index)] = [
                        (k.co[0], round(k.co[1], 9))
                        for k in fcu.keyframe_points]
        return out

    before = snap_keys(arm2)
    bpy.context.scene.frame_current = 25
    try:
        snap.snap_weapon_to_both(arm2, key=False)
        snap.snap_weapon_to_hand(arm2, "R", key=False)
        check("snap on animated rig runs", True)
    except WeaponRigError as exc:
        check("snap on animated rig runs", False, str(exc))
        return
    after = snap_keys(arm2)
    # Only weapon_root keys could be added (none, key=False) -- hand/spine
    # keys must be byte-identical.
    hand_spine_before = {k: v for k, v in before.items()
                         if "c_hand_ik" in k[0] or "spine" in k[0]}
    hand_spine_after = {k: v for k, v in after.items()
                        if "c_hand_ik" in k[0] or "spine" in k[0]}
    check("hand/spine keys unchanged by snap",
          hand_spine_before == hand_spine_after,
          "before=%s after=%s" % (hand_spine_before, hand_spine_after))
    check("no new keys anywhere (key=False)", before == after,
          "extra=%s" % {k: after.get(k) for k in after if k not in before})

    # Pose at frame 25 unchanged for the hand (weapon moved, hand not).
    bpy.context.scene.frame_current = 25
    transforms.update_view_layer()


def test_snap_attached_preserves(arm):
    section("Snap while attached keeps hands glued (rework)")
    scene = bpy.context.scene
    scene.frame_current = 70
    from weapon_animation_rig.utils import constraints as con_util

    # Offset-attach the right hand, then snap single while attached:
    # the grip must land on the captured hand spot AND the hand must
    # not move (inverse re-solve), with no warning needed.
    pb = arm.pose.bones["c_hand_ik.r"]
    pb.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((2.5, 1.5, 1.0)))
    transforms.update_view_layer()
    hand_spot = world(arm, "c_hand_ik.r").translation.copy()
    con_util.attach_preserve_transform(arm, "R", frame=70, key=True)
    result = snap.snap_weapon_to_hand(arm, "R", key=False, frame=70)
    check("attached far snap still succeeds",
          result["grip_error_r"] <= TOL_TRANSLATION,
          "err=%.6f" % result["grip_error_r"])
    check("attached hand did not move during snap",
          (world(arm, "c_hand_ik.r").translation - hand_spot).length
          <= TOL_TRANSLATION)
    check("grip landed on the captured hand spot",
          (grip_world(arm, "R").translation - hand_spot).length
          <= TOL_TRANSLATION)
    check("no warning needed (nothing displaced)",
          result["warning"] is None, str(result["warning"]))

    # Detach, move hand onto the grip, reattach: still silent.
    con_util.detach_preserve_transform(arm, "R", frame=70, key=True)
    pb.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        grip_world(arm, "R").translation)
    transforms.update_view_layer()
    con_util.attach_preserve_transform(arm, "R", frame=71, key=True)
    result2 = snap.snap_weapon_to_hand(arm, "R", key=False, frame=71)
    check("attached aligned snap stays silent",
          result2["warning"] is None, str(result2["warning"]))

    # Both-hands variant: attach L far away too, snap both while attached.
    pb_l = arm.pose.bones["c_hand_ik.l"]
    pb_l.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((-2.5, 1.5, 1.0)))
    transforms.update_view_layer()
    spots = {s: world(arm, "c_hand_ik." + s.lower()).translation.copy()
             for s in ("R", "L")}
    con_util.attach_preserve_transform(arm, "L", frame=71, key=True)
    spots["L"] = world(arm, "c_hand_ik.l").translation.copy()
    spots["R"] = world(arm, "c_hand_ik.r").translation.copy()
    result3 = snap.snap_weapon_to_both(arm, key=False, frame=71)
    check("attached snap-both grips land on captured spots",
          result3["grip_error_r"] <= TOL_TRANSLATION,
          "err=%.6f" % result3["grip_error_r"])
    check("attached snap-both needs no displacement warning",
          result3["warning"] is None
          or "followed the weapon" not in result3["warning"],
          str(result3["warning"]))
    for s in ("R", "L"):
        moved = (world(arm, "c_hand_ik." + s.lower()).translation
                 - spots[s]).length
        check("attached hand %s did not move during snap-both" % s,
              moved <= TOL_TRANSLATION, "moved %.6f" % moved)
    con_util.detach_preserve_transform(arm, "R", frame=71, key=True)
    con_util.detach_preserve_transform(arm, "L", frame=71, key=True)


def test_snap_error_handling(arm):
    section("Snap error handling (plan §54)")
    # Rig without weapon bones.
    arm3 = bpy.data.armatures.new("Bare")
    arm3_obj = bpy.data.objects.new("Bare", arm3)
    bpy.context.scene.collection.objects.link(arm3_obj)
    bpy.context.view_layer.objects.active = arm3_obj
    arm3_obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm3.edit_bones
    root = eb.new("root"); root.head = (0, 0, 0); root.tail = (0, 0, 0.3)
    h = eb.new("c_hand_ik.r"); h.head = (0.5, 0, 1); h.tail = (0.5, 0.2, 1)
    h.parent = root
    h2 = eb.new("c_hand_ik.l"); h2.head = (-0.5, 0, 1)
    h2.tail = (-0.5, 0.2, 1); h2.parent = root
    bpy.ops.object.mode_set(mode='POSE')
    try:
        snap.snap_weapon_to_hand(arm3_obj, "R")
        check("snap without weapon bones errors", False, "no exception")
    except WeaponRigError as exc:
        check("snap without weapon bones errors",
              "weapon" in str(exc).lower(), str(exc))
    bpy.data.objects.remove(arm3_obj, do_unlink=True)

    # Operator reports the error instead of crashing.
    scene = bpy.context.scene
    scene.wpn_armature = None
    for obj in list(scene.objects):
        if obj.type == 'ARMATURE':
            scene.wpn_armature = obj
            break
    res = bpy.ops.wpn.snap_to_both(key=False)
    check("operator survives (FINISHED or CANCELLED)",
          res in ({'FINISHED'}, {'CANCELLED'}), str(res))


def main():
    print("=" * 70)
    print("MILESTONE 2 TEST SUITE: SNAP (plan §49)")
    print("=" * 70)

    arm = build_rig()
    test_snap_both(arm)
    test_snap_both_matched_spacing(arm)
    test_snap_single(arm)
    test_snap_key_policy(arm)
    test_snap_operator_key(arm)
    test_degenerate_hands(arm)
    test_near_180_alignment(arm)
    test_snap_does_not_touch_animation(arm)
    test_snap_attached_preserves(arm)
    test_snap_error_handling(arm)

    print("\n" + "=" * 70)
    print("RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        for name in FAIL:
            print("  FAILED: %s" % name)
        print("=" * 70)
        sys.exit(1)
    print("ALL TESTS PASSED")
    print("=" * 70)
    sys.exit(0)


main()
