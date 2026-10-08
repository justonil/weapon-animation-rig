"""Sidebar UI: collapsible subpanels under Weapon Animation (Blender idiom).

One panel per workflow step instead of a single long scroll: Rig Setup,
Hands, Pivot, Rotate, Aim, Bake, Debug. Buttons show live state where it
matters (attached/free hands, active pivot preset), everything else is the
same operators and scene props as before.
"""
import bpy

from ..utils import constraints as con_util


def _arm(scene):
    arm = scene.wpn_armature
    if arm is None or arm.type != 'ARMATURE':
        return None
    return arm


def _attach_state(arm, side):
    try:
        con = con_util.find_attach_constraint(arm, side)
        return con is not None and con.influence > 0.0
    except Exception:
        return False


def _subpanel(label, closed=False):
    """Class decorator stamping standard subpanel boilerplate."""
    def wrap(cls):
        cls.bl_label = label
        cls.bl_idname = "WPN_PT_" + label.lower().replace(" ", "_")
        cls.bl_space_type = 'VIEW_3D'
        cls.bl_region_type = 'UI'
        cls.bl_category = "Weapon"
        cls.bl_parent_id = "WPN_PT_main"
        if closed:
            cls.bl_options = {'DEFAULT_CLOSED'}
        return cls
    return wrap


class WPN_PT_main(bpy.types.Panel):
    bl_label = "Weapon Animation"
    bl_idname = "WPN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Weapon"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        col = layout.column(align=True)
        col.operator("wpn.auto_detect", icon='VIEWZOOM')
        col.operator("wpn.create_rig", icon='ADD')
        arm = _arm(scene)
        if arm is not None:
            layout.label(text="Character: %s" % arm.name,
                         icon='ARMATURE_DATA')
        else:
            layout.label(text="No rig: Auto Detect first",
                         icon='ERROR')


@_subpanel("Rig Setup", closed=True)
class WPN_PT_rig_setup(bpy.types.Panel):
    bl_description = "Grip points, weapon presets, preview mesh"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        scene = context.scene
        arm = _arm(scene)
        wbone = arm.data.bones.get("weapon") if arm is not None else None
        if wbone is None:
            layout.label(text="Create the rig first", icon='INFO')
            return
        for prop, label, target in (("grip_r", "Grip R", "GRIP_R"),
                                    ("grip_l", "Grip L", "GRIP_L"),
                                    ("guard_l", "Guard L", "GUARD_L"),
                                    ("guard_r", "Guard R", "GUARD_R"),
                                    ("pommel", "Pommel", "POMMEL"),
                                    ("center", "Center", "CENTER"),
                                    ("tip", "Tip", "TIP")):
            row = layout.row(align=True)
            row.prop(wbone, '["%s"]' % prop, text=label)
            op = row.operator("wpn.grip_from_cursor", text="",
                              icon='CURSOR')
            op.target = target
        layout.prop(scene, "wpn_show_grips", text="Show Points")

        layout.separator()
        row = layout.row()
        row.label(text="Preset:")
        if scene.wpn_presets:
            idx = max(0, min(scene.wpn_preset_index,
                             len(scene.wpn_presets) - 1))
            row.label(text=scene.wpn_presets[idx].name, icon='PRESET')
        else:
            row.label(text="(none)", icon='PRESET')
        row = layout.row(align=True)
        row.prop(scene, "wpn_preset_name", text="")
        op = row.operator("wpn.save_preset", text="", icon='ADD')
        op.name = scene.wpn_preset_name or "Weapon"
        layout.operator("wpn.apply_preset", text="Apply Preset",
                        icon='IMPORT')

        layout.separator()
        layout.label(text="Preview Mesh", icon='MESH_DATA')
        row = layout.row(align=True)
        row.operator("wpn.set_preview_mesh", text="Set",
                     icon='MESH_CUBE')
        row.operator("wpn.clear_preview_mesh", text="Clear", icon='X')


