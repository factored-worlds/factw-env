"""One desktop with a live robot camera and settled SMSL facts."""

import math
import time

from .window import PEGS, HanoiWindow


def run_desktop(session):
    """Use the calling command's recording session until the window closes."""
    desktop = _Desktop(session)
    try:
        desktop.run()
    finally:
        desktop.view.root.destroy()


class _Desktop:
    def __init__(self, session):
        self.session = session
        self.agent = session.mode == "agent"
        self.camera = "overview"
        self.source = None
        self.paused = False
        self.status = None
        self.error = None
        self.next_move = 0.0
        self.steps_since_frame = 0
        self.callback = None
        self.view = HanoiWindow(self)

    def run(self):
        root = self.view.root
        self._update()
        root.report_callback_exception = self._callback_error
        self.callback = root.after_idle(self._start)
        try:
            root.mainloop()
        finally:
            if self.callback is not None:
                root.after_cancel(self.callback)
        if self.error is not None:
            raise self.error

    def _callback_error(self, _kind, error, traceback):
        self.error = error.with_traceback(traceback)
        self.view.root.quit()

    def _start(self):
        self._frame()
        self.next_move = time.monotonic() + 0.5
        self._tick()

    def _frame(self):
        self.view.show_frame(self.session.frame(self.camera))

    def _update(self):
        self.view.show_state(self.session, self.source, self.status, paused=self.paused)

    def _tick(self):
        self.callback = None
        started = time.monotonic()
        session = self.session
        if self.agent and not self.paused and not session.active and started >= self.next_move:
            if not session.solved and not session.failed:
                session.next_agent_move()
        if session.active and not self.paused:
            session.advance()
            self.steps_since_frame += 1
            if not session.active:
                self.next_move = time.monotonic() + 0.35
            if self.steps_since_frame >= 2 or not session.active or session.solved:
                self._frame()
                self.steps_since_frame = 0
        self._update()
        if session.solved or session.failed:
            return
        period = session.control_dt if session.active else 0.05
        seconds = max(0.001, period - (time.monotonic() - started))
        self.callback = self.view.root.after(math.ceil(seconds * 1000), self._tick)

    def choose_peg(self, peg):
        session = self.session
        if self.agent or session.active or session.solved or session.failed:
            return
        self.status = None
        if self.source is None:
            if peg in session.pegs:
                self.source = peg
            else:
                self.status = f"Peg {PEGS[peg]} is empty. Choose a peg with a disk."
        elif peg == self.source:
            self.source = None
        else:
            disk = session.pegs.index(self.source)
            if session.request(disk, peg):
                self.source = None
            else:
                self.status = session.status
        self._update()

    def cancel_selection(self):
        if not self.agent and self.source is not None:
            self.source = self.status = None
            self._update()

    def select_camera(self, camera):
        if camera != self.camera:
            self.camera = camera
            self.view.show_camera(camera)
            self._frame()

    def toggle_pause(self):
        if self.agent and not self.session.solved and not self.session.failed:
            self.paused = not self.paused
            self._update()
