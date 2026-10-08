"""Weapon rig creation (plan §35, reworked: ONE export/control bone).

Runs: detect -> verify ARP -> check conflicts -> [migrate legacy rig |
create fresh] -> constraints -> validate -> report.

NON-DESTRUCTIVE (plan §29): creation only ADDS bones and constraints, with
one explicit exception documented below: auto-migration of a PRE-REWORK
rig (weapon_root/socket/grips/tip bones carrying OUR OWN system marker).
Migration re-homes the user's data (grip layout -> custom props, fcurve
paths weapon_root -> weapon, attach constraints retargeted, preview
re-parented) instead of stranding it, and every step is reported. Foreign
bones (no system marker) are never touched -- name conflicts still refuse
(plan §38).

DEFAULT LAYOUT (placeholder data, plan §17): the weapon bone spawns at the
right hand's rest position pointing up; grip/tip offsets are bone-local
vectors. For plain weapon-driven hand follow, offsets cancel out of the
follow delta, so defaults are cosmetic -- they matter for snap-to-hands
and pivots, and presets store per-weapon values.

SPACES: rest positions are armature space, captured from the hand IK rest
head so the rig lands where the hand is.
"""
import bpy
from mathutils import Vector

from ..constants import (
    BONE_AIM,
    BONE_WEAPON,
    CHARACTER_ROOT_BONE,
    DEFAULT_GRIP_OFFSETS,
    GRIP_PROP_L,
    GRIP_PROP_R,
    HAND_BONES,
    LEGACY_NAMES,
    TIP_PROP,
    WEAPON_SLOT_KEY,
    WeaponRigError,
    missing_bone,
)
from ..utils import armature as arm_util
from ..utils import constraints as con_util


def _hand_rest_head(armature):
    hand = armature.data.bones.get(HAND_BONES["R"])
    if hand is None:
        raise missing_bone(HAND_BONES["R"])
    return Vector(hand.head_local)


def _legacy_system_bones(armature):
    """Pre-rework bones carrying OUR marker (safe to migrate, never foreign)."""
    return [n for n in LEGACY_NAMES
            if n in armature.data.bones
            and arm_util.is_system_bone(armature, n)]


def create_weapon_rig(context, armature):
    """Create (or complete, or migrate) the weapon rig. Returns report.

    Raises WeaponRigError for every failure case -- never fails silently
    (plan §54).
    """
    if armature is None or armature.type != 'ARMATURE':
        raise WeaponRigError("Auto-Rig Pro armature not found.")

    # Step 3: verify required ARP bones (hand IK; root resolves w/ fallback).
    errors = arm_util.validate_arp_requirements(armature)
    if errors:
        raise WeaponRigError(" ".join(errors))

    # Step 4/5: refuse foreign name conflicts (plan §38).
    conflicts = arm_util.conflicting_bones(armature)
    if conflicts:
        raise WeaponRigError(
            "Weapon bone name conflicts with an unrelated bone: %s. "
            "Rename or remove the conflicting bone, then retry."
            % ", ".join(conflicts))

    report = []
    legacy = _legacy_system_bones(armature)
    has_weapon = (BONE_WEAPON in armature.data.bones
                  and arm_util.is_system_bone(armature, BONE_WEAPON))
    if legacy and not has_weapon:
        # Pre-rework rig: fold it into the single-bone design.
        report.extend(_migrate_legacy_rig(context, armature, legacy))
    elif legacy and has_weapon:
        # Ambiguous user-surgery state: refuse rather than guess which
        # data wins (plan §54: clear error over silent destructive acts).
        raise WeaponRigError(
            "Stale pre-rework bones (%s) alongside the current '%s' "
            "bone. Delete the stale bones manually, then retry."
            % (", ".join(legacy), BONE_WEAPON))
    elif has_weapon:
        # Complete a partial rig (e.g. interrupted create), else refuse.
        if BONE_AIM not in armature.data.bones or \
                not arm_util.is_system_bone(armature, BONE_AIM):
            report.extend(_create_bones(context, armature, [BONE_AIM]))
        else:
            raise WeaponRigError("Weapon rig already exists.")
    else:
        report.extend(_create_fresh(context, armature))

    # Step 10: attachment constraints, influence 0 (plan §35 step 10, §9).
    for side in ("R", "L"):
        con_util.ensure_attach_constraint(armature, side)

    _ensure_weapon_collection(armature)

    # Step 11: validate (plan §35 step 11).
    from ..rig.validate import validate_weapon_rig
    ok, lines = validate_weapon_rig(armature)
    _restore_mode(armature, _prev_mode(armature), context)
    return ok, report + lines


