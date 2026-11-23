"""An explicitly closed, lazily allocated RGB/depth renderer."""

import mujoco


class Camera:
    def __init__(self, model, width, height):
        self.model, self.width, self.height = model, width, height
        self.renderer = None

    def capture(self, data):
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=self.height, width=self.width)
        self.renderer.update_scene(data, camera="overview")
        rgb = self.renderer.render().copy()
        self.renderer.enable_depth_rendering()
        depth = self.renderer.render().copy()
        self.renderer.disable_depth_rendering()
        return rgb, depth

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
