# Weapon Animation Rig

## Blender 5.2 + Auto-Rig Pro

### Technical Implementation Specification for an AI Coding Agent

---

## 1. Goal

Create a Blender add-on that provides a dedicated weapon animation-control system on top of an existing Auto-Rig Pro character rig.

The primary use case is animating melee weapons, especially two-handed swords, while keeping the weapon independent from the character's hands.

The final system must satisfy these principles:

1. The weapon must be an independent animated element.
2. The weapon must not be parented to `hand_l` or `hand_r`.
3. The character skeleton must contain dedicated weapon bones so the animated weapon transform can be exported to Unreal Engine.
4. The actual weapon in Unreal Engine should remain a normal Static Mesh, not a Skeletal Mesh.
5. Unreal Engine should attach the Static Mesh to an exported weapon socket bone.
6. Animator workflow must allow switching between:

   * free weapon / free hands,
   * weapon controlled independently with both hands attached,
   * only right hand attached,
   * only left hand attached.
7. Attach/detach operations must preserve the current visible pose without popping.
8. Existing ARP animations must not be destroyed or significantly modified by installing or using the system.
9. The animator must be able to manipulate the weapon around arbitrary pivots, including the sword tip.
10. The animator must be able to orient the weapon toward an arbitrary controller/target.
11. The system should be usable for swords first, but designed so that bows, spears, polearms, crossbows, etc. can use the same framework.

The intended final Unreal workflow is:

```text
Character Skeletal Mesh
        |
        +-- weapon_root
                |
                +-- weapon_socket
                        |
                        +-- Static Mesh Weapon
```

The weapon itself does not require a Skeletal Mesh.

---

# 2. Core Architecture

Do not make the weapon a child of either hand.

Do not use:

```text
hand_l
    |
    +-- sword
```

or:

```text
hand_r
    |
    +-- weapon
```

Instead create an independent weapon branch inside the character armature.

Recommended structure:

```text
root
|
+-- normal Auto-Rig Pro hierarchy
|
+-- weapon_root
      |
      +-- weapon_socket
      |
      +-- weapon_grip_r
      |
      +-- weapon_grip_l
      |
      +-- weapon_tip
      |
      +-- weapon_aim
```

Conceptually:

```text
                 CHARACTER ROOT
                       |
               -----------------
               |               |
          ARP CHARACTER    WEAPON SYSTEM
                               |
                         weapon_root
                               |
                         weapon_socket
                            /       \
                     grip_r          grip_l
                       |               |
                 hand IK R         hand IK L
```

The exact hierarchy can be adjusted during implementation, but the following semantic roles are mandatory.

---

# 3. Bone Roles

## 3.1 `weapon_root`

This is the main weapon animation controller.

Responsibilities:

* global weapon translation;
* global weapon rotation;
* primary weapon pivot;
* weapon animation;
* optional aim/track behavior;
* parent of the exported socket;
* parent/reference for weapon control bones.

This is the most important control in the system.

The animator should generally manipulate the weapon by moving/rotating `weapon_root`.

The weapon should not inherit transforms from the hand bones.

Recommended flags:

* custom/control bone;
* not a deform bone;
* exported to Unreal because it is part of the required hierarchy;
* clearly visually distinguishable in the viewport.

`weapon_root` should normally be placed under the character `root` so the weapon follows character/world motion correctly while remaining independent of the arms.

---

# 4. `weapon_socket`

This is the actual runtime/export bone.

It defines the transform used by Unreal Engine to attach the weapon Static Mesh.

Recommended hierarchy:

```text
weapon_root
    |
    +-- weapon_socket
```

In Unreal:

```text
Skeletal Mesh
    |
    +-- weapon_socket
            |
            +-- Sword Static Mesh
```

The socket bone is not an animation controller in normal use.

It should contain the appropriate local offset/orientation needed to place the weapon correctly.

The important distinction is:

```text
weapon_root
    = animator control

weapon_socket
    = Unreal attachment point
```

The exported weapon transform ultimately comes from the animated transform of this bone.

---

# 5. Internal Control Bones

The following bones should primarily exist to make animation convenient.

They should not necessarily be exported to Unreal.

## `weapon_grip_r`

Represents the intended position/orientation of the right hand on the weapon.

## `weapon_grip_l`

Represents the intended position/orientation of the left hand on the weapon.

For a two-handed sword:

```text
                  sword
                    |
              grip_l
                    |
              grip_r
                    |
```

The exact location and orientation are weapon-specific.

## `weapon_tip`

Reference/control point at the blade tip.

Used for:

* pivot placement;
* aiming;
* thrust setup;
* direction calculations;
* debugging;
* future weapon tools.

## `weapon_aim`

Optional target/control bone.

Used as a target for:

```text
Aim Weapon
Point Blade At Target
```

The animator moves `weapon_aim`, and the weapon can be oriented toward it.

---

# 6. Export Strategy

The control rig and Unreal runtime skeleton do not need to be identical.

Preferred result:

### Blender control rig

```text
weapon_root
weapon_socket
weapon_grip_r
weapon_grip_l
weapon_tip
weapon_aim
```

