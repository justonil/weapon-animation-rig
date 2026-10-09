"""Child Of constraint management (plan §8, §9, §10, §11, §41).

WHY Child Of and not parenting (plan §8, §57):
The ARP hand IK controllers must keep their place in the ARP hierarchy and
their own animation. A Child Of constraint has (a) animatable Influence and
(b) an inverse matrix, so we can attach/detach WITHOUT touching the armature
hierarchy and WITHOUT reparenting anything ARP owns. Detaching leaves the
constraint in place at influence 0 (plan §11 -- never delete on detach).

WHY we never create duplicates (plan §41):
Attach is a toggle pressed many times per shot. The constraint is looked up
by its dedicated name and reused; creation happens at most once.

CONSTRAINT STACK ORDER (plan §43):
The weapon constraint is appended at the END of the hand's stack. Rationale:
ARP controllers may already carry Child Of constraints (ARP's own Child Of
switcher for props/weapons). Appending last means our influence applies on
top of ARP's result, which is exactly the intended stack (plan §14):
    Weapon Grip -> (ARP constraints) -> hand IK controller
The attach/detach math below is order-independent for constraints *above*
us because we always measure the fully-evaluated matrix with our own
influence at 0 (that measured matrix IS the "P" base).

THE MATH (probe-verified on Blender 5.2 during development):
For a Child Of constraint with default target/owner spaces, the evaluated
armature-space result is:

    R = T @ Inv @ P

where T = target bone arm-space matrix, Inv = inverse_matrix (as set on the
constraint), P = the owner matrix the constraint multiplies into (i.e. the
evaluated matrix of the owner with OUR influence at 0 -- everything ARP did
above us is already baked into P).

Attach (preserve world transform, plan §10):
    W_before = world matrix of hand (any influence state)
    P = evaluated arm matrix with our influence forced to 0
    T = evaluated arm matrix of grip (influence irrelevant, grips have no
        constraints)
    We want R such that arm_world @ R == W_before  =>  R = Mw^-1 @ W_before
    Solve:  Inv = T^-1 @ (Mw^-1 @ W_before) @ P^-1
    Then set influence 1, verify |world_after - world_before| < tolerance.

Detach (preserve world transform, plan §11):
    W_before = world matrix of hand (influence 1)
    set influence 0 -> hand jumps to P (its plain local result)
    restore: set pose bone matrix (arm space) to Mw^-1 @ W_before.
    Blender solves the underlying loc/rot channels for us. We do NOT touch
    the constraint's inverse -- reattaching later re-solves it anyway.

NOTE (plan §10 mentions bpy.ops.constraint.child_of_inverse_set): that
operator does not exist in Blender 5.2 (probe-verified). The solve above is
our own equivalent; we also verify numerically after every operation, so a
future API change degrades into a reported error instead of a silent pop.
"""
import bpy

from ..constants import (
    ATTACH_CONSTRAINT,
    BONE_WEAPON,
    GRIP_PROPS,
    HAND_BONES,
    TIP_PROP,
    TOL_TRANSLATION,
    WEAPON_SLOT_KEY,
    WeaponRigError,
    missing_weapon_bone,
)
from . import transforms


# ---------------------------------------------------------------------------
# Weapon + grip resolution (rework: ONE export/control bone)
# ---------------------------------------------------------------------------

def get_weapon_bone(armature, slot=0):
    """Resolve the weapon control/export bone (plan: ONE export bone).

    Preferred by metadata (role + system marker + slot id), so a rename
    never silently resolves to the wrong bone; falls back to the canonical
    name. ``slot`` is the two-weapons-later hook (slot 0 = the weapon).

    BACKWARD COMPAT: on a pre-rework rig (no `weapon` bone) resolves the
    legacy `weapon_root` -- but ONLY if it carries our system marker
    (a foreign bone of that name must never drive anything). Legacy
    follow math is exact (same rigid delta); grip offsets fall back to
    defaults (exact for default-built rigs -- migrate for exactness).
    Raises WeaponRigError when no weapon bone exists.
    """
    for bone in armature.data.bones:
        if bone.get("weapon_rig_system") != "weapon_animation_rig":
            continue
        if bone.get("weapon_rig_role") != "weapon":
            continue
        if int(bone.get(WEAPON_SLOT_KEY, 0)) == slot:
            return bone.name
    legacy = armature.data.bones.get("weapon_root")
    if legacy is not None and \
            legacy.get("weapon_rig_system") == "weapon_animation_rig" and \
            legacy.get("weapon_rig_role") == "root":
        return "weapon_root"
    raise missing_weapon_bone(BONE_WEAPON)


def grip_offset(armature, side):
    """Grip reference point in weapon-bone LOCAL space (a Vector).

    Stored in custom properties, not bones: attach-follow math is
    identical either way (a rigid child's deltas always equal the parent
    bone's delta), and snaps/pivots only ever needed the POSITIONS.
    """
    from mathutils import Vector
    weapon = get_weapon_bone(armature)
    bone = armature.data.bones.get(weapon)
    prop = GRIP_PROPS[side]
    if bone is not None and prop in bone:
        return Vector(tuple(bone[prop]))
    from ..constants import DEFAULT_GRIP_OFFSETS
    return Vector(DEFAULT_GRIP_OFFSETS[prop])


def tip_offset(armature):
    """Blade-tip reference point in weapon-bone LOCAL space."""
    from mathutils import Vector
    weapon = get_weapon_bone(armature)
    bone = armature.data.bones.get(weapon)
    if bone is not None and TIP_PROP in bone:
        return Vector(tuple(bone[TIP_PROP]))
    from ..constants import DEFAULT_GRIP_OFFSETS
    return Vector(DEFAULT_GRIP_OFFSETS[TIP_PROP])


