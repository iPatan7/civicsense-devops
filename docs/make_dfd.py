"""Generate docs/dfd.svg - the level-1 data flow diagram of CivicSense."""
import sys

W, H = 1300, 700
FONT = "'Segoe UI', 'DejaVu Sans', Arial, sans-serif"

BLUE = "#12395f"
PROC = "#0d6efd"
STORE = "#1e7e34"
LEARN = "#c25e00"

parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
         'font-family="%s">' % (W, H, W, H, FONT),
         '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H),
         '<defs>'
         '<marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3.2" orient="auto">'
         '<path d="M0,0 L8,3.2 L0,6.4 z" fill="#5f6368"/></marker>'
         '<marker id="arrowL" markerWidth="9" markerHeight="9" refX="8" refY="3.2" orient="auto">'
         '<path d="M0,0 L8,3.2 L0,6.4 z" fill="%s"/></marker>'
         '</defs>' % LEARN]

boxes = {}


def wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    return lines


def external(key, x, y, w, h, title, subtitle=""):
    boxes[key] = (x, y, w, h)
    parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#eef1f6" '
                 'stroke="%s" stroke-width="1.6"/>' % (x, y, w, h, BLUE))
    parts.append('<text x="%d" y="%d" font-size="13" font-weight="600" fill="%s" '
                 'text-anchor="middle">%s</text>'
                 % (x + w / 2, y + h / 2 - (10 if subtitle else -4), BLUE, title))
    if subtitle:
        for index, line in enumerate(wrap(subtitle, 18)):
            parts.append('<text x="%d" y="%d" font-size="10.5" fill="#5f6368" '
                         'text-anchor="middle">%s</text>'
                         % (x + w / 2, y + h / 2 + 8 + index * 12, line))


def process(key, x, y, w, h, number, title):
    boxes[key] = (x, y, w, h)
    parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="14" fill="#ffffff" '
                 'stroke="%s" stroke-width="1.8"/>' % (x, y, w, h, PROC))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.2"/>'
                 % (x, y + 22, x + w, y + 22, PROC))
    parts.append('<text x="%d" y="%d" font-size="11.5" font-weight="700" fill="%s" '
                 'text-anchor="middle">%s</text>' % (x + w / 2, y + 15.5, PROC, number))
    for index, line in enumerate(wrap(title, 22)):
        parts.append('<text x="%d" y="%d" font-size="11.8" fill="#1c1f23" text-anchor="middle">'
                     '%s</text>' % (x + w / 2, y + 40 + index * 14, line))


def store(key, x, y, w, h, label, title):
    boxes[key] = (x, y, w, h)
    parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#f2f8f4" stroke="%s" '
                 'stroke-width="1.5"/>' % (x, y, w, h, STORE))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.5"/>'
                 % (x + 34, y, x + 34, y + h, STORE))
    parts.append('<text x="%d" y="%d" font-size="12" font-weight="700" fill="%s" '
                 'text-anchor="middle">%s</text>' % (x + 17, y + h / 2 + 4, STORE, label))
    parts.append('<text x="%d" y="%d" font-size="11.5" fill="#1c1f23">%s</text>'
                 % (x + 44, y + h / 2 + 4, title))


def side(key, where, fraction=0.5):
    x, y, w, h = boxes[key]
    return {"l": (x, y + h * fraction), "r": (x + w, y + h * fraction),
            "t": (x + w * fraction, y), "b": (x + w * fraction, y + h)}[where]


flow_labels = []


def flow(a, sa, b, sb, label, fa=0.5, fb=0.5, waypoints=(), colour="#5f6368",
         dashed=False, label_at=0.5, dx=0, dy=-6):
    x1, y1 = side(a, sa, fa)
    x2, y2 = side(b, sb, fb)
    points = [(x1, y1)] + [tuple(p) for p in waypoints] + [(x2, y2)]
    d = "M%.1f %.1f " % points[0] + " ".join("L%.1f %.1f" % p for p in points[1:])
    parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.5" %s '
                 'marker-end="url(#%s)"/>'
                 % (d, colour, 'stroke-dasharray="6 4"' if dashed else "",
                    "arrowL" if dashed else "arrow"))
    # place the label on the longest segment
    best, best_length = (points[0], points[1]), -1
    for start, end in zip(points, points[1:]):
        length = abs(end[0] - start[0]) + abs(end[1] - start[1])
        if length > best_length:
            best, best_length = (start, end), length
    (sx, sy), (ex, ey) = best
    lx = sx + (ex - sx) * label_at + dx
    ly = sy + (ey - sy) * label_at + dy
    lines = wrap(label, 26)
    width = max(len(line) for line in lines) * 5.6 + 8
    plate = ['<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#ffffff" '
             'fill-opacity="0.95"/>' % (lx - width / 2, ly - 10, width, 3 + 12 * len(lines))]
    for index, line in enumerate(lines):
        plate.append('<text x="%.1f" y="%.1f" font-size="10.2" fill="%s" text-anchor="middle">'
                     '%s</text>' % (lx, ly + index * 11, colour, line))
    flow_labels.extend(plate)