### Unreal skeleton

At minimum:

```text
weapon_root
weapon_socket
```

Internal helper bones should be excluded from the UE export where possible.

The goal is to keep Unreal's runtime skeleton minimal.

The weapon remains a Static Mesh.

No skeletal weapon asset should be required just to support animation.

Auto-Rig Pro supports custom bones and allows custom elements to be configured for export; custom bones should be added after the ARP rig has been generated/matched, rather than being inserted into the ARP reference-bone system.

---

# 7. Auto-Rig Pro Compatibility

The add-on must not modify Auto-Rig Pro's core generated rig.

Do not:

* edit ARP source files;
* regenerate the ARP rig;
* rename standard ARP bones;
* delete ARP constraints;
* replace ARP controllers;
* alter reference bones;
* modify ARP's generated rig structure destructively.

The add-on should detect an existing generated ARP armature and attach the weapon system to it.

The expected ARP hand IK controllers are:

```text
c_hand_ik.r
c_hand_ik.l
```

The add-on must verify that these bones exist before enabling hand attachment functionality.

If the expected bones are not found, display a clear error rather than guessing.

ARP explicitly supports adding custom bones after rig generation and provides a Child Of Switcher/Snap Child Of workflow for switching an IK controller between multiple parents while preserving its position.

---

# 8. Hand Attachment System

Do not actually parent the ARP hand IK bones to the weapon bones.

Use Child Of constraints.

The intended relationship is:

```text
c_hand_ik.r
    Child Of -> weapon_grip_r

c_hand_ik.l
    Child Of -> weapon_grip_l
```

This is essential because Blender's Child Of constraint has animatable Influence and an inverse transform, allowing attachment/detachment without permanently changing the hierarchy.

Each hand should have a dedicated constraint managed by the add-on.

Recommended names:

```text
WPN_Attach_R
WPN_Attach_L
```

Do not create duplicate constraints every time the user presses Attach.

The operator must first search for the dedicated constraint and reuse it if it already exists.

---

# 9. Constraint Behavior

For `c_hand_ik.r`:

```text
WPN_Attach_R
Target = character armature
Subtarget = weapon_grip_r
```

For `c_hand_ik.l`:

```text
WPN_Attach_L
Target = character armature
Subtarget = weapon_grip_l
```

The target may be the same armature because the weapon bones live inside the character skeleton.

The system must preserve the current transform when changing the constraint Influence.

Do not simply execute:

```python
constraint.influence = 1.0
```

because that may cause the hand to jump.

Instead use a robust snap procedure.

---

# 10. Attach Without Popping

When the animator presses:

```text
Attach Right
```

the visual position of `c_hand_ik.r` must remain unchanged.

Algorithm:

1. Evaluate the current pose.
2. Store the current world-space matrix of `c_hand_ik.r`.
3. Ensure `WPN_Attach_R` exists.
4. Set its target and subtarget.
5. Calculate/set the Child Of inverse matrix.
6. Set Influence to `1.0`.
7. Restore the required world transform if necessary.
8. Insert a keyframe on Influence.
9. Insert any necessary transform compensation keyframes.
10. Evaluate again.
11. Verify that the hand's world-space transform has not changed beyond a small numerical tolerance.

Use the Child Of inverse matrix rather than modifying the armature hierarchy.

Blender's Child Of API exposes `inverse_matrix` and the operator for calculating the inverse.

The add-on should implement its own transform-preserving helper rather than relying solely on UI state.

---

# 11. Detach Without Popping

When the animator presses:

```text
Detach Left
```

the hand must remain visually where it was.

Algorithm:

1. Evaluate the current frame.
2. Store the evaluated world-space transform of the hand IK controller.
3. Capture the current weapon constraint state.
4. Set the constraint Influence to zero.
5. Calculate the local transform required for the hand controller to remain at the stored world transform.
6. Write the appropriate location/rotation/scale keys.
7. Keyframe constraint Influence = `0.0`.
8. Re-evaluate.
9. Verify no visible jump occurred.

Do not delete the constraint when detaching.

Keep the constraint available for future reattachment.

---

# 12. Attach/Detach Must Be Keyframe-Aware

The system must support animation such as:

```text
Frame 1:
Both hands attached

Frame 50:
Both hands attached

Frame 51:
Left hand detached

Frame 70:
Left hand free

Frame 90:
Left hand reattached
```

The constraint Influence should therefore be animatable.

Example:

```text
Frame 50:
WPN_Attach_L = 1.0

Frame 51:
WPN_Attach_L = 0.0
```

Do not interpolate attachment states unintentionally.

The default switch behavior should use stepped transitions:

```text
1.0 -> 0.0
```

on adjacent frames.

Avoid a 10-frame blend unless explicitly requested.

Blender constraints have animatable Influence, which is suitable for this workflow.

---

# 13. High-Level Attachment Modes

The UI should expose four logical modes:

```text
FREE
RIGHT HAND
LEFT HAND
BOTH HANDS
```

Internally these correspond to:

```text
FREE:
R = 0
L = 0

RIGHT:
R = 1
L = 0

LEFT:
R = 0
L = 1

BOTH:
R = 1
L = 1
```

The add-on may provide both individual controls and mode shortcuts.

Recommended buttons:

```text
Attach R
Detach R

Attach L
Detach L

Attach Both
Detach Both
```

and optionally:

```text
Mode:
[ Free ]
[ Right ]
[ Left ]
[ Both ]
```

---

# 14. ARP Hand IK Offset Compatibility

The system should not interfere with ARP's hand IK offset controller.

Auto-Rig Pro provides an additional hand IK offset controller specifically for layering subtle hand animation on top of the primary IK position.

The intended conceptual stack should therefore be:

```text
Weapon Grip
     |
     v
ARP Hand IK
     |
     v
ARP Hand IK Offset
     |
     v
Actual hand
```

The weapon attachment system controls the broad positional relationship.

The ARP offset controller remains available for:

* wrist corrections;
* small grip adjustments;
* secondary motion;
* hand rotation;
* animation polish.

Do not duplicate this functionality unnecessarily.

---

# 15. Weapon Control Workflow

The intended animator workflow should be:

```text
1. Select weapon control
2. Move/rotate weapon_root
3. Attach one or both hands
4. Pose the sword
5. Adjust hand offsets
6. Animate weapon_root
7. Release/regrab hands when needed
8. Bake/export final animation
```

The animator should not need to manually manipulate the sword Static Mesh object inside Blender.

The weapon rig bones represent the weapon.

A helper mesh representing the actual sword may be displayed in Blender for visualization, but the animation source must be the weapon bones.

---

# 16. Weapon Representation in Blender

The tool should support two workflows.

## A. Control-only mode

No mesh is needed.

The animator sees:

```text
weapon_root
weapon_socket
weapon_grip_r
weapon_grip_l
weapon_tip
weapon_aim
```

Useful for technical setup.

## B. Preview weapon mode

A Static Mesh can be assigned to the weapon rig for viewport preview.

The mesh should follow:

```text
weapon_socket
```

but it must never become the animation source.

The mesh is purely a visual preview.

The add-on should store a relationship such as:

```text
weapon_preview_object
```

using a custom property or dedicated collection.

---

# 17. Weapon Presets

The system should support per-weapon configuration.

Example:

```text
Greatsword
    grip_r
    grip_l
    socket transform
    tip position
    blade axis
    preview mesh
```

Another weapon:

```text
Longsword
    grip_r
    grip_l
    socket transform
    tip position
    blade axis
    preview mesh
```

Do not hard-code sword-specific coordinates into the add-on.

The weapon system should treat weapon-specific transforms as data.

Suggested custom property structure:

```text
weapon_rig_id
weapon_type
weapon_name
grip_r_config
grip_l_config
socket_config
tip_config
blade_axis
```

The exact storage mechanism can be implemented using Blender PropertyGroups.

---

# 18. Snap Weapon to Right Hand

Implement:

```text
Snap Weapon -> Right Hand
```

This should calculate a weapon-root transform so that:

```text
weapon_grip_r
```

matches:

```text
c_hand_ik.r
```

Requirements:

* preserve the configured grip orientation;
* align position;
* optionally align orientation;
* do not move the character;
* do not alter the hand animation.

The operation should work at the current frame.

It must not create unnecessary keys unless the user requests keyframing.

---

# 19. Snap Weapon to Left Hand

Same concept:

```text
Snap Weapon -> Left Hand
```

Align:

```text
weapon_grip_l
```

with:

```text
c_hand_ik.l
```

---

# 20. Snap Weapon to Both Hands

This is one of the most important functions.

Implement:

```text
Snap Weapon -> Both Hands
```

The goal is to solve the weapon transform from both hand positions.

Input:

```text
Right Hand IK position/orientation
Left Hand IK position/orientation

weapon_grip_r local position/orientation
weapon_grip_l local position/orientation
```

At minimum, the solver must match both grip positions as accurately as possible.

Recommended solving method:

1. Calculate the current weapon grip vector:

```text
D_weapon = grip_l - grip_r
```

2. Calculate the target hand vector:

```text
D_hands = hand_l - hand_r
```

3. Align the weapon grip vector with the target hand vector.
4. Use one hand's orientation, or an averaged hand frame, to determine the remaining rotational degree of freedom.
5. Calculate the required weapon-root rotation.
6. Calculate the translation required so `grip_r` matches the right hand.
7. Evaluate both grip errors.
8. Apply the result.

For two points, one rotational degree of freedom remains ambiguous. Therefore the solver must deliberately choose a roll reference rather than relying on arbitrary quaternion behavior.

Preferred roll reference:

```text
Right hand orientation
```

or an explicitly defined weapon up axis.

The implementation should use `mathutils` matrices/quaternions and work in world space.

---

# 21. Pivot System

The animator must be able to quickly rotate the weapon around different points.

Required pivot presets:

```text
Center
Grip R
Grip L
Guard
Tip
Pommel
3D Cursor
Custom
```

Example:

```text
Pivot = Tip
```

allows:

```text
            sword
              |
              |
              |
              *
              ^
             TIP
              |
        weapon_root pivot
```

The blade can then be rotated around the tip.

---

# 22. Dynamic Pivot Implementation

Do not change the actual mesh origin.

Do not permanently change the rest-pose structure of the skeleton.

The pivot operation should work entirely in pose space.

Preferred approach:

1. Determine desired pivot world position.
2. Calculate current `weapon_root` head world position.
3. Calculate the translation needed to place the weapon root pivot at the desired point.
4. Apply the root translation.
5. Compensate the child socket/local transform so the weapon's world-space position does not jump.
6. Preserve all existing transforms.
7. Allow rotation of `weapon_root` around its new pivot.
8. Optionally keyframe the operation if the pivot itself needs to animate.

The pivot operation must support repeated use at different frames.

Example:

```text
Frame 1:
Pivot = Center

Frame 20:
Pivot = Tip

Frame 30:
Pivot = Cursor
```

The tool must not corrupt the weapon's transform when switching pivot modes.

---

# 23. Temporary Pivot vs Permanent Animation

The initial implementation should distinguish between:

### Pivot as an animator manipulation tool

Used to make the current rotation easier.

and:

### Pivot as actual animated control

Used when the pivot position itself is part of the animation.

For MVP, implement reliable pose-space pivot behavior first.

Do not overcomplicate the system with a dedicated pivot animation layer until the basic weapon-root solution is stable.

---

# 24. 3D Cursor Pivot

Implement:

```text
Pivot -> 3D Cursor
```

The current 3D cursor world position becomes the weapon pivot.

Example:

```text
        sword
          |
          |
          |
          X
          ^
      3D Cursor
```

After setting the pivot, rotating the weapon should behave as though the cursor were the weapon's pivot.

This is particularly useful for:

* planting the sword in the ground;
* spinning a sword around a point;
* blocking/deflecting;
* environmental interactions.

---

# 25. Aim System

Implement:

```text
Aim Weapon
```

Target:

```text
weapon_aim
```

The system should allow the weapon to orient toward the target.

Separate:

```text
direction
```

from:

```text
roll
```

Do not create a system in which the weapon automatically gets an uncontrollable roll.

Preferred conceptual system:

```text
weapon_root
    |
    +-- direction toward weapon_aim
    |
    +-- manual roll/offset
```

Blender's tracking constraints can be used as implementation components where appropriate, but the final system should expose explicit control over the weapon's roll. Blender documents Damped Track as a target-pointing constraint, while constraint Influence is animatable.

---

# 26. Point Blade At Target

Implement a dedicated operation:

```text
Point Blade At
```

The animator chooses:

```text
weapon_aim
```

and the system calculates a weapon orientation where the selected blade axis points toward the target.

The weapon configuration must define its blade axis, for example:

```text
Blade Axis = +Y
```

or:

```text
Blade Axis = -Y
```

Do not hard-code one universal axis.

Different weapons may have different local orientations.

---

# 27. Weapon Roll

When using Aim mode, expose:

```text
Roll
```

as a separate value.

The animator should be able to:

```text
Aim = target
Roll = 45°
```

without moving the target.

This is particularly important for swords because the direction alone does not determine how the blade should be rotated around its longitudinal axis.

---

# 28. Free / Attached Workflow

The system must support the following production scenario.

### Two-handed attack

```text
Both hands attached
        |
        v
Animate weapon_root
```

Both hands follow the grips.

### One-handed transition

```text
Both hands attached
        |
        v
Detach L
        |
        v
Continue animating weapon_root
```

Right hand continues following.

Left hand becomes independently animated using normal ARP controls.

### Re-grab

```text
Left hand approaches sword
        |
        v
Attach L
```

The hand should snap into the existing weapon grip without a visible discontinuity if the animator prepared the pose appropriately.

---

# 29. No Destructive Operations

The add-on must not:

* delete existing actions;
* delete existing keyframes;
* clear user constraints;
* rename ARP controllers;
* rebuild the ARP rig;
* change mesh deformation;
* apply transforms to the character;
* apply transforms to weapon meshes;
* modify the ARP reference rig;
* automatically bake the character unless explicitly commanded;
* overwrite user animation data without explicit confirmation.

Every destructive operation should require an explicit operator or confirmation.

---

# 30. Animation Safety

The tool should be designed around a core principle:

> Never change the visible character pose unless the operation explicitly intends to do so.

Before and after every major operation, the add-on should be able to compare relevant evaluated transforms.

For example:

```text
Before:
hand world matrix

Operation:
Attach

After:
hand world matrix
```

If the difference exceeds a configurable epsilon, the operation should either compensate or report failure.

Suggested numeric tolerance:

```text
translation: 0.0001 Blender units
rotation: 0.01 degrees
```

Exact tolerances can be adjusted during testing.

---

# 31. Keyframe Policy

Do not insert keyframes automatically on every transform operation unless the operation changes an animated state.

For attachment operations:

```text
Attach/Detach
```

automatically keyframe constraint Influence.

For pure viewport operations:

```text
Snap
Pivot
Aim setup
```