def _prev_mode(armature):
    return armature.mode


def _create_bones(context, armature, names):
    """Create the named weapon bones from default layout. Returns lines.

    Used for fresh rigs (both bones) and for completing partial rigs
    (e.g. a lone missing aim bone). Metadata + grip defaults included.
    """
    from mathutils import Vector
    h = _hand_rest_head(armature)
    z = Vector((0.0, 0.0, 1.0))
    layout = {
        BONE_WEAPON: (h, h + z * 0.12),
        # Independent target (Damped Track would be an evaluation cycle
        # otherwise); shares the character root as parent. Placed beyond
        # the tip, aligned with the blade at rest, so an initial Point
        # Blade At is a no-op.
        BONE_AIM: (h + z * 1.40, h + z * 1.50),
    }
    char_root, root_status = arm_util.resolve_character_root(armature)
    prev_mode = armature.mode
    _make_active(context, armature)
    bpy_set_mode(armature, 'EDIT')
    try:
        ebones = armature.data.edit_bones
        for name in names:
            if name in ebones:
                continue
            head, tail = layout[name]
            eb = ebones.new(name)
            eb.head, eb.tail = head, tail
            eb.use_connect = False
            eb.use_deform = False
            if char_root is not None:
                eb.parent = ebones.get(char_root)
    finally:
        bpy_set_mode(armature, 'OBJECT')

    # Metadata + grip offsets + blade axis (addressable outside edit mode).
    roles = {BONE_WEAPON: "weapon", BONE_AIM: "aim"}
    for name in names:
        arm_util.mark_system_bone(armature, name, roles[name])
    wbone = armature.data.bones.get(BONE_WEAPON)
    if wbone is not None:
        wbone.use_deform = False
        if WEAPON_SLOT_KEY not in wbone:
            wbone[WEAPON_SLOT_KEY] = 0
        for prop, default in DEFAULT_GRIP_OFFSETS.items():
            if prop not in wbone:
                wbone[prop] = default
        if "blade_axis" not in wbone:
            wbone["blade_axis"] = "+Y"
    lines = ["Created: %s" % ", ".join(names),
             "Character root: %s" % _parent_note(armature, char_root,
                                                 root_status)]
    _restore_mode(armature, prev_mode, context)
    return lines


def _create_fresh(context, armature):
    """Create weapon + aim bones from defaults. Returns report lines."""
    return _create_bones(context, armature, [BONE_WEAPON, BONE_AIM])


def _parent_note(armature, char_root, root_status):
    if root_status == "ideal":
        return "parented under '%s'" % char_root
    if root_status == "fallback":
        return ("no '%s' bone: parented under fallback '%s' "
                "(weapon still follows character motion)"
                % (CHARACTER_ROOT_BONE, char_root))
    return ("no '%s' or fallback bone found %s: weapon left at armature "
            "level (works in Blender; will NOT follow root motion on "
            "export -- see report)"
            % (CHARACTER_ROOT_BONE,
               arm_util.root_like_candidates(armature)))