def set_grip_from_world(armature, prop, world_pos):
    """Move a grip/tip reference point onto a world position (config).

    Solves the bone-local offset for ``prop`` (one of grip_r/grip_l/tip)
    so its world lands on ``world_pos``, writes it to the custom prop,
    and verifies. Pose channels, keys and animation are untouched --
    this edits weapon CONFIGURATION, the thing presets store.
    Raises WeaponRigError on mismatch.
    """
    from mathutils import Vector
    weapon = get_weapon_bone(armature)
    dg = transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    pbone = eval_arm.pose.bones.get(weapon)
    if pbone is None:
        raise missing_weapon_bone(weapon)
    weapon_world = eval_arm.matrix_world @ pbone.matrix
    local = weapon_world.inverted() @ Vector(world_pos)
    bone = armature.data.bones.get(weapon)
    bone[prop] = (local.x, local.y, local.z)
    transforms.update_view_layer()
    # Verify through the same path readers use (plan §30): re-resolve
    # the stored prop to world and compare with the requested target.
    wbone = armature.data.bones.get(weapon)
    got = eval_arm.matrix_world @ pbone.matrix @ Vector(tuple(wbone[prop]))
    err = (got - Vector(world_pos)).length
    if err > TOL_TRANSLATION:
        raise WeaponRigError(
            "Grip point '%s' missed target by %.6f." % (prop, err))
    return tuple(bone[prop])


def grip_world(armature, side, depsgraph=None):
    """Grip reference FRAME (world): weapon orientation at grip position.

    Rotation comes from the weapon bone itself (grips were axis-aligned
    children, so this is exactly the old grip-bone frame); translation is
    the grip offset mapped to world. Suitable for delta math.
    """
    weapon = get_weapon_bone(armature)
    dg = depsgraph or transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    pbone = eval_arm.pose.bones.get(weapon)
    if pbone is None:
        raise missing_weapon_bone(weapon)
    world = eval_arm.matrix_world @ pbone.matrix
    frame = world.copy()
    frame.translation = world @ grip_offset(armature, side)
    return frame


def tip_world(armature, depsgraph=None):
    """Blade-tip reference FRAME (world): weapon orientation at tip."""
    weapon = get_weapon_bone(armature)
    dg = depsgraph or transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    pbone = eval_arm.pose.bones.get(weapon)
    if pbone is None:
        raise missing_weapon_bone(weapon)
    world = eval_arm.matrix_world @ pbone.matrix
    frame = world.copy()
    frame.translation = world @ tip_offset(armature)
    return frame


# ---------------------------------------------------------------------------
# Lookup / creation (plan §41 -- deterministic, never duplicating)
# ---------------------------------------------------------------------------

def find_attach_constraint(armature, side):
    """Return the dedicated WPN_Attach_* constraint or None.

    Searches the hand IK controller's stack by exact name and verifies it
    is actually a CHILD_OF (a name clash must not be silently reused).
    """
    pbone = armature.pose.bones.get(HAND_BONES[side])
    if pbone is None:
        return None
    con = pbone.constraints.get(ATTACH_CONSTRAINT[side])
    if con is None:
        return None
    if con.type != 'CHILD_OF':
        raise WeaponRigError(
            "Constraint %s on %s exists but is not a Child Of constraint "
            "(found %s) -- refusing to reuse it."
            % (ATTACH_CONSTRAINT[side], HAND_BONES[side], con.type))
    return con


def ensure_attach_constraint(armature, side):
    """Find or create the dedicated constraint; returns (constraint, created).

    Never creates a second one: lookup happens first (plan §41). The
    target is ALWAYS the current weapon bone: a constraint left pointing
    at a legacy grip bone (pre-rework rigs) is retargeted, because
    attaching through a deleted/stale bone would silently break the
    follow. Retargeting with influence 0 cannot change the pose.
    """
    weapon = get_weapon_bone(armature)
    existing = find_attach_constraint(armature, side)
    if existing is not None:
        if existing.subtarget != weapon:
            # Stale target (e.g. legacy grip bone): repoint while the
            # constraint provably does nothing (influence forced 0 first
            # only if it was already 0 -- otherwise the caller (attach
            # with influence>0) gets a clear error below via position
            # rules... simpler: retarget only when detached; attached
            # stale states are reported, never silently rewritten.
            if existing.influence != 0.0:
                raise WeaponRigError(
                    "Constraint %s points at '%s' instead of the weapon "
                    "bone '%s' while active; detach it first, then "
                    "re-attach." % (existing.name, existing.subtarget,
                                      weapon))
            existing.target = armature
            existing.subtarget = weapon
        pb = armature.pose.bones[HAND_BONES[side]]
        # NOTE: RNA structs are re-wrapped on each access, so locate the
        # index by name, not by Python identity.
        idx = next(i for i, c in enumerate(pb.constraints)
                   if c.name == existing.name)
        if idx != len(pb.constraints) - 1:
            if existing.influence == 0.0:
                pb.constraints.move(idx, len(pb.constraints) - 1)
            else:
                raise WeaponRigError(
                    "Constraint %s is not last on %s and is currently "
                    "active; move it to the end of the stack manually "
                    "before attaching (plan: weapon constraint must be "
                    "evaluated last)." % (existing.name, HAND_BONES[side]))
        return existing, False

    pbone = armature.pose.bones.get(HAND_BONES[side])
    if pbone is None:
        raise missing_weapon_bone(HAND_BONES[side])

    con = pbone.constraints.new('CHILD_OF')
    con.name = ATTACH_CONSTRAINT[side]
    con.target = armature
    con.subtarget = weapon
    con.influence = 0.0
    # constraints.new appends -- already last.
    return con, True


