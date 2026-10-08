"""3D View sidebar panel (plan §32).

Milestone 1 scope (plan §48): Weapon Rig (detect/create), Hands
(attach/detach/mode), Debug (validate + report). Snap/Pivot/Aim/Bake
sections arrive with their own milestones and are intentionally absent here.
"""
import bpy


class WPN_PT_main(bpy.types.Panel):
    bl_label = "Weapon Animation"
    bl_idname = "WPN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Weapon"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ------------------------------------------------------------------
        # Weapon Rig
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Weapon Rig", icon='OUTLINER_OB_ARMATURE')
        col = box.column(align=True)
        col.operator("wpn.auto_detect", icon='VIEWZOOM')
        col.operator("wpn.create_rig", icon='ADD')

        arm = scene.wpn_armature
        if arm is not None:
            box.label(text="Character: %s" % arm.name, icon='ARMATURE_DATA')
        else:
            box.label(text="Character: (none -- Auto Detect)", icon='ERROR')

        # Grip reference points (rework: bone-local vectors in custom
        # props, not bones). Editable here; presets store per-weapon sets.
        # Markers in the 3D view show where each point is; the cursor
        # buttons place a point exactly at the 3D cursor.
        wbone = None
        if arm is not None:
            wbone = arm.data.bones.get("weapon")
        if wbone is not None:
            for prop, label, target in (("grip_r", "Grip R", "GRIP_R"),
                                        ("grip_l", "Grip L", "GRIP_L"),
                                        ("guard_l", "Guard L",
                                         "GUARD_L"),
                                        ("guard_r", "Guard R",
                                         "GUARD_R"),
                                        ("pommel", "Pommel", "POMMEL"),
                                        ("center", "Center", "CENTER"),
                                        ("tip", "Tip", "TIP")):
                row = box.row(align=True)
                row.prop(wbone, '["%s"]' % prop, text=label)
                op = row.operator("wpn.grip_from_cursor", text="",
                                  icon='CURSOR')
                op.target = target
            row = box.row(align=True)
            row.prop(scene, "wpn_show_grips", text="Show Points")

        # Weapon presets (plan §17): same framework, different weapons.
        row = box.row()
        row.label(text="Weapon:")
        if scene.wpn_presets:
            idx = max(0, min(scene.wpn_preset_index,
                             len(scene.wpn_presets) - 1))
            row.label(text=scene.wpn_presets[idx].name, icon='PRESET')
        else:
            row.label(text="(no presets)", icon='PRESET')
        row = box.row(align=True)
        row.prop(scene, "wpn_preset_name", text="")
        op = row.operator("wpn.save_preset", text="", icon='ADD')
        op.name = scene.wpn_preset_name or "Weapon"
        op = box.operator("wpn.apply_preset", text="Apply Preset",
                          icon='IMPORT')

        # Preview weapon mesh (plan §16): viewport stand-in for the UE
        # Static Mesh. Never an animation source.
        box.label(text="Preview Mesh", icon='MESH_DATA')
        row = box.row(align=True)
        row.operator("wpn.set_preview_mesh", text="Set Preview",
                     icon='MESH_CUBE')
        row.operator("wpn.clear_preview_mesh", text="Clear",
                     icon='X')

        # ------------------------------------------------------------------
        # Hands
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Hands", icon='HAND')

        col = box.column(align=True)
        row = col.row(align=True)
        row.operator("wpn.attach", text="Attach R").side = 'R'
        row.operator("wpn.detach", text="Detach R").side = 'R'
        row = col.row(align=True)
        row.operator("wpn.attach", text="Attach L").side = 'L'
        row.operator("wpn.detach", text="Detach L").side = 'L'
        row = col.row(align=True)
        row.operator("wpn.attach", text="Attach Both").side = 'BOTH'
        row.operator("wpn.detach", text="Detach Both").side = 'BOTH'

        row = box.row(align=True)
        row.label(text="Mode:")
        for mode in ('FREE', 'RIGHT', 'LEFT', 'BOTH'):
            op = row.operator("wpn.set_mode", text=mode.capitalize(),
                              icon='CHECKMARK' if scene.wpn_mode == mode
                              else 'BLANK1')
            op.mode = mode

        # ------------------------------------------------------------------
        # Snap (plan §18-20 -- Milestone 2)
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Snap", icon='ORIENTATION_GLOBAL')
        col = box.column(align=True)
        op = col.operator("wpn.snap_to_hand", text="Weapon -> Right Hand")
        op.side = 'R'
        op = col.operator("wpn.snap_to_hand", text="Weapon -> Left Hand")
        op.side = 'L'
        col.operator("wpn.snap_to_both",
                     text="Weapon -> Both Hands")

        # ------------------------------------------------------------------
        # Pivot (plan §21-24 -- Milestone 3)
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Pivot", icon='PIVOT_ACTIVE')
        col = box.column(align=True)
        row = col.row(align=True)
        for preset, label in (('CENTER', "Center"),
                              ('GRIP_R', "Grip R"),
                              ('GRIP_L', "Grip L"),
                              ('GUARD', "Guard")):
            op = row.operator("wpn.select_pivot", text=label)
            op.pivot = preset
        row = col.row(align=True)
        for preset, label in (('GUARD_L', "Guard L"),
                              ('GUARD_R', "Guard R"),
                              ('TIP', "Tip"),
                              ('POMMEL', "Pommel")):
            op = row.operator("wpn.select_pivot", text=label)
            op.pivot = preset
        row = col.row(align=True)
        for preset, label in (('CURSOR', "3D Cursor"),
                              ('CUSTOM', "Custom")):
            op = row.operator("wpn.select_pivot", text=label)
            op.pivot = preset
        if scene.wpn_pivot == 'CUSTOM':
            box.prop(scene, "wpn_pivot_custom", text="")
        op = box.operator("wpn.set_pivot", text="Set Pivot",
                          icon='PIVOT_ACTIVE')
        op.pivot = scene.wpn_pivot
        box.operator("wpn.create_weapon_orientation",
                     text="Create Orientation from Weapon",
                     icon='ORIENTATION_LOCAL')

        # ------------------------------------------------------------------
        # Aim (plan §25-27 -- Milestone 4)
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Aim", icon='ORIENTATION_VIEW')
        row = box.row()
        row.label(text="Target:")
        row.label(text="weapon_aim")
        col = box.column(align=True)
        op = col.operator("wpn.aim_weapon", text="Aim Weapon",
                          icon='TRACKING')
        op.roll = scene.wpn_roll
        op = col.operator("wpn.point_blade_at", text="Point Blade At",
                          icon='CON_TRACKTO')
        op.roll = scene.wpn_roll
        row = box.row()
        row.prop(scene, "wpn_roll", text="Roll")
        op = row.operator("wpn.set_roll", text="Apply")
        op.roll = scene.wpn_roll
        box.operator("wpn.stop_aim", text="Stop Aim")

        # ------------------------------------------------------------------
        # Rotate (user-requested: pivot + drag interaction)
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Rotate", icon='ORIENTATION_VIEW')
        # Editable selectors (user request: "add selection") -- the same
        # scene.wpn_pivot drives Set Pivot, so both stay in sync.
        row = box.row(align=True)
        row.prop(scene, "wpn_pivot", text="Pivot")
        row.prop(scene, "wpn_drag", text="Drag")
        handle = bpy.data.objects.get(scene.wpn_rot_handle or "")
        if handle is None:
            box.operator("wpn.handle_create",
                         text="Create Rotate Handle",
                         icon='EMPTY_ARROWS')
        else:
            row = box.row(align=True)
            sub = row.row(align=True)
            sub.label(text="Handle: %s" % handle.name,
                      icon='EMPTY_ARROWS')
            row.operator("wpn.handle_remove", text="", icon='X')
            row.operator("wpn.handle_create", text="",
                         icon='FILE_REFRESH')
        col = box.column(align=True)
        op = col.operator("wpn.rotate_to_cursor",
                          text="Rotate to Cursor", icon='CURSOR')
        op.pivot = scene.wpn_pivot
        op.drag = scene.wpn_drag
        op = col.operator("wpn.rotate_drag", text="Drag Rotate",
                          icon='MOUSE_LMB_DRAG')
        op.pivot = scene.wpn_pivot
        op.drag = scene.wpn_drag

        # ------------------------------------------------------------------
        # Bake (plan §44-45 -- Milestone 5)
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Bake", icon='RENDER_ANIMATION')
        row = box.row()
        row.label(text="Frame:")
        row.prop(scene, "frame_start", text="Start")
        row.prop(scene, "frame_end", text="End")
        box.operator("wpn.bake", text="Bake Weapon Animation",
                     icon='RENDER_ANIMATION')

        # ------------------------------------------------------------------
        # Debug
        # ------------------------------------------------------------------
        box = layout.box()
        box.label(text="Debug", icon='VIEWZOOM')
        row = box.row(align=True)
        row.operator("wpn.validate_rig", icon='FILE_TICK')
        op = row.operator("wpn.toggle_rig_visibility", icon='HIDE_OFF')
        op.show = True
        op = row.operator("wpn.toggle_rig_visibility", icon='HIDE_ON')
        op.show = False
        if scene.wpn_report:
            col = box.column(align=True)
            for line in scene.wpn_report.split("\n"):
                col.label(text=line)


CLASSES = (WPN_PT_main,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