def _migrate_legacy_rig(context, armature, legacy):
    """Fold a pre-rework rig into the single-bone design. Returns report.

    Preserved: grip/tip rest layout (-> local offsets), blade_axis,
    weapon_root pose channels, fcurve/driver paths, attach states,
    preview relationship. Removed: the five legacy bones.
    """
    lines = ["Migrating legacy rig (%s) to single-bone '%s'..."
             % (", ".join(legacy), BONE_WEAPON)]
    data = armature.data

    # 1. Read everything BEFORE touching anything.
    legacy_root = data.bones.get("weapon_root")
    root_rest_head = Vector(legacy_root.head_local) \
        if legacy_root is not None else _hand_rest_head(armature)
    root_rest_tail = Vector(legacy_root.tail_local) \
        if legacy_root is not None else root_rest_head + Vector((0, 0, 0.12))
    root_channels = None
    if "weapon_root" in armature.pose.bones:
        prb = armature.pose.bones["weapon_root"]
        root_channels = (tuple(prb.location),
                         tuple(prb.rotation_quaternion)
                         if prb.rotation_mode == 'QUATERNION'
                         else tuple(prb.rotation_euler),
                         prb.rotation_mode,
                         tuple(prb.scale))
    # Grip rest heads -> weapon-local offsets (legacy grips pointed +Z
    # like the root, so armature-space delta == local delta here; solved
    # properly through the rest matrices to stay correct regardless).
    offsets = {}
    if legacy_root is not None:
        root_rest_inv = legacy_root.matrix_local.inverted()
        for bone_name, prop in (("weapon_grip_r", GRIP_PROP_R),
                                ("weapon_grip_l", GRIP_PROP_L),
                                ("weapon_tip", TIP_PROP)):
            bone = data.bones.get(bone_name)
            if bone is not None:
                offsets[prop] = tuple(
                    (root_rest_inv @ bone.matrix_local).translation)
    blade_axis = (legacy_root.get("blade_axis", "+Y")
                  if legacy_root is not None else "+Y")
    # Capture attached hands' worlds BEFORE retargeting (retargeting
    # alone would jump them; preserve_attached_hands re-glues them after).
    attached = {}
    for side, hand in (("R", "c_hand_ik.r"), ("L", "c_hand_ik.l")):
        con = con_util.find_attach_constraint(armature, side)
        if con is not None and con.influence > 0.0:
            dg = armature.evaluated_get(
                bpy.context.evaluated_depsgraph_get())
            attached[side] = (armature.matrix_world
                              @ dg.pose.bones[hand].matrix).copy()

    # 2. Create the weapon bone at the legacy root's rest transform.
    char_root, root_status = arm_util.resolve_character_root(armature)
    prev_mode = armature.mode
    _make_active(context, armature)
    bpy_set_mode(armature, 'EDIT')
    try:
        ebones = armature.data.edit_bones
        if BONE_WEAPON not in ebones:
            eb = ebones.new(BONE_WEAPON)
            eb.head, eb.tail = root_rest_head, root_rest_tail
            eb.use_connect = False
            eb.use_deform = False
            if char_root is not None:
                eb.parent = ebones.get(char_root)
        # 3. Delete legacy bones (their data is captured above).
        for name in legacy:
            eb = ebones.get(name)
            if eb is not None:
                armature.data.edit_bones.remove(eb)
    finally:
        bpy_set_mode(armature, 'OBJECT')

    # 4. Metadata, grip offsets, blade axis, pose channels.
    arm_util.mark_system_bone(armature, BONE_WEAPON, "weapon")
    wbone = armature.data.bones.get(BONE_WEAPON)
    wbone.use_deform = False
    wbone[WEAPON_SLOT_KEY] = 0
    for prop, default in DEFAULT_GRIP_OFFSETS.items():
        wbone[prop] = offsets.get(prop, default)
    wbone["blade_axis"] = blade_axis \
        if blade_axis in ("+X", "-X", "+Y", "-Y", "+Z", "-Z") else "+Y"
    if root_channels is not None:
        loc, rot, mode, scl = root_channels
        prb = armature.pose.bones[BONE_WEAPON]
        prb.location = loc
        prb.scale = scl
        if mode == 'QUATERNION' and prb.rotation_mode == 'QUATERNION':
            prb.rotation_quaternion = rot
        elif mode != 'QUATERNION' and prb.rotation_mode != 'QUATERNION':
            prb.rotation_euler = rot
        # (rotation-mode switches across the rework are not migrated;
        # orientation within one mode transfers exactly.)

    # 5. Retarget attach constraints + rename fcurve/driver paths.
    _retarget_constraints(armature)
    n_paths = _rename_bone_paths(armature, "weapon_root", BONE_WEAPON)
    lines.append("fcurve/driver paths retargeted: %d" % n_paths)

    # 6. Re-parent preview mesh if it followed a legacy bone.
    from ..weapon.preview import get_preview_object, set_preview_mesh
    preview = get_preview_object(armature)
    if preview is not None:
        try:
            set_preview_mesh(armature, preview)
            lines.append("preview mesh re-parented to '%s'" % BONE_WEAPON)
        except Exception as exc:  # keep prop, report; never fail migration
            lines.append("preview re-parent skipped: %s" % exc)

    # 7. Re-glue hands that were attached (inverse re-solve, no pop).
    if attached:
        con_util.preserve_attached_hands(armature, attached)
        for side in attached:
            lines.append("re-attached %s without moving it" % side)

    lines.append("Character root: %s"
                 % _parent_note(armature, char_root, root_status))
    _restore_mode(armature, prev_mode, context)
    return lines