def count_attach_constraints(armature, side):
    """How many constraints on the hand carry the dedicated name (dup check)."""
    pbone = armature.pose.bones.get(HAND_BONES[side])
    if pbone is None:
        return 0
    return sum(1 for c in pbone.constraints if c.name == ATTACH_CONSTRAINT[side])


# ---------------------------------------------------------------------------
# Segment constraints: one inverse per attach range (history preservation)
# ---------------------------------------------------------------------------
# Child Of inverse_matrix is a single static property -- it cannot be
# keyframed (Blender 5.2: "not animatable"). So a second attach with a
# different hand/weapon offset would silently corrupt every earlier
# attached range on playback (verified: 0.27 jump after re-attach). Instead
# the earlier ranges keep their inverse on a segment constraint while the
# main constraint takes the new one; stepped influence keys partition the
# timeline so exactly one attach constraint is active per frame.
SEG_SUFFIX = "_seg"
# Divergence threshold: identical re-attach recomputes bit-identical
# inverses (~1e-7); a genuinely different catch pose differs by orders of
# magnitude more (verified 0.6).
DIVERGE_TOL = 1e-4


def _seg_prefix(side):
    return ATTACH_CONSTRAINT[side] + SEG_SUFFIX


def find_attach_segments(armature, side):
    """All WPN_Attach_*_segN CHILD_OF constraints on the hand, stack order."""
    pbone = armature.pose.bones.get(HAND_BONES[side])
    if pbone is None:
        return []
    prefix = _seg_prefix(side)
    out = []
    for c in pbone.constraints:
        if c.name == ATTACH_CONSTRAINT[side]:
            continue
        if not c.name.startswith(prefix):
            continue
        if c.type != 'CHILD_OF':
            raise WeaponRigError(
                "Constraint %s on %s exists but is not a Child Of "
                "constraint (found %s) -- refusing to use it."
                % (c.name, HAND_BONES[side], c.type))
        out.append(c)
    return out


def attached_constraint(armature, side):
    """The attach constraint (main or segment) driving the hand RIGHT NOW.

    Live-RNA based (threshold 0.5, main wins ties): this answers what the
    viewport shows, which is what detach/snap/UI operate on. Ranges exist
    precisely so RNA matches keyed playback at every settled state.
    Returns None when the hand is free. Name clashes still raise loudly
    (never silently reused).
    """
    main = find_attach_constraint(armature, side)
    if main is not None and float(main.influence) > 0.5:
        return main
    for seg in find_attach_segments(armature, side):
        if float(seg.influence) > 0.5:
            return seg
    return None


def is_hand_attached(armature, side):
    """True when any attach constraint drives the hand right now."""
    try:
        return attached_constraint(armature, side) is not None
    except Exception:
        return False


def _attached_ranges(armature, side, main_name, upto_frame, pre_rna=None):
    """[(start, end|None)] frames where MAIN reads attached (CONSTANT steps).

    Only ranges with start < upto_frame. No fcurve: the static RNA value
    applies everywhere -> [(frame_start, None)] when active, else [].
    ``pre_rna`` overrides the live RNA read (attach captures it before
    touching influence; the live value mid-operation is already 1.0).
    """
    from ..animation import keyframes
    hand = HAND_BONES[side]
    path = keyframes.influence_data_path(hand, main_name)
    fc = keyframes.find_fcurve(armature, path)
    if fc is None:
        active = float(pre_rna) if pre_rna is not None else None
        if active is None:
            pbone = armature.pose.bones.get(hand)
            con = pbone.constraints.get(main_name) if pbone else None
            active = float(con.influence) if con is not None else 0.0
        if active > 0.5:
            return [(bpy.context.scene.frame_start, None)]
        return []
    keys = sorted(fc.keyframe_points, key=lambda k: k.co[0])
    ranges = []
    for i, k in enumerate(keys):
        if float(k.co[1]) < 0.5:
            continue
        start = int(round(float(k.co[0])))
        end = None
        if i + 1 < len(keys):
            end = int(round(float(keys[i + 1].co[0])))
        if start < upto_frame:
            ranges.append((start, end))
    return ranges


def _key_influence_stepped(armature, hand, con_name, frame, value):
    """Set influence, insert one key, force CONSTANT (checked, loud)."""
    from ..animation import keyframes
    pbone = armature.pose.bones.get(hand)
    con = pbone.constraints.get(con_name) if pbone is not None else None
    if con is None:
        raise WeaponRigError(
            "Cannot key influence: constraint %s missing on %s."
            % (con_name, hand))
    # keyframe_insert records the CURRENT property value -- set it first
    # (same discipline as keyframe_influence; otherwise every key would
    # capture stale RNA, e.g. all zeros on a fresh segment constraint).
    con.influence = float(value)
    path = keyframes.influence_data_path(hand, con_name)
    if not armature.keyframe_insert(path, frame=frame):
        raise WeaponRigError(
            "Failed to insert keyframe '%s' at frame %s." % (path, frame))
    fc = keyframes.find_fcurve(armature, path)
    if fc is not None:
        for k in fc.keyframe_points:
            k.interpolation = 'CONSTANT'
        try:
            fc.update()
        except Exception:
            pass


def _next_seg_name(armature, side):
    prefix = _seg_prefix(side)
    pbone = armature.pose.bones[HAND_BONES[side]]
    taken = {c.name for c in pbone.constraints
             if c.name.startswith(prefix)}
    n = 2
    while "%s%d" % (prefix, n) in taken:
        n += 1
    return "%s%d" % (prefix, n)


