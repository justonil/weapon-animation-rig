"""Remove fcurves pointing at non-existent data paths (orphan keys).

Orphan keys make anim_auto_offset 'Relative editing' raise KeyError on
EVERY depsgraph update, silently killing it for the whole armature.
Typical orphan: influence keys of a deleted constraint, e.g.
pose.bones["c_hand_ik.r"].constraints["Child Of.001"].influence
(Blender keeps the keys when the constraint is deleted).

SAVE A BACKUP first (File -> Save As). Removal itself is undoable
(Ctrl+Z). Run in Blender's Text Editor, then save the .blend.
"""
import bpy


def iter_all_fcurves(action):
    seen = set()
    try:
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type != 'KEYFRAME':
                    continue
                try:
                    bags = list(strip.channelbags)
                except Exception:
                    bags = []
                for cb in bags:
                    try:
                        fcurves = list(cb.fcurves)
                    except Exception:
                        continue
                    for fc in fcurves:
                        if id(fc) not in seen:
                            seen.add(id(fc))
                            yield cb, fc
    except Exception as exc:
        print("layers read failed:", exc)
    try:
        legacy = getattr(action, "fcurves", None)
        if legacy is not None:
            for fc in list(legacy):
                if id(fc) not in seen:
                    seen.add(id(fc))
                    yield legacy, fc
    except Exception:
        pass


def path_resolves(obj, data_path):
    try:
        if data_path.startswith('['):
            eval('ob' + data_path, {"ob": ob})
        else:
            eval('ob.' + data_path, {"ob": ob})
        return True
    except Exception:
        return False


total_removed = 0
for ob in bpy.data.objects:
    ad = ob.animation_data
    if ad is None or ad.action is None:
        continue
    stale = [(coll, fc) for coll, fc in iter_all_fcurves(ad.action)
             if not path_resolves(ob, fc.data_path)]
    for coll, fc in stale:
        print("REMOVE %s : %s[%d]"
              % (ob.name, fc.data_path, fc.array_index))
        try:
            coll.fcurves.remove(fc)
            total_removed += 1
        except Exception as exc:
            print("  failed:", exc)
print("Removed %d stale fcurve(s). Save the file." % total_removed)
