"""Headless test suite: interactive weapon rotation (user request).

Run:
    blender -b --factory-startup --python tests/run_milestone8_tests.py

Covers the rotate feature (weapon/rotate.py + operators/rotate.py):
- pivot stays world-locked while the drag point aims at a target;
- pure rotation about the pivot (all reference points keep their radius --
  "the sword's position must not drift, only rotate around the pivot");
- arbitrary pivot/drag combinations (tip around pommel, guard L around
  guard R, ...);
- degenerate geometry refused with explicit WeaponRigError;
- attached hands follow the rotation rigidly, detached hands don't move;
- keyframe policy ([Key] / Auto Key only);
- ray->plane target math for the modal drag;
- operator surface: enum parity with scene props (panel passes
  scene.wpn_pivot straight through), one-shot execute, modal poll refuses
  headless cleanly.
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import check, section, summary  # noqa: E402

war = common.register_addon()

from weapon_animation_rig.constants import (  # noqa: E402
    WeaponRigError,
)
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.utils import constraints as con_util  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402
from weapon_animation_rig.weapon import pivot as pivot_mod  # noqa: E402
from weapon_animation_rig.weapon import rotate as rotate_mod  # noqa: E402

GEOM_PIVOTS = ('CENTER', 'GRIP_R', 'GRIP_L', 'GUARD', 'GUARD_L',
               'GUARD_R', 'TIP', 'POMMEL')
DRAG_POINTS = ('TIP', 'GUARD_L', 'GUARD_R', 'GRIP_R', 'GRIP_L',
               'POMMEL', 'CENTER')


def build_rig():
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.wpn_armature = arm
    return arm


def config_points(arm):
    """All configured weapon points in world space."""
    return pivot_mod._config_points(arm)


# =========================================================================
# Core rotation
# =========================================================================

def test_rotate_basic(arm):
    section("Rotate: pivot locked, drag aims at target (user req.)")
    pivot_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    drag_p = pivot_mod.compute_pivot_world(arm, 'TIP')
    # Target: arbitrary direction from the pivot (into +X/+Z quadrant).
    target = pivot_p + Vector((0.4, 0.15, 0.3))

    res = rotate_mod.rotate_toward(arm, 'POMMEL', 'TIP', target)
    check("rotation completes", isinstance(res, dict), str(res))
    check("direction error ~0",
          res["angle_error_deg"] <= 0.5,
          "%.6f deg" % res["angle_error_deg"])
    check("pivot world shift ~0",
          res["pivot_shift"] <= 1e-5, "%.9f" % res["pivot_shift"])
    check("no keys by default", not res["keyed"])

    # Independent re-measurement (not trusting the return dict).
    pivot_now = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    check("re-measured pivot locked",
          (pivot_now - pivot_p).length <= 1e-4,
          "%.9f" % (pivot_now - pivot_p).length)
    drag_now = pivot_mod.compute_pivot_world(arm, 'TIP')
    want_dir = (target - pivot_p).normalized()
    got_dir = (drag_now - pivot_now).normalized()
    ang = math.degrees(got_dir.angle(want_dir))
    check("re-measured tip aims at target", ang <= 0.5, "%.4f deg" % ang)
    check("tip radius preserved",
          abs((drag_now - pivot_now).length - (drag_p - pivot_p).length)
          <= 1e-4,
          "%.9f" % abs((drag_now - pivot_p).length
                       - (drag_p - pivot_p).length))


def test_pure_rotation(arm):
    section("Rotate: pure rotation -- no translation drift (user req.)")
    # The sword's position must not drift: EVERY configured point must
    # keep its distance to the pivot (isometry fixing the pivot).
    pivot_p = pivot_mod.compute_pivot_world(arm, 'GUARD_R')
    before = config_points(arm)
    target = pivot_p + Vector((-0.2, 0.3, -0.25))
    rotate_mod.rotate_toward(arm, 'GUARD_R', 'GUARD_L', target)
    after = config_points(arm)
    worst = 0.0
    for name in before:
        r0 = (before[name] - pivot_p).length
        r1 = (after[name] - pivot_p).length
        worst = max(worst, abs(r1 - r0))
    check("all 7 points keep radius to pivot", worst <= 1e-4,
          "worst radius drift=%.9f" % worst)
    moved = max((after[n] - before[n]).length for n in before)
    check("weapon actually rotated (not a no-op)", moved > 1e-3,
          "max point movement=%.6f" % moved)
    check("pivot re-check after multi-point pass",
          (pivot_mod.compute_pivot_world(arm, 'GUARD_R')
           - pivot_p).length <= 1e-4, "pivot drifted")


def test_pivot_drag_grid(arm):
    section("Rotate: arbitrary pivot/drag combos (user examples)")
    combos = [
        ('POMMEL', 'TIP'),      # dragging Tip around Pommel
        ('GUARD_R', 'GUARD_L'),  # dragging Guard L around Guard R
        ('GUARD', 'TIP'),       # tip around crossguard center
        ('GRIP_L', 'POMMEL'),   # pommel around left grip
        ('TIP', 'POMMEL'),      # reverse: pommel orbits the tip
        ('CENTER', 'GUARD_L'),
    ]
    for piv, drag in combos:
        pp = pivot_mod.compute_pivot_world(arm, piv)
        target = pp + Vector((0.3, -0.2, 0.25))
        try:
            res = rotate_mod.rotate_toward(arm, piv, drag, target)
            ok = (res["angle_error_deg"] <= 0.5
                  and res["pivot_shift"] <= 1e-5)
            detail = "err=%.5f shift=%.9f" % (res["angle_error_deg"],
                                              res["pivot_shift"])
        except WeaponRigError as exc:
            ok, detail = False, str(exc)
        check("drag %s around %s" % (drag, piv), ok, detail)


def test_sequential_interaction(arm):
    section("Rotate: sequential drags keep the pivot locked (no drift)")
    pivot_p = pivot_mod.compute_pivot_world(arm, 'GUARD')
    for i, direction in enumerate(((0.5, 0.0, 0.2),
                                   (-0.3, 0.4, 0.1),
                                   (0.1, -0.2, 0.5))):
        target = pivot_p + Vector(direction)
        rotate_mod.rotate_toward(arm, 'GUARD', 'TIP', target)
        now = pivot_mod.compute_pivot_world(arm, 'GUARD')
        check("drag %d: pivot locked" % i,
              (now - pivot_p).length <= 1e-4,
              "%.9f" % (now - pivot_p).length)
        if i == 0:
            radius0 = (pivot_mod.compute_pivot_world(arm, 'TIP')
                       - pivot_p).length
    # Radius of the drag point must not accumulate error across drags.
    radius_n = (pivot_mod.compute_pivot_world(arm, 'TIP')
                - pivot_p).length
    check("tip radius stable after 3 drags",
          abs(radius_n - radius0) <= 1e-4,
          "%.9f vs %.9f" % (radius_n, radius0))


def test_degenerate_errors(arm):
    section("Rotate: degenerate geometry refused with explicit error")
    try:
        rotate_mod.rotate_toward(arm, 'TIP', 'TIP',
                                 Vector((1, 2, 3)))
        check("drag==pivot refused", False, "no exception")
    except WeaponRigError as exc:
        check("drag==pivot refused",
              "coincide" in str(exc) or "undefined" in str(exc),
              str(exc))

    pivot_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    try:
        rotate_mod.rotate_toward(arm, 'POMMEL', 'TIP', pivot_p.copy())
        check("target==pivot refused", False, "no exception")
    except WeaponRigError as exc:
        check("target==pivot refused",
              "coincide" in str(exc) or "undefined" in str(exc),
              str(exc))
    # Failed attempt must not have corrupted the pose: pivot still there.
    check("pose intact after refusals",
          (pivot_mod.compute_pivot_world(arm, 'POMMEL')
           - pivot_p).length <= 1e-5, "pivot moved")


# =========================================================================
# Hands semantics
# =========================================================================

def test_hands_follow(arm):
    section("Rotate: attached hands follow rigidly, detached stay put")
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    # L deliberately detached.
    dg = transforms.evaluated_depsgraph()
    hand_l_before = transforms.get_pose_bone_world_matrix(
        arm, "c_hand_ik.l", dg).copy()

    pivot_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    target = pivot_p + Vector((0.0, 0.35, -0.2))
    res = rotate_mod.rotate_toward(arm, 'POMMEL', 'TIP', target)
    check("rotate with one hand attached succeeded", True,
          str(res))

    dg = transforms.evaluated_depsgraph()
    hand_l_now = transforms.get_pose_bone_world_matrix(
        arm, "c_hand_ik.l", dg)
    check("detached hand L did not move",
          (hand_l_now.translation - hand_l_before.translation).length
          <= 1e-4,
          "%.9f" % (hand_l_now.translation
                    - hand_l_before.translation).length)
    # Attached R: the core verified rigid follow internally (it rolls
    # back + raises otherwise) -- confirmed by test_hands_both_attached.


def test_hands_both_attached(arm):
    section("Rotate: both hands attached follow rigidly (verified core)")
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    con_util.attach_preserve_transform(arm, "L", frame=1, key=True)
    pivot_p = pivot_mod.compute_pivot_world(arm, 'GUARD_R')
    # The core itself raises if an attached hand deviates from the rigid
    # delta -- so reaching here without exception IS the assertion, plus
    # we check both hands actually rotated (delta not identity).
    dg = transforms.evaluated_depsgraph()
    hr_before = transforms.get_pose_bone_world_matrix(
        arm, "c_hand_ik.r", dg).translation.copy()
    target = pivot_p + Vector((0.2, 0.0, 0.35))
    res = rotate_mod.rotate_toward(arm, 'GUARD_R', 'GUARD_L', target)
    check("core verification passed (no rollback)",
          res["pivot_shift"] <= 1e-5, str(res))
    dg = transforms.evaluated_depsgraph()
    hr_now = transforms.get_pose_bone_world_matrix(
        arm, "c_hand_ik.r", dg).translation
    check("attached hand R actually rotated with weapon",
          (hr_now - hr_before).length > 1e-4,
          "moved %.6f" % (hr_now - hr_before).length)


# =========================================================================
# Keyframe policy
# =========================================================================

def test_key_policy(arm):
    section("Rotate: keyframe policy (plan §31)")
    scene = bpy.context.scene
    # Reset fcurves state by capturing count.
    def weapon_fcurves():
        ad = arm.animation_data
        if ad is None or ad.action is None:
            return []
        act = ad.action
        if hasattr(act, "layers") and act.layers:  # slotted actions
            fcs = []
            for layer in act.layers:
                for strip in layer.strips:
                    for cb in strip.channelbags:
                        fcs.extend(cb.fcurves)
            return fcs
        return list(act.fcurves)

    pivot_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    before_n = len([fc for fc in weapon_fcurves()
                    if 'weapon' in fc.data_path])

    scene.frame_set(7)
    res = rotate_mod.rotate_toward(
        arm, 'POMMEL', 'TIP',
        pivot_p + Vector((0.2, 0.2, -0.3)), key=True, frame=7)
    check("key=True reports keyed", res["keyed"])
    after_n = len([fc for fc in weapon_fcurves()
                   if 'weapon' in fc.data_path])
    check("weapon channels keyframed", after_n > before_n,
          "%d -> %d" % (before_n, after_n))
    keyed_at_7 = any(
        abs(k.co[0] - 7.0) < 1e-6
        for fc in weapon_fcurves() if 'weapon' in fc.data_path
        for k in fc.keyframe_points)
    check("keys landed on frame 7", keyed_at_7)
    scene.frame_set(1)


# =========================================================================
# Ray/plane math (modal target)
# =========================================================================

def test_ray_plane():
    section("Rotate: ray->plane target math (modal glue)")
    hit = rotate_mod.ray_plane_target(
        Vector((1, 2, 5)), Vector((0, 0, -1)),
        Vector((0, 0, 0)), Vector((0, 0, 1)))
    check("straight-down ray hits plane",
          hit is not None and (hit - Vector((1, 2, 0))).length < 1e-9,
          str(hit))
    back = rotate_mod.ray_plane_target(
        Vector((0, 0, -5)), Vector((0, 0, -1)),
        Vector((0, 0, 0)), Vector((0, 0, 1)))
    check("ray away from plane -> None", back is None, str(back))
    parallel = rotate_mod.ray_plane_target(
        Vector((0, 0, 5)), Vector((1, 0, 0)),
        Vector((0, 0, 0)), Vector((0, 0, 1)))
    check("parallel ray -> None", parallel is None, str(parallel))
    oblique = rotate_mod.ray_plane_target(
        Vector((0, 0, 10)), Vector((1, 0, -1)).normalized(),
        Vector((0, 0, 0)), Vector((0, 0, 1)))
    check("oblique ray lands on plane",
          oblique is not None and abs(oblique.z) < 1e-9,
          str(oblique))


# =========================================================================
# Operator surface
# =========================================================================

def test_operator_surface():
    section("Rotate: operator surface (enums, execute, poll)")
    # 1. Pivot enum parity: panel passes scene.wpn_pivot straight into
    #    op.pivot -- every scene value must be accepted.
    #    (Operator RNA lives on get_rna_type(), NOT on bpy.types class
    #    bl_rna -- probe-verified for registered Python operators.)
    rna_op = bpy.ops.wpn.rotate_to_cursor.get_rna_type()
    items = tuple(i.identifier
                  for i in rna_op.properties['pivot'].enum_items)
    expected = tuple(i[0] for i in pivot_mod.PIVOT_ITEMS)
    check("op pivot enum == PIVOT_ITEMS", items == expected,
          "%s vs %s" % (items, expected))
    rna_modal = bpy.ops.wpn.rotate_drag.get_rna_type()
    items2 = tuple(i.identifier
                   for i in rna_modal.properties['pivot'].enum_items)
    check("modal op pivot enum == PIVOT_ITEMS", items2 == expected,
          "%s vs %s" % (items2, expected))

    # 2. Drag enum == scene.wpn_drag values.
    scene_drag = tuple(
        i.identifier
        for i in bpy.context.scene.bl_rna.properties[
            'wpn_drag'].enum_items)
    op_drag = tuple(i.identifier
                    for i in rna_op.properties['drag'].enum_items)
    check("op drag enum == scene.wpn_drag", scene_drag == op_drag,
          "%s vs %s" % (scene_drag, op_drag))
    check("drag enum covers all config points",
          set(op_drag) == set(DRAG_POINTS), str(op_drag))

    # 3. One-shot execute on a rig-less scene: CANCELLED (or RuntimeError
    #    re-raised by bpy.ops in 5.2) -- never a crash.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    outcome = None
    try:
        outcome = bpy.ops.wpn.rotate_to_cursor(pivot='POMMEL',
                                               drag='TIP')
    except RuntimeError as exc:
        outcome = "RuntimeError: %s" % exc
    check("no-rig execute refused",
          outcome == {'CANCELLED'}
          or (isinstance(outcome, str)
              and outcome.startswith("RuntimeError")),
          str(outcome))

    # 4. Modal poll refuses headless cleanly (background has no VIEW_3D).
    check("modal poll refuses headless",
          not bpy.types.WPN_OT_rotate_drag.poll(bpy.context),
          "poll returned True headless")


def test_operator_execute(arm):
    section("Rotate: rotate_to_cursor executes end-to-end")
    scene = bpy.context.scene
    pivot_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    scene.cursor.location = pivot_p + Vector((0.25, 0.1, 0.3))
    res = bpy.ops.wpn.rotate_to_cursor(pivot='POMMEL', drag='TIP')
    check("operator finished", res == {'FINISHED'}, str(res))
    tip_now = pivot_mod.compute_pivot_world(arm, 'TIP')
    want = (scene.cursor.location - pivot_p).normalized()
    got = (tip_now - pivot_p).normalized()
    ang = math.degrees(got.angle(want))
    check("tip aims at cursor via operator", ang <= 0.5,
          "%.4f deg" % ang)


def test_exact_antiparallel(arm):
    section("Rotate: exactly anti-parallel target (180 deg degenerate)")
    # mathutils.rotation_difference picks an unstable axis here (measured
    # 0.78 deg) -- _align_rotation must land dead-on.
    pivot_p = pivot_mod.compute_pivot_world(arm, 'GRIP_L')
    drag_p = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    target = pivot_p - (drag_p - pivot_p)  # exactly opposite direction
    res = rotate_mod.rotate_toward(arm, 'GRIP_L', 'POMMEL', target)
    check("180-deg rotate lands precisely",
          res["angle_error_deg"] <= 0.1,
          "%.6f deg" % res["angle_error_deg"])
    check("pivot locked in 180-deg case",
          res["pivot_shift"] <= 1e-5, "%.9f" % res["pivot_shift"])
    # Repeat twice more (roundtrip must stay stable, no drift).
    for i in range(2):
        res = rotate_mod.rotate_toward(arm, 'GRIP_L', 'POMMEL', target)
        check("180-deg repeat %d precise" % i,
              res["angle_error_deg"] <= 0.1,
              "%.6f deg" % res["angle_error_deg"])


def test_handle_mode():
    section("Rotate: Empty handle (create, live follow, pivot choice)")
    arm = build_rig()
    scene = bpy.context.scene

    # --- create: placed exactly on the drag point, no jump ------------
    w0 = transforms.get_pose_bone_world_matrix(arm, "weapon").copy()
    obj = rotate_mod.create_handle(arm, 'POMMEL', 'TIP')
    check("handle created",
          obj is not None and obj.name in bpy.data.objects)
    check("scene pointer set", scene.wpn_rot_handle == obj.name)
    drag_w = pivot_mod.compute_pivot_world(arm, 'TIP')
    check("handle sits on drag point",
          (obj.matrix_world.translation - drag_w).length <= 1e-5,
          "%.9f" % (obj.matrix_world.translation - drag_w).length)
    t, _r = transforms.matrix_difference(
        w0, transforms.get_pose_bone_world_matrix(arm, "weapon"))
    check("creating handle causes no jump", t <= 1e-5, "%.9f" % t)
    check("live-follow handler installed",
          rotate_mod._on_depsgraph_update
          in bpy.app.handlers.depsgraph_update_post)

    # --- user's bug: pivot must be CHOOSABLE (not always pommel) ------
    scene.wpn_pivot = 'GUARD_R'   # what the user selects in the dropdown
    scene.wpn_drag = 'TIP'
    obj = rotate_mod.create_handle(arm, 'GUARD_R', 'TIP')  # re-place
    pp = pivot_mod.compute_pivot_world(arm, 'GUARD_R')
    target = pp + Vector((0.2, 0.3, 0.15))
    obj.matrix_world = Matrix.Translation(target)
    res = rotate_mod.apply_handle(arm, scene)
    check("handle aims with scene pivot", res["angle_error_deg"] <= 0.5,
          "%.5f deg" % res["angle_error_deg"])
    pp_now = pivot_mod.compute_pivot_world(arm, 'GUARD_R')
    check("selected pivot GUARD_R locked",
          (pp_now - pp).length <= 1e-4,
          "%.9f" % (pp_now - pp).length)
    tip = pivot_mod.compute_pivot_world(arm, 'TIP')
    ang = math.degrees((tip - pp_now).normalized().angle(
        (target - pp).normalized()))
    check("tip aims at handle from GUARD_R", ang <= 0.5,
          "%.4f deg" % ang)

    # --- LIVE follow: no button, moving the Empty rotates the weapon --
    scene.wpn_pivot = 'POMMEL'
    scene.wpn_drag = 'TIP'
    obj = rotate_mod.create_handle(arm, 'POMMEL', 'TIP')
    pp = pivot_mod.compute_pivot_world(arm, 'POMMEL')
    target = pp + Vector((0.0, 0.4, -0.25))
    obj.matrix_world = Matrix.Translation(target)
    transforms.update_view_layer()   # depsgraph update -> handler fires
    tip_now = pivot_mod.compute_pivot_world(arm, 'TIP')
    live_ang = math.degrees((tip_now - pp).normalized().angle(
        (target - pp).normalized()))
    check("depsgraph handler follows live (no button press)",
          live_ang <= 0.5, "%.4f deg" % live_ang)

    # --- degenerate: handle moved onto the pivot -> graceful refusal --
    w_before = transforms.get_pose_bone_world_matrix(
        arm, "weapon").copy()
    obj.matrix_world = Matrix.Translation(pp)
    try:
        rotate_mod.apply_handle(arm, scene)
        check("handle-on-pivot refused", False, "no exception")
    except WeaponRigError as exc:
        check("handle-on-pivot refused",
              "coincide" in str(exc) or "undefined" in str(exc),
              str(exc))
    t, _r = transforms.matrix_difference(
        w_before, transforms.get_pose_bone_world_matrix(arm, "weapon"))
    check("pose intact after refusal", t <= 1e-5, "%.9f" % t)
    # recovery: move away -> works again (error state not sticky)
    obj.matrix_world = Matrix.Translation(pp + Vector((0.3, 0.1, 0.2)))
    res = rotate_mod.apply_handle(arm, scene)
    check("recovers after degenerate target",
          res["angle_error_deg"] <= 0.5,
          "%.5f deg" % res["angle_error_deg"])

    # --- animated handle: keying the Empty animates the weapon --------
    # (keys first, THEN change frames -- frame_change_post drives the
    # sync, which is exactly the user's scrub/playback workflow)
    scene.frame_set(1)
    obj.keyframe_insert("location", frame=1)
    obj.location = pp + Vector((-0.2, 0.1, 0.45))
    obj.keyframe_insert("location", frame=30)
    scene.frame_set(30)   # 1 -> 30: frame_change_post fires -> sync
    tip_f30 = pivot_mod.compute_pivot_world(arm, 'TIP')
    want30 = (obj.matrix_world.translation - pp).normalized()
    f30_ang = math.degrees((tip_f30 - pp).normalized().angle(want30))
    check("animated handle drives weapon at f30", f30_ang <= 0.5,
          "%.4f deg" % f30_ang)
    scene.frame_set(1)    # 30 -> 1: sync back
    tip_f1 = pivot_mod.compute_pivot_world(arm, 'TIP')
    want1 = (obj.matrix_world.translation - pp).normalized()
    f1_ang = math.degrees((tip_f1 - pp).normalized().angle(want1))
    check("animated handle drives weapon at f1", f1_ang <= 0.5,
          "%.4f deg" % f1_ang)

    # --- operators -----------------------------------------------------
    res = bpy.ops.wpn.handle_create()
    check("handle_create operator", res == {'FINISHED'}, str(res))
    check("handle exists after op",
          rotate_mod.handle_object(scene) is not None)
    res = bpy.ops.wpn.handle_remove()
    check("handle_remove operator", res == {'FINISHED'}, str(res))
    check("handle gone after remove",
          rotate_mod.handle_object(scene) is None
          and rotate_mod.HANDLE_NAME not in bpy.data.objects)
    check("scene pointer cleared", scene.wpn_rot_handle == "")


def main():
    print("=" * 70)
    print("MILESTONE 8 TEST SUITE: INTERACTIVE ROTATE (pivot+drag)")
    print("=" * 70)

    arm = build_rig()
    test_rotate_basic(arm)
    test_pure_rotation(arm)
    test_pivot_drag_grid(arm)
    test_sequential_interaction(arm)
    test_degenerate_errors(arm)
    test_exact_antiparallel(arm)
    test_hands_follow(arm)

    arm2 = build_rig()
    test_hands_both_attached(arm2)
    test_key_policy(arm2)
    test_operator_execute(arm2)

    test_ray_plane()
    test_handle_mode()
    test_operator_surface()

    summary()


main()