def _freeze_history_to_segment(armature, side, main_con, old_inverse,
                               upto_frame, pre_rna=None):
    """Move earlier attached ranges onto a segment holding ``old_inverse``.

    Creates WPN_Attach_*_segN (target/subtarget copied from main, placed
    before main so main stays last), keys it 1 on each earlier attached
    range (0 elsewhere, CONSTANT, guarded), and zeroes the main
    constraint on those ranges. Returns (seg_name, ranges) or (None, []).
    Freezing writes the minimum keys to keep existing ranges exact -- it
    runs even with key=False, because the alternative is corrupting
    already-keyed motion (the current-frame keying still honors `key`).
    """
    from ..animation import keyframes
    hand = HAND_BONES[side]
    ranges = _attached_ranges(armature, side, main_con.name, upto_frame,
                              pre_rna=pre_rna)
    ranges = [(a, b if b is not None else upto_frame) for (a, b) in ranges]
    # Degenerate ranges (empty: static-attached history starting exactly
    # at the attach frame) need no freezing -- only pre-frame_start
    # static pose is affected, which playback never reaches.
    ranges = [(a, b) for (a, b) in ranges if a < b]
    if not ranges:
        return None, []
    pbone = armature.pose.bones[hand]
    seg_name = _next_seg_name(armature, side)
    seg = pbone.constraints.new('CHILD_OF')
    seg.name = seg_name
    if seg.name != seg_name:
        pbone.constraints.remove(seg)
        raise WeaponRigError(
            "Could not create segment constraint %s (renamed to %s)."
            % (seg_name, seg.name))
    seg.target = main_con.target
    seg.subtarget = main_con.subtarget
    seg.influence = 0.0
    seg.inverse_matrix = old_inverse
    # Segment before main: main must stay last (plan §41 stack rule).
    idx_seg = next(i for i, c in enumerate(pbone.constraints)
                   if c.name == seg_name)
    idx_main = next(i for i, c in enumerate(pbone.constraints)
                    if c.name == main_con.name)
    if idx_seg > idx_main:
        pbone.constraints.move(idx_seg, idx_main)
    first_a = min(a for (a, _b) in ranges)
    _key_influence_stepped(armature, hand, seg_name, first_a - 1, 0.0)
    for (a, b) in ranges:
        _key_influence_stepped(armature, hand, seg_name, a, 1.0)
        _key_influence_stepped(armature, hand, seg_name, b, 0.0)
    main_path = keyframes.influence_data_path(hand, main_con.name)
    main_fc = keyframes.find_fcurve(armature, main_path)
    if main_fc is not None:
        starts = {a for (a, _b) in ranges}
        for k in main_fc.keyframe_points:
            if int(round(float(k.co[0]))) in starts:
                k.co[1] = 0.0
        try:
            main_fc.update()
        except Exception:
            pass
    else:
        # Static-attached history: pin it off explicitly from frame_start
        # (a single key; playback before frame_start is out of scope).
        fs = bpy.context.scene.frame_start
        _key_influence_stepped(armature, hand, main_con.name, fs, 0.0)
    return seg_name, ranges


def _verify_channel_keys(armature, bone_name, frame, keyed):
    """Confirm transform keys landed (off-frame keying path).

    ``keyed`` is the {group: guard_written} map from key_changed_channels.
    Only existence is checked -- values are exact by construction
    (keyframe_insert reads live properties with no update in between, and
    now raises instead of silently skipping).
    """
    from ..animation import keyframes
    for group, guard in keyed.items():
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        fc = keyframes.find_fcurve(armature, path)
        if keyframes.find_key_at(fc, frame) is None:
            raise WeaponRigError(
                "Keyframe verification failed: no %s key at frame %s."
                % (path, frame))
        if guard and keyframes.find_key_at(fc, frame - 1) is None:
            raise WeaponRigError(
                "Keyframe verification failed: no guard %s key at "
                "frame %s." % (path, frame - 1))


def _native_coconstraint(armature, hand, our_name):
    """Name of an active native co-constraint on the hand, or None.

    A second (non-WPN, non-segment) CHILD_OF beside ours means step-7
    compares across constraint states (native-detached vs WPN-attached)
    and can never verify strict even for an exact solve.
    """
    pbone = armature.pose.bones.get(hand)
    if pbone is None:
        return None
    for c in pbone.constraints:
        if c.name == our_name or c.name.startswith(our_name + SEG_SUFFIX):
            continue
        if c.type == 'CHILD_OF' and float(c.influence or 0.0) > 0.5:
            return c.name
    return None


def _verify_influence_key(armature, bone_name, con_name, frame, value):
    """Confirm an influence key landed with the intended value.

    Used when keys target a frame other than the current one, where a
    pose re-read would see the fcurve's value AT THE CURRENT frame
    instead (keyframe_insert dirties animation data). Raises on mismatch.
    """
    from ..animation import keyframes
    path = keyframes.influence_data_path(bone_name, con_name)
    fc = keyframes.find_fcurve(armature, path)
    key = keyframes.find_key_at(fc, frame)
    if key is None:
        raise WeaponRigError(
            "Keyframe verification failed: no %s influence key at "
            "frame %s." % (con_name, frame))
    if abs(key.co[1] - value) > 1e-6:
        raise WeaponRigError(
            "Keyframe verification failed: %s influence at frame %s is "
            "%s, expected %s." % (con_name, frame, key.co[1], value))


def _snapshot_hand(armature, hand, con):
    """Entry-visible hand state: (channels dict, influence float).

    Attach/detach act on the VISIBLE pose (unkeyed static RNA). Captured
    before any write/update so a later assert can restore it.
    """
    from ..animation import keyframes
    return keyframes.capture_channels(armature, hand), float(con.influence)


