"""Generate docs/er.svg - the entity relationship diagram of CivicSense."""
import sys

W, H = 1250, 790
HEAD = 26
LINE = 15.5
PAD = 8

FONT = "'Segoe UI', 'DejaVu Sans', Arial, sans-serif"
MONO = "'Consolas', 'DejaVu Sans Mono', monospace"

entities = {}


def box(key, x, y, w, title, attrs, colour="#12395f"):
    height = HEAD + len(attrs) * LINE + PAD * 2
    entities[key] = dict(x=x, y=y, w=w, h=height, title=title, attrs=attrs, c=colour)


# --- master data -----------------------------------------------------------
box("DEPARTMENT", 25, 25, 232, "DEPARTMENT",
    ["PK  id", "    name", "UK  code", "    email, phone", "    head_name", "    is_active"])
box("CATEGORY", 297, 25, 262, "CATEGORY",
    ["PK  id", "UK  code            (NLP label)", "    name", "FK  department_id", "    severity  0.0 - 1.0",
     "    sla_hours", "    is_active"])
box("WARD", 599, 25, 232, "WARD",
    ["PK  id", "UK  code", "    name, zone", "    latitude, longitude", "    population", "    councillor"])
box("USER", 1000, 25, 235, "USER  (django auth)",
    ["PK  id", "UK  username", "    password  (hashed)", "    email", "    first_name, last_name"])
box("PROFILE", 1000, 185, 235, "PROFILE",
    ["PK  id", "FK  user_id        1 : 1", "    role  CITIZEN / STAFF /", "          OFFICER / ADMIN",
     "FK  ward_id", "FK  department_id", "    phone, is_verified"])

# --- the complaint ---------------------------------------------------------
box("COMPLAINT", 330, 235, 335, "COMPLAINT",
    ["PK  id",
     "UK  tracking_id",
     "FK  citizen_id  -> USER",
     "    title, description",
     "FK  category_id, department_id",
     "FK  ward_id",
     "    address, latitude, longitude",
     "--  decided by the NLP engine  --",
     "    ai_category_code, ai_confidence",
     "    ai_keywords            (JSON)",
     "    sentiment_label, polarity",
     "    urgency_score",
     "    priority, priority_score",
     "    priority_breakdown     (JSON)",
     "FK  duplicate_of_id -> COMPLAINT",
     "    duplicate_score, support_count",
     "--  workflow  --",
     "    status, source",
     "FK  assigned_to_id -> USER",
     "    created_at, due_at, resolved_at"],
    colour="#0d2942")

# --- children --------------------------------------------------------------
box("ATTACHMENT", 25, 235, 208, "ATTACHMENT",
    ["PK  id", "FK  complaint_id", "    image", "    caption", "    uploaded_at"])
box("SUPPORT", 25, 375, 208, "SUPPORT",
    ["PK  id", "FK  complaint_id", "FK  user_id", "    comment", "    created_at",
     "UK  (complaint, user)"])
box("FEEDBACK", 25, 545, 208, "FEEDBACK",
    ["PK  id", "FK  complaint_id   1 : 1", "    rating   1 - 5", "    comment",
     "    sentiment_label", "    created_at"])
box("UPDATE", 700, 300, 250, "COMPLAINT_UPDATE",
    ["PK  id", "FK  complaint_id", "FK  actor_id -> USER", "    from_status, to_status",
     "    note", "    is_public", "    created_at"])
box("TRAINING", 700, 500, 250, "TRAINING_SAMPLE",
    ["PK  id", "    text", "    category_code", "    source  CORRECTION /", "            CONFIRMED",
     "FK  complaint_id", "FK  created_by -> USER", "    created_at"])

# --------------------------------------------------------------------------
def anchor(key, side, fraction=0.5):
    e = entities[key]
    if side == "l":
        return e["x"], e["y"] + e["h"] * fraction
    if side == "r":
        return e["x"] + e["w"], e["y"] + e["h"] * fraction
    if side == "t":
        return e["x"] + e["w"] * fraction, e["y"]
    return e["x"] + e["w"] * fraction, e["y"] + e["h"]


links = [
    ("DEPARTMENT", "r", 0.5, "CATEGORY", "l", 0.35, "1", "N", "owns"),
    ("CATEGORY", "b", 0.35, "COMPLAINT", "t", 0.35, "1", "N", "classifies"),
    ("WARD", "b", 0.35, "COMPLAINT", "t", 0.8, "1", "N", "located in"),
    ("USER", "b", 0.5, "PROFILE", "t", 0.5, "1", "1", "role of"),
    ("PROFILE", "l", 0.55, "COMPLAINT", "r", 0.15, "1", "N", "files / is assigned"),
    ("COMPLAINT", "l", 0.10, "ATTACHMENT", "r", 0.5, "1", "N", "has photo"),
    ("COMPLAINT", "l", 0.45, "SUPPORT", "r", 0.4, "1", "N", "confirmed by"),
    ("COMPLAINT", "l", 0.85, "FEEDBACK", "r", 0.4, "1", "1", "rated by"),
    ("COMPLAINT", "r", 0.35, "UPDATE", "l", 0.5, "1", "N", "audit trail"),
    ("COMPLAINT", "r", 0.85, "TRAINING", "l", 0.4, "1", "N", "teaches"),
]

