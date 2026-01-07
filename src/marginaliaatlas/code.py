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
G_CANVAS = {}       # id -> canvas objects  {"rect": #, "label": #, "handles": [#,#,#,#]}

G_DRAG = {
    "item_id": None,
    "x": 0,
    "y": 0,
    "handle": None,
    "corner": None,
}

G_HOVER = {
    "canvas_item_id": None,
}

HANDLE_SIZE = 6

G_PANES = {
    "tree": True,
    "canvas": True,
    "text": True,
}

g = {
    "selected": None,  # currently selected id
    "module_highlight": None  # module name or None
}

widgets = {
    "root": None,
    "panes": None,
    "tree": None,
    "canvas": None,
    "text": None
}


# ============================================================
# Register (CUR) Support
# ============================================================

CUR = {
    "item_id": None,  # register: currently iterated item
    "item_canvas_data": None,  # register: currently iterated item's canvas data
    "item_inv": None,  # register: currently iterated item's inventory record
    "item_modules": None  # register: current iterated item's modules
}

def iterate_item(item_id):
    CUR["item_id"] = item_id
    CUR["item_canvas_data"] = G_CANVAS.get(item_id)
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

def is_dragging():
    return G_DRAG["item_id"] is not None


def move_items(items, dx, dy):
    canvas = W("c")
    for item in items:
        canvas.move(item, dx, dy)


def resize_rect(rect, dx, dy, corner):
    canvas = W("c")
    x0, y0, x1, y1 = canvas.coords(rect)

    if corner == "nw":
        x0 += dx
        y0 += dy
    elif corner == "ne":
        x1 += dx
        y0 += dy
    elif corner == "se":
        x1 += dx
        y1 += dy
    elif corner == "sw":
        x0 += dx
        y1 += dy

    canvas.coords(rect, x0, y0, x1, y1)


def apply_drag(item_id, dx, dy):
    data = G_CANVAS[item_id]
    rect = data["rect"]

    if G_DRAG["handle"]:
        resize_rect(rect, dx, dy, G_DRAG["corner"])
        update_handles(item_id)
    else:
        move_items(
            [rect, data["label"], *data.get("handles", [])],
            dx,
            dy,
        )