def _assert_hand(armature, hand, con, snap):
    """Restore snapshot RNA after an update (repair update resync).

    view_layer.update() re-applies fcurve values onto original RNA
    channels whenever the animation subsystem was tagged dirty (fcurve
    mute, keyframe_insert, influence writes), discarding unkeyed static
    poses mid-operation -- bisected: RNA (0,0,0) -> fcurve (0.945,...)
    across a single update, every later solve/verify then mixes bases
    (attach raised d-trans 4.33 on exactly this). Re-asserting the
    entry-visible values keeps capture/solve/verify on one basis. Plain
    channel writes tag transforms only (never animation), so the assert
    itself can never trigger a resync.
    """
    from ..animation import keyframes
    channels, influence = snap
    keyframes.apply_channels(armature, hand, channels)
    con.influence = influence


def _assert_weapon(armature, weapon, wsnap):
    """Restore snapshot weapon channels (same resync hazard as hand).

    The Child-Of solve is hand-independent (hand channels cancel out of
    t.inverted() @ want @ p.inverted()), so the weapon pose T is the
    only divergence carrier -- weapon statics evaporating silently
    collapses every re-attach to a no-op keep (bisected div=0 with a
    moved hand). Asserted alongside the hand everywhere it matters.
    """
    from ..animation import keyframes
    keyframes.apply_channels(armature, weapon, wsnap)


def _verify_channel_key_values(armature, bone_name, frame, snap, groups):
    """Confirm channel keys @frame hold the snapshot values (exact).

    fcurve-data reads (no depsgraph): immune to the stale evaluated
    reads that follow fresh inserts. Raises on missing key or mismatch.
    """
    from ..animation import keyframes
    for group in groups:
        values = snap.get(group)
        if not values:
            continue
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        for index, want in enumerate(values):
            fc = keyframes._find_fcurve_index(armature, path, index)
            key = keyframes.find_key_at(fc, frame)
            if key is None:
                raise WeaponRigError(
                    "Keyframe verification failed: no %s[%d] key at "
                    "frame %s." % (path, index, frame))
            if abs(key.co[1] - want) > 1e-6:
                raise WeaponRigError(
                    "Keyframe verification failed: %s[%d] at frame %s "
                    "is %s, expected %s." %
                    (path, index, frame, key.co[1], want))


def _verify_attach_postkey_exact(armature, hand, con, frame, snap,
                                 pinned_groups, seg_name, frozen_ranges):
    """Post-key verification without evaluated reads (exact values).

    Fresh inserts leave the depsgraph evaluation cache stale (verified
    0.346 misread on a hand snap+attach flow), so a pose re-read here
    can report pre-insert values. RNA + fcurve key values are exact:
    if keys provably record the asserted state, keying moved nothing.
    """
    if float(con.influence) != 1.0:
        raise WeaponRigError(
            "Attach %s moved after keyframing: RNA influence is %s, "
            "expected 1.0." % (hand, con.influence))
    _verify_influence_key(armature, hand, con.name, frame, 1.0)
    channels, _inf = snap
    _verify_channel_key_values(armature, hand, frame, channels,
                               pinned_groups)
    # NOTE: no per-key seg checks here: adjacent frozen ranges share
    # endpoints (later 1.0 overwrites earlier 0.0), so endpoint values
    # are partition-correct but not per-range-literal. Seg motion itself
    # is covered by the frozen-playback tests.


def _verify_detach_postkey_exact(armature, hand, con, frame, snap, keyed):
    """Detach post-key verification without evaluated reads."""
    channels, _inf = snap
    pbone = armature.pose.bones[hand]
    for group, values in channels.items():
        if group.startswith("_"):
            continue
        live = tuple(getattr(pbone, group))
        if any(abs(a - b) > 1e-6 for a, b in zip(live, values)):
            raise WeaponRigError(
                "Detach %s moved after keyframing: RNA %s is %s, "
                "expected %s." % (hand, group, live, values))
    if float(con.influence) != 0.0:
        raise WeaponRigError(
            "Detach %s moved after keyframing: RNA influence is %s, "
            "expected 0.0." % (hand, con.influence))
    _verify_influence_key(armature, hand, con.name, frame, 0.0)
    _verify_channel_key_values(armature, hand, frame, channels,
                               list(keyed))


# ---------------------------------------------------------------------------
# Attach (plan §10)
# ---------------------------------------------------------------------------

