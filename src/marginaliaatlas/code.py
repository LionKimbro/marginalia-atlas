import os
import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


# ============================================================
# GLOBAL STATE (INTENTIONAL)
# ============================================================

G_INV = {}          # symbol -> inventory record
G_ATTACH = {}       # symbol -> attachment metadata
G_CANVAS = {}       # symbol -> canvas objects
G_SELECTED = None   # currently selected symbol

G_DRAG = {
    "symbol": None,
    "x": 0,
    "y": 0,
    "handle": None,
    "corner": None,
}

G_HOVER = {
    "item": None,
}

HANDLE_SIZE = 6

G_PANES = {
    "tree": True,
    "canvas": True,
    "text": True,
}


# ============================================================
# DRAG / GEOMETRY HELPERS
# ============================================================

def is_dragging():
    return G_DRAG["symbol"] is not None


def move_items(items, dx, dy):
    for item in items:
        canvas.move(item, dx, dy)


def resize_rect(rect, dx, dy, corner):
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


def apply_drag(sym, dx, dy):
    data = G_CANVAS[sym]
    rect = data["rect"]

    if G_DRAG["handle"]:
        resize_rect(rect, dx, dy, G_DRAG["corner"])
        update_handles(sym)
    else:
        move_items(
            [rect, data["label"], *data.get("handles", [])],
            dx,
            dy,
        )


def sync_attachment_geometry(sym):
    data = G_CANVAS[sym]
    rect = data["rect"]
    label = data["label"]

    x0, y0, x1, y1 = canvas.coords(rect)
    G_ATTACH[sym]["bbox"] = (x0, y0, x1, y1)

    canvas.coords(label, (x0 + x1) // 2, y1 + 10)


# ============================================================
# INVENTORY
# ============================================================

def load_inventory(path="inventory.json"):
    global G_INV

    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)

    G_INV = {item["symbol"]: item for item in items}


# ============================================================
# CANVAS HELPERS
# ============================================================

def is_handle(item_id):
    return "handle" in canvas.gettags(item_id)


def corner_for_handle(item_id):
    tags = canvas.gettags(item_id)

    for t in ("nw", "ne", "se", "sw"):
        if t in tags:
            return t

    return None


def symbol_for_canvas_item(item_id):
    for sym, data in G_CANVAS.items():
        if item_id in (
            data.get("rect"),
            data.get("label"),
            *data.get("handles", []),
        ):
            return sym

    return None


def cursor_for_item(item_id):
    if not item_id:
        return ""

    return "sizing" if is_handle(item_id) else "fleur"


# ============================================================
# HANDLE MANAGEMENT
# ============================================================

def create_handles(sym):
    data = G_CANVAS[sym]
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

    data["handles"] = handles


def remove_handles(sym):
    data = G_CANVAS.get(sym)
    if not data:
        return

    for h in data.get("handles", []):
        canvas.delete(h)

    data["handles"] = []


def update_handles(sym):
    data = G_CANVAS.get(sym)
    if not data:
        return

    handles = data.get("handles", [])
    if not handles:
        return

    x0, y0, x1, y1 = canvas.coords(data["rect"])
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    for h, (x, y) in zip(handles, corners):
        canvas.coords(h, x - 5, y - 5, x + 5, y + 5)


def sync_handles():
    """
    Enforce invariant:
    Handles exist iff sym == G_SELECTED.
    """
    for sym, data in G_CANVAS.items():
        if sym == G_SELECTED:
            if not data.get("handles"):
                create_handles(sym)
        else:
            if data.get("handles"):
                remove_handles(sym)


# ============================================================
# ATTACHMENT LIFECYCLE
# ============================================================

def attach_new_square(sym, x, y):
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
        text=sym,
        fill="white",
        anchor="n",
    )

    G_ATTACH[sym] = {
        "bbox": (x0, y0, x1, y1),
        "color": "#88ccff",
    }

    G_CANVAS[sym] = {
        "rect": rect,
        "label": label,
        "handles": [],
    }

    sync_handles()


def delete_attachment(sym):
    if sym not in G_CANVAS:
        return

    data = G_CANVAS.pop(sym)
    G_ATTACH.pop(sym, None)

    for item in (data["rect"], data["label"], *data.get("handles", [])):
        canvas.delete(item)

    if G_SELECTED == sym:
        set_selected(None)

    if G_DRAG["symbol"] == sym:
        set_drag(None)


# ============================================================
# DRAG SYNC
# ============================================================

def set_drag(symbol=None, *, x=None, y=None, handle=None, corner=None):
    """
    The ONLY place drag state is allowed to change.
    Passing symbol=None cancels the drag.
    """
    if symbol is None:
        G_DRAG.update(symbol=None, handle=None, corner=None)
        return

    # Lock selection to dragged symbol
    if G_SELECTED != symbol:
        set_selected(symbol)

    G_DRAG.update(
        symbol=symbol,
        x=x,
        y=y,
        handle=handle,
        corner=corner,
    )


# ============================================================
# SELECTION SYNC
# ============================================================

def set_selected(sym):
    """
    The ONLY place selection is allowed to change.
    """
    global G_SELECTED

    if sym == G_SELECTED:
        return

    G_SELECTED = sym

    sync_handles()
    sync_canvas_selection()
    sync_tree_selection()
    sync_json_view()


def sync_canvas_selection():
    for data in G_CANVAS.values():
        canvas.itemconfigure(data["rect"], outline="white", width=1)

    if G_SELECTED in G_CANVAS:
        canvas.itemconfigure(
            G_CANVAS[G_SELECTED]["rect"],
            outline="yellow",
            width=3,
        )