def _retarget_constraints(armature):
    """Point our attach constraints at the weapon bone (post-migration)."""
    from ..constants import ATTACH_CONSTRAINT, HAND_BONES
    from ..constants import SIDES
    for side in SIDES:
        pbone = armature.pose.bones.get(HAND_BONES[side])
        if pbone is None:
            continue
        con = pbone.constraints.get(ATTACH_CONSTRAINT[side])
        if con is not None and con.type == 'CHILD_OF':
            con.target = armature
            con.subtarget = BONE_WEAPON


def _rename_bone_paths(armature, old, new):
    """Rename pose.bones["old"] fcurve/driver paths to the new bone.

    Keeps animation on the weapon control alive across the rework (plan
    §29: existing animation must not be destroyed). Only touches paths
    that start with the exact bone reference. Returns count changed.
    """
    old_prefix = 'pose.bones["%s"]' % old
    new_prefix = 'pose.bones["%s"]' % new
    changed = 0
    for action in bpy.data.actions:
        # Slotted (4.4+) layout...
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                if getattr(strip, "type", "") != 'KEYFRAME':
                    continue
                try:
                    bags = list(strip.channelbags)
                except Exception:
                    continue
                for cb in bags:
                    for fcu in cb.fcurves:
                        if fcu.data_path.startswith(old_prefix):
                            fcu.data_path = new_prefix + \
                                fcu.data_path[len(old_prefix):]
                            changed += 1
        # ...plus legacy pre-slotted actions (no layers API).
        for fcu in getattr(action, "fcurves", []) or []:
            if fcu.data_path.startswith(old_prefix):
                fcu.data_path = new_prefix + fcu.data_path[len(old_prefix):]
                changed += 1
    ad = armature.animation_data
    if ad is not None:
        for driver in getattr(ad, "drivers", []) or []:
            if driver.data_path.startswith(old_prefix):
                driver.data_path = new_prefix + \
                    driver.data_path[len(old_prefix):]
                changed += 1
            for var in driver.driver.variables:
                for tgt in var.targets:
                    if getattr(tgt, "bone_target", "") == old:
                        tgt.bone_target = new
                        changed += 1
    return changed


def _ensure_weapon_collection(armature):
    """Get-or-create the 'Weapon Rig' bone collection and assign all
    weapon bones (plan §34: isolation toggle works on data-bone hide
    flags; the collection keeps them organized in the outliner)."""
    from ..constants import ALL_WEAPON_BONES
    colls = armature.data.collections
    coll = colls.get("Weapon Rig")
    if coll is None:
        coll = colls.new("Weapon Rig")
    for name in ALL_WEAPON_BONES:
        bone = armature.data.bones.get(name)
        if bone is None:
            continue
        try:
            coll.assign(bone)
        except RuntimeError:
            pass  # already a member -- assign raises on duplicates


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------

def bpy_set_mode(armature, mode):
    bpy.ops.object.mode_set(mode=mode)


def _make_active(context, armature):
    view_layer = context.view_layer
    if view_layer.objects.active is not armature:
        # Deselect-all is required by mode_set when switching objects.
        for obj in context.selected_objects:
            obj.select_set(False)
        armature.select_set(True)
        view_layer.objects.active = armature


def _restore_mode(armature, prev_mode, context):
    if armature.mode != prev_mode:
        try:
            bpy.ops.object.mode_set(mode=prev_mode)
        except RuntimeError:
            pass  # mode already correct or not switchable -- non-fatal