do not automatically create animation keys unless there is an explicit "Key" option.

Provide:

```text
[Key]
```

or:

```text
Auto Key
```

where appropriate.

Respect Blender's current Auto Keying state where possible.

---

# 32. Main UI

Create a dedicated panel in the 3D View sidebar.

Suggested layout:

```text
WEAPON ANIMATION
────────────────────────

Weapon Rig
[ Auto Detect ]
[ Create / Rebuild ]

Character:
[ ARP Character ]

Weapon:
[ Greatsword ]

────────────────────────
HANDS

Right Hand
[ Attach ] [ Detach ]

Left Hand
[ Attach ] [ Detach ]

Both
[ Attach ] [ Detach ]

Mode:
[ FREE ▼ ]

────────────────────────
SNAP

[ Weapon -> Right Hand ]
[ Weapon -> Left Hand ]
[ Weapon -> Both Hands ]

────────────────────────
PIVOT

[ Center ]
[ Grip R ]
[ Grip L ]
[ Guard ]
[ Tip ]
[ Pommel ]
[ 3D Cursor ]
[ Custom ]

[ Set Pivot ]

────────────────────────
AIM

Target:
[ weapon_aim ]

[ Aim Weapon ]
[ Point Blade At ]

Roll:
[ 0.0° ]

────────────────────────
BAKE

[ Bake Weapon Animation ]

Frame:
[ Start ] - [ End ]

────────────────────────
DEBUG

[ Show Weapon Controls ]
[ Validate Rig ]
```

---

# 33. Fast Animation Controls

The tool should eventually support hotkeys or a pie/radial menu.

Suggested concept:

```text
                  Attach Both

          Attach L            Attach R

       Pivot                     Detach

              Weapon Menu

          Aim              Snap
```

Do not implement the hotkey system before the core operators are stable.

The first milestone should prioritize reliable operators over shortcut customization.

---

# 34. Viewport Visualization

Weapon bones should be visually recognizable.

Recommended custom shapes:

```text
weapon_root   = large diamond/circle
weapon_socket = small square
weapon_grip   = small colored box/circle
weapon_tip    = small point
weapon_aim    = target/crosshair shape
```

Do not depend on external custom-shape objects for the initial implementation unless necessary.

Native bone display may be sufficient for MVP.

Add a toggle:

```text
Show Weapon Rig
```

to isolate/hide helper controls.

---

# 35. Weapon Rig Creation Operator

Create:

```text
Create Weapon Rig
```

Behavior:

1. Detect active ARP armature.
2. Verify that it is a generated rig, not a reference armature.
3. Verify required root/hand bones exist.
4. Check whether the weapon rig already exists.
5. If it exists, do not create duplicates.
6. Create required custom bones.
7. Establish correct parenting.
8. Mark internal/export properties.
9. Create necessary custom shapes if enabled.
10. Create hand attachment constraints.
11. Validate the result.
12. Report a concise success/error message.

Use explicit names and stable identifiers.

---

# 36. Rig Validation

Implement:

```text
Validate Weapon Rig
```

The validator should check:

```text
ARP armature found
c_hand_ik.r found
c_hand_ik.l found

weapon_root exists
weapon_socket exists
weapon_grip_r exists
weapon_grip_l exists
weapon_tip exists

weapon_root parenting valid
weapon_socket parenting valid

WPN_Attach_R valid
WPN_Attach_L valid

no duplicate weapon constraints
no missing target bones
```

Output should be human-readable.

Example:

```text
Weapon Rig Validation

✓ ARP armature
✓ Right Hand IK
✓ Left Hand IK
✓ weapon_root
✓ weapon_socket
✓ weapon_grip_r
✓ weapon_grip_l
✓ weapon_tip
✓ Right attachment constraint
✓ Left attachment constraint

Result: VALID
```

---

# 37. Internal Metadata

Use custom properties to identify weapon-rig elements.

For example:

```text
["weapon_rig_role"] = "root"
["weapon_rig_role"] = "socket"
["weapon_rig_role"] = "grip_r"
["weapon_rig_role"] = "grip_l"
["weapon_rig_role"] = "tip"
["weapon_rig_role"] = "aim"
```

Use a system identifier:

```text
["weapon_rig_system"] = "weapon_animation_rig"
```

This is safer than relying exclusively on names.

Names should still be predictable:

```text
weapon_root
weapon_socket
weapon_grip_r
weapon_grip_l
weapon_tip
weapon_aim
```

---

# 38. Avoid Name Collisions

The tool must handle existing bones with these names.

Preferred behavior:

If:

```text
weapon_root
```

already exists and is identified as a weapon-system bone, reuse it.

If the name exists but belongs to something else:

```text
weapon_root.001
```

must not be silently created.

The tool should either:

* identify and reuse the correct system bone; or
* report a conflict and offer a rename prefix.

Potential configurable prefix:

```text
WPN_
```

Example:

```text
WPN_root
WPN_socket
WPN_grip_r
WPN_grip_l
WPN_tip
WPN_aim
```

Choose one naming convention and use it consistently.

---