# --- entities, processes and stores ---------------------------------------
external("CITIZEN", 20, 160, 130, 86, "Citizen", "files the complaint")
external("CITIZEN2", 20, 415, 130, 86, "Citizen", "tracks and rates")
external("OFFICER", 1140, 415, 150, 86, "Officer", "department staff and ward officer")

process("P1", 175, 160, 170, 86, "1.0", "Capture complaint (web / mobile / call centre)")
process("P2", 390, 160, 170, 86, "2.0", "Classify text and route to a department")
process("P3", 610, 160, 170, 86, "3.0", "Detect duplicates and merge reports")
process("P4", 830, 160, 170, 86, "4.0", "Score priority and set the SLA clock")
process("P5", 620, 415, 200, 86, "5.0", "Assign, resolve and track the complaint")
process("P6", 880, 415, 200, 86, "6.0", "Dashboard, SLA reports and hot-spots")

store("D2", 175, 305, 300, 42, "D2", "Departments / Categories / Wards")
store("D1", 560, 305, 340, 42, "D1", "Complaints")
store("D3", 175, 560, 300, 42, "D3", "Training samples")
store("D4", 520, 560, 270, 42, "D4", "Audit trail")
store("D5", 840, 560, 300, 42, "D5", "Support and feedback")

# --- flows -----------------------------------------------------------------
# row 1: the labels are placed in the empty band above the processes
flow("CITIZEN", "r", "P1", "l", "complaint text, photo, ward, GPS", dy=-62)
flow("P1", "r", "P2", "l", "cleaned text", dy=-62)
flow("P2", "r", "P3", "l", "category + confidence", dy=-62)
flow("P3", "r", "P4", "l", "one unique complaint", dy=-62)

flow("P2", "b", "D2", "t", "category severity + SLA", fa=0.35, fb=0.62,
     waypoints=[(449, 272), (361, 272)], dy=-10)
flow("D3", "t", "P2", "b", "labelled samples: seed corpus + officer corrections",
     fa=0.55, fb=0.70, waypoints=[(340, 265), (509, 265)],
     colour=LEARN, dashed=True, dy=-6)

flow("P1", "b", "D1", "t", "new complaint record", fa=0.5, fb=0.14,
     waypoints=[(260, 288), (608, 288)], dy=-7)
flow("D1", "t", "P3", "b", "open complaints of the last 30 days",
     fa=0.35, fb=0.35, waypoints=[(679, 288)], dy=-7, label_at=0.62)
flow("P4", "b", "D1", "t", "priority, score, due date", fa=0.55, fb=0.9,
     waypoints=[(924, 288), (866, 288)], dy=-7)

flow("P4", "b", "P5", "t", "ranked work queue", fa=0.35, fb=0.5,
     waypoints=[(890, 375), (720, 375)], dy=-7)
flow("D1", "b", "P6", "t", "counts and SLA state", fa=0.85, fb=0.4,
     waypoints=[(849, 392), (960, 392)], dy=-7)

flow("OFFICER", "l", "P5", "b", "assign / update / resolve / merge",
     fa=0.3, fb=0.95, waypoints=[(1105, 440), (1105, 530), (810, 530)], dy=-8)
flow("P6", "r", "OFFICER", "l", "KPIs, charts, SLA report", fa=0.55, fb=0.55, dy=-58)

flow("P5", "l", "CITIZEN2", "r", "status updates and resolution note",
     fa=0.3, fb=0.3, dy=-8, dx=120)
flow("CITIZEN2", "r", "P5", "l", "rating and 'I have the same problem'",
     fa=0.72, fb=0.72, dy=15, dx=120)

flow("P5", "b", "D4", "t", "every action is logged", fa=0.25, fb=0.55, dy=-8)
flow("P5", "b", "D5", "t", "support and feedback", fa=0.6, fb=0.5,
     waypoints=[(740, 552), (990, 552)], dy=-7, label_at=0.42)
flow("P5", "b", "D3", "t", "officer correction becomes a new training sample",
     fa=0.08, fb=0.25, waypoints=[(636, 522), (250, 522)],
     colour=LEARN, dashed=True, dy=-7)

flow("D4", "t", "P6", "b", "resolution times", fa=0.35, fb=0.25,
     waypoints=[(614, 545), (930, 545)], dy=-6, label_at=0.28)
flow("D5", "t", "P6", "b", "citizen ratings", fa=0.8, fb=0.8,
     waypoints=[(1080, 545)], dy=-32, label_at=0.5)

parts.extend(flow_labels)

parts.append('<rect x="20" y="%d" width="%d" height="46" rx="6" fill="#f8f9fb" '
             'stroke="#d6dade"/>' % (H - 60, W - 40))
parts.append('<text x="34" y="%d" font-size="11.5" fill="#3c4043">'
             'Level-1 DFD &#160;&#8226;&#160; rectangle = external entity &#160;&#8226;&#160; '
             'rounded box = process &#160;&#8226;&#160; open box = data store &#160;&#8226;&#160; '
             '<tspan fill="%s">the dashed orange path is the learning loop: an officer\'s '
             'correction is stored and the classifier is retrained from it</tspan></text>'
             % (H - 33, LEARN))
parts.append("</svg>")
open(sys.argv[1], "w").write("\n".join(parts))
print("wrote", sys.argv[1])
