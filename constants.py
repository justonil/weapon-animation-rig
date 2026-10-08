"""Shared constants for the Weapon Animation Rig add-on.

WHY this exists (plan §37, §38):
Bone names and constraint names are the public contract of the system -- they
end up in exported skeletons (Unreal) and in animator muscle memory. Keeping
them in one place prevents drift between rig creation, validation, attach and
detach code paths. All names use the consistent ``weapon_*`` convention
(plan §38, "choose one naming convention and use it consistently").

SPACES / transform conventions (plan §40, §56):
No transform math lives here. See utils/transforms.py for the space contract.
"""

# ---------------------------------------------------------------------------
# System identification (plan §37)
# ---------------------------------------------------------------------------
SYSTEM_ID = "weapon_animation_rig"
ROLE_KEY = "weapon_rig_role"

# Roles stored in bone custom properties.
ROLE_WEAPON = "weapon"
ROLE_AIM = "aim"

# Legacy roles (pre-rework rigs; recognized by migration only).
ROLE_ROOT = "root"             # legacy: old weapon_root
ROLE_SOCKET = "socket"         # legacy
ROLE_GRIP_R = "grip_r"          # legacy
ROLE_GRIP_L = "grip_l"          # legacy
ROLE_TIP = "tip"               # legacy

# ---------------------------------------------------------------------------
# Bone names (plan §2, §6 -- export-critical names)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Weapon bones (rework: ONE export/control bone, plan §2 roles kept minimal)
# ---------------------------------------------------------------------------
# The whole weapon system is a single bone: it is BOTH the animator control
# AND the export bone (Unreal attaches the Static Mesh to it directly).
# Grip/tip positions are bone-local vectors in custom properties, not
# bones: attach-follow math is identical either way (grip deltas of a
# rigid child always equal the parent's delta), and pivots/snaps only ever
# needed the POSITIONS. Second weapon later = second bone + slot id.
BONE_WEAPON = "weapon"
BONE_AIM = "weapon_aim"            # aim target (plan §5)

WEAPON_BONES = (
    (BONE_WEAPON, ROLE_WEAPON),
    (BONE_AIM, ROLE_AIM),
)

# Legacy bone names from the pre-rework 6-bone rig (auto-migrated on
# Create; never created anymore).
LEGACY_BONES = (
    ("weapon_root", ROLE_ROOT),
    ("weapon_socket", ROLE_SOCKET),
    ("weapon_grip_r", ROLE_GRIP_R),
    ("weapon_grip_l", ROLE_GRIP_L),
    ("weapon_tip", ROLE_TIP),
)
LEGACY_NAMES = tuple(name for name, _ in LEGACY_BONES)

# All weapon bones, for visibility toggles and collection assignment
# (plan §34).
ALL_WEAPON_BONES = (BONE_WEAPON, BONE_AIM)

# Grip/tip reference points, stored as bone-LOCAL vectors in custom
# properties on the weapon bone (replacing the old grip/tip bones).
# Local frame: bone origin at head, +Y along the bone toward the tail.
# Defaults reproduce the original two-handed layout (grip_l 0.15 above
# grip_r along the blade, tip 1.1 above).
GRIP_PROP_R = "grip_r"
GRIP_PROP_L = "grip_l"
GUARD_PROP_L = "guard_l"
GUARD_PROP_R = "guard_r"
POMMEL_PROP = "pommel"
CENTER_PROP = "center"
TIP_PROP = "tip"
GRIP_PROPS = {"R": GRIP_PROP_R, "L": GRIP_PROP_L}
# Every configurable weapon point (rework follow-up: guard/pommel/center
# are explicit data, not mirrored heuristics -- mirroring assumed a fixed
# handle geometry and was wrong on real swords).
CONFIG_PROPS = (GRIP_PROP_R, GRIP_PROP_L, GUARD_PROP_L, GUARD_PROP_R,
                POMMEL_PROP, CENTER_PROP, TIP_PROP)
DEFAULT_GRIP_OFFSETS = {
    GRIP_PROP_R: (0.0, 0.0, 0.0),
    GRIP_PROP_L: (0.0, 0.15, 0.0),
    # Crossguard bar just above the upper hand, ~14 cm wide.
    GUARD_PROP_L: (-0.07, 0.19, 0.0),
    GUARD_PROP_R: (0.07, 0.19, 0.0),
    # Pommel knob just below the lower hand.
    POMMEL_PROP: (0.0, -0.06, 0.0),
    # Mass center between pommel and tip (placeholder; tune per weapon).
    CENTER_PROP: (0.0, 0.52, 0.0),
    TIP_PROP: (0.0, 1.10, 0.0),
}