def attach_preserve_transform(armature, side, frame=None, key=True):
    """Attach hand `side` to its grip without any visible jump.

    IK solvers on the hand are DISABLED for the duration of the attach
    (plan §53): a re-evaluation triggered by keying (the guard-key
    transient) would otherwise re-solve the IK to a different minimum and
    make the hand "move after keyframing". The solvers are re-enabled
    afterwards and a final check guarantees the hand stayed at the attach
    pose -- a conflict between the IK target and the attach point is
    reported as an explicit error instead of a silent pop.
    """
    weapon = get_weapon_bone(armature)
    hand = HAND_BONES[side]
    if hand not in armature.data.bones:
        raise missing_weapon_bone(hand)
    if frame is None:
        frame = bpy.context.scene.frame_current

    # --- freeze IK solvers on this hand (save active state) ----------------
    _freeze = []
    pbone = armature.pose.bones[hand]
    for c in pbone.constraints:
        if c.type == 'IK':
            _freeze.append((c, c.active))
            c.active = False

    try:
        dg = transforms.evaluated_depsgraph()

        # 2/3. Ensure constraint exists AND sits last in the stack (plan §10
        # step 3, §41, §43) BEFORE capturing the pose to preserve, so stack
        # normalization can never invalidate the captured transform.
        con, created = ensure_attach_constraint(armature, side)

        # Entry-visible hand state (snapshot BEFORE any write/update:
        # later updates can re-sync RNA from fcurves, discarding unkeyed
        # static poses -- the snapshot lets us re-assert it (see below).
        # Weapon too: the solve's T must use the intended weapon pose
        # (weapon statics evaporate identically; the solve is
        # hand-independent, so T is the only divergence carrier).
        _snap = _snapshot_hand(armature, hand, con)
        from ..animation import keyframes as _kf_wsnap
        _wsnap = _kf_wsnap.capture_channels(armature, weapon)
        _kept_native_warn = False

        # Pre-operation influence for the guard value and the static
        # history branch below: both must read this, never the live RNA
        # (later steps set it to 1.0 for the new attach).
        _pre_rna = float(con.influence)
        at_current = (frame == bpy.context.scene.frame_current)
        # 0. Pin hand channels FIRST (before any read/measure/solve).
        # Establishes RNA==fcurve coherence (guard history + flat current
        # values): without this, an update can re-sync RNA from stale
        # fcurves mid-operation and every later read/solve operates on a
        # different basis than intended (verified post-key misread when
        # static poses overlay old keys). Needs live RNA (frame==current).
        pinned_groups = []
        if at_current:
            from ..animation import keyframes as _kf_pin0
            pinned_groups = _kf_pin0.pin_hold_channels(
                armature, hand, frame)

        # 1. Store current world transform of the hand (plan §10 step 2).
        w_before = transforms.get_pose_bone_world_matrix(armature, hand, dg)

        # 4. Compute inverse (plan §10 step 5). First measure P: evaluated
        #    arm-space matrix with OUR influence at 0 (ARP's stack included).
        #    T is the weapon bone itself (rework: single export/control bone;
        #    the follow delta is identical to the old per-grip targets because
        #    rigid-child deltas always equal the parent bone's delta).
        #    Mute our own influence fcurve for the transient measurement:
        #    otherwise the update below re-syncs RNA from the fcurve (which
        #    may read attached here from earlier keys) and P gets measured
        #    with the constraint active (verified 0.08/28-deg solve garbage
        #    on a real file). Restored immediately afterwards.
        from ..animation import keyframes as _kf_mute
        _mute_fc = _kf_mute.find_fcurve(
            armature, _kf_mute.influence_data_path(hand, con.name))
        _was_muted = False
        if _mute_fc is not None:
            try:
                _was_muted = bool(_mute_fc.mute)
                _mute_fc.mute = True
            except Exception:
                _was_muted = False
        con.influence = 0.0
        transforms.update_view_layer()
        # Repair update resync (mute/influence writes tag animation dirty,
        # so this update re-applies fcurve values onto RNA, discarding
        # unkeyed statics): restore entry-visible pose before measuring
        # P/T, or the solve mixes bases (entry world + fcurve channels).
        _assert_hand(armature, hand, con, _snap)
        _assert_weapon(armature, weapon, _wsnap)
        dg = transforms.evaluated_depsgraph()
        p = transforms.get_pose_bone_arm_matrix(armature, hand, dg)
        t = transforms.get_pose_bone_arm_matrix(armature, weapon, dg)
        if _mute_fc is not None:
            try:
                _mute_fc.mute = _was_muted
            except Exception:
                pass

        mw_inv = armature.matrix_world.inverted()
        want_arm = mw_inv @ w_before  # desired arm-space result
        prev_inverse = con.inverse_matrix.copy()
        new_inverse = t.inverted() @ want_arm @ p.inverted()
        # Same relative pose as authored (nothing moved): keep the stored
        # inverse bit-identical instead of rewriting it. A recompute from
        # identical inputs matches to ~1e-12; any needless rewrite
        # perturbs every attached frame on playback proportionally to the
        # pose levers (verified 0.12 drift on a real file). Threshold 1e-6:
        # identical poses recompute identically, a genuinely different
        # catch pose differs by orders of magnitude more.
        div_pre = max(abs(a - b)
                      for ra, rb in zip(prev_inverse, new_inverse)
                      for a, b in zip(ra, rb))
        inverse_kept = div_pre <= 1e-6
        if not inverse_kept:
            con.inverse_matrix = new_inverse

        # 6. Influence 1 (plan §10 step 6).
        con.influence = 1.0
        transforms.update_view_layer()
        # Influence intentionally flipped: snapshot follows it (channels
        # are still entry-visible); assert repairs a channel resync.
        _snap = (_snap[0], 1.0)
        _assert_hand(armature, hand, con, _snap)
        _assert_weapon(armature, weapon, _wsnap)

        # 7/10. Verify no pop (plan §10 steps 10-11, §30). The solve
        # above is exact by construction (or bit-identical via div-skip),
        # so this must always verify strict; anything else is a loud bug
        # -- EXCEPT on double-constrained hands (a native ARP Child Of
        # beside ours): w_before is native-driven (influence 0) while
        # w_after is WPN-driven (influence 1), and those constraint paths
        # differ by the native-vs-WPN basis gap even for an exact solve
        # (bisected 0.08/28.6° with bit-identical channels in and out).
        # There the recompute is unverifiable: keep the stored inverse
        # (history/playback untouched) and warn instead of raising, so a
        # stale-X file stays workable and the lean is preserved.
        dg = transforms.evaluated_depsgraph()
        w_after = transforms.get_pose_bone_world_matrix(armature, hand, dg)
        _native_gap = _native_coconstraint(armature, hand, con.name)
        if not transforms.is_same_transform(w_before, w_after):
            if _native_gap is not None and not inverse_kept:
                # Unverifiable recompute on a native-co-constrained hand:
                # roll back ONLY the inverse write (keep history exact),
                # leave influence glued, warn loudly (returned flag).
                con.inverse_matrix = prev_inverse
                transforms.update_view_layer()
                import warnings as _warnings
                _warnings.warn(
                    "Attach %s keeps the stored offset (native '%s' "
                    "beside the weapon follow makes the re-aimed solve "
                    "unverifiable here: d-trans %.6f, d-rot %.4f deg). "
                    "Playback/history untouched." %
                    (hand, _native_gap,
                     *transforms.matrix_difference(w_before, w_after)))
                _kept_native_warn = True
                inverse_kept = True
            else:
                # Roll back to a clean detached state before reporting.
                con.influence = 0.0
                transforms.update_view_layer()
                raise WeaponRigError(
                    "Attach %s failed: hand moved (d-trans %.6f, "
                    "d-rot %.4f deg). Constraint rolled back to detached."
                    % (hand, *transforms.matrix_difference(w_before,
                                                           w_after)))

        # 7b. History preservation: inverse_matrix is static, so a
        # divergent re-attach would corrupt every earlier attached range
        # on playback. Freeze those ranges onto a segment constraint
        # holding the PREVIOUS inverse first (their motion stays exact).
        # (div_pre computed at step 5 against the stored inverse.)
        div = div_pre
        seg_name, frozen_ranges = None, []
        if div > DIVERGE_TOL and not inverse_kept:
            seg_name, frozen_ranges = _freeze_history_to_segment(
                armature, side, con, prev_inverse, frame,
                pre_rna=_pre_rna)
        # Post-key check is frame-aware: a pose re-read is only meaningful at
        # the CURRENT frame (keyframe_insert dirties animation data, so reads
        # elsewhere would see the fcurve's current-frame value, not the key).
        # Off-frame, verify the written key values instead.
        # (The main 1@G key below is mandatory on freeze even with
        # key=False, otherwise RNA (1.0) and fcurves (0 at G) disagree and
        # the hand drops on the next scrub.)
        if key or seg_name is not None or _kept_native_warn:
            # NOTE: keep-warn forces the 1@F key even with key=False
            # (like freeze): RNA is attached while fcurves may read
            # detached there, and the hand would drop on scrub.
            from ..animation import keyframes
            keyframes.keyframe_influence(armature, hand, con.name, frame,
                                          1.0, pre_value=_pre_rna)
            if at_current:
                # 10-11. Verify AFTER keying (plan §10): writing keys must
                # not have moved anything either. Exact value checks (no
                # evaluated reads): fresh inserts leave the depsgraph
                # cache stale, but RNA + fcurve key values are exact.
                # Keys provably record the asserted state, so step-7's
                # w_after stays valid (no re-read: it would hit the stale
                # cache the exact checks sidestep).
                _assert_hand(armature, hand, con, _snap)
                _verify_attach_postkey_exact(
                    armature, hand, con, frame, _snap, pinned_groups,
                    seg_name, frozen_ranges)
            else:
                _verify_influence_key(armature, hand, con.name, frame, 1.0)

        # How far the hand sits from its grip AT the attach frame. Attach
        # never moves the hand onto the grip (it glues where things are),
        # so a large value means the hand is NOT holding the weapon -- the
        # operator turns this into a guidance warning, never a failure.
        # (Fresh read: grip world is unaffected by the attach itself.
        # Assert first: post-key inserts tagged animation dirty, and a
        # resync here would hand the grip math stale-basis channels.)
        _assert_hand(armature, hand, con, _snap)
        _assert_weapon(armature, weapon, _wsnap)
        grip_now = grip_world(armature, side)
        return {
            "side": side,
            "created": created,
            "world_before": w_before,
            "world_after": w_after,
            "grip_distance": (grip_now.translation
                                - w_after.translation).length,
            "segment": seg_name,
            "frozen_ranges": frozen_ranges,
            "pinned_groups": pinned_groups,
            "inverse_kept": inverse_kept,
            "native_kept_warn": _kept_native_warn,
        }
    finally:
        # Re-enable IK solvers. After that the solver evaluates the now-
        # attached hand once more: verify it stayed at the attach pose. If
        # the IK target doesn't match the attach point the solver will move
        # the hand -- that's a genuine conflict, reported as an error and
        # rolled back to a clean detached state.
        for c, old in _freeze:
            c.active = old
        if _freeze:
            # Assert before the solver re-evaluation (same resync hazard).
            _assert_hand(armature, hand, con, _snap)
            _assert_weapon(armature, weapon, _wsnap)
            dg = transforms.evaluated_depsgraph()
            w_after_ik = transforms.get_pose_bone_world_matrix(
                armature, hand, dg)
            if not transforms.is_same_transform(w_before, w_after_ik):
                con.influence = 0.0
                transforms.update_view_layer()
                raise WeaponRigError(
                    "Attach %s failed: the hand's IK solver re-solved to a "
                    "different pose (d-trans %.6f, d-rot %.4f deg) after "
                    "restoring IK. Attach with the IK solver target at the "
                    "same pose as the weapon grip, or attach a copy of the "
                    "hand without IK. Constraint rolled back to detached."
                    % (hand, *transforms.matrix_difference(
                        w_before, w_after_ik)))



