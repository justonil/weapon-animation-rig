"""Armature detection and metadata helpers (plan §7, §35, §37).

Detection contract (plan §7, §35):
- A *generated* ARP rig is identified by the presence of its hand IK
  controllers ``c_hand_ik.r`` / ``c_hand_ik.l``. The ARP reference armature
  contains only ``*_ref`` bones, so this test cleanly separates
  "generated rig" from "reference armature" (plan §35 step 2).
- If an armature is found but a required bone is missing, we raise a
  precise error naming the bone (plan §54) instead of guessing.

Metadata contract (plan §37):
- Identity is stored in bone custom properties (``weapon_rig_system`` /
  ``weapon_rig_role``), NOT derived from names alone. Names are kept
  predictable but the properties are authoritative -- that is what lets us
  distinguish "weapon from this system" from "an unrelated bone that
  happens to be called weapon" (plan §38).
"""
from ..constants import (
    CHARACTER_ROOT_BONE,
    CHARACTER_ROOT_FALLBACKS,
    HAND_BONES,
    ROLE_KEY,
    ROOT_SUFFIX_VARIANTS,
    SIDES,
    SYSTEM_ID,
    WEAPON_BONES,
    missing_bone,
    no_arp_armature,
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def find_generated_rig(context):
    """Return the generated ARP armature, or raise with a precise message.

    Preference order: active object, then selected objects, then any object
    in the scene. Only armatures carrying both hand IK controllers qualify.
    """
    candidates = []
    active = context.view_layer.objects.active
    if active is not None:
        candidates.append(active)
    candidates.extend(o for o in context.selected_objects if o not in candidates)
    candidates.extend(o for o in context.scene.objects if o not in candidates)

    armature = None
    for obj in candidates:
        if obj.type != 'ARMATURE':
            continue
        if _has_hand_ik(obj):
            return obj
        if armature is None:
            armature = obj  # remember an armature without hand IK for errors

    if armature is None:
        raise no_arp_armature()
    # An armature exists but lacks the hand IK controllers -> either a
    # reference armature or a non-ARP rig. Name the missing element.
    raise missing_bone(HAND_BONES["R"])


def _has_hand_ik(armature):
    return all(name in armature.data.bones for name in HAND_BONES.values())


def validate_arp_requirements(armature):
    """Verify all ARP bones the system needs (plan §35 step 3).

    Returns a list of error strings (empty == OK) so callers can decide
    whether to raise or to fold the messages into a validation report.

    Only the hand IK controllers are fatal: without them there is nothing
    to attach. A missing character root is NOT fatal -- create falls back
    to c_root_master (or armature level) and validation reports exactly
    which parent is in effect, so a rig is never brick-walled by naming.
    """
    errors = []
    for side in SIDES:
        name = HAND_BONES[side]
        if name not in armature.data.bones:
            errors.append("Required ARP bone %s was not found." % name)
    return errors


def _root_variants(base_name):
    """Yield 'base' then 'base.x' -- ARP's center-bone notation."""
    for suffix in ROOT_SUFFIX_VARIANTS:
        yield base_name + suffix


def resolve_character_root(armature):
    """Find the bone the weapon bone should hang under.

    Returns (bone_name_or_None, status) where status is one of:
      "ideal"    -- the character root deform bone ('root' or ARP's own
                     'root.x' notation) present, plan §3.1 path
      "fallback" -- only a fallback (e.g. ARP master control, with or
                     without the .x suffix) present
      "missing"  -- nothing root-like; the weapon stays armature-level
    """
    for variant in _root_variants(CHARACTER_ROOT_BONE):
        if variant in armature.data.bones:
            return variant, "ideal"
    for fallback in CHARACTER_ROOT_FALLBACKS:
        for variant in _root_variants(fallback):
            if variant in armature.data.bones:
                return variant, "fallback"
    return None, "missing"


def root_like_candidates(armature, limit=6):
    """Bone names containing 'root' -- shown to help diagnose a missing
    character root (plan §54: errors must identify the missing element
    AND help the user find what they have instead)."""
    found = [b.name for b in armature.data.bones
             if "root" in b.name.lower()]
    # Most plausible first: exact-ish matches, then shortest names.
    found.sort(key=lambda n: (n.lower() != "root",
                              n.lower() not in ("root", "c_root_master"),
                              len(n)))
    return found[:limit]


# ---------------------------------------------------------------------------
# Metadata (plan §37)
# ---------------------------------------------------------------------------

def is_system_bone(armature, bone_name):
    """True iff the bone carries this system's identity marker."""
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        return False
    return bone.get("weapon_rig_system") == SYSTEM_ID


def get_bone_role(armature, bone_name):
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        return None
    return bone.get(ROLE_KEY)


def mark_system_bone(armature, bone_name, role):
    """Stamp identity onto a data bone (must run OUTSIDE edit mode -- data
    bones are not addressable until edit mode is left, probe-verified)."""
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise KeyError("bone %r not found" % bone_name)
    bone["weapon_rig_system"] = SYSTEM_ID
    bone[ROLE_KEY] = role


def weapon_bone_exists(armature, bone_name):
    return bone_name in armature.data.bones


def existing_system_bones(armature):
    """Names of all bones already belonging to this system."""
    out = []
    for bone_name, _role in WEAPON_BONES:
        if is_system_bone(armature, bone_name):
            out.append(bone_name)
    return out


def conflicting_bones(armature):
    """Bones that use a reserved name but are NOT ours (plan §38).

    These must never be silently renamed or overwritten -- the operator
    reports the conflict instead.
    """
    out = []
    for bone_name, _role in WEAPON_BONES:
        if bone_name in armature.data.bones and not is_system_bone(armature, bone_name):
            out.append(bone_name)
    return out
