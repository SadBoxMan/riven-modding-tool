import os, sys, time, ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(1)
GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
sys.path.insert(0, GAME)
import tkinter as tk
import riven_gui as G
from PIL import ImageGrab

G.save_settings = lambda **k: None
G.load_settings = lambda: {}
root = tk.Tk()
root.geometry("1400x820+30+30")
app = G.App(root, GAME)


def pump(cond=lambda: True, timeout=90):
    t = time.time()
    while not cond():
        root.update()
        time.sleep(0.02)
        if time.time() - t > timeout:
            break
    for _ in range(8):
        root.update()
        time.sleep(0.03)


pump(lambda: app.area_res and not app.busy)

# Switch to CARD mode, pick Temple Island
app.kind.set("CARD")
app.on_kind()
pump()
app.nav.selection_set("A|Temple Island")
pump()

# Pick card 159 (the Atrus intro / Gate Room) by direct tree selection
tree_items = app.tree.get_children()
print(f"Tree items: {len(tree_items)}")
if tree_items:
    # pick item at index 5 (should be a Gate Room card with good hotspots)
    target = tree_items[min(5, len(tree_items) - 1)]
    app.tree.selection_set(target)
    app.tree.see(target)
    app.tree.event_generate("<<TreeviewSelect>>")
    pump(lambda: bool(app.images), 15)

print("cur_card:", app.cur_card and app.cur_card.cid, "| images:", list(app.images.keys()))
print("hotspots:", app.cur_card.hspts[:3] if app.cur_card else "none")

# Turn on hotspot overlay
app.show_spots.set(True)
app.redraw()
pump()

root.lift()
root.attributes("-topmost", True)
pump()
x, y = root.winfo_rootx(), root.winfo_rooty()
img = ImageGrab.grab((x, y - 32, x + root.winfo_width(), y + root.winfo_height()))
out = r"C:\Users\lukea\AppData\Local\Temp\claude\C--Users-lukea-Claude-Projects-Guild\1d2ef8db-f5fa-4996-9c42-e843e2d74117\scratchpad\hotspot_test.png"
img.save(out)
print("Screenshot saved to", out)
root.destroy()