def sync_attachment_geometry(item_id):
    canvas = W("c")
    
    data = G_CANVAS[item_id]
    rect = data["rect"]
    label = data["label"]

    x0, y0, x1, y1 = canvas.coords(rect)
    G_ATTACH[item_id]["bbox"] = (x0, y0, x1, y1)

    canvas.coords(label, (x0 + x1) // 2, y1 + 10)


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


def item_id_for_canvas_item(canvas_item_id):
    for item_id, data in G_CANVAS.items():
        if canvas_item_id in (
            data.get("rect"),
            data.get("label"),
            *data.get("handles", []),
        ):
            return item_id

    return None


def cursor_for_item(canvas_item_id):
    if not canvas_item_id:
        return ""

    return "sizing" if is_handle(canvas_item_id) else "fleur"


# ============================================================
# HANDLE MANAGEMENT
# ============================================================

def create_handles(item_id):
    canvas = W("c")
    data = G_CANVAS[item_id]
    rect = data["rect"]

    x0, y0, x1, y1 = canvas.coords(rect)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    tags = ["nw", "ne", "se", "sw"]

    handles = []

    for (x, y), tag in zip(corners, tags):
        h = canvas.create_rectangle(
            x - 5,
            y - 5,
            x + 5,
            y + 5,
            fill="#ffcc00",
            outline="#000000",
            tags=("handle", tag),
        )
        handles.append(h)

    item_canvas_data["handles"] = handles


def update_handles():
    canvas = W("c")
    item_canvas_data = CUR["item_canvas_data"]

    handles = item_canvas_data.get("handles", [])
    if not handles:
        return

    rect = item_canvas_data["rect"]
    x0, y0, x1, y1 = canvas.coords(rect)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    for h, (x, y) in zip(handles, corners):
        canvas.coords(h, x - 5, y - 5, x + 5, y + 5)


def remove_handles():
    canvas = W("c")
    item_id = CUR["item_id"]
    item_canvas_data = G_CANVAS.get(item_id)
    if not item_canvas_data:
        return

    for h in item_canvas_data.get("handles", []):
        canvas.delete(h)

    item_canvas_data["handles"] = []


def set_handles(should_have_fn):
    if should_have_fn():
        if not has_handles():
            create_handles()
        else:
            update_handles()
    else:
        if has_handles():
            remove_handles()

def should_have_handles():
    return CUR["item_id"] == g["selected"]

def rule_handles():
    set_handles(should_have_handles)



# ============================================================
# ATTACHMENT LIFECYCLE
# ============================================================

def attach_new_square(item_id, x, y):
    canvas = W("c")
    size = 60
    x0, y0 = x - size // 2, y - size // 2
    x1, y1 = x + size // 2, y + size // 2

    rect = canvas.create_rectangle(
        x0,
        y0,
        x1,
        y1,
        fill="#88ccff",
        outline="white",
    )

    label = canvas.create_text(
        (x0 + x1) // 2,
        y1 + 10,
        text=G_INV[item_id]["symbol"],
        fill="white",
        anchor="n",
    )

    G_ATTACH[item_id] = {
        "bbox": (x0, y0, x1, y1),
        "color": "#88ccff",
    }

    G_CANVAS[item_id] = {
        "rect": rect,
        "label": label,
        "handles": [],
    }

    sync_all()


def delete_attachment(item_id):
    if item_id not in G_CANVAS:
        return

    data = G_CANVAS.pop(item_id)
    G_ATTACH.pop(item_id, None)

    for item in (data["rect"], data["label"], *data.get("handles", [])):
        canvas.delete(item)

    if g["selected"] == item_id:
        set_selected(None)

    if G_DRAG["item_id"] == item_id:
        set_drag(None)


# ============================================================
# DRAG SYNC
# ============================================================

def set_drag(item_id=None, *, x=None, y=None, handle=None, corner=None):
    """
    The ONLY place drag state is allowed to change.
    Passing item_id=None cancels the drag.
    """
    if item_id is None:
        G_DRAG.update(item_id=None, handle=None, corner=None)
        return

    # Lock selection to dragged item_id
    if g["selected"] != item_id:
        set_selected(item_id)

    G_DRAG.update(
        item_id=item_id,
        x=x,
        y=y,
        handle=handle,
        corner=corner,
    )


# ============================================================
# SELECTION SYNC
# ============================================================

def set_selected(item_id):
    """
    The ONLY place selection is allowed to change.
    """
    if item_id == g["selected"]:
        return

    g["selected"] = item_id
    g["module_highlight"] = None

    sync_all()
    sync_tree_selection()
    sync_json_view()

def rule_default_appearance():
    widgets["canvas"].itemconfigure(CUR["item_canvas_data"]["rect"], outline="white", width=1)

def rule_selected_highlight():
    if CUR["item_id"] == g["selected"]:
        rect = CUR["item_canvas_data"]["rect"]
        widgets["canvas"].itemconfigure(rect, outline="yellow", width=3)

def sync_tree_selection():
    tree = W("t")
    sel = g["selected"]

    if sel and tree.exists(sel):
        tree.selection_set(sel)
        tree.see(sel)

def sync_json_view():
    text = W("x")
    sel = g["selected"]

    if not sel:
        text.delete("1.0", "end")
        return

    render_inventory_item(text, G_INV[sel])


# ============================================================
# MODULE/ITEM SELECTION
# ============================================================

def rule_module_highlight():
    rect = CUR["item_canvas_data"]["rect"]
    highlight = g["module_highlight"]

    if highlight and highlight in CUR["item_modules"]:
        width = 3
        outline = "red"
        widgets["canvas"].itemconfigure(rect, outline=outline, width=width)


# ============================================================
# EVENT HANDLERS
# ============================================================

def on_tree_select(event):
    tree = W("t")
    sel = tree.selection()
    if not sel:
        return

    iid = sel[0]
    
    if iid.startswith("module::"):
        module = iid.split("::", 1)[1]
        set_selected(None)
        set_module_highlight(module)
        return

    if iid.startswith("leaf::"):
        _, _, item_id = iid.split("::", 2)
        set_selected(item_id)


def on_delete_key(event=None):
    selected = g["selected"]
    if selected in G_CANVAS:
        delete_attachment(selected)


def on_canvas_hover(event):
    canvas = W("c")
    items = canvas.find_withtag("current")
    item = items[0] if items else None

    if item == G_HOVER["canvas_item_id"]:
        return

    G_HOVER["canvas_item_id"] = item
    canvas.config(cursor=cursor_for_item(item))


def on_canvas_leave(event):
    G_HOVER["canvas_item_id"] = None
    widgets["canvas"].config(cursor="")


def on_canvas_button_press(event):
    selected = g["selected"]
    canvas_items = widgets["canvas"].find_withtag("current")

    if not canvas_items:
        if selected and selected not in G_CANVAS:
            attach_new_square(selected, event.x, event.y)
        return

    canvas_item = canvas_items[0]
    item_id = item_id_for_canvas_item(canvas_item)
    if not item_id:
        return

    set_drag(
        item_id,
        x=event.x,
        y=event.y,
        handle=canvas_item if is_handle(canvas_item) else None,
        corner=corner_for_handle(canvas_item) if is_handle(canvas_item) else None,
    )
    
    set_selected(item_id)


def on_canvas_motion(event):
    item_id = G_DRAG["item_id"]

    if not item_id or item_id not in G_CANVAS:
        set_drag(None)
        return

    dx = event.x - G_DRAG["x"]
    dy = event.y - G_DRAG["y"]

    apply_drag(item_id, dx, dy)
    sync_attachment_geometry(item_id)

    G_DRAG["x"], G_DRAG["y"] = event.x, event.y


def on_canvas_button_release(event):
    set_drag(None)
    G_HOVER["canvas_item_id"] = None
    widgets["canvas"].config(cursor="")


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
    canvas = W("c")
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Clear existing attachments
    for item_id in list(G_CANVAS.keys()):
        delete_attachment(item_id)

    layout = data.pop("_layout", None)
    window_geom = data.pop("_window", None)

    # Rebuild from file
    for item_id, meta in data.items():
        if item_id not in G_INV:
            continue  # inventory changed — skip safely

        x0, y0, x1, y1 = meta["bbox"]
        color = meta.get("color", "#88ccff")

        rect = canvas.create_rectangle(
            x0, y0, x1, y1,
            fill=color,
            outline="white",
        )

        label = canvas.create_text(
            (x0 + x1) // 2,
            y1 + 10,
            text=G_INV[item_id]["symbol"],
            fill="white",
            anchor="n",
        )

        G_ATTACH[item_id] = {
            "bbox": (x0, y0, x1, y1),
            "color": color,
        }

        G_CANVAS[item_id] = {
            "rect": rect,
            "label": label,
            "handles": [],
        }

    sync_all()

    if layout:
        set_pane_layout(layout)

    if window_geom:
        set_window_geometry(window_geom)

    print(f"[loaded] {path}")


def toggle_pane(widget):
    name = widget._pane_name

    if G_PANES[name]:
        panes.forget(widget)
        G_PANES[name] = False
    else:
        panes.add(widget)
        G_PANES[name] = True

def focus_canvas():
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


def main():
    widgets["root"] = root = tk.Tk()
    root.title("Inventory Attachments")

    root.bind("<Delete>", on_delete_key)
    root.bind("<BackSpace>", on_delete_key)

    root.bind("<Control-s>", lambda e: save_attachments())
    root.bind("<Control-o>", lambda e: load_attachments())

    root.bind("<Control-1>", lambda e: toggle_pane(tree))
    root.bind("<Control-2>", lambda e: toggle_pane(canvas))
    root.bind("<Control-3>", lambda e: toggle_pane(text))
    root.bind("<Control-space>", lambda e: focus_canvas())

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

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    canvas.bind("<ButtonPress-1>", on_canvas_button_press)
    canvas.bind("<B1-Motion>", on_canvas_motion)
    canvas.bind("<Motion>", on_canvas_hover)
    canvas.bind("<ButtonRelease-1>", on_canvas_button_release)
    canvas.bind("<Leave>", on_canvas_leave)

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
