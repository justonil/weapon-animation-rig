# Weapon Animation Rig

Blender add-on: an independent weapon-animation control system layered on top
of an Auto-Rig Pro character rig. The weapon is animated through dedicated
control bones (never parented to the hands); ARP hand-IK controllers follow
the weapon grips through Child Of constraints with animatable influence.

- **Single-bone export rig**: one `weapon` control bone (plus an independent
  `weapon_aim` tracking target). Grips, tip, guard, pommel and center are
  bone-local vector data, not bones.
- **One-click auto-rig** with automatic migration of legacy multi-bone rigs.
- **7 configurable weapon points** (Grip R/L, Guard L/R, Pommel, Center, Tip):
  numeric fields, 3D-cursor pick, per-weapon presets.
- **8 pivot presets** (Center, Grip R/L, Guard, Tip, Pommel, 3D Cursor,
  Custom). Set Pivot re-anchors the origin **without moving existing
  animation** (location keys compensated per-frame, rotation-aware) and
  converges on scaled rigs.
- **Attach / Detach without pops**: snap-preserving Child Of solve, IK
  solvers frozen for the duration so keyframing never re-poses the chain;
  genuine IK conflicts raise an explicit error with numbers instead of a
  silent pop.
- **Snap, Aim (track / point blade / roll), Rotate** (rotate-to-cursor,
  modal drag, animatable Empty handle), **Bake**, validation report,
  3D-view point markers, 3D-cursor focus + custom `WPN_Weapon` orientation.

## Install

Blender 4.4+ required (slotted-action API); developed and tested on 5.2 LTS.
Needs an Auto-Rig Pro generated rig (`c_hand_ik.l/r` + a root bone).

- Copy the `weapon_animation_rig` folder into Blender's `scripts/addons`
  (or zip it and use *Preferences → Add-ons → Install from Disk*), then
  enable **Weapon Animation Rig**. Panel: *3D View → Sidebar → Weapon*.

## Tests

Headless suites, all green (410 checks):

```sh
for t in run_milestone1_tests run_milestone2_tests run_milestone34_tests \
         run_milestone5_tests run_milestone6_tests run_milestone7_tests \
         run_milestone8_tests; do
  blender -b --factory-startup --python tests/$t.py
done
```

Plus `pyflakes` clean on the package.

## Tools

Standalone Text-Editor scripts (run via *Text Editor → Open → Run Script*):

- `tools/diag_rel_offset.py` — read-only diagnostics for the
  `anim_auto_offset` "Relative editing" feature (toggle state, handlers,
  action/slot, stale fcurve paths).
- `tools/clean_stale_fcurves.py` — removes fcurves pointing at deleted data
  (e.g. influence keys of a deleted `Child Of.001`), which otherwise kill
  Relative Editing for the whole armature. Back up the .blend first.

`Plan.md` is the original design spec the add-on was built from.