@_subpanel("Hands")
class WPN_PT_hands(bpy.types.Panel):
    bl_description = "Attach / detach hands, snap weapon to hands"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        arm = _arm(scene)
        col = layout.column(align=True)
        for side, label in (('R', "Right"), ('L', "Left")):
            row = col.row(align=True)
            attached = _attach_state(arm, side) if arm else False
            row.label(text="%s: %s" % (
                label, "Attached" if attached else "Free"),
                icon='CHECKMARK' if attached else 'BLANK1')
            op = row.operator("wpn.attach", text="Attach")
            op.side = side
            op = row.operator("wpn.detach", text="Detach")
            op.side = side
        row = col.row(align=True)
        op = row.operator("wpn.attach", text="Attach Both")
        op.side = 'BOTH'
        op = row.operator("wpn.detach", text="Detach Both")
        op.side = 'BOTH'

        row = layout.row(align=True)
        row.label(text="Mode:")
        for mode in ('FREE', 'RIGHT', 'LEFT', 'BOTH'):
            op = row.operator("wpn.set_mode",
                              text=mode.capitalize(),
                              depress=(scene.wpn_mode == mode))
            op.mode = mode

        layout.separator()
        layout.label(text="Weapon home (follows hand):", icon='BOOKMARKS')
        try:
            from ..weapon import snap as _snap_mod
        except Exception:
            _snap_mod = None
        col = layout.column(align=True)
        for side, label in (('R', "R"), ('L', "L")):
            row = col.row(align=True)
            stored = False
            if arm is not None and _snap_mod is not None:
                try:
                    stored = _snap_mod.has_home_pose(arm, side)
                except Exception:
                    stored = False
            row.label(text="", icon='CHECKMARK' if stored
                      else 'BLANK1')
            op = row.operator("wpn.snap_record", text="W: Record %s" % label)
            op.side = side
            op = row.operator("wpn.snap_to_home", text="W: Home %s" % label)
            op.side = side

        layout.label(text="Hand home (follows weapon):", icon='BOOKMARKS')
        col = layout.column(align=True)
        for side, label in (('R', "R"), ('L', "L")):
            row = col.row(align=True)
            stored = False
            if arm is not None and _snap_mod is not None:
                try:
                    stored = _snap_mod.has_hand_home(arm, side)
                except Exception:
                    stored = False
            row.label(text="", icon='CHECKMARK' if stored
                      else 'BLANK1')
            op = row.operator("wpn.hand_home_record",
                              text="H: Record %s" % label)
            op.side = side
            op = row.operator("wpn.snap_hand_to_home",
                              text="H: Home %s" % label)
            op.side = side

        row = layout.row(align=True)
        row.prop(scene, "wpn_show_direct_snaps", text="",
                 icon='TRIA_DOWN' if scene.wpn_show_direct_snaps
                 else 'TRIA_RIGHT', emboss=False)
        row.label(text="Direct snaps (first placement only)")
        if scene.wpn_show_direct_snaps:
            layout.label(text="Weapon to hand:", icon='SNAP_ON')
            col = layout.column(align=True)
            op = col.operator("wpn.snap_to_hand", text="To Right Hand")
            op.side = 'R'
            op = col.operator("wpn.snap_to_hand", text="To Left Hand")
            op.side = 'L'
            col.operator("wpn.snap_to_both", text="To Both Hands")
            layout.label(text="Hand to weapon:", icon='BONE_DATA')
            col = layout.column(align=True)
            op = col.operator("wpn.snap_hand_to_weapon",
                              text="To Weapon R")
            op.side = 'R'
            op = col.operator("wpn.snap_hand_to_weapon",
                              text="To Weapon L")
            op.side = 'L'


