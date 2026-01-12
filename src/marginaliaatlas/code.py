import os
import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from collections import defaultdict


# ============================================================
# GLOBAL STATE (INTENTIONAL)
# ============================================================

G_INV = {}          # id -> inventory record
G_ATTACH = {}       # id -> attachment metadata

G_DRAG = {
    "item_id": None,
    "x": 0,
    "y": 0,
    "handle": None,
    "corner": None,
    "mode": None  # "item" | "pan"
}

HANDLE_SIZE = 6

G_PANES = {
    "tree": True,
    "canvas": True,
    "text": True,
}

g = {
    "module_highlight": None,  # module name or None
    "hover_canvas_item": None,  # formerly G_HOVER["canvas_item"]

    "cam_x": 0,  # camera X, Y position
    "cam_y": 0,
    "zoom_num": 1,  # zoom numerator
    "zoom_den": 1,  # zoom denominator

    "canvas_view_w": 0,  # We record this, because Tk is weirdly forgetful
    "canvas_view_h": 0
}

widgets = {
    "root": None,
    "panes": None,
    "tree": None,
    "canvas": None,
    "text": None
}

selection_set = set()  # set of item ids that are selected


# ============================================================
# Render State (Projected, Screen-Space)
# ============================================================
#
# G_CANVAS maps item_id -> render description for that item.
#
# This structure is NOT the source of truth for world geometry.
# World geometry lives in:
#     G_ATTACH[item_id]["bbox"]   # (x0, y0, x1, y1) in world coords
#
# G_CANVAS holds only *projected, screen-space render intent*
# plus the canvas object IDs needed to realize that intent.
#
# Rules write ONLY to these fields.
# A flush pass (render_all()) reads these fields and updates Tk canvas.
#
# Typical entry:
#
#   G_CANVAS[item_id] = {
#       # ============================================================
#       # Canvas object identities (Tk implementation detail)
#       # ============================================================
#       # These are managed ONLY by the renderer.
#       # Rules must never read or write these fields.
#
#       "rect": <canvas_id or None>,         # rectangle item on Tk canvas
#       "label": <canvas_id or None>,        # text item on Tk canvas
#       "handles": [h0, h1, h2, h3] or [],   # corner handle rectangles
#
#       # ============================================================
#       # Existence intent (declarative)
#       # ============================================================
#       # These are written by RULES and describe whether visual
#       # elements should exist at all for this item this frame.
#
#       "rect_shouldexist": True,            # whether rectangle should be drawn
#       "label_shouldexist": True,           # whether label should be drawn
#       "handles_shouldexist": False,        # whether corner handles should exist
#
#       # ============================================================
#       # Render intent (projected, screen-space)
#       # ============================================================
#       # These are written by RULES and describe what the canvas
#       # *should* look like for this item this frame.
#       # In Phase 3, ONLY the renderer reads these and applies them.
#
#       "rect_coords": (x0, y0, x1, y1),     # projected rectangle geometry
#       "rect_outline": "white",             # outline color
#       "rect_width": 1,                     # outline width (pixels)
#       "rect_fill": "#88ccff",              # fill color
#
#       "label_coord": (x, y),               # projected label position
#       "label_text": "A",                   # text content
#       "label_color": "white",              # text color
#   }
#
G_CANVAS = {}


# ============================================================
# Register (CUR) Support
# ============================================================

S = []  # stack

CUR = {
    "item_id": None,  # register: currently iterated item
    "item_canvas_data": None,  # register: currently iterated item's G_CANVAS data
    "item_attachment_data": None,  # register: currently iterated item's G_ATTACH data
    "item_inv": None,  # register: currently iterated item's inventory record
    "item_modules": None,  # register: current iterated item's modules

    "event": None,  # register: current event processing
    "top": None,  # canvas item beneath mouse on canvas, if any, at event processing
    "top_item_id": None,  # item_id for top, if there is one, otherwise None
    
    "x": 0, "y": 0,  # pt register
    "x0": 0, "y0": 0, "x1": 0, "y1": 0,  # rect register
    "coord_type": "w"  # world (w) or canvas (c) space
}

def iterate_item(item_id):
    if item_id is None:
        CUR["item_id"] = None
        CUR["item_canvas_data"] = None
        CUR["item_attachment_data"] = None
        CUR["item_inv"] = None
        CUR["item_modules"] = []
    else:
        CUR["item_id"] = item_id
        CUR["item_canvas_data"] = G_CANVAS.get(item_id)
        CUR["item_attachment_data"] = G_ATTACH.get(item_id)
        inv = G_INV.get(item_id)
        CUR["item_inv"] = inv
        CUR["item_modules"] = inv.get("modules", []) if inv else []

def has_handles():
    D = CUR["item_canvas_data"]
    return bool(D and D.get("handles"))

