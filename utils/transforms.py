"""Transform utilities. All math is matrix/quaternion based (plan §40, §56).

SPACE CONTRACT (plan §40):
- ``world``       = armature object matrix_world @ armature-space matrix
- ``arm-space``   = PoseBone.matrix / evaluated PoseBone.matrix space
                    (probe-verified in Blender 5.2: pb.matrix is armature
                    space; world = arm.matrix_world @ pb.matrix)
- Never manipulate Euler angles for solving; decompose only at the very end
  (and only implicitly, via Blender's own channel setters).

All "get" helpers read through the evaluated depsgraph (plan §42): with
ARP IK + Child Of constraints active, the raw pose matrix of the *original*
object is NOT the final result -- only the evaluated copy is.
"""
import bpy

from ..constants import TOL_ROTATION_DEG, TOL_TRANSLATION


def evaluated_depsgraph():
    return bpy.context.evaluated_depsgraph_get()


def get_evaluated_armature(armature, depsgraph=None):
    dg = depsgraph or evaluated_depsgraph()
    return armature.evaluated_get(dg)


def get_pose_bone_world_matrix(armature, bone_name, depsgraph=None):
    """World-space 4x4 of a pose bone, constraints fully evaluated.

    Returns None if the bone does not exist (callers decide the error).
    """
    eval_arm = get_evaluated_armature(armature, depsgraph)
    pbone = eval_arm.pose.bones.get(bone_name)
    if pbone is None:
        return None
    return eval_arm.matrix_world @ pbone.matrix


def get_pose_bone_arm_matrix(armature, bone_name, depsgraph=None):
    """Armature-space 4x4 of a pose bone, constraints fully evaluated."""
    eval_arm = get_evaluated_armature(armature, depsgraph)
    pbone = eval_arm.pose.bones.get(bone_name)
    if pbone is None:
        return None
    return pbone.matrix.copy()


def set_pose_bone_arm_matrix(armature, bone_name, matrix):
    """Write an armature-space matrix into a pose bone's channels.

    Uses Blender's own matrix setter, which solves the underlying
    location/rotation channels (handles parents, rest pose, rotation mode).
    Requires pose bones to exist on the *original* armature.
    """
    pbone = armature.pose.bones.get(bone_name)
    if pbone is None:
        raise KeyError("pose bone %r not found" % bone_name)
    pbone.matrix = matrix
    return pbone


def update_view_layer():
    """Force evaluation after direct RNA writes before re-reading matrices."""
    bpy.context.view_layer.update()


def matrix_difference(a, b):
    """(translation_distance, rotation_angle_degrees) between two 4x4 matrices.

    plan §30 tolerances: 0.0001 BU translation, 0.01 deg rotation.
    """
    trans = (a.translation - b.translation).length
    qa = a.to_quaternion()
    qb = b.to_quaternion()
    # rotation_difference -> shortest arc; .angle is in radians (0..pi)
    angle_deg = abs(qa.rotation_difference(qb).angle) * 57.29577951308232
    return trans, angle_deg


def is_same_transform(a, b,
                      tol_trans=TOL_TRANSLATION,
                      tol_rot=TOL_ROTATION_DEG):
    trans, rot = matrix_difference(a, b)
    return trans <= tol_trans and rot <= tol_rot


def max_elementwise_error(a, b):
    """Max abs element difference -- for test/debug reporting."""
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))
