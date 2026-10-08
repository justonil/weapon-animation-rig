"""Headless test suite: presets + preview mesh + rig visibility + pie menu
(plan §16, §17, §33, §34).

Run:
    blender -b --factory-startup --python tests/run_milestone6_tests.py
"""
import os
import sys

import bpy
from mathutils import Euler, Matrix, Vector

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
from weapon_animation_rig.weapon import preview  # noqa: E402
from weapon_animation_rig.weapon.preview import PREVIEW_PROP  # noqa: E402


def world(arm, name):
    return transforms.get_pose_bone_world_matrix(arm, name)


def object_world(obj):
    dg = transforms.evaluated_depsgraph()
    return obj.evaluated_get(dg).matrix_world.copy()


def make_sword_mesh(name="SwordMesh"):
    mesh = bpy.data.meshes.new(name)
    verts = [(0, -0.05, 0), (0, 0.05, 0), (0, 0, 1.2),
             (0.03, 0, 0.15), (-0.03, 0, 0.15)]
    faces = [(0, 1, 2, 3, 4)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (2.0, 1.0, 3.0)
    transforms.update_view_layer()
    return obj


def test_visibility_toggle(arm):
    section("Show Weapon Rig toggle (plan §34)")
    bones = ["weapon", "weapon_aim"]
    res = bpy.ops.wpn.toggle_rig_visibility(show=False)
    check("hide runs", res == {'FINISHED'}, str(res))
    check("all weapon bones hidden",
          all(arm.data.bones[n].hide for n in bones))
    res = bpy.ops.wpn.toggle_rig_visibility(show=True)
    check("show runs", res == {'FINISHED'}, str(res))
    check("all weapon bones visible",
          all(not arm.data.bones[n].hide for n in bones))
    # Bone collection exists for organization.
    check("Weapon Rig bone collection",
          "Weapon Rig" in arm.data.collections,
          str([c.name for c in arm.data.collections]))


def test_preview_mesh(arm):
    section("Preview mesh follows socket (plan §16)")
    mesh = make_sword_mesh()
    mw_before = object_world(mesh).copy()

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    try:
        preview.set_preview_mesh(arm, mesh)
        check("set preview runs", True)
    except WeaponRigError as exc:
        check("set preview runs", False, str(exc))
        return
    check("preview relationship stored",
          arm.get(PREVIEW_PROP) == mesh.name, str(arm.get(PREVIEW_PROP)))
    check("parented to armature/socket",
          mesh.parent is arm and mesh.parent_type == 'BONE'
          and mesh.parent_bone == "weapon",
          "%s/%s/%s" % (mesh.parent, mesh.parent_type, mesh.parent_bone))
    t, _ = transforms.matrix_difference(mw_before, object_world(mesh))
    check("preview world preserved at assignment", t <= TOL_TRANSLATION,
          "d=%.6f" % t)

    # Move the weapon: the mesh must follow rigidly (delta of socket).
    socket_before = world(arm, "weapon")
    mesh_before = object_world(mesh)
    wr = arm.pose.bones["weapon"]
    wr.matrix = (Matrix.Translation(Vector((0.4, -0.3, 0.5)))
                 @ Euler((0.3, -0.2, 0.6)).to_matrix().to_4x4()
                 @ wr.matrix)
    transforms.update_view_layer()
    socket_after = world(arm, "weapon")
    mesh_after = object_world(mesh)
    predicted = (socket_after @ socket_before.inverted()) @ mesh_before
    t, r = transforms.matrix_difference(predicted, mesh_after)
    check("preview follows socket rigidly", t <= 1e-3,
          "d-trans=%.6f d-rot=%.4f" % (t, r))

    # Must not be an animation source: no constraints, no fcurves.
    check("preview has no constraints", len(mesh.constraints) == 0)
    check("registered on armature",
          arm.get(PREVIEW_PROP) == mesh.name)

    # Clear: transform stays, relationship gone.
    mw = object_world(mesh).copy()
    try:
        obj = preview.clear_preview_mesh(arm)
        check("clear preview runs", obj is mesh)
    except WeaponRigError as exc:
        check("clear preview runs", False, str(exc))
        return
    t, _ = transforms.matrix_difference(mw, object_world(mesh))
    check("clear keeps transform", t <= TOL_TRANSLATION, "d=%.6f" % t)
    check("clear removes parent", mesh.parent is None)
    check("clear removes relationship", arm.get(PREVIEW_PROP) in (None, ""))

    # Non-mesh rejected, missing rig refused (plan §54).
    try:
        preview.set_preview_mesh(arm, arm)
        check("armature-as-preview refused", False, "no exception")
    except WeaponRigError:
        check("armature-as-preview refused", True)
    bpy.data.objects.remove(mesh, do_unlink=True)


def test_presets_roundtrip(arm):
    section("Preset save/apply round-trip (plan §17)")
    scene = bpy.context.scene
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    wbone = arm.data.bones["weapon"]

    # Set a distinctive weapon config (grip offsets are plain vectors).
    wbone["grip_r"] = (0.05, -0.02, 0.03)
    wbone["grip_l"] = (0.02, 0.20, -0.01)
    wbone["tip"] = (0.0, 1.30, 0.05)
    wbone["pommel"] = (0.01, -0.09, 0.02)
    wbone["blade_axis"] = "-Z"

    # Save via operator.
    scene.wpn_preset_name = "Greatsword"
    res = bpy.ops.wpn.save_preset(name="Greatsword")
    check("save preset runs", res == {'FINISHED'}, str(res))
    check("preset stored", len(scene.wpn_presets) >= 1)
    preset = scene.wpn_presets[scene.wpn_preset_index]
    check("preset named", preset.name == "Greatsword", preset.name)
    check("preset captured blade axis", preset.blade_axis == 'NZ',
          preset.blade_axis)
    check("preset captured grip_r",
          all(abs(a - b) < 1e-6
              for a, b in zip(tuple(preset.grip_r), (0.05, -0.02, 0.03))),
          tuple(preset.grip_r))

    check("preset captured pommel",
          all(abs(a - b) < 1e-6
              for a, b in zip(tuple(preset.pommel), (0.01, -0.09, 0.02))),
          tuple(preset.pommel))

    # Scramble the config, then apply -> restored.
    wbone["grip_r"] = (9.0, 9.0, 9.0)
    wbone["pommel"] = (8.0, 8.0, 8.0)
    wbone["blade_axis"] = "+Y"
    res = bpy.ops.wpn.apply_preset()
    check("apply preset runs", res == {'FINISHED'}, str(res))
    check("grip_r config restored",
          all(abs(a - b) < 1e-6
              for a, b in zip(tuple(wbone["grip_r"]), (0.05, -0.02, 0.03))),
          tuple(wbone["grip_r"]))
    check("blade axis restored",
          wbone["blade_axis"] == "-Z",
          str(wbone.get("blade_axis")))
    check("pommel config restored",
          all(abs(a - b) < 1e-6
              for a, b in zip(tuple(wbone["pommel"]),
                               (0.01, -0.09, 0.02))),
          tuple(wbone["pommel"]))

    # Second save with same name overwrites instead of duplicating.
    n = len(scene.wpn_presets)
    bpy.ops.wpn.save_preset(name="Greatsword")
    check("save same name updates in place", len(scene.wpn_presets) == n,
          "count=%d" % len(scene.wpn_presets))

    # Save/apply are pure prop reads/writes: channels and constraints
    # untouched (plan §29).
    check("preset ops add no constraints",
          len(arm.pose.bones["weapon"].constraints) == 0)


def test_pie_and_keymap():
    section("Pie menu + hotkey (plan §33)")
    check("pie menu registered", hasattr(bpy.types, "WPN_MT_pie"))
    from weapon_animation_rig.ui import menus
    if not menus.ADDON_KEYMAPS:
        # Background blender has no addon keyconfig: the menu itself
        # (reachable via F3 search) is the verifiable part here.
        check("keymap skipped in background (no addon keyconfig)", True)
        return
    km, kmi = menus.ADDON_KEYMAPS[0]
    check("pie bound to Ctrl+Shift+W",
          kmi.type == 'W' and kmi.ctrl and kmi.shift and not kmi.alt,
          "%s ctrl=%s shift=%s" % (kmi.type, kmi.ctrl, kmi.shift))
    check("pie calls weapon menu",
          getattr(kmi.properties, "name", "") == "WPN_MT_pie",
          str(getattr(kmi.properties, "name", "")))


def main():
    print("=" * 70)
    print("MILESTONE 6 TEST SUITE: PRESETS + PREVIEW + VIS + PIE")
    print("=" * 70)

    arm = common.build_mock_rig()
    rig_create.create_weapon_rig(bpy.context, arm)
    bpy.context.scene.wpn_armature = arm

    test_visibility_toggle(arm)
    test_preview_mesh(arm)
    test_presets_roundtrip(arm)
    test_pie_and_keymap()

    summary()


main()
