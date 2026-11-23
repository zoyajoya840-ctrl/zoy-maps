p = "app/main.py"
with open(p, "r", encoding="utf-8") as f:
    s = f.read()

old = '"streets": f"https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",'
new = '"streets": f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",'

old_dark = '"dark": f"https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",'
new_dark = '"dark": f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",'

s = s.replace(old, new).replace(old_dark, new_dark)
with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("TILES FIXED SUCCESSFULLY")
