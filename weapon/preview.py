"""Preview weapon mesh handling (plan §16).

The preview mesh is a PURE viewport stand-in for the real (Unreal) Static
Mesh: it must follow weapon_socket rigidly but must NEVER become an
animation source -- constraints/animation are never added to it, and the
bone parenting below only reads the socket's transform.

Relationship storage (plan §16): armature custom property
``weapon_preview_object`` holding the object name.

Parenting approach: bone-parent the object to weapon_socket
(parent_type='BONE'), solving matrix_parent_inverse empirically from
measured matrices so the object's world transform is preserved exactly
(no assumptions about Blender's bone-tail/head anchor convention).
"""
import bpy

from ..constants import WeaponRigError
from ..utils import transforms

PREVIEW_PROP = "weapon_preview_object"


def get_preview_object(armature):
    """The assigned preview mesh object, or None."""
    name = armature.get(PREVIEW_PROP)
    if not name:
        return None
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def set_preview_mesh(armature, obj):
    """Parent ``obj`` to the weapon bone, preserving its world transform.

    Raises WeaponRigError on wrong input (never silently parents).
    """
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    if obj is None or obj.type != 'MESH':
        raise WeaponRigError(
            "Preview mesh must be a mesh object (got %s)."
            % (obj.name if obj is not None else "nothing"))
    if obj is armature:
        raise WeaponRigError("Cannot use the armature itself as preview.")

    world_before = obj.matrix_world.copy()

    obj.parent = armature
    obj.parent_type = 'BONE'
    obj.parent_bone = weapon
    transforms.update_view_layer()

    # Solve the parent inverse from measured matrices:
    #   world == P @ inverse @ local, with P @ local == W1 (measured).
    # Want world == world_before  =>  inverse ~= local @ W1^-1 @ W_before.
    # Only touch the inverse when the world actually jumped; otherwise the
    # default (identity) is already correct.
    w1 = obj.matrix_world.copy()
    if (w1.translation - world_before.translation).length > 1e-9:
        # Only compute when needed (identity inverse already correct).
        local = obj.matrix_basis.copy()
        inv = local @ w1.inverted() @ world_before @ local.inverted()
        obj.matrix_parent_inverse = inv
    transforms.update_view_layer()

    # Verify: world preserved (plan §30), no transforms applied to mesh.
    w_after = obj.matrix_world.copy()
    trans, _rot = transforms.matrix_difference(world_before, w_after)
    if trans > transforms.TOL_TRANSLATION:
        raise WeaponRigError(
            "Preview assignment moved the mesh by %.6f (must preserve)."
            % trans)

    armature[PREVIEW_PROP] = obj.name
    return obj


def clear_preview_mesh(armature):
    """Remove the preview assignment, keeping the mesh's world transform.

    Raises WeaponRigError when nothing is assigned.
    """
    obj = get_preview_object(armature)
    if obj is None:
        raise WeaponRigError("No preview mesh assigned.")
    world_before = obj.matrix_world.copy()
    obj.parent = None
    obj.parent_type = 'OBJECT'
    obj.parent_bone = ""
    obj.matrix_world = world_before
    transforms.update_view_layer()
    if PREVIEW_PROP in armature:
        del armature[PREVIEW_PROP]
    return obj