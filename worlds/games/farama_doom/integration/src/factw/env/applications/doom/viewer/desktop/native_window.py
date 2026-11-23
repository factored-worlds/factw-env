"""Host one SDL game window in a Tk widget on an X11 display."""

from contextlib import contextmanager
from ctypes import (
    CDLL,
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_int16,
    c_uint8,
    c_uint16,
    c_uint32,
    c_void_p,
    string_at,
)


class Cookie(Structure):
    _fields_ = [("sequence", c_uint32)]


class Error(Structure):
    _fields_ = [("response_type", c_uint8), ("code", c_uint8)]


HEADER = [
    ("response_type", c_uint8),
    ("flags", c_uint8),
    ("sequence", c_uint16),
    ("length", c_uint32),
]


class Tree(Structure):
    _fields_ = [*HEADER, ("root", c_uint32), ("parent", c_uint32)]


class Geometry(Structure):
    _fields_ = [
        *HEADER,
        ("root", c_uint32),
        ("x", c_int16),
        ("y", c_int16),
        ("width", c_uint16),
        ("height", c_uint16),
    ]


class Attributes(Structure):
    _fields_ = [
        *HEADER,
        ("visual", c_uint32),
        ("window_class", c_uint16),
        ("bit_gravity", c_uint8),
        ("win_gravity", c_uint8),
        ("backing_planes", c_uint32),
        ("backing_pixel", c_uint32),
        ("save_under", c_uint8),
        ("map_is_installed", c_uint8),
        ("map_state", c_uint8),
    ]


WM_CLASS = 67
STRING = 31
BAD_WINDOW, BAD_MATCH, BAD_DRAWABLE = 3, 8, 9
CURRENT_TIME = 0
REVERT_TO_PARENT = 2
POSITION_AND_SIZE = 0b1111
UNMAPPED = 0


def _library():
    xcb = CDLL("libxcb.so.1")
    connection, window, error = c_void_p, c_uint32, POINTER(Error)
    bindings = {
        "connect": ([c_char_p, POINTER(c_int)], connection),
        "connection_has_error": ([connection], c_int),
        "disconnect": ([connection], None),
        "query_tree": ([connection, window], Cookie),
        "query_tree_reply": ([connection, Cookie, POINTER(error)], POINTER(Tree)),
        "query_tree_children": ([POINTER(Tree)], POINTER(window)),
        "query_tree_children_length": ([POINTER(Tree)], c_int),
        "get_property": ([connection, c_uint8, window, window, window, window, window], Cookie),
        "get_property_reply": ([connection, Cookie, POINTER(error)], c_void_p),
        "get_property_value": ([c_void_p], c_void_p),
        "get_property_value_length": ([c_void_p], c_int),
        "get_geometry": ([connection, window], Cookie),
        "get_geometry_reply": ([connection, Cookie, POINTER(error)], POINTER(Geometry)),
        "get_window_attributes": ([connection, window], Cookie),
        "get_window_attributes_reply": ([connection, Cookie, POINTER(error)], POINTER(Attributes)),
        "reparent_window_checked": ([connection, window, window, c_int16, c_int16], Cookie),
        "map_window_checked": ([connection, window], Cookie),
        "configure_window_checked": ([connection, window, c_uint16, POINTER(c_uint32)], Cookie),
        "set_input_focus_checked": ([connection, c_uint8, window, c_uint32], Cookie),
        "request_check": ([connection, Cookie], error),
    }
    for name, (arguments, result) in bindings.items():
        method = getattr(xcb, f"xcb_{name}")
        method.argtypes, method.restype = arguments, result
    return xcb


def _free():
    free = CDLL(None).free
    free.argtypes, free.restype = [c_void_p], None
    return free