# 39. Recommended Internal Python Architecture

Use a modular add-on structure.

Example:

```text
weapon_animation_rig/
│
├── __init__.py
├── properties.py
├── constants.py
│
├── rig/
│   ├── create.py
│   ├── validate.py
│   └── metadata.py
│
├── attachment/
│   ├── attach.py
│   ├── detach.py
│   └── constraints.py
│
├── weapon/
│   ├── snap.py
│   ├── pivot.py
│   ├── aim.py
│   └── presets.py
│
├── animation/
│   ├── keyframes.py
│   ├── bake.py
│   └── evaluation.py
│
├── operators/
│   ├── rig.py
│   ├── attachment.py
│   ├── weapon.py
│   └── bake.py
│
├── ui/
│   ├── panel.py
│   └── menus.py
│
└── utils/
    ├── armature.py
    ├── transforms.py
    ├── constraints.py
    └── math.py
```

Do not put all functionality into `__init__.py`.

---

# 40. Transform Utilities

Create reliable reusable functions such as:

```python
get_world_matrix(...)
set_world_matrix(...)
get_pose_bone_world_matrix(...)
set_pose_bone_world_matrix(...)
get_bone_world_position(...)
set_child_of_inverse(...)
evaluate_pose(...)
matrix_difference(...)
```

All operations should be based on matrices rather than manually adding Euler rotations.

Prefer:

```python
mathutils.Matrix
mathutils.Quaternion
mathutils.Vector
```

over direct Euler manipulation.

Handle:

* parent transforms;
* pose transforms;
* armature object transforms;
* bone local matrices;
* world matrices;
* rotation mode differences.

---

# 41. Constraint Utilities

Create functions:

```python
find_weapon_attach_constraint(armature, hand_side)
ensure_weapon_attach_constraint(...)
set_child_of_target(...)
calculate_child_of_inverse(...)
attach_preserve_transform(...)
detach_preserve_transform(...)
keyframe_attachment(...)
```

Constraint management must be deterministic.

Never create duplicate constraints on repeated button presses.

---

# 42. Evaluation and Depsgraph

The implementation must use Blender's evaluated dependency graph when determining final transforms.

Do not assume that the current raw pose-bone matrix always represents the final evaluated transform when constraints are active.

When required:

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
```

and evaluate the relevant object.

This is especially important when:

```text
ARP IK
+
Child Of
+
weapon constraints
```

are active simultaneously.

---

# 43. Constraint Stack Safety

Constraint order matters.

The add-on must inspect existing constraints on:

```text
c_hand_ik.r
c_hand_ik.l
```

before inserting weapon constraints.

Do not blindly place the weapon constraint at an arbitrary index.

The implementation should:

1. inspect existing constraints;
2. identify ARP Child Of/parenting behavior;
3. determine a safe insertion point;
4. test the resulting evaluated transform;
5. preserve existing ARP behavior.

If the ARP hand controller already has a Child Of switch setup, integrate with it rather than creating an incompatible competing hierarchy.

Auto-Rig Pro explicitly documents multiple Child Of targets and a Snap Child Of mechanism for IK controllers.

---

# 44. Bake System

Implement:

```text
Bake Weapon Animation
```

The purpose is to convert the current control-rig result into animation data that Unreal can reproduce.

The final exported animation must contain the correct animation of:

```text
weapon_root
weapon_socket
```

The bake system should evaluate every frame in a selected range.

For each frame:

1. Evaluate the complete ARP + weapon-control rig.
2. Read final pose-space transforms.
3. Store required transforms.
4. Insert keys on the exportable bones.
5. Preserve existing animation according to the selected bake mode.

Possible MVP bake modes:

```text
Bake Selected Range
Bake Current Action
Bake New Action
```

Do not overwrite the original action by default.

Create a new baked action:

```text
Attack_Greatsword_Baked
```

or similar.

---

# 45. Bake Scope

At minimum, bake:

```text
weapon_root
weapon_socket
```

If the character's hand animation itself is also driven by weapon constraints, the exported character animation must preserve the final evaluated hand transforms as well.

Therefore the production bake should eventually support:

```text
Character + Weapon
```

rather than only the weapon bones.

The exact bake implementation should be tested with ARP-generated controllers and the deformation skeleton.

---

# 46. Unreal Target

The expected runtime setup is:

```text
Character Skeletal Mesh
        |
        +-- weapon_socket
                 |
                 +-- Sword Static Mesh Component
```

The Static Mesh should be attached to the socket in Unreal.

The animation contains the weapon socket transform.

Therefore:

```text
Animation changes weapon_socket
        |
        v
Unreal sees socket movement
        |
        v
Attached Static Mesh moves with it
```

The Static Mesh does not need:

```text
Armature
Skeleton
Skinning
Animation
```

for this purpose.

---

# 47. Important Coordinate-System Requirement

The tool must clearly define the weapon coordinate system.

For every weapon preset, store:

```text
Grip R transform
Grip L transform

Socket transform

Tip position

