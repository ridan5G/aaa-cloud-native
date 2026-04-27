slide_path = r"docs/aaa-platform-presentation-unpacked/ppt/slides/slide19.xml"

# 8-column layout — usable width 8844000
# Container: 1800000, 7 value cols: 1006285 each (last 1006290)
X  = [150000, 1950000, 2956285, 3962570, 4968855, 5975140, 6981425, 7987710]
CX = [1800000, 1006285, 1006285, 1006285, 1006285, 1006285, 1006285, 1006290]

HDR_Y  = 760000;  HDR_CY = 400000
ROW_Y  = [1160000 + i*375000 for i in range(9)]
ROW_CY = 375000

ODD_FILL  = "CADCFC"
EVEN_FILL = "FFFFFF"
HDR_FILL  = "1E2761"
NAVY      = "1E2761"
WHITE     = "FFFFFF"
GRAY      = "6B7280"
BORDER    = "9EB3D8"
AMBER_BG  = "FFF3CD"
AMBER_TX  = "7B4F00"
GREEN_BG  = "D6EAD6"
GREEN_TX  = "1A5C1A"
TEAL_BG   = "D0EEF2"
TEAL_TX   = "014F5A"
ORANGE    = "C45000"
TEAL_HDR  = "025F6B"
MUTED_TX  = "888888"

headers = [
    "Container",
    "CPU\nRequest", "CPU\nLimit",
    "RAM\nRequest", "RAM\nLimit",
    "Storage\n(PVC)",
    "Replicas\n@ 2k rps",
    "Max RPS\nper Pod",
]

# col 7 = Replicas, col 8 = Max RPS per pod
# (name, cpu_req, cpu_lim, ram_req, ram_lim, storage, replicas, rps_per_pod)
rows = [
    ("aaa-lookup-service",     "500m",  "2,000m", "256 Mi",   "512 Mi",   "\u2014",  "5",    "~600 rps"),
    ("subscriber-profile-api", "250m",  "1,000m", "256 Mi",   "512 Mi",   "\u2014",  "2",    "~50 rps"),
    ("Radius-to-Rest pod",     "250m",  "1,000m", "128 Mi",   "256 Mi",   "\u2014",  "5",    "~500 rps"),
    ("PostgreSQL (primary)",   "500m",  "2,000m", "512 Mi",   "2,048 Mi", "20 Gi",   "1",    "~2,000 qps"),
    ("PostgreSQL (replica)",   "500m",  "2,000m", "512 Mi",   "2,048 Mi", "20 Gi",   "2",    "~5,000 qps"),
    ("PgBouncer",              "100m",  "500m",   "64 Mi",    "128 Mi",   "\u2014",  "2",    ">10,000"),
    ("UI pod",                 "100m",  "500m",   "128 Mi",   "256 Mi",   "\u2014",  "1",    "~200 rps"),
    ("aaa-regression-tester",  "250m",  "500m",   "256 Mi",   "512 Mi",   "\u2014",  "1 *",  "N/A"),
    ("Load-test pod",          "500m",  "2,000m", "256 Mi",   "1,024 Mi", "\u2014",  "1 *",  "N/A (gen.)"),
]

def esc(t):
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def rpr_xml(sz=800, bold=0, italic=0, color=NAVY):
    return (f'<a:rPr lang="en-US" sz="{sz}" b="{"1" if bold else "0"}" '
            f'i="{"1" if italic else "0"}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="Calibri"/></a:rPr>')

def sp_cell(spId, x, y, cx, cy, fill, lines, colors, sz, bolds, algn="ctr", valign="ctr", border=True):
    ln = (f'<a:ln><a:solidFill><a:srgbClr val="{BORDER}"/></a:solidFill></a:ln>'
          if border else '<a:ln><a:noFill/></a:ln>')
    paras = ""
    for txt, tc, bld in zip(lines, colors, bolds):
        paras += (f'      <a:p><a:pPr algn="{algn}" spcBef="0" spcAft="0"/>'
                  f'<a:r>{rpr_xml(sz=sz,bold=bld,color=tc)}<a:t>{esc(txt)}</a:t></a:r></a:p>\n')
    return (f'  <p:sp><p:nvSpPr><p:cNvPr id="{spId}" name="sp{spId}"/>'
            f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr anchor="{valign}" lIns="45720" rIns="45720" tIns="30480" bIns="30480"/>'
            f'<a:lstStyle/>\n{paras}    </p:txBody></p:sp>')

def sp_simple(spId, x, y, cx, cy, fill, text, tcolor, sz,
              bold=0, algn="ctr", valign="ctr", italic=0, border=True):
    ln = (f'<a:ln><a:solidFill><a:srgbClr val="{BORDER}"/></a:solidFill></a:ln>'
          if border else '<a:ln><a:noFill/></a:ln>')
    b = "1" if bold else "0"; it = "1" if italic else "0"
    return (f'  <p:sp><p:nvSpPr><p:cNvPr id="{spId}" name="sp{spId}"/>'
            f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr anchor="{valign}" lIns="91440" rIns="91440" tIns="45720" bIns="45720"/>'
            f'<a:lstStyle/><a:p><a:pPr algn="{algn}"/><a:r>'
            f'<a:rPr lang="en-US" sz="{sz}" b="{b}" i="{it}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{tcolor}"/></a:solidFill>'
            f'<a:latin typeface="Calibri"/></a:rPr>'
            f'<a:t>{esc(text)}</a:t></a:r></a:p></p:txBody></p:sp>')

