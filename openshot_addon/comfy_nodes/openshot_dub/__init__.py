"""OpenShot dubbing nodes for ComfyUI.

Installed as ``custom_nodes/openshot_dub`` — see openshot_addon/README.md.
"""

from .nodes import OpenShotDubAudio

NODE_CLASS_MAPPINGS = {
    "OpenShotDubAudio": OpenShotDubAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenShotDubAudio": "OpenShot · Dub to another language",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
