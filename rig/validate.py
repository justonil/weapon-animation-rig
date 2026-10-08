"""Rig validation (plan §36, reworked: ONE export/control bone).

Produces the human-readable checklist:

    Weapon Rig Validation

    ✓ ARP armature
    ✓ Right Hand IK
    ...
    Result: VALID

Checks are pure reads -- validation never mutates the scene (plan §29).

A pre-rework rig (legacy weapon_root/socket/grips/tip with our marker but
no `weapon` bone) is reported as INVALID with an explicit pointer to
Create-to-migrate, never silently accepted (plan §54).
"""
from ..constants import (
    ATTACH_CONSTRAINT,
    BONE_AIM,
    BONE_WEAPON,
    CENTER_PROP,
    CHARACTER_ROOT_BONE,
    GRIP_PROPS,
    GUARD_PROP_L,
    GUARD_PROP_R,
    HAND_BONES,
    LEGACY_NAMES,
    POMMEL_PROP,
    TIP_PROP,
)
from ..utils import armature as arm_util
from ..utils import constraints as con_util


def validate_weapon_rig(armature):
    """Return (is_valid, lines). ``lines`` is ready for display/report."""
    checks = []  # (ok, label)

    is_armature = armature is not None and armature.type == 'ARMATURE'
    checks.append((is_armature, "ARP armature"))
    if not is_armature:
        return False, _format(checks)

    for side, label in (("R", "Right Hand IK"), ("L", "Left Hand IK")):
        name = HAND_BONES[side]
        exists = name in armature.data.bones
        checks.append((exists, label))
        if not exists:
            # Remaining checks would be noise; report what we have.
            return False, _format(checks)

    # Character root for parenting (plan §3.1, with fallback chain).
    char_root, root_status = arm_util.resolve_character_root(armature)
    if root_status == "ideal":
        checks.append((True, "root bone"))
    elif root_status == "fallback":
        checks.append((True, "root bone (fallback '%s' in use -- no '%s')"
                       % (char_root, CHARACTER_ROOT_BONE)))
    else:
        candidates = arm_util.root_like_candidates(armature)
        hint = ("root-like bones: %s" % ", ".join(candidates)) \
            if candidates else "no root-like bones at all"
        checks.append((False, "root bone (missing; %s)" % hint))

    # Pre-rework rig still present: point at migration, don't validate half.
    legacy = [n for n in LEGACY_NAMES
              if n in armature.data.bones
              and arm_util.is_system_bone(armature, n)]
    if legacy and BONE_WEAPON not in armature.data.bones:
        checks.append((False, "pre-rework rig (%s) -- run Create to migrate"
                       % ", ".join(legacy)))
        return False, _format(checks)

    # The weapon bone: exists, ours, non-deform, parented correctly,
    # grip/tip/blade config present.
    weapon = armature.data.bones.get(BONE_WEAPON)
    ours = weapon is not None and arm_util.is_system_bone(
        armature, BONE_WEAPON)
    checks.append((ours, BONE_WEAPON))
    if weapon is not None and not ours:
        checks.append((False, "%s (name conflict: not a weapon-rig bone)"
                       % BONE_WEAPON))
    if ours:
        checks.append((not weapon.use_deform,
                       "%s non-deform (export control)" % BONE_WEAPON))
        parent = weapon.parent.name if weapon.parent else None
        checks.append((parent == char_root,
                       "%s parenting (parent=%s%s)"
                       % (BONE_WEAPON, parent,
                          "" if parent == char_root
                          else " -- expected %s" % char_root)))
        for prop in (GRIP_PROPS["R"], GRIP_PROPS["L"],
                     GUARD_PROP_L, GUARD_PROP_R, POMMEL_PROP,
                     CENTER_PROP, TIP_PROP, "blade_axis"):
            checks.append((prop in weapon,
                           "%s config '%s'" % (BONE_WEAPON, prop)))

    # Aim target: exists, ours, independent of the weapon bone (a
    # weapon-parented aim would be an evaluation cycle for live tracking).
    aim = armature.data.bones.get(BONE_AIM)
    aim_ours = aim is not None and arm_util.is_system_bone(
        armature, BONE_AIM)
    checks.append((aim_ours, BONE_AIM))
    if aim_ours:
        parent = aim.parent.name if aim.parent else None
        checks.append((parent == char_root,
                       "%s parenting (parent=%s%s, must stay independent)"
                       % (BONE_AIM, parent,
                          "" if parent == char_root
                          else " -- expected %s" % char_root)))

    # Attachment constraints (plan §9): exactly one per side, CHILD_OF,
    # targeting armature + the weapon bone, no duplicates (plan §41).
    for side in ("R", "L"):
        con_name = ATTACH_CONSTRAINT[side]
        hand = HAND_BONES[side]
        pbone = armature.pose.bones.get(hand)
        count = con_util.count_attach_constraints(armature, side)
        label = "%s on %s" % (con_name, hand)
        if pbone is None or count == 0:
            checks.append((False, label + " (missing)"))
            continue
        if count > 1:
            checks.append((False, label + " (DUPLICATE x%d)" % count))
            continue
        con = pbone.constraints.get(con_name)
        problems = []
        if con.type != 'CHILD_OF':
            problems.append("type=%s" % con.type)
        if con.target is not armature:
            problems.append("target=%s" % (con.target.name if con.target else "None"))
        if con.subtarget != BONE_WEAPON:
            problems.append("subtarget=%s (expected %s)"
                            % (con.subtarget, BONE_WEAPON))
        checks.append((not problems,
                       label + (" OK" if not problems else
                                " (%s)" % "; ".join(problems))))

    return all(ok for ok, _ in checks), _format(checks)


def _format(checks):
    lines = ["Weapon Rig Validation", ""]
    for ok, label in checks:
        lines.append("%s %s" % ("✓" if ok else "✗", label))
    valid = all(ok for ok, _ in checks)
    lines.append("")
    lines.append("Result: %s" % ("VALID" if valid else "INVALID"))
    return lines