def foreach_item(fn):
    for item_id in G_CANVAS:
        iterate_item(item_id)
        fn()


# ============================================================
# Coordinates Machine
# ============================================================

# ------------------------------------------------------------
# Machine State
# ------------------------------------------------------------
#
# Registers:
#   CUR["x"], CUR["y"]                     # point register
#   CUR["x0"], CUR["y0"], CUR["x1"], CUR["y1"]   # rect register
#   CUR["coord_type"] = "w" | "c"          # world or canvas space
#
# Stack:
#   S = []     # stores snapshots of point or rect registers
#
# Invariant:
#   Point and rect registers are ALWAYS in the same coord space.
# ------------------------------------------------------------


# -- Load / Store (World <-> Machine) ------------------------

def load_rect(src):
    """
    Load rectangle into rect registers.

    src:
        "attachment"  -> load G_ATTACH[CUR["item_id"]]["bbox"]

    Effects:
        CUR["x0"], CUR["y0"], CUR["x1"], CUR["y1"] set
        CUR["coord_type"] set to "w"
    """
    if src == "attachment":
        item_id = CUR["item_id"]
        x0, y0, x1, y1 = G_ATTACH[item_id]["bbox"]
        CUR["x0"] = x0
        CUR["y0"] = y0
        CUR["x1"] = x1
        CUR["y1"] = y1
        CUR["coord_type"] = "w"
    else:
        raise ValueError(f"load_rect: unknown src '{src}'")


def store_rect(dst):
    """
    Store rect registers into world data.

    dst:
        "attachment" -> write to G_ATTACH[CUR["item_id"]]["bbox"]

    Requires:
        CUR["coord_type"] == "w"

    Effects:
        World geometry updated from rect registers.
    """
    if dst == "attachment":
        if CUR.get("coord_type") != "w":
            raise RuntimeError("store_rect: coord_type must be 'w' to store to attachment")
        
        item_id = CUR["item_id"]
        G_ATTACH[item_id]["bbox"] = (
            CUR["x0"],
            CUR["y0"],
            CUR["x1"],
            CUR["y1"],
        )
    else:
        raise ValueError(f"store_rect: unknown dst '{dst}'")


def load_pt(src):
    """
    Load point into point registers.

    src:
        "event"   -> load from last mouse event (screen coords)
        "center"  -> load rect center point
        "nw" | "ne" | "se" | "sw" -> load rect corner
        "label"   -> load CUR["item_canvas_data"]'s label coordinates

    Effects:
        CUR["x"], CUR["y"] set
        coord space unchanged (except "event" which sets to "c")
    """
    if src == "event":
        ev = CUR.get("event")
        if ev is None:
            raise RuntimeError("load_pt('event'): no event in CUR")
        CUR["x"] = ev.x
        CUR["y"] = ev.y
        CUR["coord_type"] = "c"
        return

    x0 = CUR["x0"]; y0 = CUR["y0"]; x1 = CUR["x1"]; y1 = CUR["y1"]

    if src == "center":
        CUR["x"] = (x0 + x1) // 2
        CUR["y"] = (y0 + y1) // 2
    elif src == "center-south":
        CUR["x"] = (x0 + x1) // 2
        CUR["y"] = y1

    elif src == "nw":
        CUR["x"] = x0; CUR["y"] = y0
    elif src == "ne":
        CUR["x"] = x1; CUR["y"] = y0
    elif src == "se":
        CUR["x"] = x1; CUR["y"] = y1
    elif src == "sw":
        CUR["x"] = x0; CUR["y"] = y1

    elif src == "label":
        CUR["x"], CUR["y"] = CUR["item_canvas_data"]["label_coord"]
        CUR["coord_type"] = "w"

    else:
        raise ValueError(f"load_pt: unknown src '{src}'")


def store_pt(dst):
    """
    Store point registers back into rect geometry.

    dst:
        "nw" | "ne" | "se" | "sw" | "center"

    Effects:
        Updates rect registers based on point registers.
        coord space unchanged.
    """
    x = CUR["x"]; y = CUR["y"]

    if dst == "center":
        # move entire rect so its center becomes (x, y)
        x0 = CUR["x0"]; y0 = CUR["y0"]; x1 = CUR["x1"]; y1 = CUR["y1"]
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        dx = x - cx
        dy = y - cy
        CUR["x0"] = x0 + dx
        CUR["y0"] = y0 + dy
        CUR["x1"] = x1 + dx
        CUR["y1"] = y1 + dy
        return

    if dst == "nw":
        CUR["x0"] = x; CUR["y0"] = y
    elif dst == "ne":
        CUR["x1"] = x; CUR["y0"] = y
    elif dst == "se":
        CUR["x1"] = x; CUR["y1"] = y
    elif dst == "sw":
        CUR["x0"] = x; CUR["y1"] = y
    else:
        raise ValueError(f"store_pt: unknown dst '{dst}'")

    