def sync_tree_selection():
    if G_SELECTED and tree.exists(G_SELECTED):
        tree.selection_set(G_SELECTED)
        tree.see(G_SELECTED)


def sync_json_view():
    if not G_SELECTED:
        text.delete("1.0", "end")
        return

    render_inventory_item(text, G_INV[G_SELECTED])



# ============================================================
# EVENT HANDLERS
# ============================================================

def on_tree_select(event):
    sel = tree.selection()
    if sel:
        set_selected(sel[0])


def on_delete_key(event=None):
    if G_SELECTED in G_CANVAS:
        delete_attachment(G_SELECTED)


def on_canvas_hover(event):
    items = canvas.find_withtag("current")
    item = items[0] if items else None

    if item == G_HOVER["item"]:
        return

    G_HOVER["item"] = item
    canvas.config(cursor=cursor_for_item(item))


def on_canvas_leave(event):
    G_HOVER["item"] = None
    canvas.config(cursor="")


def on_canvas_button_press(event):
    items = canvas.find_withtag("current")

    if not items:
        if G_SELECTED and G_SELECTED not in G_CANVAS:
            attach_new_square(G_SELECTED, event.x, event.y)
        return

    item = items[0]
    sym = symbol_for_canvas_item(item)
    if not sym:
        return

    set_drag(
        sym,
        x=event.x,
        y=event.y,
        handle=item if is_handle(item) else None,
        corner=corner_for_handle(item) if is_handle(item) else None,
    )

    set_selected(sym)


def on_canvas_motion(event):
    sym = G_DRAG["symbol"]

    if not sym or sym not in G_CANVAS:
        set_drag(None)
        return

    dx = event.x - G_DRAG["x"]
    dy = event.y - G_DRAG["y"]

    apply_drag(sym, dx, dy)
    sync_attachment_geometry(sym)

    G_DRAG["x"], G_DRAG["y"] = event.x, event.y


def on_canvas_button_release(event):
    set_drag(None)
    G_HOVER["item"] = None
    canvas.config(cursor="")


# ============================================================
# UI SETUP
# ============================================================

def get_window_geometry():
    # Ensure geometry is up-to-date
    root.update_idletasks()
    return root.geometry()

def set_window_geometry(geom):
    if geom:
        root.geometry(geom)


def save_attachments(path="attachments.json"):
    data = {}

    for sym, meta in G_ATTACH.items():
        data[sym] = {
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
    for sym in list(G_CANVAS.keys()):
        delete_attachment(sym)

    layout = data.pop("_layout", None)
    window_geom = data.pop("_window", None)

    # Rebuild from file
    for sym, meta in data.items():
        if sym not in G_INV:
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
            text=sym,
            fill="white",
            anchor="n",
        )

        G_ATTACH[sym] = {
            "bbox": (x0, y0, x1, y1),
            "color": color,
        }

        G_CANVAS[sym] = {
            "rect": rect,
            "label": label,
            "handles": [],
        }

    sync_handles()
    sync_canvas_selection()

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
    layout = {
        "visible": dict(G_PANES),
        "sashes": [],
    }

    for i in range(panes.panes().__len__() - 1):
        x, y = panes.sash_coord(i)
        layout["sashes"].append((x, y))

    return layout

def set_pane_layout(layout):
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



root = tk.Tk()
root.title("Inventory Attachments")

root.bind("<Delete>", on_delete_key)
root.bind("<BackSpace>", on_delete_key)

root.bind("<Control-s>", lambda e: save_attachments())
root.bind("<Control-o>", lambda e: load_attachments())

root.bind("<Control-1>", lambda e: toggle_pane(tree))
root.bind("<Control-2>", lambda e: toggle_pane(canvas))
root.bind("<Control-3>", lambda e: toggle_pane(text))
root.bind("<Control-space>", lambda e: focus_canvas())



panes = tk.PanedWindow(
    root,
    orient=tk.HORIZONTAL,
    sashrelief=tk.RAISED,
    sashwidth=6,
    bg="#333333",
)
panes.pack(fill=tk.BOTH, expand=True)

tree = ttk.Treeview(root, show="tree")
canvas = tk.Canvas(root, bg="#1e1e1e")
text = ScrolledText(root, wrap="none")

text.configure(
    bg="#0b1220",        # deep navy
    fg="#e6e6e6",        # default text
    insertbackground="#ffffff",  # cursor
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

panes.add(tree, minsize=150)    # left: inventory
panes.add(canvas, minsize=300)  # middle: canvas
panes.add(text, minsize=200)    # right: JSON

root.update_idletasks()
panes.sash_place(0, 200, 0)  # between tree and canvas
panes.sash_place(1, 900, 0)  # between canvas and text

tree.bind("<<TreeviewSelect>>", on_tree_select)

canvas.bind("<ButtonPress-1>", on_canvas_button_press)
canvas.bind("<B1-Motion>", on_canvas_motion)
canvas.bind("<Motion>", on_canvas_hover)
canvas.bind("<ButtonRelease-1>", on_canvas_button_release)
canvas.bind("<Leave>", on_canvas_leave)


# ============================================================
# BOOT
# ============================================================

load_inventory()

tree.delete(*tree.get_children())
for sym in sorted(G_INV):
    tree.insert("", "end", iid=sym, text=sym)

load_attachments()
root.update_idletasks()

root.mainloop()