def preserve_attached_hands(armature, captured):
    """Re-solve Child Of inverses so attached hands return to captured worlds.

    Used after operations that move the weapon bone itself (snap, pivot):
    attached hands would otherwise chase the weapon by the full delta and
    end up OFF their grips. Instead the weapon lands where it should and
    each attached hand is re-glued exactly where it was -- no channels
    touched, no keys written, influence untouched.

    ``captured``: {side: world Matrix} measured BEFORE the weapon move.
    Raises WeaponRigError with rollback (influence forced 0) on mismatch.
    """
    weapon = get_weapon_bone(armature)
    mw_inv = armature.matrix_world.inverted()
    for side, want_world in captured.items():
        hand = HAND_BONES[side]
        # Re-glue only the constraint actually driving the hand right now
        # (main or history segment) -- rewriting a frozen segment's
        # inverse would corrupt its ranges.
        con = attached_constraint(armature, side)
        if con is None:
            continue  # detached: constraint off, hand never moved
        # Measure P with OUR influence at 0 (transient).
        con.influence = 0.0
        transforms.update_view_layer()
        dg = transforms.evaluated_depsgraph()
        p = transforms.get_pose_bone_arm_matrix(armature, hand, dg)
        t = transforms.get_pose_bone_arm_matrix(armature, weapon, dg)
        con.inverse_matrix = (t.inverted() @ (mw_inv @ want_world)
                              @ p.inverted())
        con.influence = 1.0
        transforms.update_view_layer()
        dg = transforms.evaluated_depsgraph()
        got = transforms.get_pose_bone_world_matrix(armature, hand, dg)
        if not transforms.is_same_transform(want_world, got):
            con.influence = 0.0
            transforms.update_view_layer()
            trans, rot = transforms.matrix_difference(want_world, got)
            raise WeaponRigError(
                "Snap/pivot displaced attached %s (d-trans %.6f, "
                "d-rot %.4f deg). Constraint rolled back to detached."
                % (hand, trans, rot))


