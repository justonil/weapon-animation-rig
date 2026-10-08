"""Headless test suite: Milestone 3 (pivot, plan §50) and
Milestone 4 (aim, plan §51).

Run:
    blender -b --factory-startup --python tests/run_milestone34_tests.py

Covers plan §53 Tests G (pivot tip) and §51 (aim: sword points toward
target, roll controllable, moving target works), plus §21-24 pivot presets
and repeated pivot switching without corruption (plan §22).
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
    TOL_TRANSLATION,
    WeaponRigError,
)
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402
from weapon_animation_rig.weapon import pivot  # noqa: E402
from weapon_animation_rig.weapon import aim  # noqa: E402


def world(arm, name):
    return transforms.get_pose_bone_world_matrix(arm, name)


# =========================================================================
# Milestone 3 -- Pivot (plan §21-24, §50; Test G)
# =========================================================================

def build_rig():
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.wpn_armature = arm
    return arm


def grip_pos(arm, side):
    """Grip reference world position (rework: prop, not bone)."""
    from weapon_animation_rig.utils import constraints as con_util
    return con_util.grip_world(arm, side).translation.copy()


def tip_pos(arm):
    from weapon_animation_rig.utils import constraints as con_util
    return con_util.tip_world(arm).translation.copy()


def make_preview_mesh(name="SwordPreview"):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (2.0, 1.0, 3.0)
    transforms.update_view_layer()
    return obj


def test_pivot_presets(arm):
    section("Pivot presets resolve (plan §21)")
    scene = bpy.context.scene
    scene.frame_current = 1

    tip = tip_pos(arm)
    gr = grip_pos(arm, "R")
    gl = grip_pos(arm, "L")
    wbone = arm.data.bones["weapon"]
    from mathutils import Vector as _V
    mw = arm.matrix_world
    wmat = (mw @ arm.pose.bones["weapon"].matrix).copy()

    def prop_world(prop):
        return (wmat @ _V(tuple(wbone[prop])))

    res = {}
    for preset in ('CENTER', 'GRIP_R', 'GRIP_L', 'GUARD', 'TIP', 'POMMEL'):
        res[preset] = pivot.compute_pivot_world(arm, preset)
    check("preset GRIP_R == grip_r head", (res['GRIP_R'] - gr).length
          <= TOL_TRANSLATION, str(res['GRIP_R']))
    check("preset GRIP_L == grip_l head", (res['GRIP_L'] - gl).length
          <= TOL_TRANSLATION, str(res['GRIP_L']))
    check("preset TIP == tip head", (res['TIP'] - tip).length
          <= TOL_TRANSLATION, str(res['TIP']))
    # GUARD = midpoint of the two configured quillon ends (explicit
    # config now, not a mirror -- plan user request).
    want_guard = (prop_world("guard_l") + prop_world("guard_r")) * 0.5
    check("preset GUARD == quillon midpoint",
          (res['GUARD'] - want_guard).length <= TOL_TRANSLATION)
    # POMMEL / CENTER come straight from config.
    check("preset POMMEL == pommel point",
          (res['POMMEL'] - prop_world("pommel")).length <= TOL_TRANSLATION)
    check("preset CENTER == center point",
          (res['CENTER'] - prop_world("center")).length <= TOL_TRANSLATION)
    # GUARD_L / GUARD_R resolve to the individual quillon ends (their
    # own pivot buttons).
    for preset, prop in (("GUARD_L", "guard_l"),
                         ("GUARD_R", "guard_r")):
        want = prop_world(prop)
        got = pivot.compute_pivot_world(arm, preset)
        check("preset %s == quillon end" % preset,
              (got - want).length <= TOL_TRANSLATION)
    old_guard_l = tuple(wbone["guard_l"])
    wbone["guard_l"] = (-0.30, 0.22, 0.05)
    transforms.update_view_layer()
    moved = pivot.compute_pivot_world(arm, 'GUARD')
    check("GUARD follows guard_l config",
          (moved - (prop_world("guard_l") + prop_world("guard_r"))
           * 0.5).length <= TOL_TRANSLATION)
    wbone["guard_l"] = old_guard_l
    transforms.update_view_layer()

    # 3D cursor (plan §24).
    scene.cursor.location = (9.0, -8.0, 7.0)
    c = pivot.compute_pivot_world(arm, 'CURSOR')
    check("preset CURSOR == scene cursor",
          (c - Vector((9.0, -8.0, 7.0))).length <= TOL_TRANSLATION)

    # Custom value passes through.
    custom = pivot.compute_pivot_world(arm, 'CUSTOM',
                                       custom=(1.1, 2.2, 3.3))
    check("preset CUSTOM passthrough",
          (custom - Vector((1.1, 2.2, 3.3))).length <= 1e-9)


def test_set_pivot_tip(arm):
    section("Test G: pivot -> tip, rotate around tip (plan §53 G, §21)")
    scene = bpy.context.scene
    scene.frame_current = 5

    # Attach both hands + assign a preview mesh: NEITHER may move when
    # the pivot relocates (rework: inverse re-solve + mesh restore).
    from weapon_animation_rig.utils import constraints as con_util
    from weapon_animation_rig.weapon import preview as preview_mod
    con_util.attach_preserve_transform(arm, "R", frame=5, key=True)
    con_util.attach_preserve_transform(arm, "L", frame=5, key=True)
    mesh = make_preview_mesh()
    preview_mod.set_preview_mesh(arm, mesh)

    hands_before = {s: world(arm, "c_hand_ik." + s.lower())
                    for s in ("R", "L")}
    mesh_before = mesh.matrix_world.copy()
    tip_target = tip_pos(arm)

    try:
        pivot.set_pivot(arm, 'TIP', key=False)
        check("set_pivot TIP runs", True)
    except WeaponRigError as exc:
        check("set_pivot TIP runs", False, str(exc))
        return

    # Weapon head now sits at the tip (plan §22 step 3).
    head = world(arm, "weapon").translation
    check("weapon head moved onto tip",
          (head - tip_target).length <= TOL_TRANSLATION,
          "off by %.6f" % (head - tip_target).length)

    # Attached hands + preview must not jump (plan §22 step 5, §30).
    worst = 0.0
    for s in ("R", "L"):
        t, _ = transforms.matrix_difference(
            hands_before[s], world(arm, "c_hand_ik." + s.lower()))
        worst = max(worst, t)
    t, _ = transforms.matrix_difference(mesh_before,
                                        mesh.matrix_world.copy())
    worst = max(worst, t)
    check("hands + preview preserved by set_pivot",
          worst <= TOL_TRANSLATION, "worst jump %.6f" % worst)

    # Rotate weapon about its own head (= tip): the TIP must stay
    # fixed while the blade swings. Mimics an R-key rotation about the
    # bone's own origin in armature space.
    transforms.update_view_layer()
    root_arm = transforms.get_pose_bone_arm_matrix(arm, "weapon")
    # Rotate in armature space about the pivot (the bone's own origin -
    # exactly what Blender's R-key does for a single selected pose bone).
    pivot_arm = arm.matrix_world.inverted() @ head
    rot = Matrix.Rotation(0.6, 4, 'X') @ Matrix.Rotation(0.4, 4, 'Z')
    t_to = Matrix.Translation(Vector((pivot_arm.x, pivot_arm.y, pivot_arm.z)))
    t_back = Matrix.Translation(Vector((-pivot_arm.x, -pivot_arm.y,
                                        -pivot_arm.z)))
    new_arm = t_to @ rot @ t_back @ root_arm
    transforms.set_pose_bone_arm_matrix(arm, "weapon", new_arm)
    transforms.update_view_layer()

    tip_now = tip_pos(arm)
    check("tip stays fixed under rotation about tip",
          (tip_now - tip_target).length <= 2e-4,
          "moved %.6f" % (tip_now - tip_target).length)
    grip_now = grip_pos(arm, "R")
    swing = (grip_now - tip_target).length
    check("grip swings around tip (weapon rotated)", swing > 1e-3,
          "swing=%.6f" % swing)
    # Attached hands follow the rotation (they are glued to the weapon).
    hand_now = world(arm, "c_hand_ik.r").translation
    check("attached hand follows pivot rotation",
          (hand_now - hands_before["R"].translation).length > 1e-3)
    con_util.detach_preserve_transform(arm, "R", frame=5, key=True)
    con_util.detach_preserve_transform(arm, "L", frame=5, key=True)
    preview_mod.clear_preview_mesh(arm)
    bpy.data.objects.remove(mesh, do_unlink=True)


def test_pivot_switching_no_corruption(arm):
    section("Pivot switching across frames (plan §22)")
    scene = bpy.context.scene
    from weapon_animation_rig.utils import constraints as con_util
    from weapon_animation_rig.weapon import preview as preview_mod
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    con_util.attach_preserve_transform(arm, "L", frame=1, key=True)
    mesh = make_preview_mesh("SwordPreview2")
    preview_mod.set_preview_mesh(arm, mesh)

    def watched_worlds():
        out = {("hand", s): world(arm, "c_hand_ik." + s.lower())
               for s in ("R", "L")}
        out[("mesh",)] = mesh.matrix_world.copy()
        out[("tip",)] = tip_pos(arm)
        return out

    def same_as(before):
        current = watched_worlds()
        for key, mat in before.items():
            if key[0] == "mesh":
                t, _ = transforms.matrix_difference(mat, current[key])
            elif key[0] == "tip":
                t = (mat - current[key]).length
            else:
                t, _ = transforms.matrix_difference(mat, current[key])
            if t > TOL_TRANSLATION:
                return False
        return True

    # Frame 1: pivot to tip; frame 20: pivot to 3D cursor; frame 30: custom.
    scene.frame_current = 1
    before = watched_worlds()
    pivot.set_pivot(arm, 'TIP', key=False)
    check("frame 1 -> TIP: no jump", same_as(before))

    scene.cursor.location = (4.0, 1.0, 0.5)
    scene.frame_current = 20
    before = watched_worlds()
    pivot.set_pivot(arm, 'CURSOR', key=False)
    check("frame 20 -> CURSOR: no jump", same_as(before))
    head = world(arm, "weapon").translation
    check("frame 20 -> CURSOR: root on cursor",
          (head - Vector((4.0, 1.0, 0.5))).length <= TOL_TRANSLATION)

    scene.frame_current = 30
    before = watched_worlds()
    pivot.set_pivot(arm, 'CUSTOM', custom=(0.5, -0.5, 2.5), key=False)
    check("frame 30 -> CUSTOM: no jump", same_as(before))

    # Guard L end-to-end: root lands on the quillon end, nothing jumps.
    scene.frame_current = 35
    before = watched_worlds()
    pivot.set_pivot(arm, 'GUARD_L', key=False)
    check("frame 35 -> GUARD_L: no jump", same_as(before))
    head = world(arm, "weapon").translation
    want_gl = pivot.compute_pivot_world(arm, 'GUARD_L')
    check("frame 35 -> GUARD_L: root on quillon end",
          (head - want_gl).length <= TOL_TRANSLATION)

    # Back to center: still no jump.
    scene.frame_current = 40
    before = watched_worlds()
    pivot.set_pivot(arm, 'CENTER', key=False)
    check("pivot switching never corrupts transform", same_as(before))

    con_util.detach_preserve_transform(arm, "R", frame=40, key=True)
    con_util.detach_preserve_transform(arm, "L", frame=40, key=True)
    preview_mod.clear_preview_mesh(arm)
    bpy.data.objects.remove(mesh, do_unlink=True)


def test_pivot_operator_and_keys(arm):
    section("Pivot operator + key policy (plan §31)")
    scene = bpy.context.scene
    scene.frame_current = 50
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    res = bpy.ops.wpn.select_pivot(pivot='TIP')
    check("select_pivot runs", res == {'FINISHED'}, str(res))
    check("select_pivot sets scene enum", scene.wpn_pivot == 'TIP')

    res = bpy.ops.wpn.set_pivot(pivot='TIP', key=False)
    check("set_pivot op runs", res == {'FINISHED'}, str(res))

    # Key policy: no weapon fcurves from key=False.
    from weapon_animation_rig.animation import keyframes
    has_keys = any(
        keyframes.find_fcurve(
            arm, 'pose.bones["weapon"].%s' % ch) is not None
        for ch in ("location", "rotation_quaternion", "scale"))
    check("set_pivot creates no keys with key=False", not has_keys)

    # key=True keys the changed channels (with guard at frame-1).
    bpy.ops.wpn.set_pivot(pivot='POMMEL', key=True)
    fc = keyframes.find_fcurve(arm, 'pose.bones["weapon"].location')
    check("set_pivot key=True keys weapon location",
          fc is not None and any(abs(k.co[0] - 50) < 1e-6
                                 for k in fc.keyframe_points))


def test_pivot_preserves_animation(arm):
    section("Set Pivot preserves existing animation (pivot must not break keyed motion)")
    from weapon_animation_rig.utils import constraints as con_util
    scene = bpy.context.scene
    weapon = con_util.get_weapon_bone(arm)
    pb = arm.pose.bones[weapon]
    loc_path = 'pose.bones["%s"].location' % weapon

    # Animate like a real idle: distinct locations at frames 1 and 10.
    scene.frame_set(1)
    pb.location = (0.0, 0.0, 0.0)
    transforms.update_view_layer()
    if not arm.keyframe_insert(loc_path, frame=1):
        check("location keys inserted", False, "frame 1 insert failed")
        return
    scene.frame_set(10)
    pb.location = (0.5, -0.2, 0.3)
    transforms.update_view_layer()
    if not arm.keyframe_insert(loc_path, frame=10):
        check("location keys inserted", False, "frame 10 insert failed")
        return
    check("location keys inserted", True)

    # Plus a real swing: rotation keys so the blade orbits (the reported
    # breakage was old rotation keys swinging around the NEW origin
    # instead of preserving their world motion).
    mode = pb.rotation_mode
    if mode == 'QUATERNION':
        rot_path = 'pose.bones["%s"].rotation_quaternion' % weapon
        r1 = (1.0, 0.0, 0.0, 0.0)
        _n = math.sqrt(0.9 * 0.9 + 0.435 * 0.435 + 0.1 * 0.1)
        r10 = (0.9 / _n, 0.0, 0.435 / _n, 0.1 / _n)
    elif mode == 'AXIS_ANGLE':
        rot_path = 'pose.bones["%s"].rotation_axis_angle' % weapon
        r1, r10 = (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 1.0, 0.9)
    else:
        rot_path = 'pose.bones["%s"].rotation_euler' % weapon
        r1, r10 = (0.0, 0.0, 0.0), (0.0, 0.9, 0.2)
    scene.frame_set(1)
    if mode == 'QUATERNION':
        pb.rotation_quaternion = r1
    elif mode == 'AXIS_ANGLE':
        pb.rotation_axis_angle = r1
    else:
        pb.rotation_euler = r1
    transforms.update_view_layer()
    if not arm.keyframe_insert(rot_path, frame=1):
        check("rotation keys inserted", False, "frame 1 insert failed")
        return
    scene.frame_set(10)
    if mode == 'QUATERNION':
        pb.rotation_quaternion = r10
    elif mode == 'AXIS_ANGLE':
        pb.rotation_axis_angle = r10
    else:
        pb.rotation_euler = r10
    transforms.update_view_layer()
    if not arm.keyframe_insert(rot_path, frame=10):
        check("rotation keys inserted", False, "frame 10 insert failed")
        return
    check("rotation keys inserted", True)

    def geom_at(f):
        # Weapon GEOMETRY (what the eye sees): tip + grip worlds. The bone
        # head relocates to the pivot BY DESIGN, so comparing bone worlds
        # would always differ -- geometry must stay frozen instead.
        scene.frame_set(f)
        transforms.update_view_layer()
        return (tip_pos(arm), grip_pos(arm, "R"))

    before = {f: geom_at(f) for f in (1, 5, 10)}

    # Set Pivot BETWEEN keyed frames (the exact reported breakage).
    scene.frame_set(5)
    transforms.update_view_layer()
    try:
        res = pivot.set_pivot(arm, 'CENTER')
    except WeaponRigError as exc:
        check("set pivot with animation succeeds", False, str(exc))
        return
    check("set pivot reports shifted location keys",
          res.get("shifted_keys", 0) > 0, str(res))

    # World-space GEOMETRY identical at keyed AND in-between frames.
    ok, detail = True, ""
    for f in (1, 5, 10):
        tip0, grp0 = before[f]
        tip1, grp1 = geom_at(f)
        for label, a, b in (("tip", tip0, tip1), ("grip", grp0, grp1)):
            d = (a - b).length
            if d > TOL_TRANSLATION:
                ok = False
                detail += "f%d %s d=%.5f; " % (f, label, d)
    check("weapon world animation preserved across Set Pivot", ok, detail)
    scene.frame_set(5)
    transforms.update_view_layer()


def test_pivot_on_scaled_rig(arm):
    section("Set Pivot converges on scaled rigs (setter imprecision)")
    scene = bpy.context.scene
    # Non-uniform object scale amplifies setter float error, like real
    # production rigs with unit conversions (user's CENTER miss was 0.007).
    # The convergence loop must land the head exactly instead of raising.
    prev_scale = tuple(arm.scale)
    arm.scale = (1.0, 1.0, 2.5)
    transforms.update_view_layer()
    try:
        scene.frame_set(1)
        transforms.update_view_layer()
        tip0, grp0 = tip_pos(arm), grip_pos(arm, "R")
        try:
            pivot.set_pivot(arm, 'CENTER')
        except WeaponRigError as exc:
            check("set pivot succeeds on scaled rig", False, str(exc))
            return
        check("set pivot succeeds on scaled rig", True)
        tip1, grp1 = tip_pos(arm), grip_pos(arm, "R")
        dt, dg = (tip1 - tip0).length, (grp1 - grp0).length
        check("geometry frozen on scaled rig",
              dt <= TOL_TRANSLATION and dg <= TOL_TRANSLATION,
              "tip d=%.5f grip d=%.5f" % (dt, dg))
    finally:
        arm.scale = prev_scale
        transforms.update_view_layer()


def test_focus_point(arm):
    section("Focus 3D cursor + orientation on weapon points")
    from weapon_animation_rig.constants import WeaponRigError as _WRE
    from weapon_animation_rig.weapon import focus as focus_mod
    from weapon_animation_rig.weapon import pivot as pivot_mod
    scene = bpy.context.scene
    prev_cursor = scene.cursor.location.copy()
    prev_pivot = scene.tool_settings.transform_pivot_point
    prev_orient = scene.transform_orientation_slots[0].type
    try:
        for preset in ('GRIP_L', 'GRIP_R', 'TIP', 'CENTER', 'GUARD'):
            res = focus_mod.focus_on_point(arm, preset)
            want = pivot_mod.compute_pivot_world(arm, preset)
            got = scene.cursor.location
            check("focus %s moves 3D cursor" % preset,
                  (got - want).length <= TOL_TRANSLATION,
                  "d=%.5f" % (got - want).length)
            check("focus %s returns point" % preset,
                  (res["point"] - want).length <= TOL_TRANSLATION)
        check("focus sets pivot to 3D Cursor",
              scene.tool_settings.transform_pivot_point == 'CURSOR',
              scene.tool_settings.transform_pivot_point)
        check("focus sets Normal orientation",
              scene.transform_orientation_slots[0].type == 'NORMAL',
              scene.transform_orientation_slots[0].type)
        try:
            focus_mod.focus_on_point(arm, 'NOPE')
            check("focus unknown preset raises", False, "no exception")
        except _WRE:
            check("focus unknown preset raises", True)
        # Operator: stores preset AND focuses (headless -> Normal fallback
        # because create_orientation needs a 3D view).
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        res = bpy.ops.wpn.select_pivot(pivot='GRIP_L')
        check("select_pivot runs with focus", res == {'FINISHED'},
              str(res))
        check("select_pivot stores preset", scene.wpn_pivot == 'GRIP_L')
        want = pivot_mod.compute_pivot_world(arm, 'GRIP_L')
        check("select_pivot moves cursor to Grip L",
              (scene.cursor.location - want).length <= TOL_TRANSLATION)
        check("select_pivot fallback orientation sane",
              scene.transform_orientation_slots[0].type in (
                  'NORMAL', focus_mod.WEAPON_ORIENTATION_NAME),
              scene.transform_orientation_slots[0].type)
    finally:
        scene.cursor.location = prev_cursor
        try:
            scene.tool_settings.transform_pivot_point = prev_pivot
        except Exception:
            pass
        try:
            scene.transform_orientation_slots[0].type = prev_orient
        except Exception:
            pass


def test_weapon_orientation_operator(arm):
    section("Create Orientation from Weapon operator")
    from weapon_animation_rig.constants import WeaponRigError as _WRE
    from weapon_animation_rig.weapon import focus as focus_mod
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    try:
        res = bpy.ops.wpn.create_weapon_orientation()
    except RuntimeError as exc:
        # Blender 5.2 re-raises ERROR+CANCELLED as RuntimeError -- this
        # IS the graceful cancel path, carrying the reason.
        res = {'CANCELLED'}
        check("cancel reason mentions orientation",
              "Orientation" in str(exc), str(exc)[:160])
    # Background Blender has no 3D view, so create_orientation cannot
    # poll -- the operator must cancel gracefully with a reason, never
    # crash, and restore mode/selection.
    check("orientation op cancels gracefully headless",
          res == {'CANCELLED'}, str(res))
    check("mode restored to OBJECT",
          bpy.context.object is not None
          and bpy.context.object.mode == 'OBJECT',
          str(getattr(bpy.context.object, 'mode', None)))
    check("armature still active",
          bpy.context.view_layer.objects.active is arm)
    # Bone selection must be restored too: the helper selects the weapon
    # bone internally, the user's hand bone must be back afterwards.
    hand = arm.pose.bones["c_hand_ik.r"]
    hand.select = True
    arm.data.bones.active = arm.data.bones.get("c_hand_ik.r")
    try:
        focus_mod.ensure_weapon_orientation(bpy.context, arm)
    except _WRE:
        pass
    check("hand bone selection restored",
          hand.select
          and not arm.pose.bones["weapon"].select,
          "hand=%s weapon=%s" % (hand.select,
                                   arm.pose.bones["weapon"].select))
    active_bone = arm.data.bones.active
    check("active bone restored",
          active_bone is not None and active_bone.name == "c_hand_ik.r",
          str(getattr(active_bone, 'name', None)))
    try:
        focus_mod.ensure_weapon_orientation(bpy.context, arm)
        check("helper raises headless", False, "no exception")
    except _WRE as exc:
        check("helper explains background limitation",
              "Viewport" in str(exc), str(exc)[:160])


# =========================================================================
# Milestone 4 -- Aim (plan §25-27, §51)
# =========================================================================

def build_aim_rig():
    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.wpn_armature = arm
    return arm


def test_aim_bone_present(arm):
    section("weapon_aim bone role + parenting (plan §5)")
    check("weapon_aim created",
          "weapon_aim" in arm.data.bones)
    aim_bone = arm.data.bones.get("weapon_aim")
    if aim_bone is None:
        return
    parent = aim_bone.parent.name if aim_bone.parent else None
    check("weapon_aim parented to root (independent target)",
          parent == "root",
          "parent=%s (documented deviation from §62 diagram: avoids "
          "an aim->weapon->aim evaluation cycle)" % parent)
    check("weapon_aim carries system metadata",
          arm.data.bones["weapon_aim"].get("weapon_rig_system")
          == "weapon_animation_rig")


def test_blade_axis_config(arm):
    section("Blade axis config (plan §47)")
    tag = arm.data.bones["weapon"].get("blade_axis")
    check("blade_axis default is +Y", tag == "+Y", "got %r" % tag)
    axis, track = aim.get_blade_axis(arm)
    check("blade axis vector is +Y",
          (axis - Vector((0, 1, 0))).length < 1e-9)
    check("track axis maps to TRACK_Y", track == 'TRACK_Y')
    try:
        aim.set_blade_axis(arm, "bogus")
        check("invalid blade axis refused", False, "no exception")
    except WeaponRigError:
        check("invalid blade axis refused", True)
    aim.set_blade_axis(arm, "-Z")
    check("blade axis round-trips",
          arm.data.bones["weapon"]["blade_axis"] == "-Z")
    aim.set_blade_axis(arm, "+Y")


def test_point_blade_at(arm):
    section("Point Blade At (plan §26, §51)")
    scene = bpy.context.scene
    scene.frame_current = 10

    # Place the aim target off to the side in world space.
    pa = arm.pose.bones["weapon_aim"]
    mw_inv = arm.matrix_world.inverted()
    pa.matrix = mw_inv @ Matrix.Translation(Vector((5.0, 1.0, 3.0)))
    transforms.update_view_layer()

    root_before = world(arm, "weapon")
    try:
        result = aim.point_blade_at(arm, roll_degrees=0.0, key=False)
        check("point_blade_at runs", True)
    except WeaponRigError as exc:
        check("point_blade_at runs", False, str(exc))
        return

    check("aim error small (plan §51: sword points at target)",
          result["angle_error_deg"] <= 0.5,
          "off %.4f deg" % result["angle_error_deg"])

    # Position untouched (§26: orientation only).
    trans, _ = transforms.matrix_difference(
        Matrix.Translation(root_before.translation),
        Matrix.Translation(world(arm, "weapon").translation))
    check("point_blade_at preserves position", trans <= TOL_TRANSLATION,
          "moved %.6f" % trans)

    # Manual direction check: blade dir vs (aim - root).
    blade_world = (world(arm, "weapon").to_3x3()
                   @ Vector((0, 1, 0))).normalized()
    want = ((world(arm, "weapon_aim").translation
             - world(arm, "weapon").translation).normalized())
    check("blade parallel to aim direction",
          (blade_world - want).length <= 1e-3,
          "d=%.8f" % (blade_world - want).length)


def test_aim_weapon_and_roll(arm):
    section("Aim Weapon + Roll (plan §25, §27, §51)")
    scene = bpy.context.scene
    scene.frame_current = 20

    pa = arm.pose.bones["weapon_aim"]
    pa.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((-4.0, 3.0, 2.5)))
    transforms.update_view_layer()

    try:
        result = aim.aim_weapon(arm, roll_degrees=45.0, key=False)
        check("aim_weapon runs", True)
    except WeaponRigError as exc:
        check("aim_weapon runs", False, str(exc))
        return

    con = arm.pose.bones["weapon"].constraints.get("WPN_Aim")
    check("WPN_Aim damped track created",
          con is not None and con.type == 'DAMPED_TRACK')
    check("aim influence is 1", con is not None and con.influence == 1.0)
    check("aim error small", result["angle_error_deg"] <= 0.5,
          "off %.4f deg" % result["angle_error_deg"])

    # Moving the target re-points (live, plan §51).
    pa.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((0.0, -6.0, 4.0)))
    transforms.update_view_layer()
    blade = (world(arm, "weapon").to_3x3()
             @ Vector((0, 1, 0))).normalized()
    want = ((world(arm, "weapon_aim").translation
             - world(arm, "weapon").translation).normalized())
    check("moving target re-points (plan §51)",
          math.degrees(blade.angle(want)) <= 0.5,
          "off %.4f deg" % math.degrees(blade.angle(want)))

    # Aim again is idempotent, constraint never duplicated.
    aim.aim_weapon(arm, roll_degrees=0.0, key=False)
    count = sum(1 for c in arm.pose.bones["weapon"].constraints
                if c.name == "WPN_Aim")
    check("WPN_Aim never duplicated", count == 1, "count=%d" % count)

    # stop_aim leaves the pose, zeroes influence.
    res = aim.stop_aim(arm, key=False)
    check("stop_aim reports", res.get("stopped") is True)
    check("stop_aim zeroes influence",
          arm.pose.bones["weapon"].constraints["WPN_Aim"]
          .influence == 0.0)


def test_set_roll(arm):
    section("Set Roll about blade axis (plan §27)")
    scene = bpy.context.scene
    scene.frame_current = 30

    # Aim live first so the direction is locked; roll must not disturb it.
    pa = arm.pose.bones["weapon_aim"]
    pa.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((3.0, 3.0, 1.0)))
    transforms.update_view_layer()
    aim.aim_weapon(arm, roll_degrees=0.0, key=False)

    blade_before = (world(arm, "weapon").to_3x3()
                    @ Vector((0, 1, 0))).normalized()
    # Reference axis perpendicular to the blade.
    x0 = (world(arm, "weapon").to_3x3() @ Vector((1, 0, 0)))
    x0 = (x0 - blade_before * x0.dot(blade_before)).normalized()

    try:
        aim.set_roll(arm, 45.0, key=False)
        check("set_roll runs", True)
    except WeaponRigError as exc:
        check("set_roll runs", False, str(exc))
        return

    blade_after = (world(arm, "weapon").to_3x3()
                   @ Vector((0, 1, 0))).normalized()
    check("roll preserves blade direction (plan §27: target unmoved)",
          (blade_after - blade_before).length <= 2e-3,
          "d=%.8f" % (blade_after - blade_before).length)
    x1 = world(arm, "weapon").to_3x3() @ Vector((1, 0, 0))
    x1 = (x1 - blade_after * x1.dot(blade_after)).normalized()
    measured = math.degrees(x0.angle(x1))
    check("roll rotates flat by 45 deg", abs(measured - 45.0) <= 0.5,
          "measured %.4f deg" % measured)


def test_aim_operators_and_keys(arm):
    section("Aim operators, key policy, auto-key (plan §31)")
    scene = bpy.context.scene
    scene.frame_current = 40
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    scene.wpn_armature = arm

    pa = arm.pose.bones["weapon_aim"]
    pa.matrix = arm.matrix_world.inverted() @ Matrix.Translation(
        Vector((2.0, -3.0, 2.0)))
    transforms.update_view_layer()

    res = bpy.ops.wpn.point_blade_at(roll=30.0)
    check("point_blade_at op runs", res == {'FINISHED'}, str(res))

    # key=False + Auto Key off: no new keys on weapon_root.
    from weapon_animation_rig.animation import keyframes
    before = keyframes.find_fcurve(
        arm, 'pose.bones["weapon"].location')
    res = bpy.ops.wpn.aim_weapon(roll=0.0)
    check("aim_weapon op runs", res == {'FINISHED'}, str(res))
    after = keyframes.find_fcurve(
        arm, 'pose.bones["weapon"].location')
    check("no weapon_root location keys with key=False",
          before is None and after is None)

    # Auto Key ON => keys appear (§31). point_blade_at is orientation-only,
    # so rotation (not location) is what gets keyed.
    arm.animation_data_clear()
    scene.tool_settings.use_keyframe_insert_auto = True
    res = bpy.ops.wpn.aim_weapon(roll=15.0)
    scene.tool_settings.use_keyframe_insert_auto = False
    check("aim_weapon runs with Auto Key", res == {'FINISHED'}, str(res))
    fc = keyframes.find_fcurve(
        arm, 'pose.bones["weapon"].rotation_quaternion')
    check("Auto Key keys weapon_root rotation", fc is not None and
          any(abs(k.co[0] - 40) < 1e-6 for k in fc.keyframe_points))

    # Degenerate: aim coincident with root -> clear error, not NaN.
    pa.matrix = arm.matrix_world.inverted() @ world(arm, "weapon")
    transforms.update_view_layer()
    try:
        aim.point_blade_at(arm)
        check("coincident aim refused", False, "no exception")
    except WeaponRigError as exc:
        check("coincident aim refused", "coincid" in str(exc).lower()
              or "undefined" in str(exc).lower(), str(exc))


def main():
    print("=" * 70)
    print("MILESTONES 3+4 TEST SUITE: PIVOT + AIM (plan §50, §51)")
    print("=" * 70)

    arm = build_rig()
    test_pivot_presets(arm)
    test_set_pivot_tip(arm)
    test_pivot_switching_no_corruption(arm)
    test_pivot_operator_and_keys(arm)
    test_pivot_preserves_animation(arm)
    test_pivot_on_scaled_rig(arm)
    test_focus_point(arm)
    test_weapon_orientation_operator(arm)

    arm2 = build_aim_rig()
    test_aim_bone_present(arm2)
    test_blade_axis_config(arm2)
    test_point_blade_at(arm2)
    test_aim_weapon_and_roll(arm2)
    test_set_roll(arm2)
    test_aim_operators_and_keys(arm2)

    summary()


main()
