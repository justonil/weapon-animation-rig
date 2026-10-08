"""Weapon Animation Rig -- Blender add-on entry point.

Purpose (plan §1): an independent weapon-animation control system layered on
top of an Auto-Rig Pro character rig. The weapon is animated via dedicated
weapon bones (never parented to the hands); ARP hand IK controllers follow
the weapon grips through Child Of constraints with animatable influence.

This file only wires registration. Subsystems live in their own modules
(plan §39: "Do not put all functionality into __init__.py").
"""
bl_info = {
    "name": "Weapon Animation Rig",
    "author": "Assistant",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),  # uses slotted-action API (4.4+), tested on 5.2
    "location": "View3D > Sidebar > Weapon",
    "description": "Independent weapon animation controls on top of "
                   "Auto-Rig Pro: weapon bones, hand attach/detach without "
                   "pops, keyframed attachment states",
    "category": "Animation",
}

from . import properties  # noqa: E402
from .operators import aim as aim_ops  # noqa: E402
from .operators import attachment as attachment_ops  # noqa: E402
from .operators import bake as bake_ops  # noqa: E402
from .operators import pivot as pivot_ops  # noqa: E402
from .operators import presets as preset_ops  # noqa: E402
from .operators import preview as preview_ops  # noqa: E402
from .operators import rig as rig_ops  # noqa: E402
from .operators import rotate as rotate_ops  # noqa: E402
from .operators import weapon as weapon_ops  # noqa: E402
from .ui import menus  # noqa: E402
from .ui import overlay  # noqa: E402
from .ui import panel  # noqa: E402

_MODULES = (properties, rig_ops, attachment_ops, pivot_ops, weapon_ops,
            rotate_ops, aim_ops, bake_ops, preset_ops, preview_ops, menus,
            overlay, panel)


def register():
    for mod in _MODULES:
        mod.register()


def unregister():
    for mod in reversed(_MODULES):
        mod.unregister()


if __name__ == "__main__":
    register()