Blade forward axis
Blade up axis
```

Do not assume:

```text
+Y = blade direction
```

without exposing it as configuration.

This is essential for supporting different imported weapon meshes and Blender/Unreal axis conventions.

---

# 48. First Implementation Milestone

Do NOT implement everything at once.

Milestone 1 should only contain:

```text
Create Weapon Rig

weapon_root
weapon_socket
weapon_grip_r
weapon_grip_l
weapon_tip

Attach R
Detach R
Attach L
Detach L

Attach Both
Detach Both

Validate Rig
```

Success criterion:

A two-handed sword can be animated with both ARP hands following independent weapon grip bones, and attachment/detachment never causes a visible pop.

Do not implement Aim/Pivot/Bake UI before this is reliable.

---

# 49. Second Milestone

Add:

```text
Snap Weapon -> Right Hand
Snap Weapon -> Left Hand
Snap Weapon -> Both Hands
```

Test especially:

```text
existing character pose
existing hand animation
existing weapon animation
```

The snapping operation must not unexpectedly modify the character.

---

# 50. Third Milestone

Add:

```text
Pivot -> Tip
Pivot -> Grip R
Pivot -> Grip L
Pivot -> 3D Cursor
```

Test:

```text
weapon remains visually stationary when switching pivot
rotation occurs around the selected point
```

---

# 51. Fourth Milestone

Add:

```text
weapon_aim
Aim Weapon
Point Blade At
Roll
```

Test:

```text
sword points toward target
sword roll remains controllable
moving target produces expected result
```

---

# 52. Fifth Milestone

Add baking:

```text
Bake Weapon Animation
```

Test exported transforms independently of the control rig.

The ultimate validation is:

```text
Blender control rig
        |
        v
Bake
        |
        v
FBX
        |
        v
Unreal Engine
        |
        v
Static Mesh attached to weapon_socket
```

The UE result should visually match Blender.

---

# 53. Testing Matrix

The agent must create repeatable tests for these cases.

## Test A — Right hand attachment

```text
Move weapon.
Attach right hand.
```

Expected:

```text
Right hand follows weapon.
No initial jump.
```

## Test B — Left hand attachment

Same for left.

## Test C — Both hands

```text
Attach both.
Move/rotate weapon_root.
```

Expected:

```text
Both hands follow their grips.
```

## Test D — Detach

```text
Both attached.
Detach left.
```

Expected:

```text
Left hand remains visually stationary at detach frame.
Weapon continues independently.
```

## Test E — Reattach

```text
Left hand approaches grip.
Attach left.
```

Expected:

```text
No unexpected teleportation.
```

## Test F — Existing animation

Start with an existing ARP animation.

Create weapon rig.

Expected:

```text
Character animation remains unchanged.
```

## Test G — Pivot tip

```text
Set pivot to tip.
Rotate weapon_root.
```

Expected:

```text
Sword rotates around the tip.
```

## Test H — Two-hand snap

```text
Pose both hands.
Snap weapon to both hands.
```

Expected:

```text
Both grips align with hands within acceptable error.
```

## Test I — Unreal export

Bake and export.

Expected:

```text
weapon_socket animation reproduces the Blender result.
```

---

# 54. Error Handling

The add-on should never fail silently.

Examples:

```text
"Auto-Rig Pro armature not found."

"Required ARP bone c_hand_ik.l was not found."

"Weapon rig already exists."

"Weapon root name conflicts with an unrelated bone."

"Cannot attach hand because weapon_grip_l is missing."

"Both-hand solve failed: target hand distance is too small."

"Bake failed: evaluated pose could not be resolved."
```

Errors should identify the exact missing element.

---

# 55. Two-Hand Solver Edge Cases

The solver must handle:

```text
hands extremely close together
```

without producing unstable rotations.

If:

```text
distance(hand_r, hand_l) < epsilon
```

then two-hand orientation is mathematically ambiguous.

Fallback:

```text
Use right-hand orientation + current weapon roll.
```

Report a warning rather than generating an unstable quaternion.

Also handle:

* mirrored poses;
* crossed hands;
* hands passing through each other;
* weapon pointing directly along the chosen up axis;
* near-180-degree vector alignment.

Quaternion alignment must account for these cases.

---

# 56. Avoid Euler Flip Problems

All internal calculations should use quaternions/matrices.

Do not calculate weapon aiming using:

```python
rotation_euler = ...
```

from manually computed `atan2` values unless there is a specific reason.

The resulting animation can use the existing bone rotation mode, but mathematical calculations should be performed in quaternion/matrix space.

---

# 57. Documentation Required Inside the Code

Every major subsystem must include comments explaining:

```text
WHY the system is structured this way
WHAT transform space is expected
WHICH bones are exported
WHICH bones are controls
WHY Child Of is used rather than actual parenting
```

Especially document:

```text
Attach/detach compensation
Both-hand solver
Dynamic pivot
Bake process
```

These are the highest-risk components.

---

# 58. Design Principle

The entire system should follow this conceptual model:

```text
                 WEAPON IS PRIMARY

                       weapon_root
                            |
                       weapon_socket
                            |
                          SWORD


             HANDS ARE OPTIONAL FOLLOWERS

                       grip_r
                          |
                     hand IK R

                       grip_l
                          |
                     hand IK L
