"""Headless test suite for Milestone 1 (plan §48, §53).

Run:
    blender -b --factory-startup --python tests/run_milestone1_tests.py

Covers plan §53 tests A-F plus the invariants of §30 (pose preservation),
§35 (creation idempotency + name conflicts), §36 (validation output),
§41 (no duplicate constraints), §12 (stepped influence keys).

A mock armature reproduces the ARP contract this add-on depends on: a
generated rig is identified by c_hand_ik.r / c_hand_ik.l (plan §7) plus a
root bone (plan §3.1). Real ARP is not required to test the math.
"""
import sys

import bpy
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Setup: import + register the add-on from source (not installed).
# ---------------------------------------------------------------------------
import os
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(ADDON_DIR))

try:
    import weapon_animation_rig as war
except ImportError:
    # Fallback: load the package directly from ADDON_DIR's parent.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "weapon_animation_rig",
        os.path.join(ADDON_DIR, "__init__.py"),
        submodule_search_locations=[ADDON_DIR])
    war = importlib.util.module_from_spec(spec)
    sys.modules["weapon_animation_rig"] = war
    spec.loader.exec_module(war)

war.register()

from weapon_animation_rig.constants import (  # noqa: E402
    TOL_ROTATION_DEG,
    TOL_TRANSLATION,
    WeaponRigError,
)
from weapon_animation_rig.rig import create as rig_create  # noqa: E402
from weapon_animation_rig.rig import validate as rig_validate  # noqa: E402
from weapon_animation_rig.utils import armature as arm_util  # noqa: E402
from weapon_animation_rig.utils import constraints as con_util  # noqa: E402
from weapon_animation_rig.utils import transforms  # noqa: E402

# ---------------------------------------------------------------------------
# Tiny test harness
# ---------------------------------------------------------------------------
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


def pose_diff(a, b):
    trans, rot = transforms.matrix_difference(a, b)
    return trans, rot


def grip_world(arm, side):
    """World-space grip reference point (rework: prop, not bone)."""
    return con_util.grip_world(arm, side)


# ---------------------------------------------------------------------------
# Mock ARP rig
# ---------------------------------------------------------------------------

def create_mock_armature(name="MockARP", root_style="root"):
    """Create a mock ARP-like armature in the CURRENT scene (no reset).

    Non-identity object transform: catches space-conversion bugs (§40).

    root_style: "root" (standard), "master" (only 'c_root_master'),
    "xroot" (ARP '.x' center-bone notation), or "none" (no root-like
    bone at all).
    """
    scene = bpy.context.scene
    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    scene.collection.objects.link(arm)
    arm.location = (1.3, -0.7, 2.1)
    arm.rotation_euler = Euler((0.23, -0.61, 0.42), 'XYZ')

    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones

    def mk(bname, head, tail, parent=None):
        b = eb.new(bname)
        b.head, b.tail = head, tail
        b.parent = parent
        return b

    if root_style == "root":
        root_name = "root"
        mk(root_name, (0, 0, 0), (0, 0, 0.3))
    elif root_style == "master":
        root_name = "c_root_master"
        mk(root_name, (0, 0, 0), (0, 0, 0.3))
    elif root_style == "xroot":
        # Real-world ARP variant (seen in BodyBase_Female_Sword_New.blend):
        # center bones keep ARP's internal '.x' notation -- 'root.x' with
        # 'c_root.x' under 'c_root_master.x' -- while sided controllers
        # stay plain 'c_hand_ik.r/l'.
        mk("c_root_master.x", (0, 0, 0), (0, 0, 0.3))
        mk("c_root.x", (0, 0, 0.3), (0, 0, 0.5),
           eb["c_root_master.x"])
        root_name = "root.x"
        mk(root_name, (0, 0, 0.5), (0, 0, 0.8), eb["c_root.x"])
    else:
        root_name = "pelvis"
        mk(root_name, (0, 0, 0), (0, 0, 0.3))
    spine = mk("spine_01", (0, 0, 1.0), (0, 0.15, 1.0), eb[root_name])
    mk("c_hand_ik.r", (0.6, 0.0, 1.3), (0.6, 0.18, 1.3), spine)
    mk("c_hand_ik.l", (-0.6, 0.0, 1.3), (-0.6, 0.18, 1.3), spine)
    # An FK bone with constraints on it to test stack safety (§43):
    # a pre-existing constraint must survive our ops untouched.
    mk("c_prop.r", (0.9, 0.1, 1.1), (0.9, 0.28, 1.1), spine)
    bpy.ops.object.mode_set(mode='POSE')

    # Pre-existing constraint on the hand: must never be touched (§29).
    pb_r = arm.pose.bones["c_hand_ik.r"]
    existing = pb_r.constraints.new('COPY_LOCATION')
    existing.name = "ARP_KeepMe"
    existing.target = arm
    existing.subtarget = root_name
    existing.influence = 0.0  # neutral for pose math, present for stack tests

    return arm


