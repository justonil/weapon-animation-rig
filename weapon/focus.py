"""Focus helpers: 3D cursor + transform pivot/orientation on a weapon point.

Workflow (user request): click e.g. "Grip L" and the 3D cursor jumps onto
that weapon point with transform pivot = 3D Cursor, so the hand can be
rotated straight around it (R key). Transform orientation becomes a custom
"Weapon" orientation built from the weapon bone when the UI context allows
it, otherwise plain Normal -- both keep the rotation axes aligned with the
weapon instead of the hand.

All scene-state writes here are headless-safe (cursor, pivot point,
orientation slot). Building the custom orientation needs a 3D-view context
and lives in the operator with a Normal fallback.
"""
from ..constants import WeaponRigError
from .pivot import compute_pivot_world

WEAPON_ORIENTATION_NAME = "WPN_Weapon"


def ensure_weapon_orientation(context, armature):
    """Select the weapon bone and create/activate the Weapon orientation.

    Builds (or overwrites) a custom "WPN_Weapon" transform orientation
    from the weapon bone and activates it, so rotations use the weapon's
    axes with any pivot (e.g. 3D Cursor on a grip point). Selection and
    mode are restored afterwards.

    Returns the orientation name. Raises WeaponRigError with the exact
    reason when it cannot be built (missing bone, Pose Mode refused, or
    ``create_orientation`` poll failure -- the latter needs a real 3D
    Viewport, so it cannot work in background mode).

    NOTE (Blender 5.2): bone selection lives on the PoseBone
    (``pb.select``) -- ``Bone.select`` no longer exists.
    """
    import bpy
    from ..utils.constraints import get_weapon_bone
    weapon = get_weapon_bone(armature)  # raises with a clear error
    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = list(context.selected_objects)
    prev_mode = None
    if context.object is not None:
        try:
            prev_mode = context.object.mode
        except Exception:
            prev_mode = None
    # Bone selection is NOT part of object selection: save it too, or the
    # user's hand bone stays deselected with weapon selected at the end.
    prev_selected_bones = set()
    prev_active_bone = None
    try:
        prev_selected_bones = {pb.name for pb in armature.pose.bones
                               if pb.select}
        active_bone = armature.data.bones.active
        prev_active_bone = active_bone.name if active_bone is not None \
            else None
    except Exception:
        pass
    try:
        view_layer.objects.active = armature
        try:
            bpy.ops.object.mode_set(mode='POSE')
        except Exception as exc:
            raise WeaponRigError(
                "Cannot enter Pose Mode on '%s': %s"
                % (armature.name, exc))
        bone = armature.data.bones.get(weapon)
        if bone is None:
            raise WeaponRigError(
                "Weapon bone '%s' not found." % weapon)
        for pb in armature.pose.bones:
            try:
                pb.select = (pb.name == weapon)
            except Exception:
                pass
        try:
            armature.data.bones.active = bone
        except Exception as exc:
            raise WeaponRigError(
                "Cannot activate weapon bone: %s" % exc)
        if not armature.pose.bones[weapon].select:
            raise WeaponRigError(
                "Cannot select the weapon bone (hidden or locked?).")
        try:
            bpy.ops.transform.create_orientation(
                name=WEAPON_ORIENTATION_NAME, use=True, overwrite=True)
        except Exception as exc:
            raise WeaponRigError(
                "Create Orientation failed (%s). Run it from a 3D "
                "Viewport with the weapon rig visible." % exc)
        return WEAPON_ORIENTATION_NAME
    finally:
        try:
            # 1. Bone selection first (armature still active + POSE here).
            try:
                for pb in armature.pose.bones:
                    try:
                        pb.select = (pb.name in prev_selected_bones)
                    except Exception:
                        pass
                if prev_active_bone is not None:
                    try:
                        armature.data.bones.active = \
                            armature.data.bones.get(prev_active_bone)
                    except Exception:
                        pass
            except Exception:
                pass
            # 2. Mode (on the previously active object when it differs;
            # OBJECT fallback when there was no mode to return to).
            try:
                if prev_active is not None and prev_active is not armature:
                    try:
                        view_layer.objects.active = prev_active
                    except Exception:
                        pass
                if prev_mode is not None:
                    if context.object is None \
                            or context.object.mode != prev_mode:
                        bpy.ops.object.mode_set(mode=prev_mode)
                else:
                    try:
                        bpy.ops.object.mode_set(mode='OBJECT')
                    except Exception:
                        pass
                    try:
                        view_layer.objects.active = None
                    except Exception:
                        pass
            except Exception:
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass
            # 3. Object selection + active object.
            try:
                for obj in list(context.selected_objects):
                    try:
                        obj.select_set(False)
                    except Exception:
                        pass
                for obj in prev_selected:
                    try:
                        obj.select_set(True)
                    except Exception:
                        pass
                if prev_active is not None:
                    try:
                        view_layer.objects.active = prev_active
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass


def focus_on_point(armature, pivot, custom=(0.0, 0.0, 0.0)):
    """Aim the viewport at a weapon point (non-destructive).

    - 3D cursor -> pivot world position;
    - transform pivot point -> 3D Cursor (rotations orbit the point);
    - transform orientation slot 0 -> Normal (weapon-ish axes; the
      operator upgrades this to the custom Weapon orientation when
      a UI context is available).

    Returns {"point": Vector, "pivot": preset}. Raises WeaponRigError for
    unknown presets / missing weapon bone (via compute_pivot_world).
    """
    import bpy
    point = compute_pivot_world(armature, pivot, custom)
    scene = bpy.context.scene
    scene.cursor.location = point
    scene.tool_settings.transform_pivot_point = 'CURSOR'
    try:
        scene.transform_orientation_slots[0].type = 'NORMAL'
    except Exception as exc:
        raise WeaponRigError(
            "Could not set transform orientation to Normal: %s" % exc)
    return {"point": point, "pivot": pivot}