# ---------------------------------------------------------------------------
# Detach (plan §11)
# ---------------------------------------------------------------------------

def detach_preserve_transform(armature, side, frame=None, key=True):
    """Detach hand `side` from its grip without any visible jump.

    The constraint is NOT deleted (plan §11 step -- keep for reattachment);
    influence goes to 0 and the hand's local channels are rewritten to hold
    the world transform, then keyed if requested (plan §11 steps 6-7).
    Compensation keys stay gated on `key`: a no-op detach/attach round
    trip must not touch fcurves at all (and the hold pinning on attach).
    """
    hand = HAND_BONES[side]
    if hand not in armature.data.bones:
        raise missing_weapon_bone(hand)
    if frame is None:
        frame = bpy.context.scene.frame_current

    con = find_attach_constraint(armature, side)
    if con is None:
        # Nothing to detach: report rather than silently succeed? The plan
        # treats detach as idempotent UI -- but a missing constraint while
        # influence would matter is worth an explicit no-op result.
        return {"side": side, "created": False, "had_constraint": False,
                "changed": False}

    dg = transforms.evaluated_depsgraph()
    w_before = transforms.get_pose_bone_world_matrix(armature, hand, dg)

    # Detach whatever actually drives the hand right now: the main
    # constraint or a history segment (a frozen range edited later).
    active = attached_constraint(armature, side)
    if active is None:
        return {"side": side, "created": False, "had_constraint": True,
                "changed": False, "world_before": w_before,
                "world_after": w_before}
    con = active
    # Entry influence for the guard value below (must precede any write).
    _det_pre = float(con.influence)

    # Snapshot channels BEFORE compensation so we can guard-key the old
    # values at frame-1 if we end up rewriting them (plan §30).
    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, hand)

    # 4. Influence 0 (plan §11 step 4).
    con.influence = 0.0
    transforms.update_view_layer()
    # Snapshot follows the intentional flip; assert repairs an update
    # resync of the channels (same hazard as attach: mute/influence
    # writes tag animation dirty, update re-applies fcurve values).
    _snap = (old_channels, 0.0)
    _assert_hand(armature, hand, con, _snap)

    # 5. Restore world transform by rewriting local channels (plan §11
    #    step 5). pb.matrix setter solves loc/rot for us; parents, rest
    #    pose and rotation mode are handled by Blender.
    dg = transforms.evaluated_depsgraph()
    w_after = transforms.get_pose_bone_world_matrix(armature, hand, dg)
    if not transforms.is_same_transform(w_before, w_after):
        transforms.set_pose_bone_arm_matrix(
            armature, hand, armature.matrix_world.inverted() @ w_before)
        # Compensation intentionally rewrites channels: snapshot follows
        # it, then assert repairs any resync before re-reading.
        _snap = (keyframes.capture_channels(armature, hand), 0.0)
        transforms.update_view_layer()
        _assert_hand(armature, hand, con, _snap)
        dg = transforms.evaluated_depsgraph()
        w_after = transforms.get_pose_bone_world_matrix(armature, hand, dg)

    # 9. Verify (plan §11 step 9, §30).
    if not transforms.is_same_transform(w_before, w_after):
        raise WeaponRigError(
            "Detach %s failed: hand moved (d-trans %.6f, d-rot %.4f deg)."
            % (hand, *transforms.matrix_difference(w_before, w_after)))

    # 6/7. Write transform keys (only changed groups, guarded) + influence
    # 0 key (plan §11 steps 6-7, §12 stepped). Compensation keys stay
    # gated on `key` (a no-op round trip must not touch fcurves at all;
    # the attach restore path below reunites RNA with history instead).
    # Post-key check is frame-aware like attach (pose re-read only at the
    # current frame).
    at_current = (frame == bpy.context.scene.frame_current)
    if key:
        # Key the asserted (intended) values, not resync leftovers.
        _assert_hand(armature, hand, con, _snap)
        keyed = keyframes.key_changed_channels(armature, hand, frame,
                                               old_channels)
        keyframes.keyframe_influence(armature, hand, con.name, frame, 0.0,
                                      pre_value=_det_pre)
        if at_current:
            # 8/9. Verify AFTER keying (plan §11). Exact value checks
            # (no evaluated reads): fresh inserts leave the depsgraph
            # cache stale; RNA + fcurve key values are exact.
            _assert_hand(armature, hand, con, _snap)
            _verify_detach_postkey_exact(armature, hand, con, frame,
                                         _snap, keyed)
        else:
            _verify_influence_key(armature, hand, con.name, frame, 0.0)
            _verify_channel_keys(armature, hand, frame, keyed)

    return {"side": side, "created": False, "had_constraint": True,
            "changed": True, "world_before": w_before, "world_after": w_after}
