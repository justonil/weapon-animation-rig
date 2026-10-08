"""Fast animation controls: weapon pie menu (plan §33).

The first milestone prioritized reliable operators over shortcuts; with the
core now covered by repeatable headless tests, the pie menu wires them
together for animation speed. The default hotkey is registered into the
addon's own keymap (removable in Preferences > Keymap) and never touches
Blender's defaults beyond adding one entry.
"""
import bpy

ADDON_KEYMAPS = []


class WPN_MT_pie(bpy.types.Menu):
    """Weapon fast controls (plan §33 concept layout)"""
    bl_label = "Weapon"
    bl_idname = "WPN_MT_pie"

    def draw(self, context):
        # Slot order: left, right, bottom, top, top-left, top-right,
        # bottom-left, bottom-right (matches plan §33 concept layout).
        pie = self.layout.menu_pie()
        op = pie.operator("wpn.attach", text="Attach L")
        op.side = 'L'
        op = pie.operator("wpn.attach", text="Attach R")
        op.side = 'R'
        pie.operator("wpn.aim_weapon", text="Aim")
        op = pie.operator("wpn.attach", text="Attach Both")
        op.side = 'BOTH'
        op = pie.operator("wpn.set_pivot", text="Pivot")
        op.pivot = 'TIP'
        op = pie.operator("wpn.detach", text="Detach")
        op.side = 'BOTH'
        pie.operator("wpn.snap_to_both", text="Snap")
        pie.operator("wpn.validate_rig", text="Validate")


def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="3D View", space_type='VIEW_3D')
    # Ctrl+Shift+W: unlikely to collide; operator still reachable via the
    # pie menu search (F3 "Weapon") if the user removes the binding.
    kmi = km.keymap_items.new("wm.call_menu_pie", 'W', 'PRESS',
                              ctrl=True, shift=True)
    kmi.properties.name = "WPN_MT_pie"
    ADDON_KEYMAPS.append((km, kmi))


def unregister_keymap():
    for km, kmi in ADDON_KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except (ValueError, ReferenceError, RuntimeError):
            pass
    ADDON_KEYMAPS.clear()


def register():
    bpy.utils.register_class(WPN_MT_pie)
    register_keymap()


def unregister():
    unregister_keymap()
    bpy.utils.unregister_class(WPN_MT_pie)
