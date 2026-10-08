"""Read-only diagnostics for anim_auto_offset 'Relative editing' failures.

Run in Blender's Text Editor (Open + Run Script) in the file where
Relative Editing stopped working. Prints a checklist; send the output
back for interpretation. Changes NOTHING in the scene.
"""
import bpy

print("=" * 60)
print("RELATIVE EDITING DIAGNOSTICS")
print("=" * 60)

keys = [k for k in bpy.context.preferences.addons.keys()
        if "offset" in k.lower()]
print("0. offset addons in prefs:",
      keys if keys else "NONE -> extension disabled?")

scene = bpy.context.scene
for sc in bpy.data.scenes:
    try:
        print("1. scene '%s' use_anim_offset_mode = %s"
              % (sc.name, sc.use_anim_offset_mode))
    except Exception as exc:
        print("1. scene '%s': prop missing (%s)" % (sc.name, exc))
print("   current scene:", scene.name)
print("2. auto-key:", scene.tool_settings.use_keyframe_insert_auto,
      "(must be False)")

for bucket, name in ((bpy.app.handlers.depsgraph_update_pre, "pre"),
                     (bpy.app.handlers.depsgraph_update_post, "post")):
    names = [getattr(h, "__name__", "?") for h in bucket]
    print("3. %s handlers:" % name,
          [n for n in names if "offset" in n or "update" in n])

for ob in bpy.data.objects:
    if ob.type != 'ARMATURE':
        continue
    ad = ob.animation_data
    act = ad.action if ad is not None else None
    slot = getattr(ad, "action_slot", None) if ad is not None else None
    slot_id = getattr(slot, "identifier", None)
    print("4. armature '%s': action=%s slot=%s"
          % (ob.name, act.name if act is not None else None, slot_id))
    if act is None:
        nla = len(ad.nla_tracks) if ad is not None else 0
        print("   NO active action (NLA tracks: %d) -> addon is blind"
              % nla)
        continue
    fcurves = []
    try:
        if slot is not None:
            for layer in act.layers:
                for strip in layer.strips:
                    if strip.type != 'KEYFRAME':
                        continue
                    try:
                        cb = strip.channelbag(slot)
                    except Exception:
                        cb = None
                    if cb is not None:
                        fcurves.extend(list(cb.fcurves))
    except Exception as exc:
        print("   layers read failed:", exc)
    try:
        legacy = getattr(act, "fcurves", None)
        if legacy is not None:
            fcurves.extend(list(legacy))
    except Exception:
        pass
    bad = []
    for fc in fcurves:
        try:
            if fc.data_path.startswith('['):
                eval('ob' + fc.data_path, {"ob": ob})
            else:
                eval('ob.' + fc.data_path, {"ob": ob})
        except Exception:
            bad.append(fc.data_path)
    print("   fcurves: %d, STALE paths: %d" % (len(fcurves), len(bad)))
    for p in bad[:10]:
        print("     STALE:", p)
print("=" * 60)