shapes = []
sid = 2

# Background
shapes.append(sp_simple(sid, 0, 0, 9144000, 5143500, "EEF3FB", "", "EEF3FB", 100, border=False)); sid+=1

# Title bar
shapes.append(
    f'  <p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="sp{sid}"/>'
    f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
    f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="490000"/></a:xfrm>'
    f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    f'<a:solidFill><a:srgbClr val="1E2761"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
    f'<p:txBody><a:bodyPr anchor="ctr" lIns="228600" rIns="228600" tIns="45720" bIns="45720"/>'
    f'<a:lstStyle/><a:p><a:pPr algn="l"/><a:r>'
    f'<a:rPr lang="en-US" sz="1900" b="1" dirty="0">'
    f'<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
    f'<a:latin typeface="Calibri"/></a:rPr>'
    f'<a:t>Container Resource Requirements \u2014 CPU, RAM, Storage, Replicas &amp; Throughput</a:t>'
    f'</a:r></a:p></p:txBody></p:sp>'
); sid+=1

# Subtitle (left)
shapes.append(sp_simple(sid, 150000, 510000, 6050000, 210000, "EEF3FB",
    "Sized for 2,000 Access-Requests/sec  |  99.9% fast path (subscriber profile exists in DB)  |  0.1% first-connection",
    "2E75B6", 800, bold=0, algn="l", valign="ctr", italic=1, border=False)); sid+=1

# Callout box (right) — fast/slow path split
shapes.append(sp_simple(sid, 6300000, 510000, 2694000, 210000, "1E2761",
    "Fast path: 1,998 rps  |  Slow path: 2 rps",
    WHITE, 800, bold=1, algn="ctr", valign="ctr", border=False)); sid+=1

# Header row
hdr_fills = [HDR_FILL, HDR_FILL, HDR_FILL, HDR_FILL, HDR_FILL, HDR_FILL, ORANGE, TEAL_HDR]
for ci, (hdr, hx, hcx, hf) in enumerate(zip(headers, X, CX, hdr_fills)):
    algn = "l" if ci == 0 else "ctr"
    lines = hdr.split("\n")
    shapes.append(sp_cell(sid, hx, HDR_Y, hcx, HDR_CY, hf,
                          lines, [WHITE]*len(lines), 800,
                          [1]*len(lines), algn=algn)); sid+=1

# Data rows
for ri, row in enumerate(rows):
    base = ODD_FILL if (ri % 2 == 0) else EVEN_FILL
    ry = ROW_Y[ri]
    for ci, (val, hx, hcx) in enumerate(zip(row, X, CX)):
        algn = "l" if ci == 0 else "ctr"
        bold = 1 if ci == 0 else 0

        if ci == 5 and val != "\u2014":          # Storage — amber for PVC values
            cf, tc, bold = AMBER_BG, AMBER_TX, 1
        elif ci == 6:                             # Replicas column
            if "*" in val:
                cf, tc, bold = base, MUTED_TX, 0
            else:
                cf, tc, bold = GREEN_BG, GREEN_TX, 1
        elif ci == 7:                             # RPS per pod — colour by tier
            if val == "N/A" or val.startswith("N/A"):
                cf, tc, bold = base, MUTED_TX, 0
            elif ">10,000" in val or "5,000" in val:
                cf, tc, bold = GREEN_BG, GREEN_TX, 1
            elif "2,000" in val or "600" in val or "500" in val:
                cf, tc, bold = TEAL_BG, TEAL_TX, 1
            else:                                 # ~50 rps, ~200 rps
                cf, tc, bold = base, NAVY, 0
        else:
            cf, tc = base, NAVY

        shapes.append(sp_simple(sid, hx, ry, hcx, ROW_CY, cf, val, tc, 820,
                                bold=bold, algn=algn)); sid+=1

# Footer
shapes.append(sp_simple(sid, 150000, 4710000, 8844000, 260000, "EEF3FB",
    "* On-demand job pod  |  RPS figures are for fast-path requests only (subscriber profile exists in DB)  |  1 SQL query per IMSI lookup \u2192 ~2,000 qps at 2k rps  |  Replica counts sized for N-1 fault tolerance  |  PVC size configurable (20 Gi = baseline)",
    GRAY, 700, bold=0, algn="l", valign="ctr", italic=1, border=False)); sid+=1

xml = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">\n'
    '  <p:cSld name="Container Resources">\n'
    '    <p:spTree>\n'
    '      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>\n'
    '      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>\n'
    + "\n".join(shapes) + "\n"
    '    </p:spTree>\n'
    '  </p:cSld>\n'
    '  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>\n'
    '</p:sld>'
)

with open(slide_path, "w", encoding="utf-8") as f:
    f.write(xml)
print(f"Written {slide_path} — {sid-2} shapes, 8 columns")