def build_mock_rig():
    """Full factory reset + a fresh mock armature (first test only)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 100
    scene.frame_current = 1
    return create_mock_armature()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_setup_detection():
    section("Setup: detection + ARP requirements (plan §7, §35)")
    arm = build_mock_rig()
    try:
        found = arm_util.find_generated_rig(bpy.context)
        check("detect mock ARP armature", found is arm,
              "got %s" % (found.name if found else None))
    except WeaponRigError as exc:
        check("detect mock ARP armature", False, str(exc))
    errs = arm_util.validate_arp_requirements(arm)
    check("ARP requirements satisfied", not errs, "; ".join(errs))
    return arm


def test_create_rig(arm):
    section("Create Weapon Rig (plan §35, rework: single bone)")
    try:
        ok, lines = rig_create.create_weapon_rig(bpy.context, arm)
        check("create returns valid", ok, "\n".join(lines))
        check("report is human-readable", any("Result: VALID" in l
                                              for l in lines), str(lines))
    except WeaponRigError as exc:
        check("create returns valid", False, str(exc))
        return

    for bone_name in ("weapon", "weapon_aim"):
        check("bone exists: %s" % bone_name,
              bone_name in arm.data.bones)
    check("weapon parented to root",
          arm.data.bones["weapon"].parent is not None
          and arm.data.bones["weapon"].parent.name == "root")
    check("weapon_aim parented to root (independent target)",
          arm.data.bones["weapon_aim"].parent is not None
          and arm.data.bones["weapon_aim"].parent.name == "root")
    check("weapon bone is non-deform (export control)",
          not arm.data.bones["weapon"].use_deform)
    check("metadata marks system bone",
          arm_util.is_system_bone(arm, "weapon"))
    check("grip offsets present as props",
          all(p in arm.data.bones["weapon"]
              for p in ("grip_r", "grip_l", "guard_l", "guard_r",
                        "pommel", "center", "tip", "blade_axis")))
    for side, con_name in (("R", "WPN_Attach_R"), ("L", "WPN_Attach_L")):
        con = con_util.find_attach_constraint(arm, side)
        check("constraint created: %s" % con_name,
              con is not None and con.type == 'CHILD_OF')
        check("constraint targets the weapon bone: %s" % con_name,
              con is not None and con.subtarget == "weapon",
              con.subtarget if con else None)
        check("constraint influence starts 0: %s" % con_name,
              con is not None and con.influence == 0.0)

    # Pre-existing ARP constraint untouched (§29).
    pb_r = arm.pose.bones["c_hand_ik.r"]
    keep = pb_r.constraints.get("ARP_KeepMe")
    check("pre-existing constraint preserved",
          keep is not None and keep.type == 'COPY_LOCATION'
          and keep.influence == 0.0)
    # Our constraint must be LAST (§43).
    check("WPN_Attach_R is last in stack",
          pb_r.constraints[-1].name == "WPN_Attach_R",
          "stack=%s" % [c.name for c in pb_r.constraints])


def test_idempotency_and_conflicts(arm):
    section("Idempotency + name conflicts (plan §35 step 4-5, §38)")
    try:
        rig_create.create_weapon_rig(bpy.context, arm)
        check("second create refuses (no duplicates)", False,
              "no exception raised")
    except WeaponRigError as exc:
        check("second create refuses (no duplicates)",
              "already exists" in str(exc).lower(), str(exc))
    n_constraints = con_util.count_attach_constraints(arm, "R")
    check("still exactly one WPN_Attach_R", n_constraints == 1,
          "count=%d" % n_constraints)

    # Foreign bone with a reserved name -> conflict error, no .001 rename.
    arm2 = create_mock_armature("MockARP_conflict")
    bpy.context.view_layer.objects.active = arm2
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm2.data.edit_bones
    root_eb = eb["root"]
    clash = eb.new("weapon")  # NOT created by us -> foreign
    clash.head, clash.tail = Vector((0.5, 0, 0.5)), Vector((0.5, 0, 0.7))
    clash.parent = root_eb
    bpy.ops.object.mode_set(mode='POSE')
    try:
        rig_create.create_weapon_rig(bpy.context, arm2)
        check("foreign name conflict refused", False, "no exception")
    except WeaponRigError as exc:
        check("foreign name conflict refused",
              "conflict" in str(exc).lower(), str(exc))
    check("no silent .001 rename created",
          "weapon.001" not in arm2.data.bones)
    return arm2


def test_validation_output(arm):
    section("Validation output (plan §36)")
    ok, lines = rig_validate.validate_weapon_rig(arm)
    text = "\n".join(lines)
    check("validation VALID after create", ok, text)
    for expected in ("Weapon Rig Validation", "Right Hand IK", "Left Hand IK",
                     "weapon", "weapon_aim",
                     "WPN_Attach_R", "WPN_Attach_L", "Result: VALID"):
        check("report mentions %r" % expected,
              expected in text, text)

    # Break something -> INVALID with the offending line.
    # Bone.parent is read-only outside edit mode, so re-parent in edit mode.
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    arm.data.edit_bones["weapon"].parent = arm.data.edit_bones["spine_01"]
    bpy.ops.object.mode_set(mode='POSE')
    ok2, lines2 = rig_validate.validate_weapon_rig(arm)
    check("validation detects broken parenting", not ok2,
          "\n".join(lines2))
    bpy.ops.object.mode_set(mode='EDIT')
    arm.data.edit_bones["weapon"].parent = \
        arm.data.edit_bones["root"]
    bpy.ops.object.mode_set(mode='POSE')


def _attach_both_no_pop(arm, frame):
    """Attach both hands at `frame`; return max (trans, rot) jumps."""
    bpy.context.scene.frame_current = frame
    before = {s: world(arm, "c_hand_ik." + s.lower()) for s in ("R", "L")}
    con_util.attach_preserve_transform(arm, "R", frame=frame, key=True)
    con_util.attach_preserve_transform(arm, "L", frame=frame, key=True)
    transforms.update_view_layer()
    after = {s: world(arm, "c_hand_ik." + s.lower()) for s in ("R", "L")}
    worst_t = worst_r = 0.0
    for s in ("R", "L"):
        t, r = pose_diff(before[s], after[s])
        worst_t = max(worst_t, t)
        worst_r = max(worst_r, r)
    return worst_t, worst_r


def test_attach_no_pop(arm):
    section("Test A/B: attach right/left without pop (plan §53 A, B, §10)")
    # Pose the weapon somewhere first so attach is non-trivial.
    wr = arm.pose.bones["weapon"]
    wr.matrix = Matrix.Translation((0.4, 0.2, 0.1)) @ \
        Euler((0.3, 0.1, -0.5)).to_matrix().to_4x4() @ wr.matrix
    transforms.update_view_layer()

    t, r = _attach_both_no_pop(arm, 1)
    check("attach both: no translation jump", t <= TOL_TRANSLATION,
          "d-trans=%.6f" % t)
    check("attach both: no rotation jump", r <= TOL_ROTATION_DEG,
          "d-rot=%.4f deg" % r)

    # Single-side tests: detach L first, then attach only R.
    con_util.detach_preserve_transform(arm, "L", frame=1, key=True)
    b = world(arm, "c_hand_ik.r")
    con_util.attach_preserve_transform(arm, "R", frame=2, key=True)
    transforms.update_view_layer()
    t, r = pose_diff(b, world(arm, "c_hand_ik.r"))
    check("Test A: attach R alone, no pop", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG, "d-trans=%.6f d-rot=%.4f" % (t, r))

    b = world(arm, "c_hand_ik.l")
    con_util.attach_preserve_transform(arm, "L", frame=3, key=True)
    transforms.update_view_layer()
    t, r = pose_diff(b, world(arm, "c_hand_ik.l"))
    check("Test B: attach L alone, no pop", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG, "d-trans=%.6f d-rot=%.4f" % (t, r))


def test_follow_and_detach(arm):
    section("Test C: both hands follow weapon (plan §53 C)")
    bpy.context.scene.frame_current = 10
    # Both attached from previous test (frame 3 state). Move weapon_root.
    wr = arm.pose.bones["weapon"]
    grip_r_before = grip_world(arm, "R")
    hand_r_before = world(arm, "c_hand_ik.r")
    wr.matrix = Matrix.Translation((0.35, -0.25, 0.4)) @ \
        Euler((-0.4, 0.7, 0.2)).to_matrix().to_4x4() @ wr.matrix
    transforms.update_view_layer()
    grip_r_after = grip_world(arm, "R")
    hand_r_after = world(arm, "c_hand_ik.r")

    # Hand must move by the SAME delta as the grip (world-space rigid follow).
    grip_delta = grip_r_after @ grip_r_before.inverted()
    predicted = grip_delta @ hand_r_before
    t, r = pose_diff(predicted, hand_r_after)
    check("Test C: right hand follows grip delta", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (t, r))

    # Same for left hand.
    grip_l_before = grip_world(arm, "L")
    hand_l_before = world(arm, "c_hand_ik.l")
    wr.matrix = Matrix.Translation((0.1, 0.1, -0.2)) @ wr.matrix
    transforms.update_view_layer()
    grip_l_after = grip_world(arm, "L")
    hand_l_after = world(arm, "c_hand_ik.l")
    predicted_l = (grip_l_after @ grip_l_before.inverted()) @ hand_l_before
    t, r = pose_diff(predicted_l, hand_l_after)
    check("Test C: left hand follows grip delta", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG, "d-trans=%.6f d-rot=%.4f" % (t, r))

    section("Test D: detach left without pop (plan §53 D, §11)")
    bpy.context.scene.frame_current = 51
    b = world(arm, "c_hand_ik.l")
    con_util.detach_preserve_transform(arm, "L", frame=51, key=True)
    transforms.update_view_layer()
    t, r = pose_diff(b, world(arm, "c_hand_ik.l"))
    check("Test D: detach L, no pop", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG, "d-trans=%.6f d-rot=%.4f" % (t, r))
    check("Test D: constraint kept (not deleted)",
          con_util.find_attach_constraint(arm, "L") is not None)
    check("Test D: influence now 0",
          con_util.find_attach_constraint(arm, "L").influence == 0.0)

    # Weapon keeps moving independently; detached hand must NOT follow.
    hand_l_after_detach = world(arm, "c_hand_ik.l")
    wr.matrix = Matrix.Translation((0.6, 0.0, 0.0)) @ wr.matrix
    transforms.update_view_layer()
    t, r = pose_diff(hand_l_after_detach, world(arm, "c_hand_ik.l"))
    check("Test D: detached hand does not follow weapon",
          t <= TOL_TRANSLATION and r <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (t, r))
    # ...while the right hand still does.
    hand_r_pos = world(arm, "c_hand_ik.r")
    wr.matrix = Matrix.Translation((0.0, 0.3, 0.0)) @ wr.matrix
    transforms.update_view_layer()
    t, r = pose_diff(hand_r_pos, world(arm, "c_hand_ik.r"))
    check("Test D: attached right hand still follows", t > TOL_TRANSLATION,
          "d-trans=%.6f (expected movement)" % t)


def test_reattach(arm):
    section("Test E: reattach without teleport (plan §53 E)")
    bpy.context.scene.frame_current = 90
    # Bring the left hand near the grip "by animation" is the ideal case,
    # but the no-pop guarantee must hold regardless of distance (§10).
    b = world(arm, "c_hand_ik.l")
    con_util.attach_preserve_transform(arm, "L", frame=90, key=True)
    transforms.update_view_layer()
    t, r = pose_diff(b, world(arm, "c_hand_ik.l"))
    check("Test E: reattach L, no pop", t <= TOL_TRANSLATION
          and r <= TOL_ROTATION_DEG, "d-trans=%.6f d-rot=%.4f" % (t, r))
    con_util.detach_preserve_transform(arm, "L", frame=91, key=True)
    con_util.detach_preserve_transform(arm, "R", frame=91, key=True)


def test_influence_keys(arm):
    section("Attachment keyframes stepped (plan §12, §31)")
    from weapon_animation_rig.animation import keyframes

    path_r = ('pose.bones["c_hand_ik.r"].constraints["WPN_Attach_R"].'
              'influence')
    path_l = ('pose.bones["c_hand_ik.l"].constraints["WPN_Attach_L"].'
              'influence')
    fc_r = keyframes.find_fcurve(arm, path_r)
    fc_l = keyframes.find_fcurve(arm, path_l)
    check("influence fcurve exists (R)", fc_r is not None)
    check("influence fcurve exists (L)", fc_l is not None)
    if fc_r is None or fc_l is None:
        return
    for label, fc in (("R", fc_r), ("L", fc_l)):
        interp = {k.interpolation for k in fc.keyframe_points}
        check("all influence keys CONSTANT (%s)" % label,
              interp == {'CONSTANT'}, "interps=%s" % interp)
        frames = sorted(k.co[0] for k in fc.keyframe_points)
        check("guard key exists before first attach (%s)" % label,
              frames[0] < 1.0, "frames=%s" % frames)

    # Timeline produced by the preceding tests:
    #   R: attach @1, re-attach @2, detach @91
    #   L: attach @1, detach @1, attach @3, detach @51, attach @90, det @91
    check("R influence is 1 at frame 10 (attached)", fc_r.evaluate(10) == 1.0,
          "got %s" % fc_r.evaluate(10))
    check("R influence is 1 at frame 51 (still attached)",
          fc_r.evaluate(51) == 1.0, "got %s" % fc_r.evaluate(51))
    check("R influence is 0 at frame 92 (detached)",
          fc_r.evaluate(92) == 0.0, "got %s" % fc_r.evaluate(92))
    check("L influence is 0 at frame 51 (detached)",
          fc_l.evaluate(51) == 0.0, "got %s" % fc_l.evaluate(51))
    check("L influence is 1 at frame 10 (attached)",
          fc_l.evaluate(10) == 1.0, "got %s" % fc_l.evaluate(10))
    check("L influence is 1 at frame 90 (reattached)",
          fc_l.evaluate(90) == 1.0, "got %s" % fc_l.evaluate(90))
    check("L influence is 0 at frame 92 (detached)",
          fc_l.evaluate(92) == 0.0, "got %s" % fc_l.evaluate(92))


def test_existing_animation_intact(arm):
    section("Test F: existing animation untouched (plan §53 F, §29)")

    def snapshot_keys(arm_obj):
        ad = arm_obj.animation_data
        if ad is None or ad.action is None:
            return {}
        out = {}
        action = ad.action
        slot = getattr(ad, "action_slot", None)
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type != 'KEYFRAME':
                    continue
                cb = strip.channelbag(slot)
                if cb is None:
                    continue
                for fcu in cb.fcurves:
                    out[(fcu.data_path, fcu.array_index)] = [
                        (k.co[0], k.co[1]) for k in fcu.keyframe_points]
        return out

    # Create a rig WITH pre-existing animation on the spine and hand.
    arm2 = create_mock_armature("MockARP_anim")
    bpy.context.view_layer.objects.active = arm2
    sp = arm2.pose.bones["spine_01"]
    sp.rotation_mode = 'XYZ'
    sp.rotation_euler = (0.1, 0.0, 0.0)
    arm2.keyframe_insert('pose.bones["spine_01"].rotation_euler', frame=1)
    sp.rotation_euler = (0.4, 0.2, 0.0)
    arm2.keyframe_insert('pose.bones["spine_01"].rotation_euler', frame=50)
    hr = arm2.pose.bones["c_hand_ik.r"]
    hr.location = (0.0, 0.0, 0.0)
    arm2.keyframe_insert('pose.bones["c_hand_ik.r"].location', frame=1)
    hr.location = (0.2, 0.1, -0.1)
    arm2.keyframe_insert('pose.bones["c_hand_ik.r"].location', frame=50)

    before = snapshot_keys(arm2)

    # Create rig, attach, detach -- none of these may touch those keys.
    try:
        rig_create.create_weapon_rig(bpy.context, arm2)
    except WeaponRigError as exc:
        check("Test F: create on animated rig", False, str(exc))
        return
    bpy.context.scene.frame_current = 20
    try:
        con_util.attach_preserve_transform(arm2, "R", frame=20, key=True)
        con_util.detach_preserve_transform(arm2, "R", frame=30, key=True)
    except WeaponRigError as exc:
        check("Test F: attach/detach on animated rig", False, str(exc))
        return
    check("Test F: attach/detach on animated rig", True)

    after = snapshot_keys(arm2)
    spine_before = {k: v for k, v in before.items() if "spine_01" in k[0]}
    spine_after = {k: v for k, v in after.items() if "spine_01" in k[0]}
    check("Test F: spine keys unchanged", spine_before == spine_after,
          "before=%s after=%s" % (spine_before, spine_after))

    # Hand location keys: only the frames WE keyed may change (30 = detach
    # compensation); frames 1 and 50 must be untouched.
    hand_before = {k: v for k, v in before.items()
                   if k[0] == 'pose.bones["c_hand_ik.r"].location'}
    hand_after = {k: v for k, v in after.items()
                  if k[0] == 'pose.bones["c_hand_ik.r"].location'}
    if hand_before:
        kb = dict(hand_before[('pose.bones["c_hand_ik.r"].location', 0)])
        ka = dict(hand_after.get(
            ('pose.bones["c_hand_ik.r"].location', 0), {}))
        check("Test F: hand key @1 unchanged", kb.get(1.0) == ka.get(1.0),
              "b=%s a=%s" % (kb.get(1.0), ka.get(1.0)))
        check("Test F: hand key @50 unchanged", kb.get(50.0) == ka.get(50.0),
              "b=%s a=%s" % (kb.get(50.0), ka.get(50.0)))

    # Pose at unkeyed frames must be identical before/after the whole op.
    bpy.context.scene.frame_current = 40
    transforms.update_view_layer()
    # (validated by spine equality above; frame 40 interpolates unchanged)


def test_mode_operator(arm):
    section("Mode switching (plan §13)")
    bpy.context.scene.frame_current = 100
    scene = bpy.context.scene
    # Operators resolve the armature from context -- make ours active and
    # point the scene property at it explicitly.
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    scene.wpn_armature = arm

    def influence(side):
        con = con_util.find_attach_constraint(arm, side)
        return con.influence if con else 0.0

    for mode, want in (("FREE", (0, 0)), ("RIGHT", (1, 0)),
                       ("LEFT", (0, 1)), ("BOTH", (1, 1))):
        res = bpy.ops.wpn.set_mode(mode=mode)
        check("set_mode %s runs" % mode, res == {'FINISHED'}, str(res))
        got = (round(influence("R")), round(influence("L")))
        check("mode %s -> R=%d L=%d" % (mode, want[0], want[1]),
              got == want, "got %s" % (got,))
    # Leave detached for cleanliness.
    bpy.ops.wpn.set_mode(mode='FREE')


def test_error_messages(arm):
    section("Error handling (plan §54)")
    # Missing grip bone -> precise message.
    # (use a rig WITHOUT weapon bones)
    arm3 = create_mock_armature("MockARP_bare")
    try:
        con_util.attach_preserve_transform(arm3, "R", frame=1, key=True)
        check("attach without rig reports missing bone", False,
              "no exception")
    except WeaponRigError as exc:
        check("attach without rig reports missing bone",
              "missing" in str(exc).lower() or "weapon\"" in str(exc),
              str(exc))

    # No armature at all -> 'Auto-Rig Pro armature not found.'
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    try:
        arm_util.find_generated_rig(bpy.context)
        check("no-armature detection error", False, "no exception")
    except WeaponRigError as exc:
        check("no-armature detection error",
              "not found" in str(exc).lower(), str(exc))


def test_attach_grip_distance_diagnostic():
    section("Attach reports hand-to-grip distance (glue-vs-snap UX)")
    arm = create_mock_armature("MockDist")
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.frame_current = 1
    # Move the hand far from its grip first (T-pose-ish offset).
    pb_far = arm.pose.bones["c_hand_ik.r"]
    pb_far.matrix = (arm.matrix_world.inverted()
                     @ Matrix.Translation(Vector((3.0, 2.0, 1.0))))
    transforms.update_view_layer()
    # Hand far from grip: attach still pop-free, but flags the distance.
    before = world(arm, "c_hand_ik.r")
    grip_w = grip_world(arm, "R")
    far = (before.translation - grip_w.translation).length
    check("mock hand starts far from grip", far > 0.30,
          "d=%.3f" % far)
    result = con_util.attach_preserve_transform(arm, "R", frame=1,
                                                key=True)
    check("far attach reports grip_distance",
          abs(result["grip_distance"] - far) <= 1e-4,
          "got %.3f want %.3f" % (result["grip_distance"], far))
    trans, rot = pose_diff(before, world(arm, "c_hand_ik.r"))
    check("far attach still pop-free",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))
    # Move the hand onto the grip, detach, reattach: distance ~0.
    con_util.detach_preserve_transform(arm, "R", frame=1, key=True)
    pb = arm.pose.bones["c_hand_ik.r"]
    pb.matrix = arm.matrix_world.inverted() @ (Matrix.Translation(
        grip_world(arm, "R").translation))
    transforms.update_view_layer()
    result2 = con_util.attach_preserve_transform(arm, "R", frame=2,
                                                 key=True)
    check("near attach reports ~zero distance",
          result2["grip_distance"] <= 1e-3,
          "got %.6f" % result2["grip_distance"])


def test_character_root_fallback():
    section("Character root fallback: c_root_master, then none (plan §3.1)")
    # Rig whose root deform bone has a different name: creation must
    # succeed, parenting weapon_root under the ARP master control, and
    # validation must stay VALID while naming the fallback.
    arm = create_mock_armature("MockNoRoot", root_style="master")
    name, status = arm_util.resolve_character_root(arm)
    check("resolver picks c_root_master", name == "c_root_master"
          and status == "fallback", "%s/%s" % (name, status))
    try:
        ok, lines = rig_create.create_weapon_rig(bpy.context, arm)
        check("create succeeds without 'root' bone", ok,
              "\n".join(lines))
    except WeaponRigError as exc:
        check("create succeeds without 'root' bone", False, str(exc))
        return
    check("weapon parented under fallback",
          arm.data.bones["weapon"].parent.name == "c_root_master")
    text = "\n".join(rig_validate.validate_weapon_rig(arm)[1])
    check("validation VALID with fallback noted",
          "Result: VALID" in text and "fallback" in text, text)

    # Attach still pop-free when parented under the fallback.
    bpy.context.scene.frame_current = 1
    before = world(arm, "c_hand_ik.r")
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    transforms.update_view_layer()
    trans, rot = pose_diff(before, world(arm, "c_hand_ik.r"))
    check("attach pop-free under fallback parent",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))

    # ARP '.x' center-bone notation (real rig: 'root.x' under 'c_root.x'
    # under 'c_root_master.x', plain 'c_hand_ik.r/l'). Must resolve as the
    # ideal character root, not a fallback.
    armx = create_mock_armature("MockXRoot", root_style="xroot")
    namex, statusx = arm_util.resolve_character_root(armx)
    check("resolver accepts ARP '.x' root notation",
          namex == "root.x" and statusx == "ideal",
          "%s/%s" % (namex, statusx))
    try:
        okx, linesx = rig_create.create_weapon_rig(bpy.context, armx)
        check("create succeeds on '.x' rig", okx, "\n".join(linesx))
    except WeaponRigError as exc:
        check("create succeeds on '.x' rig", False, str(exc))
        return
    check("weapon parented under 'root.x'",
          armx.data.bones["weapon"].parent.name == "root.x")
    textx = "\n".join(rig_validate.validate_weapon_rig(armx)[1])
    check("validation VALID on '.x' rig",
          "Result: VALID" in textx, textx)

    # No root-like bone at all: creation still succeeds (armature level),
    # but validation reports exactly what is wrong and what still works.
    arm2 = create_mock_armature("MockBare", root_style="none")
    cands = arm_util.root_like_candidates(arm2)
    check("no root-like candidates listed honestly", cands == [],
          str(cands))
    try:
        ok2, lines2 = rig_create.create_weapon_rig(bpy.context, arm2)
    except WeaponRigError as exc:
        check("create succeeds with no root at all", False, str(exc))
        return
    check("create succeeds with no root at all (armature level)", True)
    check("weapon unparented (armature level)",
          arm2.data.bones["weapon"].parent is None)
    ok3, lines3 = rig_validate.validate_weapon_rig(arm2)
    text3 = "\n".join(lines3)
    check("validation INVALID without any root, with reason",
          (not ok3) and "root bone" in text3, text3)


def build_legacy_rig(name="MockLegacy"):
    """Construct a PRE-REWORK rig manually (6 bones + old constraints).

    Replicates the old default layout exactly so migration has realistic
    data to fold: grips/tip as bones, constraints targeting grip bones,
    keys on weapon_root channels, preview parented to the old socket.
    """
    arm = create_mock_armature(name)
    h = Vector(arm.data.bones["c_hand_ik.r"].head_local)
    z = Vector((0.0, 0.0, 1.0))
    layout = {
        "weapon_root": (h, h + z * 0.12, "root"),
        "weapon_socket": (h, h + z * 0.06, "weapon_root"),
        "weapon_grip_r": (h, h + z * 0.10, "weapon_root"),
        "weapon_grip_l": (h + z * 0.15, h + z * 0.25, "weapon_root"),
        "weapon_tip": (h + z * 1.10, h + z * 1.20, "weapon_root"),
        "weapon_aim": (h + z * 1.40, h + z * 1.50, "root"),
    }
    roles = {"weapon_root": "root", "weapon_socket": "socket",
             "weapon_grip_r": "grip_r", "weapon_grip_l": "grip_l",
             "weapon_tip": "tip", "weapon_aim": "aim"}
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        eb = arm.data.edit_bones
        for bname, (head, tail, parent) in layout.items():
            e = eb.new(bname)
            e.head, e.tail = head, tail
            e.use_connect = False
            e.use_deform = False
            if parent is not None:
                e.parent = eb[parent]
    finally:
        bpy.ops.object.mode_set(mode='POSE')
    for bname, role in roles.items():
        bone = arm.data.bones[bname]
        bone["weapon_rig_system"] = "weapon_animation_rig"
        bone["weapon_rig_role"] = role
        bone.use_deform = False
    arm.data.bones["weapon_root"]["blade_axis"] = "+Y"
    # Old-style attach constraints targeting the grip BONES.
    for side, grip in (("R", "weapon_grip_r"), ("L", "weapon_grip_l")):
        pb = arm.pose.bones["c_hand_ik." + side.lower()]
        con = pb.constraints.new('CHILD_OF')
        con.name = "WPN_Attach_" + side
        con.target = arm
        con.subtarget = grip
        con.influence = 0.0
    return arm


def test_migration():
    section("Legacy rig auto-migration (rework)")
    arm = build_legacy_rig()
    bpy.context.scene.frame_current = 1
    scene = bpy.context.scene
    scene.frame_current = 1

    # Pose the weapon + key it (tests fcurve path rename), attach R so
    # the migration must preserve a live attached hand.
    wr = arm.pose.bones["weapon_root"]
    wr.matrix = Matrix.Translation((0.4, -0.2, 0.3)) @ wr.matrix
    transforms.update_view_layer()
    arm.keyframe_insert('pose.bones["weapon_root"].location', frame=1)
    arm.keyframe_insert(
        'pose.bones["weapon_root"].rotation_quaternion', frame=1)
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    hand_before = world(arm, "c_hand_ik.r")
    weapon_before = world(arm, "weapon_root")

    try:
        ok, lines = rig_create.create_weapon_rig(bpy.context, arm)
        text = "\n".join(lines)
        check("migration runs and validates", ok, text)
    except WeaponRigError as exc:
        check("migration runs and validates", False, str(exc))
        return
    check("migration reported", any("Migrat" in l for l in lines), text)

    # New bone at the old rest transform, old bones gone.
    check("weapon bone created", "weapon" in arm.data.bones)
    for gone in ("weapon_root", "weapon_socket", "weapon_grip_r",
                 "weapon_grip_l", "weapon_tip"):
        check("legacy %s removed" % gone, gone not in arm.data.bones,
              "still present")
    check("weapon_aim reused (same name)",
          arm_util.is_system_bone(arm, "weapon_aim"))

    # Grip offsets derived from old rest positions.
    wbone = arm.data.bones["weapon"]
    for prop, want in (("grip_r", (0.0, 0.0, 0.0)),
                        ("grip_l", (0.0, 0.15, 0.0)),
                        ("tip", (0.0, 1.10, 0.0))):
        got = tuple(wbone.get(prop, ()))
        check("migrated %s offset" % prop,
              len(got) == 3 and all(abs(a - b) < 1e-4
                                    for a, b in zip(got, want)),
              str(got))
    check("blade_axis carried over", wbone.get("blade_axis") == "+Y")

    # Weapon world unchanged (rest + channels transferred).
    trans, rot = pose_diff(weapon_before, world(arm, "weapon"))
    check("weapon world preserved by migration",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))

    # Attached hand preserved through retarget.
    trans, rot = pose_diff(hand_before, world(arm, "c_hand_ik.r"))
    check("attached hand preserved by migration",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))
    con = arm.pose.bones["c_hand_ik.r"].constraints["WPN_Attach_R"]
    check("constraint retargeted to weapon",
          con.subtarget == "weapon", con.subtarget)
    check("influence still 1 (still attached)", con.influence == 1.0)

    # fcurve paths renamed: keys drive the new bone now.
    from weapon_animation_rig.animation import keyframes
    fc = keyframes.find_fcurve(arm, 'pose.bones["weapon"].location')
    check("location keys renamed to weapon",
          fc is not None and any(abs(k.co[0] - 1) < 1e-6
                                 for k in fc.keyframe_points))
    check("no orphan keys left on old name",
          keyframes.find_fcurve(
              arm, 'pose.bones["weapon_root"].location') is None)

    # Full workflow still works after migration.
    con_util.detach_preserve_transform(arm, "R", frame=2, key=True)
    trans, rot = pose_diff(hand_before, world(arm, "c_hand_ik.r"))
    # NOTE: detach at frame 2 (hand was attached at 1, weapon static) --
    # hand must stay where it was.
    check("detach works post-migration",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))
    ok2, lines2 = rig_validate.validate_weapon_rig(arm)
    check("migrated rig validates", ok2, "\n".join(lines2))


def test_legacy_ops_without_migration():
    section("Legacy rig stays operable without migrating (back-compat)")
    arm = build_legacy_rig("MockLegacyOps")
    bpy.context.scene.frame_current = 1
    # Attach works through the legacy root fallback.
    before = world(arm, "c_hand_ik.r")
    con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    trans, rot = pose_diff(before, world(arm, "c_hand_ik.r"))
    check("attach works on legacy rig",
          trans <= TOL_TRANSLATION and rot <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (trans, rot))
    con = arm.pose.bones["c_hand_ik.r"].constraints["WPN_Attach_R"]
    check("legacy attach targets legacy root",
          con.subtarget == "weapon_root", con.subtarget)
    # Snap/pivot resolve the legacy bone too.
    from weapon_animation_rig.weapon import snap as snap_mod
    from weapon_animation_rig.weapon import pivot as pivot_mod
    snap_mod.snap_weapon_to_hand(arm, "R", key=False, frame=1)
    check("snap works on legacy rig", True)
    pivot_mod.set_pivot(arm, 'GRIP_R', key=False, frame=1)
    check("pivot works on legacy rig", True)
    # ...but validation correctly demands migration, naming it.
    ok, lines = rig_validate.validate_weapon_rig(arm)
    text = "\n".join(lines)
    check("legacy rig INVALID with migrate hint",
          (not ok) and "migrate" in text.lower(), text)
    con_util.detach_preserve_transform(arm, "R", frame=1, key=True)


def build_rig():
    """Build an additional mock ARP armature (NO scene reset -- main's `arm`
    must survive) and generate the weapon rig in it."""
    arm = create_mock_armature(name="MockARP_IK")
    ok, lines = rig_create.create_weapon_rig(bpy.context, arm)
    assert ok, chr(10).join(lines)
    transforms.update_view_layer()
    return arm


def test_attach_ik_target_conflict_error():
    """External IK target + attach: the IK is frozen for the whole attach so
    the guard-key transient (influence 0 at frame-1) can never let the
    solver re-pose the chain behind our back -- that re-pose is exactly the
    user's 'moved after keyframing' (hand rotated 19 deg). Blender's
    depsgraph always lets a later Child Of win over IK, so no error is
    expected here; what MUST hold is: chain untouched, hand unpopped, IK
    restored active afterwards.
    """
    section("Attach: external IK target -> chain untouched, no pop")
    prev_active = bpy.context.view_layer.objects.active  # restore at end
    arm = build_rig()
    scene = bpy.context.scene
    scene.frame_set(1)
    transforms.update_view_layer()

    # Realistic arm chain so the solver has something to re-pose.
    hb = "c_hand_ik.r"
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    sh = eb.new("shoulder_01")
    sh.head = Vector((0.15, 0.0, 1.0)); sh.tail = Vector((0.30, 0.0, 1.4))
    sh.parent = eb["spine_01"]
    el = eb.new("elbow_01")
    el.head = Vector((0.30, 0.0, 1.4)); el.tail = Vector((0.45, 0.0, 1.6))
    el.parent = sh
    h = eb[hb]
    h.tail = Vector((0.60, 0.0, 1.8))
    h.parent = el
    tgt = eb.new("IK_target_r")  # reachable, clearly off the grip
    tgt.head = Vector((1.5, 0.5, 2.0))
    tgt.tail = Vector((1.5, 0.5, 2.2))
    bpy.ops.object.mode_set(mode='POSE')
    transforms.update_view_layer()

    wr = arm.pose.bones["weapon"]
    wr.matrix = Matrix.Translation((0.4, 0.2, 0.1)) @ \
        Euler((0.3, 0.1, -0.5)).to_matrix().to_4x4() @ wr.matrix
    transforms.update_view_layer()

    # Manual hand pose, then an ACTIVE external IK (no update after -- the
    # solver's first run must happen inside attach, while it is frozen).
    arm.pose.bones[hb].rotation_euler = Euler((0.5, 0.2, -0.3))
    arm.pose.bones[hb].location = Vector((0.1, 0.05, 0.0))
    transforms.update_view_layer()
    chain0 = {bn: (tuple(arm.pose.bones[bn].rotation_euler),
                   tuple(arm.pose.bones[bn].location))
              for bn in ("spine_01", "shoulder_01", "elbow_01")}
    ik = arm.pose.bones[hb].constraints.new('IK')
    ik.name = "IK_r_ext"
    ik.target = arm
    ik.subtarget = "IK_target_r"
    ik.chain_count = 3
    ik.use_location = True
    ik.use_rotation = True
    # ik.active defaults True; deliberately NO update here.

    try:
        res = con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    except WeaponRigError as exc:
        check("attach with external IK succeeds", False, str(exc))
        bpy.context.view_layer.objects.active = prev_active
        return
    check("attach with external IK succeeds",
          res.get("side") == "R", str(res))

    # 1. Chain bones untouched by any solver transient.
    moved = []
    for bn in ("spine_01", "shoulder_01", "elbow_01"):
        pb = arm.pose.bones[bn]
        r0, l0 = chain0[bn]
        r1 = tuple(pb.rotation_euler)
        l1 = tuple(pb.location)
        if any(abs(a - b) > 1e-6 for a, b in zip(r0, r1)) or \
                any(abs(a - b) > 1e-6 for a, b in zip(l0, l1)):
            moved.append(bn)
    check("solver transient did not re-pose the chain",
          not moved, "re-posed: %s" % moved)
    # 2. IK restored active (frozen only for the duration).
    check("IK solver restored active after attach",
          ik.active, "active=%s" % ik.active)
    # 3. Constraint created and on.
    con = con_util.find_attach_constraint(arm, "R")
    check("attach constraint present and enabled",
          con is not None and con.influence == 1.0,
          "influence=%s" % (con.influence if con else None))
    bpy.context.view_layer.objects.active = prev_active

def test_attach_ik_hand():
    section("Attach: hand with IK solver -- IK frozen for the duration")
    prev_active = bpy.context.view_layer.objects.active  # restore at end
    arm = build_rig()
    scene = bpy.context.scene
    scene.frame_set(1)
    transforms.update_view_layer()

    # Pose the weapon so attach is non-trivial.
    wr = arm.pose.bones["weapon"]
    wr.matrix = Matrix.Translation((0.4, 0.2, 0.1)) @ \
        Euler((0.3, 0.1, -0.5)).to_matrix().to_4x4() @ wr.matrix
    transforms.update_view_layer()

    # Give the hand an IK solver (mimics real rigs such as BodyBase).
    # The mock's hand chain is too short to solve a self-targeting IK
    # (solver would hit a dependency cycle), so extend it first:
    # spine_01 -> shoulder_01 -> elbow_01 -> c_hand_ik.r.
    hb = "c_hand_ik.r"
    eb = arm.data.edit_bones
    bpy.ops.object.mode_set(mode='EDIT')
    sh = eb.new("shoulder_01")
    sh.head = Vector((0.15, 0.0, 1.0)); sh.tail = Vector((0.30, 0.0, 1.4))
    sh.parent = eb["spine_01"]
    el = eb.new("elbow_01")
    el.head = Vector((0.30, 0.0, 1.4)); el.tail = Vector((0.45, 0.0, 1.6))
    el.parent = sh
    h = eb[hb]
    h.tail = Vector((0.60, 0.0, 1.8))
    h.parent = el
    bpy.ops.object.mode_set(mode='POSE')
    transforms.update_view_layer()
    ik = arm.pose.bones[hb].constraints.new('IK')
    ik.name = "IK_r"
    ik.target = arm
    ik.chain_count = 3                    # spine -> shoulder -> elbow
    ik.use_location = True                # subtarget defaults to the IK
    ik.use_rotation = True                # bone itself -> self-targeting
                                          # IK: keeps the hand at its own pose.
    transforms.update_view_layer()

    w0 = world(arm, hb)
    before_l = world(arm, "c_hand_ik.l")

    # Attach: the code disables the IK solver during capture + keying so the
    # guard-key transient (guard value 0) can never re-solve the IK to a
    # different minimum -- that's the "moved after keyframing" bug.
    res = con_util.attach_preserve_transform(arm, "R", frame=1, key=True)
    check("attach with IK hand returned diagnostics",
          "grip_distance" in res and res.get("side") == "R", str(res))

    w1 = world(arm, hb)
    now_l = world(arm, "c_hand_ik.l")
    t, r = transforms.matrix_difference(w0, w1)
    check("hand stayed at attach pose after IK restore",
          t <= TOL_TRANSLATION and r <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (t, r))
    tl, rl = transforms.matrix_difference(before_l, now_l)
    check("right-hand IK re-solve did not pull the spine/left hand",
          tl <= TOL_TRANSLATION and rl <= TOL_ROTATION_DEG,
          "left d-trans=%.6f d-rot=%.4f" % (tl, rl))

    # Relative frame hand->grip right after attach (the Child Of "glue"):
    # this matrix must be IDENTICAL before/after the weapon moves, no matter
    # how the IK solver re-poses the chain -- that's the attach guarantee.
    rel0 = con_util.grip_world(arm, "R").inverted() @ w1

    # Follow: weapon moves -> the attached hand must stay rigid on the grip:
    # Child Of re-poses the hand rigidly with the grip even if an IK solver
    # re-runs behind it: comparing hand->grip BEFORE vs AFTER the move proves
    # rigidity in one shot (translation + rotation, rest-pose safe).
    wr = arm.pose.bones["weapon"]
    wr.matrix = Matrix.Translation((0.7, -0.1, 0.3)) @ \
        Euler((-0.2, 0.4, 0.1)).to_matrix().to_4x4() @ world(arm, "weapon")
    transforms.update_view_layer()
    h1 = world(arm, hb)
    g1 = con_util.grip_world(arm, "R")      # grip reference frame (Matrix)
    rel1 = g1.inverted() @ h1
    t, r = transforms.matrix_difference(rel0, rel1)
    check("attached hand tracks the weapon grip (rigid Child Of)",
          t <= TOL_TRANSLATION and r <= TOL_ROTATION_DEG,
          "d-trans=%.6f d-rot=%.4f" % (t, r))
    check("hand moved with the weapon (not stuck in place)",
          (h1.translation - w1.translation).length > 0.5,
          "hand moved=%.4f" % (h1.translation - w1.translation).length)
    bpy.context.view_layer.objects.active = prev_active



def main():
    print("=" * 70)
    print("MILESTONE 1 TEST SUITE (plan §48, §53)")
    print("=" * 70)

    arm = test_setup_detection()
    test_create_rig(arm)
    test_idempotency_and_conflicts(arm)
    test_validation_output(arm)
    test_attach_no_pop(arm)
    test_attach_ik_hand()
    test_attach_ik_target_conflict_error()
    test_follow_and_detach(arm)
    test_reattach(arm)
    test_influence_keys(arm)
    test_existing_animation_intact(arm)
    test_mode_operator(arm)
    test_error_messages(arm)
    test_character_root_fallback()
    test_attach_grip_distance_diagnostic()
    test_migration()
    test_legacy_ops_without_migration()

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


# =========================================================================
# Attachment with IK solvers on the hand (user's real rigs have IK on
# c_hand_ik.r -- this is where "moved after keyframing" was observed).
# =========================================================================