class NativeWindow:
    """Aspect-fit the SDL child selected by its launcher-specific WM_CLASS."""

    def __init__(self, display, parent_id, window_class):
        self._xcb, self._free = _library(), _free()
        self._parent = parent_id
        self._window_class = window_class.encode("ascii")
        self._connection = self._xcb.xcb_connect(display.encode(), None)
        if self._xcb.xcb_connection_has_error(self._connection):
            self.close()
            raise RuntimeError(f"Could not connect to Doom's X11 display {display}")
        self._window = None
        self._size = None
        self._last_bounds = None
        self._focused = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._connection:
            self._xcb.xcb_disconnect(self._connection)
            self._connection = None

    def _error(self, error, action, recoverable):
        if not error:
            return False
        code = error.contents.code
        self._free(error)
        if code in recoverable:
            return True
        raise RuntimeError(f"Doom X11 {action} failed with error {code}")

    @contextmanager
    def _reply(self, action, *args):
        request = getattr(self._xcb, f"xcb_{action}")
        receive = getattr(self._xcb, f"xcb_{action}_reply")
        error = POINTER(Error)()
        reply = receive(self._connection, request(self._connection, *args), byref(error))
        try:
            if self._error(error, action, {BAD_WINDOW, BAD_DRAWABLE}):
                yield None
            elif not reply:
                raise RuntimeError(f"Doom X11 {action} did not return a reply")
            else:
                yield reply
        finally:
            self._free(reply)

    def _checked(self, action, *args, recoverable=(BAD_WINDOW,)):
        request = getattr(self._xcb, f"xcb_{action}_checked")
        error = self._xcb.xcb_request_check(self._connection, request(self._connection, *args))
        return not self._error(error, action, recoverable)

    def _children(self, window):
        with self._reply("query_tree", window) as tree:
            if tree is None:
                return []
            length = self._xcb.xcb_query_tree_children_length(tree)
            return self._xcb.xcb_query_tree_children(tree)[:length]

    def _find(self):
        with self._reply("query_tree", self._parent) as tree:
            if tree is None:
                return None
            root = tree.contents.root
        pending = self._children(root)
        for window in pending:
            with self._reply("get_property", 0, window, WM_CLASS, STRING, 0, 64) as prop:
                if prop:
                    raw = string_at(
                        self._xcb.xcb_get_property_value(prop),
                        self._xcb.xcb_get_property_value_length(prop),
                    )
                    if self._window_class in raw.split(b"\0"):
                        return window
            pending.extend(self._children(window))
        return None

    def _bounds(self, width, height):
        native_width, native_height = self._size
        scale = min(width / native_width, height / native_height)
        fitted_width = max(1, round(native_width * scale))
        fitted_height = max(1, round(native_height * scale))
        return (
            (width - fitted_width) // 2,
            (height - fitted_height) // 2,
            fitted_width,
            fitted_height,
        )

    def poll(self, width, height):
        """Attach or resize the game and report whether its native window exists."""
        if not self._connection or width <= 1 or height <= 1:
            return False
        if self._window is None:
            window = self._find()
            if window is None:
                return False
            with self._reply("get_window_attributes", window) as attributes:
                if attributes is None:
                    return False
                if attributes.contents.map_state != UNMAPPED:
                    raise RuntimeError("The embedded Doom worker must start with a hidden window")
            with self._reply("get_geometry", window) as geometry:
                if geometry is None:
                    return False
                self._size = geometry.contents.width, geometry.contents.height
            bounds = self._bounds(width, height)
            if not self._checked("reparent_window", window, self._parent, *bounds[:2]):
                return False
            if not self._checked(
                "configure_window", window, POSITION_AND_SIZE, (c_uint32 * 4)(*bounds)
            ) or not self._checked("map_window", window):
                return False
            self._window = window
            self._last_bounds = bounds
            self._focused = False
        else:
            window = self._window
            with self._reply("query_tree", window) as tree:
                if tree is None or tree.contents.parent != self._parent:
                    self._window = None
                    return False
            bounds = self._bounds(width, height)
        if bounds != self._last_bounds:
            if not self._checked(
                "configure_window", window, POSITION_AND_SIZE, (c_uint32 * 4)(*bounds)
            ):
                self._window = None
                return False
            self._last_bounds = bounds
        if not self._focused:
            self._focused = self._checked(
                "set_input_focus",
                REVERT_TO_PARENT,
                window,
                CURRENT_TIME,
                recoverable=(BAD_WINDOW, BAD_MATCH),
            )
        return True