# -- Convenience Access --------------------------------------

def get_xy():
    return (CUR["x"], CUR["y"])

def get_xyxy():
    return (CUR["x0"], CUR["y0"], CUR["x1"], CUR["y1"])

# -- Projection (Camera Transform) ---------------------------

def project_to(dst):
    """
    Project all registers to new coordinate space.

    dst:
        "c"  -> project world -> canvas (apply camera + viewport + zoom)
        "w"  -> unproject canvas -> world

    Effects:
        Transforms:
            CUR["x"], CUR["y"]
            CUR["x0"], CUR["y0"], CUR["x1"], CUR["y1"]
        Sets:
            CUR["coord_type"] = dst

    Notes:
        Camera and viewport math live ONLY here.
        All math is integer; zoom is rational (num/den).
    """
    src = CUR.get("coord_type")
    if src == dst:
        return

    cam_x = g["cam_x"]
    cam_y = g["cam_y"]
    zn = g["zoom_num"]
    zd = g["zoom_den"]

    canvas = W("c")
    vcx = g["canvas_view_w"] // 2
    vcy = g["canvas_view_h"] // 2

    def w_to_c(x, y):
        return (
            ((x - cam_x) * zn) // zd + vcx,
            ((y - cam_y) * zn) // zd + vcy,
        )

    def c_to_w(x, y):
        return (
            ((x - vcx) * zd) // zn + cam_x,
            ((y - vcy) * zd) // zn + cam_y,
        )

    if src == "w" and dst == "c":
        CUR["x"], CUR["y"] = w_to_c(CUR["x"], CUR["y"])
        CUR["x0"], CUR["y0"] = w_to_c(CUR["x0"], CUR["y0"])
        CUR["x1"], CUR["y1"] = w_to_c(CUR["x1"], CUR["y1"])

    elif src == "c" and dst == "w":
        CUR["x"], CUR["y"] = c_to_w(CUR["x"], CUR["y"])
        CUR["x0"], CUR["y0"] = c_to_w(CUR["x0"], CUR["y0"])
        CUR["x1"], CUR["y1"] = c_to_w(CUR["x1"], CUR["y1"])

    else:
        raise RuntimeError(f"project_to: invalid transition {src} -> {dst}")

    CUR["coord_type"] = dst


# -- Geometry Ops (Pure Spatial) -----------------------------

def slide_pt(dx, dy):
    """
    Translate point registers by (dx, dy) in current coord space.
    """
    CUR["x"] += dx
    CUR["y"] += dy


def slide_rect(dx, dy):
    """
    Translate rect registers by (dx, dy) in current coord space.
    """
    CUR["x0"] += dx
    CUR["y0"] += dy
    CUR["x1"] += dx
    CUR["y1"] += dy


def explode_pt(size):
    """
    Convert point register into rect register centered on point.

    Effects:
        rect = (x-size, y-size, x+size, y+size)
    """
    x = CUR["x"]
    y = CUR["y"]
    CUR["x0"] = x - size
    CUR["y0"] = y - size
    CUR["x1"] = x + size
    CUR["y1"] = y + size


# -- Stack Ops (Context Save/Restore) ------------------------

def push_pt():
    S.append((CUR["x"], CUR["y"], CUR.get("coord_type")))


def pop_pt():
    if not S:
        raise RuntimeError("pop_pt: stack empty")

    x, y, coord_type = S.pop()
    CUR["x"] = x
    CUR["y"] = y
    CUR["coord_type"] = coord_type


def push_rect():
    S.append((
        CUR["x0"],
        CUR["y0"],
        CUR["x1"],
        CUR["y1"],
        CUR.get("coord_type"),
    ))


def pop_rect():
    if not S:
        raise RuntimeError("pop_rect: stack empty")

    x0, y0, x1, y1, coord_type = S.pop()
    CUR["x0"] = x0
    CUR["y0"] = y0
    CUR["x1"] = x1
    CUR["y1"] = y1
    CUR["coord_type"] = coord_type


# ============================================================
# Rules Support
# ============================================================

RULES = []

def initialize_rules_at_program_start():
    RULES.extend([
        rule_default_appearance,
        rule_module_highlight,
        rule_selected_highlight,
        rule_handles
    ])

def apply_rules():
    for rule in RULES:
        rule()

def sync_all():
    foreach_item(apply_rules)
    render_all()


# ============================================================
# Widget Retrieval
# ============================================================

_WIDGET_ORDER = ("tree", "canvas", "text", "panes", "root")

_WIDGET_CODES = {
    "t": "tree",
    "c": "canvas",
    "x": "text",   # x = teXt
    "p": "panes",
    "r": "root",
}