# Weapon slot id (custom prop on the weapon bone). Slot 0 is the only one
# used today; a second weapon later = second bone carrying slot 1, and all
# lookups below already take the slot.
WEAPON_SLOT_KEY = "weapon_slot"
DEFAULT_BLADE_AXIS = "+Y"

# ---------------------------------------------------------------------------
# ARP bones the add-on depends on (plan §7)
# ---------------------------------------------------------------------------
# Expected hand IK controllers of a *generated* ARP rig. The ARP reference
# armature does not contain c_* controller bones, so the presence of these
# two bones doubles as the "is this a generated rig?" test (plan §35 step 2).
HAND_BONES = {"R": "c_hand_ik.r", "L": "c_hand_ik.l"}
# Character root the weapon bone is parented under (plan §3.1).
CHARACTER_ROOT_BONE = "root"
# Fallback parents when `root` is absent (some rigs only carry the ARP
# master control). Order matters: first present wins. The weapon still
# functions fully in Blender when unparented, but then it will NOT follow
# character/root motion -- hence a validation warning, not silence.
CHARACTER_ROOT_FALLBACKS = ("c_root_master",)
# ARP's own data files notate center bones with a '.x' suffix
# (auto_rig_datas.py: 'root':'root.x', 'c_root_master':'c_root_master.x'),
# and some generated rigs keep that suffix literally (seen in the wild:
# 'root.x', 'c_root_master.x'). A trailing '.x' on an otherwise exact
# root name is therefore the SAME bone role, not a guess.
ROOT_SUFFIX_VARIANTS = ("", ".x")

# ---------------------------------------------------------------------------
# Attachment constraints (plan §8, §9)
# ---------------------------------------------------------------------------
# Dedicated, per-side, always-reused constraints. The operators must find
# these by name and never create duplicates (plan §41).
ATTACH_CONSTRAINT = {"R": "WPN_Attach_R", "L": "WPN_Attach_L"}
SIDES = ("R", "L")

# High-level attachment modes (plan §13).
MODES = {
    "FREE":  {"R": False, "L": False},
    "RIGHT": {"R": True,  "L": False},
    "LEFT":  {"R": False, "L": True},
    "BOTH":  {"R": True,  "L": True},
}

# Bone-local blade axis tags: vector + Damped Track axis enum.
# (plan §47: configurable per weapon, exposed but never hardcoded.)
from mathutils import Vector as _Vector

BLADE_AXES = {
    '+X': (_Vector((1, 0, 0)), 'TRACK_X'),
    '-X': (_Vector((-1, 0, 0)), 'TRACK_NEGATIVE_X'),
    '+Y': (_Vector((0, 1, 0)), 'TRACK_Y'),
    '-Y': (_Vector((0, -1, 0)), 'TRACK_NEGATIVE_Y'),
    '+Z': (_Vector((0, 0, 1)), 'TRACK_Z'),
    '-Z': (_Vector((0, 0, -1)), 'TRACK_NEGATIVE_Z'),
}

# ---------------------------------------------------------------------------
# Tolerances (plan §30)
# ---------------------------------------------------------------------------
TOL_TRANSLATION = 0.0001   # Blender units
TOL_ROTATION_DEG = 0.01    # degrees

# Above this hand-to-grip distance (Blender units ~meters) the hand is
# clearly NOT holding the weapon. Attach/snap still succeed (pose
# preserved), but operators warn: attach glues in place and snap displaces
# attached followers, so operating at a large offset is usually a workflow
# mistake (attach/snap first, then attach -- not the reverse).
GRIP_DISTANCE_WARN = 0.30

# ---------------------------------------------------------------------------
# Errors (plan §54 -- never fail silently, always name the missing element)
# ---------------------------------------------------------------------------
class WeaponRigError(Exception):
    """User-facing error. Operators catch this and report it via self.report."""


def no_arp_armature():
    return WeaponRigError("Auto-Rig Pro armature not found.")


def missing_bone(name):
    return WeaponRigError("Required ARP bone %s was not found." % name)


def missing_weapon_bone(name):
    return WeaponRigError("Cannot attach hand because %s is missing." % name)