parts = []
parts.append(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
    'font-family="%s">' % (W, H, W, H, FONT))
parts.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H))
parts.append(
    '<defs><marker id="dot" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5">'
    '<circle cx="3.5" cy="3.5" r="2.6" fill="#5f6368"/></marker></defs>')

# relationships first, so the boxes sit on top of the lines
def plate(x, y, text, colour, size=10.5, style=""):
    width = len(text) * size * 0.53 + 8
    return ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="#ffffff"/>'
            '<text x="%.1f" y="%.1f" font-size="%.1f" fill="%s" text-anchor="middle" %s>%s</text>'
            % (x - width / 2, y - size + 1, width, size + 5, x, y + 2, size, colour, style, text))


labels = []
for a, sa, fa, b, sb, fb, ca, cb, label in links:
    x1, y1 = anchor(a, sa, fa)
    x2, y2 = anchor(b, sb, fb)
    length = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1.0)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8a929c" '
                 'stroke-width="1.4" marker-start="url(#dot)" marker-end="url(#dot)"/>'
                 % (x1, y1, x2, y2))
    offset = min(24.0, length * 0.3)
    labels.append(plate(x1 + ux * offset, y1 + uy * offset - 7, ca, "#3c4043", 10.5,
                        'font-weight="600"'))
    labels.append(plate(x2 - ux * offset, y2 - uy * offset - 7, cb, "#3c4043", 10.5,
                        'font-weight="600"'))
    if label:
        labels.append(plate(mx, my - 6, label, "#0d6efd", 10.5, 'font-style="italic"'))

for key, e in entities.items():
    parts.append('<rect x="%d" y="%d" width="%d" height="%.1f" rx="6" fill="#ffffff" '
                 'stroke="%s" stroke-width="1.4"/>' % (e["x"], e["y"], e["w"], e["h"], e["c"]))
    parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s"/>'
                 % (e["x"], e["y"], e["w"], HEAD, e["c"]))
    parts.append('<rect x="%d" y="%d" width="%d" height="6" fill="%s"/>'
                 % (e["x"], e["y"] + HEAD - 6, e["w"], e["c"]))
    parts.append('<text x="%d" y="%.1f" font-size="12.5" font-weight="600" fill="#ffffff">%s</text>'
                 % (e["x"] + 10, e["y"] + 17.5, e["title"]))
    for index, attr in enumerate(e["attrs"]):
        colour = "#b3261e" if attr.startswith("PK") else (
            "#0d6efd" if attr.startswith("FK") else (
                "#1e7e34" if attr.startswith("UK") else "#3c4043"))
        weight = "600" if attr[:2] in ("PK", "FK", "UK") else "400"
        parts.append('<text x="%d" y="%.1f" font-size="10.6" font-family="%s" fill="%s" '
                     'font-weight="%s" xml:space="preserve">%s</text>'
                     % (e["x"] + 10, e["y"] + HEAD + PAD + 11 + index * LINE, MONO, colour,
                        weight, attr.replace("&", "&amp;").replace("<", "&lt;")))

parts.extend(labels)          # relationship labels sit on top of everything

# self relationship on COMPLAINT (duplicate_of): merging a repeat report
c = entities["COMPLAINT"]
sx, sy = c["x"] + c["w"] * 0.30, c["y"] + c["h"]
ex, ey = c["x"] + c["w"] * 0.62, c["y"] + c["h"]
parts.append('<path d="M%.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" fill="none" '
             'stroke="#c25e00" stroke-width="1.4" stroke-dasharray="5 3" '
             'marker-start="url(#dot)" marker-end="url(#dot)"/>'
             % (sx, sy, sx, sy + 52, ex, ey + 52, ex, ey))
parts.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="#c25e00" text-anchor="middle" '
             'font-style="italic">duplicate_of  (a repeat report is merged into the first one)</text>'
             % ((sx + ex) / 2, sy + 52))

parts.append('<text x="25" y="%d" font-size="11" fill="#5f6368">'
             'PK primary key &#160;&#160; FK foreign key &#160;&#160; UK unique key '
             '&#160;&#160;&#160; a dashed line is the self relation used to merge duplicates</text>'
             % (H - 18))
parts.append("</svg>")

open(sys.argv[1], "w").write("\n".join(parts))
print("wrote", sys.argv[1])