def W(codes=None):
    w = widgets  # local alias

    # --- Case 1: return all ---
    if not codes:
        return tuple(w[name] for name in _WIDGET_ORDER)

    # --- Case 2 & 3: decode string ---
    if not isinstance(codes, str):
        raise TypeError("W() expects a string of widget codes, e.g. 'cp' or 'x'")

    result = []
    for ch in codes:
        name = _WIDGET_CODES.get(ch)
        if not name:
            raise KeyError(f"Unknown widget code: {ch!r}")
        result.append(w[name])

    # --- Case 2: single ---
    if len(result) == 1:
        return result[0]

    # --- Case 3: multiple ---
    return tuple(result)


# ============================================================
# Canvas Rendering
# ============================================================

def render_all():
    canvas = W("c")

    orphan_candidates = set(canvas.find_withtag("rendered"))
    
    for item_id, D in G_CANVAS.items():

        CUR["item_id"] = item_id
        CUR["item_canvas_data"] = D
        
        # ============================================================
        # RECTANGLE
        # ============================================================

        if D["rect_shouldexist"]:
            if D["rect"] is None:
                D["rect"] = canvas.create_rectangle(0, 0, 0, 0,
                                                    tags=("rendered",))
            else:
                # It exists, and should not be orphan discarded.
                orphan_candidates.discard(D["rect"])
            
            # world -> canvas via coordinate machine
            load_rect("attachment")
            project_to("c")

            canvas.coords(D["rect"], *get_xyxy())
            canvas.itemconfigure(
                D["rect"],
                outline=D["rect_outline"],
                width=D["rect_width"],
                fill=D["rect_fill"],
            )
        else:
            if D["rect"] is not None:
                D["rect"] = None

        # ============================================================
        # LABEL
        # ============================================================

        if D["label_shouldexist"]:
            if D["label"] is None:
                D["label"] = canvas.create_text(0, 0, anchor="w",
                                                tags=("rendered",))
            else:
                # It exists, and should not be orphan discarded.
                orphan_candidates.discard(D["label"])
            
            # world -> canvas via coordinate machine
            load_pt("label")
            project_to("c")

            canvas.coords(D["label"], *get_xy())
            canvas.itemconfigure(
                D["label"],
                text=D["label_text"],
                fill=D["label_color"],
            )
        else:
            if D["label"] is not None:
                D["label"] = None

        # ============================================================
        # HANDLES
        # ============================================================

        if D["handles_shouldexist"]:
            tags = ["nw", "ne", "se", "sw"]
            
            if not D["handles"]:
                # create 4 handles
                handles = []
                for tag in tags:
                    h = canvas.create_rectangle(
                        0, 0, 0, 0,
                        fill="#ffcc00", outline="#000000",
                        tags=("handle", tag, "rendered")
                    )
                    handles.append(h)
                D["handles"] = handles
            else:
                for h in D["handles"]:
                    orphan_candidates.discard(h)
            
            # corners derivced from world rect -> projected per-handle
            load_rect("attachment")
            project_to("c")
            x0,y0, x1, y1 = get_xyxy()
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]  # canvas-coordinates!

            for h, (x, y) in zip(D["handles"], corners):
                canvas.coords(h, x - 5, y - 5, x + 5, y + 5)

        else:
            if D["handles"]:
                del D["handles"][:]

    # delete orphans
    for canvas_item in orphan_candidates:
        canvas.delete(canvas_item)


# ============================================================
# MODULE HELPERS
# ============================================================

def build_module_index():
    """
    Returns:
      dict: module_name -> [item_id, ...]
    """
    index = defaultdict(list)

    for item_id, item in G_INV.items():
        modules = item.get("modules") or []
        for m in modules:
            index[m].append(item_id)

    return dict(index)

def items_in_module(module):
    result = []
    for item_id, item in G_INV.items():
        if module in (item.get("modules") or []):
            result.append(item_id)
    return result

def set_module_highlight(module):
    if module == g["module_highlight"]:
        return

    g["module_highlight"] = module
    sync_all()


# ============================================================
# DRAG / GEOMETRY HELPERS
# ============================================================

def apply_drag(item_id, dx, dy):
    load_rect("attachment")
    
    if G_DRAG["handle"]:
        c = G_DRAG["corner"]
        load_pt(c)
        slide_pt(dx,dy)
        store_pt(c)
    else:
        slide_rect(dx,dy)

    store_rect("attachment")


# ============================================================
# INVENTORY
# ============================================================

def load_inventory(path="inventory.json"):
    global G_INV

    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)

    G_INV = {item["id"]: item for item in items}


# ============================================================
# CANVAS HELPERS
# ============================================================

def is_handle(item_id):
    return "handle" in widgets["canvas"].gettags(item_id)


def corner_for_handle(item_id):
    canvas = W("c")
    tags = canvas.gettags(item_id)

    for t in ("nw", "ne", "se", "sw"):
        if t in tags:
            return t

    return None


