"""Shared harness for the milestone test suites (plan §53).

Each run_milestoneN_tests.py does:
    import common  (after inserting the tests/ dir on sys.path)
    war = common.register_addon()
"""
import os
import sys

import bpy
from mathutils import Euler

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


def summary():
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


def register_addon():
    here = os.path.dirname(os.path.abspath(__file__))
    addon_dir = os.path.dirname(here)
    if os.path.dirname(addon_dir) not in sys.path:
        sys.path.insert(0, os.path.dirname(addon_dir))
    import weapon_animation_rig as war
    try:
        war.register()
    except Exception:
        pass  # already registered (e.g. suite re-run in one session)
    return war


def build_mock_rig(name="MockARP"):
    """Fresh factory scene + mock ARP-like armature with a weapon rig."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 100
    scene.frame_current = 1
    scene.tool_settings.use_keyframe_insert_auto = False  # plan §31

    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    scene.collection.objects.link(arm)
    arm.location = (1.3, -0.7, 2.1)  # non-identity: catches space bugs
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

    root = mk("root", (0, 0, 0), (0, 0, 0.3))
    spine = mk("spine_01", (0, 0, 1.0), (0, 0.15, 1.0), root)
    mk("c_hand_ik.r", (0.6, 0.0, 1.3), (0.6, 0.18, 1.3), spine)
    mk("c_hand_ik.l", (-0.6, 0.0, 1.3), (-0.6, 0.18, 1.3), spine)
    bpy.ops.object.mode_set(mode='POSE')
    return arm