@_subpanel("Pivot")
class WPN_PT_pivot(bpy.types.Panel):
    bl_description = "Pivot presets, Set Pivot, focus, orientation"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        arm = _arm(scene)
        if arm is None:
            layout.label(text="Create the rig first", icon='INFO')
            return
        # 3x3 spatial map as explicit rows (grid_flow collapses to one
        # column on narrow sidebars; rows cannot). Row-major order:
        # Guard | Tip | Cursor / Guard L | Center | Guard R /
        # Grip L | Pommel | Grip R. Custom stays in the Rotate dropdown.
        col = layout.column(align=True)
        for presets in ((('GUARD', "Guard"),
                         ('TIP', "Tip"),
                         ('CURSOR', "Cursor")),
                        (('GUARD_L', "Guard L"),
                         ('CENTER', "Center"),
                         ('GUARD_R', "Guard R")),
                        (('GRIP_L', "Grip L"),
                         ('POMMEL', "Pommel"),
                         ('GRIP_R', "Grip R"))):
            row = col.row(align=True)
            for preset, label in presets:
                op = row.operator("wpn.select_pivot", text=label,
                                   depress=(scene.wpn_pivot == preset))
                op.pivot = preset
        if scene.wpn_pivot == 'CUSTOM':
            layout.prop(scene, "wpn_pivot_custom", text="Custom Point")
        row = layout.row(align=True)
        op = row.operator("wpn.set_pivot", text="Set Pivot",
                          icon='PIVOT_ACTIVE')
        op.pivot = scene.wpn_pivot
        row.operator("wpn.create_weapon_orientation",
                     text="Orientation", icon='ORIENTATION_LOCAL')


@_subpanel("Rotate")
class WPN_PT_rotate(bpy.types.Panel):
    bl_description = "Rotate weapon around the pivot"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        scene = context.scene
        layout.prop(scene, "wpn_pivot", text="Pivot")
        layout.prop(scene, "wpn_drag", text="Drag")
        handle = bpy.data.objects.get(scene.wpn_rot_handle or "")
        if handle is None:
            layout.operator("wpn.handle_create",
                            text="Create Rotate Handle",
                            icon='EMPTY_ARROWS')
        else:
            row = layout.row(align=True)
            row.label(text="Handle: %s" % handle.name,
                      icon='EMPTY_ARROWS')
            row.operator("wpn.handle_remove", text="", icon='X')
            row.operator("wpn.handle_create", text="",
                         icon='FILE_REFRESH')
        col = layout.column(align=True)
        op = col.operator("wpn.rotate_to_cursor",
                          text="Rotate to Cursor", icon='CURSOR')
        op.pivot = scene.wpn_pivot
        op.drag = scene.wpn_drag
        op = col.operator("wpn.rotate_drag", text="Drag Rotate",
                          icon='MOUSE_LMB_DRAG')
        op.pivot = scene.wpn_pivot
        op.drag = scene.wpn_drag


@_subpanel("Aim", closed=True)
class WPN_PT_aim(bpy.types.Panel):
    bl_description = "Aim the weapon at weapon_aim"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row()
        row.label(text="Target:")
        row.label(text="weapon_aim")
        col = layout.column(align=True)
        op = col.operator("wpn.aim_weapon", text="Aim Weapon",
                          icon='TRACKING')
        op.roll = scene.wpn_roll
        op = col.operator("wpn.point_blade_at", text="Point Blade At",
                          icon='CON_TRACKTO')
        op.roll = scene.wpn_roll
        row = layout.row(align=True)
        row.prop(scene, "wpn_roll", text="Roll")
        op = row.operator("wpn.set_roll", text="Apply")
        op.roll = scene.wpn_roll
        layout.operator("wpn.stop_aim", text="Stop Aim")


@_subpanel("Bake", closed=True)
class WPN_PT_bake(bpy.types.Panel):
    bl_description = "Bake weapon animation to keys"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row()
        row.label(text="Frame:")
        row.prop(scene, "frame_start", text="Start")
        row.prop(scene, "frame_end", text="End")
        layout.operator("wpn.bake", text="Bake Weapon Animation",
                        icon='RENDER_ANIMATION')


@_subpanel("Debug", closed=True)
class WPN_PT_debug(bpy.types.Panel):
    bl_description = "Validation and reports"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row(align=True)
        row.operator("wpn.validate_rig", icon='FILE_TICK')
        op = row.operator("wpn.toggle_rig_visibility", icon='HIDE_OFF')
        op.show = True
        op = row.operator("wpn.toggle_rig_visibility", icon='HIDE_ON')
        op.show = False
        if scene.wpn_report:
            col = layout.column(align=True)
            for line in scene.wpn_report.split("\n"):
                col.label(text=line)


CLASSES = (WPN_PT_main, WPN_PT_rig_setup, WPN_PT_hands, WPN_PT_pivot,
           WPN_PT_rotate, WPN_PT_aim, WPN_PT_bake, WPN_PT_debug)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