def item_id_for_canvas_item(canvas_item):
    for item_id, data in G_CANVAS.items():
        if canvas_item in (
            data.get("rect"),
            data.get("label"),
            *data.get("handles", []),
        ):
            return item_id

    return None


def cursor_for_item(canvas_item):
    if not canvas_item:
        return ""

    return "sizing" if is_handle(canvas_item) else "fleur"


# ============================================================
# HANDLE MANAGEMENT
# ============================================================

def rule_handles():
    CUR["item_canvas_data"]["handles_shouldexist"] = is_only_selected()


# ============================================================
# ATTACHMENT LIFECYCLE
# ============================================================

def attach_new_square():
    canvas = W("c")
    size = 40

    item_id = only_selected()
    iterate_item(item_id)
    
    # ---- world geometry (source of truth) ----
    load_pt("event")
    project_to("w")
    explode_pt(size//2)

    x0, y0, x1, y1 = get_xyxy()

    G_ATTACH[item_id] = {
        "bbox": (x0, y0, x1, y1),
        "color": "#88ccff",
    }

    # ---- projected render intent ----
    load_pt("sw")
    slide_pt(5,10)
    label_x, label_y = get_xy()

    G_CANVAS[item_id] = {
        # canvas identities
        "rect": None,
        "label": None,
        "handles": [],

        # render intent (screen space)
        "rect_shouldexist": True,
        "label_shouldexist": True,
        "handles_shouldexist": False,
        
        "rect_coords": (x0, y0, x1, y1),
        "rect_outline": "white",
        "rect_width": 1,
        "rect_fill": "#88ccff",

        "label_coord": (label_x, label_y),
        "label_text": G_INV[item_id]["symbol"],
        "label_color": "white",
    }

    sync_all()


def delete_attachment():
    item_id = g["item_id"]
    
    # de-select
    if is_selected():
        toggle_selected()
    
    if item_id == G_DRAG["item_id"]:
        cancel_drag()
    
    del G_CANVAS[item_id]
    del G_ATTACH[item_id]


# ============================================================
# SELECTION SYNC
# ============================================================

def is_selected():
    return CUR["item_id"] in selection_set

def is_only_selected():
    return is_selected() and len(selection_set) == 1

def only_selected():
    return next(iter(selection_set)) if len(selection_set) == 1 else None

def toggle_selected():
    item_id = CUR["item_id"]
    if item_id in selection_set:
        selection_set.remove(item_id)
    else:
        selection_set.add(item_id)
    sync_all()

def clear_selection():
    selection_set.clear()
    sync_all()
    sync_tree_selection()
    sync_json_view()

def set_selected():
    """invariant: set_selected, clear_selection, and toggle_selected are the only places selection can change"""
    selection_set.clear()
    selection_set.add(CUR["item_id"])
    g["module_highlight"] = None
    sync_all()
    sync_tree_selection()
    sync_json_view()

def rule_default_appearance():
    attach = CUR["item_attachment_data"]
    x0, y0, x1, y1 = attach["bbox"]

    D = CUR["item_canvas_data"]
    rect_id = D["rect"]
    label_id = D["label"]

    # project rect
    D["rect_coords"] = (x0,y0,x1,y1)
    D["rect_outline"] = "white"
    D["rect_width"] = 1

    # project label (centered under rect)
    if label_id is not None:
        label_x = x0 + 5
        label_y = y1 + 10
        D["label_coord"] = (label_x, label_y)
        D["label_color"] = "white"

def rule_default_appearance():
    attach = CUR["item_attachment_data"]
    x0, y0, x1, y1 = attach["bbox"]

    D = CUR["item_canvas_data"]
    rect_id = D["rect"]
    label_id = D["label"]

    # ---- render intent ----
    D["rect_coords"] = (x0, y0, x1, y1)
    D["rect_outline"] = "white"
    D["rect_width"] = 1
    D["rect_fill"] = "#88ccff"

    cx = x0 + 5
    cy = y1 + 10
    D["label_coord"] = (cx, cy)
    D["label_text"] = G_INV[CUR["item_id"]]["symbol"]
    D["label_color"] = "white"


def rule_selected_highlight():
    if is_selected():
        D = CUR["item_canvas_data"]
        rect = D["rect"]
        D["rect_outline"] = "yellow"
        D["rect_width"] = 3

def sync_tree_selection():
    # WARNING: THIS IS BROKEN RIGHT NOW.
    # the code has changed in multiple ways since it was written:
    # 1. the tree has two layers, and a more complex way of naming its elements
    # 2. selection has become multiple
    tree = W("t")
    sel = only_selected()

    if sel and tree.exists(sel):
        tree.selection_set(sel)
        tree.see(sel)

def sync_json_view():
    text = W("x")
    item_id = only_selected()

    if not item_id:
        text.delete("1.0", "end")
        return

    render_inventory_item(text, G_INV[item_id])


# ============================================================
# MODULE/ITEM SELECTION
# ============================================================

def rule_module_highlight():
    D = CUR["item_canvas_data"]
    rect = D["rect"]
    highlight = g["module_highlight"]

    if highlight and highlight in CUR["item_modules"]:
        D["rect_width"] = 3
        D["rect_outline"] = "red"


# ============================================================
# EVENT HANDLERS
# ============================================================

def canvas_top():
    """helper: Return the first canvas item labelled 'current'."""
    items = widgets["canvas"].find_withtag("current")
    return items[0] if items else None

def on_tree_select():
    tree = W("t")
    sel = tree.selection()
    if not sel:
        return

    iid = sel[0]
    
    if iid.startswith("module::"):
        module = iid.split("::", 1)[1]
        clear_selection()
        set_module_highlight(module)
        return

    if iid.startswith("leaf::"):
        _, _, item_id = iid.split("::", 2)
        iterate_item(item_id)
        set_selected()


def on_delete_key():
    for item_id in set(selection_set):
        iterate_item(item_id)
        delete_attachment()


def on_canvas_hover():
    item = CUR["top"]
    
    if item == g["hover_canvas_item"]:
        return
    
    g["hover_canvas_item"] = item
    widgets["canvas"].config(cursor=cursor_for_item(item))


def on_canvas_mouse_leaves():
    g["hover_canvas_item"] = None
    widgets["canvas"].config(cursor="")


def clear_drag():
    G_DRAG["item_id"] = None
    G_DRAG["x"] = 0
    G_DRAG["y"] = 0
    G_DRAG["handle"] = None
    G_DRAG["corner"] = None
    G_DRAG["mode"] = None
    
def start_drag(mode):
    """
    Capture drag-start context from current UI state.
    mode: "item" | "pan"
    """
    ev = CUR["event"]

    clear_drag()
    G_DRAG["mode"] = mode
    G_DRAG["x"] = ev.x
    G_DRAG["y"] = ev.y

    if mode == "item":
        G_DRAG["item_id"] = item_id = CUR["top_item_id"]
        G_DRAG["canvas_item"] = top = CUR["top"]
        G_DRAG["handle"] = top if top and is_handle(top) else None
        G_DRAG["corner"] = corner_for_handle(top) if top and is_handle(top) else None
        
        if not is_selected():
            set_selected()
    
    elif mode == "pan":
        G_DRAG["item_id"] = None
        G_DRAG["canvas_item"] = None
        G_DRAG["handle"] = None
        G_DRAG["corner"] = None

    else:
        raise ValueError(f"start_drag: unknown mode '{mode}'")

def cancel_drag():
    clear_drag()

def on_canvas_button_press():
    selected_item_id = only_selected()  # None if 0 or >1 items selected
    if not CUR["top"] and selected_item_id and selected_item_id not in G_CANVAS:
        attach_new_square()
    else:
        start_drag("item" if CUR["top_item_id"] else "pan")

def on_canvas_motion():
    event = CUR["event"]
    if G_DRAG["mode"] == "pan":
        dx = event.x - G_DRAG["x"]
        dy = event.y - G_DRAG["y"]

        # move camera opposite to mouse motion
        g["cam_x"] -= dx * g["zoom_den"] // g["zoom_num"]
        g["cam_y"] -= dy * g["zoom_den"] // g["zoom_num"]

        G_DRAG["x"], G_DRAG["y"] = event.x, event.y
        sync_all()
        
    elif G_DRAG["mode"] == "item":
        item_id = G_DRAG["item_id"]
        iterate_item(item_id)

        if not item_id or item_id not in G_CANVAS:
            cancel_drag()
            return

        dx = event.x - G_DRAG["x"]
        dy = event.y - G_DRAG["y"]

        apply_drag(item_id, dx, dy)
        sync_all()

        G_DRAG["x"], G_DRAG["y"] = event.x, event.y


def on_canvas_button_release():
    cancel_drag()
    g["hover_canvas_item"] = None
    widgets["canvas"].config(cursor="")


def on_canvas_configure():
    # We have to do this, because Tk is weirdly forgetful.
    event = CUR["event"]
    g["canvas_view_w"] = event.width
    g["canvas_view_h"] = event.height
    sync_all()


# ============================================================
# UI SETUP
# ============================================================

def get_window_geometry():
    root = W("r")
    # Ensure geometry is up-to-date
    root.update_idletasks()
    return root.geometry()

def set_window_geometry(geom):
    if geom:
        widgets["root"].geometry(geom)


def save_attachments(path="attachments.json"):
    data = {}

    for item_id, meta in G_ATTACH.items():
        data[item_id] = {
            "bbox": list(meta["bbox"]),
            "color": meta.get("color", "#88ccff"),
        }

    data["_layout"] = get_pane_layout()
    data["_window"] = get_window_geometry()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[saved] {path}")


def load_attachments(path="attachments.json"):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Clear existing attachments
    for item_id in list(G_CANVAS.keys()):
        iterate_item(item_id)
        delete_attachment()

    layout = data.pop("_layout", None)
    window_geom = data.pop("_window", None)

    # Rebuild from file (model first, render intent second)
    for item_id, meta in data.items():
        if item_id not in G_INV:
            continue  # inventory changed — skip safely

        x0, y0, x1, y1 = meta["bbox"]
        color = meta.get("color", "#88ccff")

        # ---- model (world truth) ----
        G_ATTACH[item_id] = {
            "bbox": (x0, y0, x1, y1),
            "color": color,
        }

        # ---- projected render intent ----
        cx = (x0 + x1) / 2
        cy = y1 + 10

        G_CANVAS[item_id] = {
            # canvas IDs
            "rect": None,
            "label": None,
            "handles": [],
            
            # render intent
            "rect_shouldexist": True,
            "label_shouldexist": True,
            "handles_shouldexist": False,
            
            "rect_coords": (x0, y0, x1, y1),
            "rect_outline": "white",
            "rect_width": 1,
            "rect_fill": color,

            "label_coord": (cx, cy),
            "label_text": G_INV[item_id]["symbol"],
            "label_color": "white",
        }

    print(f"[loaded] {path}")
    
    sync_all()
    
    if layout:
        set_pane_layout(layout)
    
    if window_geom:
        set_window_geometry(window_geom)


def toggle_pane(widget):
    name = widget._pane_name

    G_PANES[name] = not G_PANES[name]
    update_panes()

def update_panes():
    panes = W("p")
    for name in ("tree", "canvas", "text"):
        panes.forget(widgets[name])
    for name in ("tree", "canvas", "text"):
        if G_PANES[name]:
            panes.add(widgets[name])

def focus_canvas():
    panes, tree, text = W("ptx")
    for w in (tree, text):
        if G_PANES[w._pane_name]:
            panes.forget(w)
            G_PANES[w._pane_name] = False


def get_pane_layout():
    panes = W("p")
    layout = {
        "visible": dict(G_PANES),
        "sashes": [],
    }

    for i in range(panes.panes().__len__() - 1):
        x, y = panes.sash_coord(i)
        layout["sashes"].append((x, y))

    return layout

def set_pane_layout(layout):
    tree, canvas, text, panes, root = W()
    # Restore visibility
    for widget in (tree, canvas, text):
        name = widget._pane_name
        should_be_visible = layout["visible"].get(name, True)

        if should_be_visible and not G_PANES[name]:
            panes.add(widget)
            G_PANES[name] = True
        elif not should_be_visible and G_PANES[name]:
            panes.forget(widget)
            G_PANES[name] = False

    root.update_idletasks()

    # Restore sashes
    for i, (x, y) in enumerate(layout.get("sashes", [])):
        try:
            panes.sash_place(i, x, y)
        except Exception:
            pass

def insert_line(text_widget, content, tag=None):
    start = text_widget.index("end-1c")
    text_widget.insert("end", content + "\n")
    if tag:
        end = text_widget.index("end-1c")
        text_widget.tag_add(tag, start, end)


def insert_kv(text_widget, label, value, label_tag="label", value_tag="value"):
    start = text_widget.index("end-1c")
    text_widget.insert("end", f"{label:<9} ")
    mid = text_widget.index("end-1c")
    text_widget.insert("end", f"{value}\n")

    text_widget.tag_add(label_tag, start, mid)
    text_widget.tag_add(value_tag, mid, text_widget.index("end-1c"))

def render_inventory_item(text_widget, item):
    text_widget.delete("1.0", "end")

    # --- Title ---
    name = item.get("symbol", "<unnamed>")
    kind = item.get("symbol_type", "")
    title = f"{name} ({kind})" if kind else name
    insert_line(text_widget, title, "title")
    insert_line(text_widget, "─" * 40, "subtitle")
    insert_line(text_widget, "")

    # --- Source ---
    src = item.get("source_file")
    ln = item.get("line_number")
    if src:
        if ln:
            insert_line(text_widget, f"src: {src}  (ln {ln})", "subtitle")
        else:
            insert_line(text_widget, f"src: {src}", "subtitle")

    raw = item.get("raw")
    if raw:
        insert_line(text_widget, f"  {raw}", "comment")

    if src or raw:
        insert_line(text_widget, "")

    # --- Structured fields ---
    def emit(label, value):
        if not value:
            return
        if isinstance(value, list):
            value = ", ".join(value)
        insert_kv(text_widget, f"{label}:", value)

    emit("modules", item.get("modules"))
    emit("threads", item.get("threads"))
    emit("callers", item.get("callers"))
    emit("flags", item.get("flags"))

    # --- Custom ---
    custom = item.get("custom")
    if custom:
        for k, v in custom.items():
            insert_kv(text_widget, f"{k}:", v, label_tag="custom")

def populate_tree_grouped_by_module():
    tree = W("t")
    tree.delete(*tree.get_children())

    module_index = build_module_index()

    # Optional: collect unmodule'd items
    ungrouped = []

    for item_id, item in G_INV.items():
        if not item.get("modules"):
            ungrouped.append(item_id)

    # Create module folders
    for module in sorted(module_index):
        module_iid = f"module::{module}"

        tree.insert(
            "",
            "end",
            iid=module_iid,
            text=module,
            open=True,
        )

        for item_id in sorted(module_index[module]):
            leaf_iid = f"leaf::{module}::{item_id}"
            
            tree.insert(
                module_iid,
                "end",
                iid=leaf_iid,
                text=G_INV[item_id]["symbol"],
                values=(item_id,)
            )

    # Optional: Ungrouped bucket
    if ungrouped:
        tree.insert("", "end", iid="module::<none>", text="(no module)", open=True)
        for item_id in sorted(ungrouped):
            tree.insert(
                "module::<none>",
                "end",
                iid=item_id,
                text=G_INV[item_id]["symbol"],
            )


def dispatch_event(event, handler_fn):
    CUR["event"] = event
    CUR["top"] = top = canvas_top()
    CUR["top_item_id"] = item_id = item_id_for_canvas_item(top) if top else None
    iterate_item(item_id)
    handler_fn()


def main():
    def doit(fn):
        """
        Wrap a handler function so it is called through dispatch_event.
        
        Returns a Tk-compatible callback that first normalizes the event
        into CUR, then invokes the given handler with no arguments.
        """
        return lambda e: dispatch_event(e, fn)
    
    widgets["root"] = root = tk.Tk()
    root.title("Inventory Attachments")

    root.bind("<Delete>", doit(on_delete_key))
    root.bind("<BackSpace>", doit(on_delete_key))

    root.bind("<Control-s>", doit(save_attachments))
    root.bind("<Control-o>", doit(load_attachments))

    root.bind("1", doit(lambda: toggle_pane(tree)))
    root.bind("2", doit(lambda: toggle_pane(canvas)))
    root.bind("3", doit(lambda: toggle_pane(text)))
    root.bind("<Control-space>", doit(focus_canvas))

    widgets["panes"] = panes = tk.PanedWindow(
        root,
        orient=tk.HORIZONTAL,
        sashrelief=tk.RAISED,
        sashwidth=6,
        bg="#333333",
    )
    panes.pack(fill=tk.BOTH, expand=True)

    widgets["tree"] = tree = ttk.Treeview(root, show="tree")
    widgets["canvas"] = canvas = tk.Canvas(root, bg="#1e1e1e")
    widgets["text"] = text = ScrolledText(root, wrap="none")

    text.configure(
        bg="#0b1220",
        fg="#e6e6e6",
        insertbackground="#ffffff",
        selectbackground="#264f78",
        font=("TkFixedFont", 11),
        padx=12,
        pady=12,
    )

    # --- TAG STYLES ---
    text.tag_configure("title", foreground="#ffffff", font=("Consolas", 13, "bold"))
    text.tag_configure("subtitle", foreground="#a8d8ff")
    text.tag_configure("comment", foreground="#7ec699")
    text.tag_configure("label", foreground="#ffcc66")
    text.tag_configure("value", foreground="#dddddd")
    text.tag_configure("custom", foreground="#c792ea")

    tree._pane_name = "tree"
    canvas._pane_name = "canvas"
    text._pane_name = "text"

    panes.add(tree, minsize=150)
    panes.add(canvas, minsize=300)
    panes.add(text, minsize=200)

    root.update_idletasks()
    panes.sash_place(0, 200, 0)
    panes.sash_place(1, 900, 0)

    tree.bind("<<TreeviewSelect>>", doit(on_tree_select))

    canvas.bind("<ButtonPress-1>", doit(on_canvas_button_press))
    canvas.bind("<B1-Motion>", doit(on_canvas_motion))
    canvas.bind("<Motion>", doit(on_canvas_hover))
    canvas.bind("<ButtonRelease-1>", doit(on_canvas_button_release))
    canvas.bind("<Leave>", doit(on_canvas_mouse_leaves))
    canvas.bind("<Configure>", doit(on_canvas_configure))

    # -----------------
    # BOOT
    # -----------------
    
    initialize_rules_at_program_start()
    load_inventory()

    populate_tree_grouped_by_module()
    
    load_attachments()
    root.update_idletasks()
    
    root.mainloop()

if __name__ == "__main__":
    main()