```

Not:

```text
                         HAND IS PRIMARY

                         hand_l
                            |
                          sword
```

This distinction is the foundation of the system.

---

# 59. Final Desired Animator Experience

The animator should be able to think in terms of:

```text
"I am animating the sword."
```

rather than:

```text
"I am trying to make the sword follow my hand correctly."
```

Typical workflow:

```text
1. Create/open weapon rig.
2. Select weapon_root.
3. Move and rotate the sword.
4. Attach both hands.
5. Refine hand IK offsets.
6. Animate the sword attack.
7. Detach a hand when needed.
8. Reattach when needed.
9. Change pivot to tip/guard/cursor whenever useful.
10. Aim the blade at targets where required.
11. Bake.
12. Export character animation.
13. Attach the weapon Static Mesh to weapon_socket in Unreal.
```

The animator should rarely need to manually touch:

```text
Child Of inverse
constraint Influence
constraint ordering
local/world matrix conversion
bone parenting
FBX export settings for control bones
```

The add-on exists specifically to hide this technical complexity.

---

# 60. MVP Definition of Done

The first production-ready version is complete when all of the following are true:

```text
[ ] Works with a generated Auto-Rig Pro character.
[ ] Creates weapon_root.
[ ] Creates weapon_socket.
[ ] Creates weapon_grip_r.
[ ] Creates weapon_grip_l.
[ ] Creates weapon_tip.
[ ] Does not modify ARP reference bones.
[ ] Does not break existing ARP controls.
[ ] Attach R works.
[ ] Attach L works.
[ ] Attach Both works.
[ ] Detach R works.
[ ] Detach L works.
[ ] Detach Both works.
[ ] Attach preserves current pose.
[ ] Detach preserves current pose.
[ ] Attachment states can be keyframed.
[ ] Weapon remains independent from hand rotations.
[ ] Weapon can be animated independently.
[ ] Weapon can drive both hands through IK.
[ ] Weapon can drive only one hand.
[ ] Weapon can be completely independent.
[ ] Weapon socket is suitable for UE export.
[ ] No skeletal weapon mesh is required.
[ ] Existing animation remains intact.
[ ] Rig validation works.
```

The advanced version is complete when these additionally work:

```text
[ ] Snap Weapon -> Right Hand
[ ] Snap Weapon -> Left Hand
[ ] Snap Weapon -> Both Hands
[ ] Pivot -> Tip
[ ] Pivot -> Grip R
[ ] Pivot -> Grip L
[ ] Pivot -> 3D Cursor
[ ] Aim Weapon
[ ] Point Blade At
[ ] Manual Roll
[ ] Weapon presets
[ ] Preview weapon mesh
[ ] Bake weapon/character animation
[ ] UE round-trip validation
```

---

# 61. Recommended Implementation Order

Do not attempt to implement all features in one pass.

Use this exact order:

```text
PHASE 1
Rig creation + validation

PHASE 2
Weapon bone hierarchy

PHASE 3
Child Of attachment constraints

PHASE 4
Transform-preserving Attach/Detach

PHASE 5
Keyframed attachment states

PHASE 6
Snap to one hand

PHASE 7
Snap to both hands

PHASE 8
Dynamic pivot

PHASE 9
Aim/target system

PHASE 10
Bake/export

PHASE 11
Weapon presets

PHASE 12
UI polish/hotkeys
```

After each phase, run the relevant tests before continuing.

Do not proceed to Phase 7 if Phase 4 still produces occasional transform pops.

Do not implement the Unreal export layer until the Blender-side evaluated result is stable.

---

# 62. Final Architectural Summary

The final architecture should be:

```text
                           CHARACTER ROOT
                                  |
                +-----------------+-----------------
                |                                   |
          AUTO-RIG PRO                        WEAPON SYSTEM
                |                                   |
         normal ARP rig                        weapon_root
                |                                   |
       c_hand_ik.r / l                       weapon_socket
                |                              /          \
                |                         grip_r          grip_l
                |                           ^                ^
                |                           |                |
                +------ Child Of -----------+                |
                |                                            |
                +------------- Child Of --------------------+
```

More precisely:

```text
weapon_root
    |
    +-- weapon_socket        [EXPORT]
    +-- weapon_grip_r        [CONTROL]
    +-- weapon_grip_l        [CONTROL]
    +-- weapon_tip           [CONTROL]
    +-- weapon_aim           [CONTROL]
```

with:

```text
c_hand_ik.r
    -> WPN_Attach_R
    -> weapon_grip_r

c_hand_ik.l
    -> WPN_Attach_L
    -> weapon_grip_l
```

The central design rule is:

```text
WEAPON BONES ARE INDEPENDENT.
HANDS FOLLOW WEAPON GRIPS WHEN ATTACHED.
UNREAL FOLLOWS weapon_socket.
THE WEAPON ITSELF REMAINS A STATIC MESH.
```

This architecture should be treated as the foundation of the add-on. Additional features should extend this system rather than introducing another competing hierarchy.
