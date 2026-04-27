// AAA Cloud-Native Platform — Executive Presentation
// gen_pptx.js — regenerate: node docs/gen_pptx.js
//
// Font sizes LOCKED to user-approved values (Apr 2026):
//   capCard title  : 16pt bold
//   capCard body   : 14pt
//   svcBox name    : 14pt bold
//   svcBox sub     : 10.5pt
//   arrow labels   : 10pt
//
"use strict";

const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";     // 13.3" × 7.5"
pres.title  = "AAA Cloud-Native Platform";
pres.author = "Platform Engineering";

const W = 13.3;
const H = 7.5;

// ── Palette ───────────────────────────────────────────────────────────────────
const C = {
  navy:    "1C2340",
  amber:   "F5A623",
  white:   "FFFFFF",
  light:   "F4F6F9",
  muted:   "8892A4",
  dark:    "111827",
  green:   "38A169",
  red:     "E53E3E",
  blue:    "3182CE",
  bgLight: "EFF2F7",
  gray:    "374151",
  iceBlue: "CADCFC",
  skyBlue: "7FB3D3",
  bgDark:  "172055",
  darkGray:"4A5568",
};

// Shadow factory — NEVER reuse: PptxGenJS mutates options in-place
const mkSdw = () => ({ type: "outer", color: "000000", blur: 8, offset: 2, angle: 135, opacity: 0.12 });

// ── Backgrounds ───────────────────────────────────────────────────────────────
function darkBg(s)  { s.background = { color: C.navy }; }
function lightBg(s) { s.background = { color: "F8F9FC" }; }

// ── Header bar (amber top strip + navy band) ─────────────────────────────────
// Returns Y coordinate where content should start
function hdr(s, title, sub) {
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0,    w: W, h: 0.08, fill: { color: C.amber }, line: { color: C.amber } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.08, w: W, h: 0.72, fill: { color: C.navy  }, line: { color: C.navy  } });
  s.addText(title, { x: 0.45, y: 0.08, w: W - 0.9, h: 0.72, fontSize: 26, bold: true, color: C.white, valign: "middle", margin: 0 });
  if (sub) {
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.8, w: W, h: 0.35, fill: { color: "F0F3FA" }, line: { color: "DDE3F0" } });
    s.addText(sub, { x: 0.45, y: 0.8, w: W - 0.9, h: 0.35, fontSize: 11, italic: true, color: C.blue, valign: "middle", margin: 0 });
    return 1.2;
  }
  return 0.95;
}

// ── Capability card ───────────────────────────────────────────────────────────
// USER-APPROVED: title=16pt bold  body=14pt
function capCard(s, x, y, w, h, num, title, body) {
  const AS = 0.055; // amber strip width
  const HH = 0.52;  // header zone height
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.white }, line: { color: "E2E8F0", width: 0.75 }, shadow: mkSdw() });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: AS, h, fill: { color: C.amber }, line: { color: C.amber } });
  s.addShape(pres.shapes.RECTANGLE, { x: x + AS, y, w: w - AS, h: HH, fill: { color: C.bgLight }, line: { color: C.bgLight } });
  s.addText(num,   { x: x + 0.09, y: y + 0.06, w: 0.44, h: 0.42, fontSize: 13, bold: true, color: C.amber, align: "center", valign: "middle", margin: 0 });
  s.addText(title, { x: x + 0.60, y: y + 0.06, w: w - 0.72, h: 0.42, fontSize: 16, bold: true, color: C.navy, valign: "middle", margin: 0 });
  s.addText(body,  { x: x + 0.14, y: y + HH + 0.1, w: w - 0.22, h: h - HH - 0.18, fontSize: 14, color: C.gray, margin: 0 });
}

// ── Service box for architecture slide ────────────────────────────────────────
// USER-APPROVED: name=14pt bold  sub=10.5pt
function svcBox(s, x, y, w, h, name, sub, fillColor) {
  const fc = fillColor || C.navy;
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fc }, line: { color: fc }, shadow: mkSdw() });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.07, fill: { color: C.amber }, line: { color: C.amber } });
  s.addText(name, { x: x + 0.08, y: y + 0.08, w: w - 0.16, h: 0.44, fontSize: 14, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
  if (sub) s.addText(sub, { x: x + 0.08, y: y + 0.50, w: w - 0.16, h: 0.26, fontSize: 10.5, color: C.iceBlue, align: "center", italic: true, margin: 0 });
}

// ── Horizontal connector line + arrowhead ────────────────────────────────────
function hLine(s, x1, x2, y, color, label, labelBelow) {
  const lc = color || C.iceBlue;
  s.addShape(pres.shapes.LINE, { x: x1, y, w: x2 - x1, h: 0, line: { color: lc, width: 1.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: x2 - 0.13, y: y - 0.09, w: 0.13, h: 0.18, fill: { color: lc }, line: { color: lc } });
  if (label) {
    const lY = labelBelow ? y + 0.04 : y - 0.28;
    // USER-APPROVED: arrow labels = 10pt
    s.addText(label, { x: x1 + 0.05, y: lY, w: x2 - x1 - 0.05, h: 0.24, fontSize: 10, italic: true, color: lc, align: "center", margin: 0 });
  }
}

// ── Vertical dashed line ──────────────────────────────────────────────────────
function vDash(s, x, y1, y2, color) {
  s.addShape(pres.shapes.LINE, { x, y: y1, w: 0, h: y2 - y1, line: { color: color || C.amber, width: 1.5, dashType: "dash" } });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 1 — TITLE
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkBg(s);

  // Amber top accent line
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.08, fill: { color: C.amber }, line: { color: C.amber } });

  // Logo text block
  s.addText("AAA Cloud-Native",  { x: 0.6, y: 0.6,  w: 8, h: 1.05, fontSize: 48, bold: true, color: C.white,  fontFace: "Calibri", margin: 0 });
  s.addText("Platform",          { x: 0.6, y: 1.55, w: 8, h: 0.95, fontSize: 48, bold: true, color: C.amber,  fontFace: "Calibri", margin: 0 });
  s.addText("Telecom Subscriber Provisioning & Real-Time RADIUS Authentication", { x: 0.6, y: 2.62, w: 8.5, h: 0.55, fontSize: 16, color: C.iceBlue, fontFace: "Calibri", margin: 0 });

  // Stats row
  const stats = [
    { v: "<15ms",  l: "p99 Lookup SLA" },
    { v: "443",    l: "Regression Tests" },
    { v: "8M+",    l: "Subscriber Profiles" },
    { v: "4",      l: "IP Resolution Modes" },
  ];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.1;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 3.45, w: 2.8, h: 1.1, fill: { color: C.bgDark }, line: { color: C.blue, width: 0.75 }, shadow: mkSdw() });
    s.addText(st.v, { x, y: 3.52, w: 2.8, h: 0.58, fontSize: 30, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(st.l, { x, y: 4.10, w: 2.8, h: 0.38, fontSize: 11,  color: C.iceBlue, align: "center", margin: 0 });
  });

  // Tech stack strip
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.0, w: W, h: 0.45, fill: { color: "13193A" }, line: { color: "13193A" } });
  const stack = ["C++20 / Drogon", "Python / FastAPI", "PostgreSQL 15", "Helm 3", "Prometheus / Grafana"];
  s.addText(stack.join("   |   "), { x: 0.5, y: 5.0, w: W - 1.0, h: 0.45, fontSize: 11, color: C.muted, align: "center", valign: "middle", margin: 0 });

  // Footer
  s.addText("TELECOM  |  AAA  |  KUBERNETES-NATIVE  |  APRIL 2026", { x: 0, y: 6.9, w: W, h: 0.35, fontSize: 9, color: C.muted, align: "center", charSpacing: 3, margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 2 — PLATFORM OVERVIEW  (6 capability cards)
// USER-APPROVED: card title=16pt  card body=14pt
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "Platform Overview");

  const CW = 4.0, CH = 2.3;
  const cols = [0.35, 4.60, 8.85];
  const rows = [1.05, 3.60];

  const cards = [
    { num: "01", title: "Cloud-Native AAA",       body: "Telecom subscriber provisioning & RADIUS authentication platform built for Kubernetes" },
    { num: "02", title: "Static IP Assignment",   body: "Assigns static IPs to SIM cards via RADIUS. Supports IMSI-level, card-level, and APN-aware modes" },
    { num: "03", title: "8M+ Subscribers",        body: "Migration path from 7 regional MariaDB/Galera clusters. Supports 300K-row bulk imports per job" },
    { num: "04", title: "443 Regression Tests",   body: "Full pytest suite: REST endpoints, IP allocation, bulk ops, first-connection, RADIUS, Grafana metrics" },
    { num: "05", title: "Multi-Region Ready",     body: "Read replicas per region, cross-region first-connection writes. EU/US replica failover supported" },
    { num: "06", title: "Full Observability",     body: "Prometheus metrics, Grafana dashboards, pre-built alerts for p99 SLA, pool exhaustion & DB health" },
  ];

  cards.forEach((c, i) => {
    capCard(s, cols[i % 3], rows[Math.floor(i / 3)], CW, CH, c.num, c.title, c.body);
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 3 — THE CHALLENGE  (added from gen-presentation.js)
// USER-APPROVED: card title=16pt  card body=14pt
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkBg(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.08, fill: { color: C.amber }, line: { color: C.amber } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.08, w: W, h: 0.72, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("The Challenge", { x: 0.45, y: 0.08, w: 8, h: 0.72, fontSize: 26, bold: true, color: C.white, valign: "middle", margin: 0 });

  const CW = 6.2, CH = 2.6;
  const probs = [
    { t: "Speed vs. Scale",          d: "RADIUS must authenticate subscribers in <15ms while serving millions of requests per day — but provisioning writes are slower and less frequent." },
    { t: "Unknown IMSIs at First Attach", d: "Network equipment cannot predict when a new SIM activates. Operators need dynamic, zero-touch provisioning on first connection — no manual intervention." },
    { t: "Multi-IMSI SIM Complexity", d: "A single physical SIM card can carry up to 10 distinct IMSIs. Provisioning one slot must automatically provision all sibling slots in a single atomic step." },
    { t: "IP Pool Race Conditions",  d: "Concurrent first-connection events can race to claim the same IP address. A safe, lock-free allocation mechanism is critical for correctness at scale." },
  ];

  probs.forEach((p, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * (CW + 0.5);
    const y = 1.0 + row * (CH + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: CH, fill: { color: C.bgDark }, line: { color: C.blue, width: 0.75 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: CH, fill: { color: C.amber }, line: { color: C.amber } });
    // USER-APPROVED: title=16pt, body=14pt
    s.addText(p.t, { x: x + 0.16, y: y + 0.1,  w: CW - 0.24, h: 0.38, fontSize: 16, bold: true, color: C.white, margin: 0 });
    s.addText(p.d, { x: x + 0.16, y: y + 0.54, w: CW - 0.24, h: CH - 0.66, fontSize: 14, color: C.iceBlue, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 4 — SYSTEM ARCHITECTURE
// USER-APPROVED: svcBox name=14pt  sub=10.5pt  arrow labels=10pt
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "System Architecture", "Request path: SMF → Radius-to-Rest → Lookup Service ↔ 1st Connection & Provisioning ↔ PostgreSQL (HA cluster)");

  // ── Row 1 service boxes (y=1.9) ──
  const R1Y = 1.9;
  const R1H = 0.85;

  svcBox(s, 0.3,   R1Y, 2.4, R1H, "SMF / PGW / GGSN",      "Access Node",          "223060");
  svcBox(s, 3.5,   R1Y, 2.8, R1H, "aaa-radius-server",      "C++20  UDP/1812",       C.navy);
  svcBox(s, 7.2,   R1Y, 2.9, R1H, "aaa-lookup-service",     "C++20/Drogon  :8081",   C.navy);
  svcBox(s, 11.0,  R1Y, 2.15,R1H, "PostgreSQL Replica",     "Read-only",            "2C3E70");

  // Row 1 connectors (y = midpoint of boxes)
  const MID1 = R1Y + R1H / 2;
  hLine(s, 2.7,  3.5,  MID1, C.blue,    "RADIUS UDP/1812");
  hLine(s, 6.3,  7.2,  MID1, C.blue,    "GET /lookup?imsi=&apn=");
  hLine(s, 10.1, 11.0, MID1, C.iceBlue, null);
  // Reverse arrow from replica to lookup
  s.addShape(pres.shapes.LINE, { x: 7.2, y: MID1 + 0.12, w: 2.9, h: 0, line: { color: C.iceBlue, width: 1.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.2, y: MID1 + 0.04, w: 0.13, h: 0.18, fill: { color: C.iceBlue }, line: { color: C.iceBlue } });

  // ── DB miss vertical arrow ──
  const LOOKUP_CX = 7.2 + 2.9 / 2; // centre-x of lookup box
  const R2Y = 3.85;
  vDash(s, LOOKUP_CX, R1Y + R1H, R2Y, C.amber);
  s.addText("DB miss →", { x: LOOKUP_CX + 0.1, y: R1Y + R1H + 0.05, w: 2.4, h: 0.22, fontSize: 10, italic: true, color: C.amber, margin: 0 });
  s.addText("POST /first-connection", { x: LOOKUP_CX + 0.1, y: R1Y + R1H + 0.28, w: 2.6, h: 0.22, fontSize: 10, italic: true, color: C.amber, margin: 0 });

  // ── Row 2 service boxes (y=R2Y) ──
  const R2H = 0.85;
  svcBox(s, 0.3,  R2Y, 2.8, R2H, "aaa-management-ui",       "React/TypeScript  :80", "1A4A7A");
  svcBox(s, 6.8,  R2Y, 3.35,R2H, "subscriber-profile-api",  "Python/FastAPI  :8080",  C.navy);
  svcBox(s, 11.0, R2Y, 2.15,R2H, "PostgreSQL Primary",      "Read/Write",            "2C3E70");

  // Connector: subscriber-profile-api ↔ PostgreSQL Primary
  const MID2 = R2Y + R2H / 2;
  hLine(s, 10.15, 11.0, MID2, C.iceBlue, null);
  s.addShape(pres.shapes.LINE, { x: 10.15, y: MID2 + 0.12, w: 0.85, h: 0, line: { color: C.iceBlue, width: 1.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 10.15, y: MID2 + 0.04, w: 0.13, h: 0.18, fill: { color: C.iceBlue }, line: { color: C.iceBlue } });

  // PostgreSQL replication arrow (vertical replica → primary)
  const PG_CX = 11.0 + 2.15 / 2;
  s.addShape(pres.shapes.LINE, { x: PG_CX, y: R1Y + R1H, w: 0, h: R2Y - R1Y - R1H, line: { color: C.muted, width: 1, dashType: "dash" } });

  // Footer note
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 6.55, w: W, h: 0.65, fill: { color: "EAECF5" }, line: { color: "C8CCDD" } });
  s.addText(
    "PostgreSQL streaming replication → read replicas per region (EU/US)\n" +
    "First-connection writes cross-region once per IMSI lifetime (~50–100ms — acceptable)",
    { x: 0.4, y: 6.58, w: W - 0.8, h: 0.58, fontSize: 10, color: C.darkGray, margin: 0 }
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 5 — PLATFORM SERVICES AT A GLANCE
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "Platform Services at a Glance");

  const services = [
    {
      name: "aaa-radius-server", tech: "C++20", port: "UDP / 1812",
      points: [
        "RADIUS protocol termination (RFC 2865)",
        "Single GET /lookup call per Access-Request",
        "3GPP VSA mapping: IMSI, IMEISV, Charging-Characteristics",
        "Thread pool: 16 workers → ~1600 RPS at 5ms p50",
        "Optional: remove if access nodes speak REST directly",
      ],
    },
    {
      name: "aaa-lookup-service", tech: "C++20 / Drogon", port: "HTTP / 8081",
      points: [
        "Hot-path: GET /v1/lookup?imsi=&apn= — single endpoint",
        "SLA: p99 < 15ms on DB hit (3–6 replicas per region)",
        "DB miss → calls subscriber-profile-api internally (transparent)",
        "4 IP resolution modes: iccid | iccid_apn | imsi | imsi_apn",
        "Read-only PostgreSQL replica — no writes ever",
      ],
    },
    {
      name: "subscriber-profile-api", tech: "Python / FastAPI", port: "HTTP / 8080",
      points: [
        "Full CRUD: SIM profiles, IMSI ranges, IP pools, bulk jobs",
        "First-connection IP allocation with per-APN pool routing",
        "Multi-IMSI SIM pre-provisioning (atomic per-slot allocation)",
        "Async bulk jobs (batch 500, thread pool)",
        "Routing domains for IP uniqueness scoping",
      ],
    },
    {
      name: "aaa-management-ui", tech: "React 18 / TypeScript", port: "HTTP / 80",
      points: [
        "Operator web console: SIMs, Pools, Range Configs, Bulk Jobs",
        "OAuth 2.0 / OIDC authentication (JWT in memory only)",
        "Live metrics panel with Grafana embed links",
        "Bulk import wizard with per-row error display",
      ],
    },
  ];

  const CW = 3.0, CH = 5.3, GAP = 0.18;
  const startX = (W - 4 * CW - 3 * GAP) / 2;

  services.forEach((svc, i) => {
    const x = startX + i * (CW + GAP);
    const y = 1.0;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: CH, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: 1.0, fill: { color: C.navy }, line: { color: C.navy } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: 0.07, fill: { color: C.amber }, line: { color: C.amber } });
    s.addText(svc.name, { x: x + 0.1, y: y + 0.1,  w: CW - 0.2, h: 0.42, fontSize: 12, bold: true, color: C.white, align: "center", margin: 0 });
    s.addText(svc.tech, { x: x + 0.1, y: y + 0.52, w: CW - 0.2, h: 0.24, fontSize: 10, color: C.amber, align: "center", margin: 0 });
    s.addText(svc.port, { x: x + 0.1, y: y + 0.74, w: CW - 0.2, h: 0.22, fontSize: 10, italic: true, color: C.iceBlue, align: "center", margin: 0 });
    s.addText(
      svc.points.map(p => ({ text: p, options: { bullet: true, breakLine: true } })),
      { x: x + 0.14, y: y + 1.08, w: CW - 0.28, h: CH - 1.18, fontSize: 11, color: C.gray, paraSpaceAfter: 3, margin: 0 }
    );
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 6 — PERFORMANCE AT A GLANCE  (added from gen-presentation.js)
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkBg(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.08, fill: { color: C.amber }, line: { color: C.amber } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.08, w: W, h: 0.72, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("Performance at a Glance", { x: 0.45, y: 0.08, w: 10, h: 0.72, fontSize: 26, bold: true, color: C.white, valign: "middle", margin: 0 });

  // Big stats row
  const stats = [
    { v: "< 15ms", l: "p99 Lookup Latency",     bg: "1E4FA8" },
    { v: "1–3ms",  l: "p50 Typical Latency",     bg: "1A4491" },
    { v: "100K",   l: "Profiles per Bulk Job",   bg: "163A7A" },
    { v: "253",    l: "IPs per /24 Pool",         bg: "122F64" },
    { v: "10",     l: "Max IMSIs per SIM",        bg: "0E244E" },
  ];
  const SW = 2.42;
  stats.forEach((st, i) => {
    const x = 0.4 + i * (SW + 0.12);
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.0, w: SW, h: 1.45, fill: { color: st.bg }, line: { color: st.bg }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.0, w: SW, h: 0.07, fill: { color: C.amber }, line: { color: C.amber } });
    s.addText(st.v, { x, y: 1.1,  w: SW, h: 0.72, fontSize: 30, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(st.l, { x, y: 1.82, w: SW, h: 0.52, fontSize: 10, color: C.iceBlue, align: "center", margin: 0 });
  });

  // How we achieve <15ms section
  s.addText("How we achieve < 15ms", { x: 0.4, y: 2.7, w: W - 0.8, h: 0.36, fontSize: 15, bold: true, color: C.amber, margin: 0 });

  const perfs = [
    { t: "Index-only B-tree seek",  d: "imsi2sim.imsi is a PK — single-page lookup, no full-table scan" },
    { t: "Near 100% cache hit",     d: "~80MB index fits entirely in PostgreSQL shared_buffers at steady state" },
    { t: "Async C++ / Drogon",      d: "Non-blocking I/O with coroutines; zero context-switching overhead per request" },
    { t: "Read replica isolation",  d: "Lookup never competes with write transactions on the primary" },
  ];
  const PCW = 6.1;
  perfs.forEach((p, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.4 + col * (PCW + 0.5);
    const y = 3.2 + row * 1.2;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: PCW, h: 1.05, fill: { color: C.bgDark }, line: { color: C.blue, width: 0.5 } });
    s.addText(p.t, { x: x + 0.14, y: y + 0.08, w: PCW - 0.22, h: 0.32, fontSize: 12, bold: true, color: C.white, margin: 0 });
    s.addText(p.d, { x: x + 0.14, y: y + 0.42, w: PCW - 0.22, h: 0.52, fontSize: 11, color: C.iceBlue, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 7 — IP RESOLUTION MODES
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "IP Resolution Modes", "Configured per IMSI range; controls how the lookup service resolves a Framed-IP-Address for each subscriber");

  const modes = [
    {
      id: "iccid",
      scope: "Card-level", apn: "Ignored", ips: "1 / SIM",
      color: "1C7ED6",
      body: "One static IP per SIM card regardless of IMSI or APN. Both IMSIs on a dual-SIM card get the same IP.",
    },
    {
      id: "iccid_apn",
      scope: "Card-level", apn: "Per-APN", ips: "N / SIM",
      color: "0CA678",
      body: "One IP per APN per SIM card. Both IMSIs share the same card-level APN-keyed IPs.",
    },
    {
      id: "imsi",
      scope: "IMSI-level", apn: "Ignored", ips: "1 / IMSI",
      color: "7048D8",
      body: "One IP per IMSI. Two IMSIs on the same card get independent IPs. APN in request is ignored.",
    },
    {
      id: "imsi_apn",
      scope: "IMSI-level", apn: "Per-APN", ips: "N / IMSI",
      color: "D6336C",
      body: "One IP per APN per IMSI. Finest granularity. A dual-SIM card with 3 APNs yields 6 distinct IPs.",
    },
  ];

  const CW = 2.9;
  const CH = 5.3;
  const GAP = 0.25;
  const startX = (W - 4 * CW - 3 * GAP) / 2;

  modes.forEach((m, i) => {
    const x = startX + i * (CW + GAP);
    const y = 1.25;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: CH, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: 0.07, fill: { color: m.color }, line: { color: m.color } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.07, w: CW, h: 1.45, fill: { color: m.color }, line: { color: m.color } });
    s.addText(m.id, { x: x + 0.1, y: y + 0.15, w: CW - 0.2, h: 0.55, fontSize: 22, bold: true, color: C.white, align: "center", fontFace: "Courier New", margin: 0 });

    const attrs = [
      { label: "Scope:", val: m.scope },
      { label: "APN:",   val: m.apn   },
      { label: "IPs:",   val: m.ips   },
    ];
    attrs.forEach((a, ai) => {
      const ay = y + 0.78 + ai * 0.28;
      s.addText(a.label, { x: x + 0.12, y: ay, w: 0.75, h: 0.26, fontSize: 10, bold: true, color: C.white, margin: 0 });
      s.addText(a.val,   { x: x + 0.90, y: ay, w: CW - 1.05, h: 0.26, fontSize: 10, color: C.white, margin: 0 });
    });

    s.addText(m.body, { x: x + 0.14, y: y + 1.65, w: CW - 0.28, h: CH - 1.78, fontSize: 13, color: C.darkGray, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 8 — FIRST-CONNECTION AUTO-PROVISIONING
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "First-Connection Auto-Provisioning", "Triggered on DB miss — once per IMSI lifetime, transparent to the network");

  const steps = [
    { n: "1", title: "RADIUS Access-Request arrives",    desc: "NAS/SMF sends IMSI + APN to aaa-radius-server (UDP/1812)" },
    { n: "2", title: "Lookup queries read replica",      desc: "GET /lookup?imsi=&apn= — fast B-tree lookup, typically <5ms" },
    { n: "3", title: "DB miss detected",                 desc: "IMSI not in imsi2sim → first-connection path triggered" },
    { n: "4", title: "POST /first-connection",           desc: "subscriber-profile-api finds matching range config, allocates IP with SKIP LOCKED" },
    { n: "5", title: "IP returned to lookup",            desc: "Fresh IP stored in DB; returned to aaa-lookup-service in response" },
    { n: "6", title: "Access-Accept sent",               desc: "aaa-radius-server responds with Framed-IP-Address — transparent to NAS" },
  ];

  const CW = 3.85, CH = 1.35, GAP = 0.25;

  steps.forEach((st, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.4 + col * (CW + GAP);
    const y = 1.25 + row * (CH + 0.25);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: CH, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: CH, fill: { color: C.amber }, line: { color: C.amber } });
    // Step circle
    s.addShape(pres.shapes.OVAL, { x: x + 0.14, y: y + 0.1, w: 0.42, h: 0.42, fill: { color: C.navy }, line: { color: C.navy } });
    s.addText(st.n, { x: x + 0.14, y: y + 0.1, w: 0.42, h: 0.42, fontSize: 12, bold: true, color: C.amber, align: "center", valign: "middle", margin: 0 });
    s.addText(st.title, { x: x + 0.65, y: y + 0.08, w: CW - 0.78, h: 0.38, fontSize: 12, bold: true, color: C.navy, margin: 0 });
    s.addText(st.desc,  { x: x + 0.14, y: y + 0.55, w: CW - 0.24, h: 0.7,  fontSize: 11, color: C.darkGray, margin: 0 });
  });

  // Key properties
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.65, w: W - 0.8, h: 2.35, fill: { color: "EAECF5" }, line: { color: "C8CCDD", width: 0.75 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.65, w: 0.07, h: 2.35, fill: { color: C.blue }, line: { color: C.blue } });
  s.addText("Key Properties", { x: 0.6, y: 4.72, w: 4, h: 0.32, fontSize: 12, bold: true, color: C.navy, margin: 0 });
  const kp = [
    ["Frequency:",    "Once per IMSI lifetime (never repeats)"],
    ["Latency:",      "~50–500ms (adds to first RADIUS round-trip)"],
    ["Steady-state:", "All subsequent lookups: p99 < 15ms (DB hit)"],
    ["Atomicity:",    "Multi-IMSI SIM: all slots allocated in 1 COMMIT"],
    ["SKIP LOCKED:",  "Race-safe pool allocation — no duplicate IPs"],
  ];
  kp.forEach(([k, v], i) => {
    const ky = 5.1 + i * 0.35;
    s.addText(k, { x: 0.65, y: ky, w: 1.8, h: 0.3, fontSize: 11, bold: true, color: C.navy, margin: 0 });
    s.addText(v, { x: 2.55, y: ky, w: 10.5, h: 0.3, fontSize: 11, color: C.darkGray, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 9 — SIM PROFILE TYPES
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "SIM Profile Types — 8 Provisioning Scenarios");

  const headers = ["ID", "SIM Type", "Mode", "APN Catalog", "IPs/SIM", "Config Required", "First-Connection Result"];
  const rows = [
    ["S1", "Single-IMSI", "imsi",      "—",      "1",  "range-config + pool",         "1 IP → imsi_apn_ips (apn=NULL)"],
    ["S2", "Single-IMSI", "imsi_apn",  "N APNs", "N",  "range-config + apn-pools (×N)", "N IPs → imsi_apn_ips per APN"],
    ["S3", "Single-IMSI", "iccid",     "—",      "1",  "range-config + pool",         "1 IP → sim_apn_ips (apn=NULL)"],
    ["S4", "Single-IMSI", "iccid_apn", "N APNs", "N",  "range-config + apn-pools (×N)", "N IPs → sim_apn_ips per APN"],
    ["M1", "Multi-IMSI",  "imsi",      "—",      "N slots × 1",   "iccid-range + slots + pool",    "1 IP per slot → imsi_apn_ips"],
    ["M2", "Multi-IMSI",  "imsi_apn",  "N APNs", "N slots × N",   "iccid-range + slots + apn-pools","N IPs per slot per APN"],
    ["M3", "Multi-IMSI",  "iccid",     "—",      "1 (shared)",    "iccid-range + slots + pool",    "1 IP → sim_apn_ips (shared)"],
    ["M4", "Multi-IMSI",  "iccid_apn", "N APNs", "N (shared/APN)","iccid-range + slots + apn-pools","N IPs → sim_apn_ips per APN"],
  ];

  const colW = [0.6, 1.3, 1.3, 1.25, 1.25, 2.7, 4.6];
  const rowH  = 0.46;
  const tX    = 0.35;
  const tY    = 1.05;

  // Header row
  let cx = tX;
  headers.forEach((h, hi) => {
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: tY, w: colW[hi], h: rowH, fill: { color: C.navy }, line: { color: C.navy } });
    s.addText(h, { x: cx + 0.04, y: tY + 0.03, w: colW[hi] - 0.08, h: rowH - 0.06, fontSize: 10, bold: true, color: C.white, valign: "middle", margin: 0 });
    cx += colW[hi];
  });

  // Data rows
  rows.forEach((row, ri) => {
    const ry = tY + rowH * (ri + 1);
    const bg = ri % 2 === 0 ? C.white : "F3F5FB";
    const isSingle = row[1] === "Single-IMSI";
    let cx2 = tX;
    row.forEach((cell, ci) => {
      s.addShape(pres.shapes.RECTANGLE, { x: cx2, y: ry, w: colW[ci], h: rowH, fill: { color: bg }, line: { color: "D0D8EC", width: 0.5 } });
      const bold = ci === 0 || ci === 2;
      const color = ci === 0 ? (isSingle ? C.blue : C.green) : C.dark;
      s.addText(cell, { x: cx2 + 0.04, y: ry + 0.03, w: colW[ci] - 0.08, h: rowH - 0.06, fontSize: 10, bold, color, valign: "middle", fontFace: ci <= 2 ? "Courier New" : "Calibri", margin: 0 });
      cx2 += colW[ci];
    });
  });

  // Legend
  s.addShape(pres.shapes.RECTANGLE, { x: 0.35, y: 6.5, w: W - 0.7, h: 0.65, fill: { color: "EBF5FF" }, line: { color: "C0D8F0" } });
  s.addText("Key: All siblings provisioned in ONE transaction (thundering herd protection). imsi mode → IP per slot. iccid mode → 1 shared IP per card.", { x: 0.55, y: 6.55, w: W - 0.9, h: 0.55, fontSize: 11, bold: true, color: C.navy, valign: "middle", margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 10 — PROVISIONING API — COMPLETE ENDPOINT REFERENCE
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "Provisioning API — Complete Endpoint Reference");

  const groups = [
    {
      title: "SIM Profiles", color: C.blue,
      eps: [
        "POST /profiles — Create profile (201)",
        "GET  /profiles — Paginated list with filters (iccid, imsi, status, pool_id, ip…)",
        "GET  /profiles/{id} — Full profile by UUID",
        "PUT  /profiles/{id} — Replace full profile",
        "PATCH /profiles/{id} — Partial update (JSON Merge Patch)",
        "DELETE /profiles/{id} — Soft-delete (sets terminated, hard-deletes IPs)",
        "GET  /profiles/export — Export in bulk-import format",
        "POST /profiles/bulk — Async bulk upsert job",
      ],
    },
    {
      title: "IMSI Operations", color: "0CA678",
      eps: [
        "GET  /profiles/{id}/imsis — List all IMSIs on SIM",
        "POST /profiles/{id}/imsis — Add IMSI + apn_ips",
        "PATCH /profiles/{id}/imsis/{imsi} — Update IMSI status or priority",
        "DELETE /profiles/{id}/imsis/{imsi} — Remove IMSI, return IPs to pool",
        "POST /profiles/{id}/release-ips — Return all pool IPs",
      ],
    },
    {
      title: "IP Pools & Routing Domains", color: C.amber,
      eps: [
        "POST/GET/PATCH/DELETE /pools — Pool CRUD + overlap validation",
        "GET  /pools/{id}/stats — total / allocated / available counts",
        "POST/GET/PATCH/DELETE /routing-domains — Domain CRUD",
        "GET  /routing-domains/{id}/suggest-cidr?size=N — Free CIDR finder",
      ],
    },
    {
      title: "Range Configs & APN Pools", color: C.red,
      eps: [
        "POST/GET/PATCH/DELETE /range-configs — IMSI range CRUD",
        "GET/POST/DELETE /range-configs/{id}/apn-pools — Per-APN pool overrides",
        "POST/GET/PATCH/DELETE /iccid-range-configs — Multi-IMSI SIM ranges",
        "GET/POST/DELETE /iccid-range-configs/{id}/imsi-slots — IMSI slot management",
        "POST /first-connection — Internal; called by aaa-lookup-service on DB miss",
      ],
    },
  ];

  const GW = 5.85, GH = 4.75, GAP = 0.45;
  const startX = (W - 2 * GW - GAP) / 2;

  groups.forEach((g, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = startX + col * (GW + GAP);
    const y = 1.05 + row * (GH + 0.35);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: GW, h: GH, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: GW, h: 0.42, fill: { color: g.color }, line: { color: g.color } });
    s.addText(g.title, { x: x + 0.12, y, w: GW - 0.2, h: 0.42, fontSize: 12, bold: true, color: C.white, valign: "middle", margin: 0 });
    s.addText(
      g.eps.map(ep => ({ text: ep, options: { bullet: true, breakLine: true } })),
      { x: x + 0.14, y: y + 0.50, w: GW - 0.24, h: GH - 0.60, fontSize: 10, color: C.dark, fontFace: "Courier New", paraSpaceAfter: 2, margin: 0 }
    );
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 11 — POSTGRESQL SCHEMA — 9 TABLES
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "PostgreSQL Schema — 9 Tables");

  const tables = [
    // Subscriber data group
    { grp: "SUBSCRIBER DATA", name: "sim_profiles",        pk: "id (UUID)",  desc: "Core SIM record: iccid, status, ip_resolution, account_name",         color: C.blue },
    { grp: "SUBSCRIBER DATA", name: "imsi2sim",            pk: "imsi",       desc: "IMSI ↔ SIM mapping. Supports multiple IMSIs per SIM (dual-SIM)",       color: C.blue },
    { grp: "IP POOLS",        name: "ip_pools",            pk: "id",         desc: "Pool definition: subnet, start_ip, end_ip, routing_domain_id",         color: "0CA678" },
    { grp: "IP POOLS",        name: "ip_pool_available",   pk: "ip, pool_id",desc: "Available IP slots. SKIP LOCKED ensures race-safe allocation",         color: "0CA678" },
    { grp: "IP POOLS",        name: "imsi_apn_ips",        pk: "imsi, apn",  desc: "IMSI-level allocated IPs with optional APN key",                       color: "0CA678" },
    { grp: "IP POOLS",        name: "sim_apn_ips",         pk: "iccid, apn", desc: "Card-level allocated IPs with optional APN key (iccid modes)",         color: "0CA678" },
    { grp: "RANGE CONFIGS",   name: "iccid_range_configs", pk: "id",         desc: "ICCID-based SIM ranges with IMSI slot definitions",                   color: C.amber },
    { grp: "RANGE CONFIGS",   name: "imsi_range_configs",  pk: "id",         desc: "IMSI range configs with pool_id and provisioning_mode",               color: C.amber },
    { grp: "RANGE CONFIGS",   name: "range_config_apn_pools", pk: "range_config_id, apn", desc: "Per-APN pool routing overrides for any range config",     color: C.amber },
  ];

  const groups = ["SUBSCRIBER DATA", "IP POOLS", "RANGE CONFIGS"];
  const groupCols = [
    { x: 0.35, w: 3.75, tables: tables.filter(t => t.grp === "SUBSCRIBER DATA") },
    { x: 4.40, w: 3.75, tables: tables.filter(t => t.grp === "IP POOLS") },
    { x: 8.45, w: 4.5,  tables: tables.filter(t => t.grp === "RANGE CONFIGS") },
  ];

  groupCols.forEach(gc => {
    const grpColor = gc.tables[0].color;
    s.addShape(pres.shapes.RECTANGLE, { x: gc.x, y: 1.02, w: gc.w, h: 0.36, fill: { color: grpColor }, line: { color: grpColor } });
    s.addText(gc.tables[0].grp, { x: gc.x + 0.08, y: 1.02, w: gc.w - 0.16, h: 0.36, fontSize: 11, bold: true, color: C.white, align: "center", valign: "middle", charSpacing: 2, margin: 0 });
    gc.tables.forEach((t, ti) => {
      const ty = 1.48 + ti * 1.08;
      s.addShape(pres.shapes.RECTANGLE, { x: gc.x, y: ty, w: gc.w, h: 1.0, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
      s.addShape(pres.shapes.RECTANGLE, { x: gc.x, y: ty, w: 0.06, h: 1.0, fill: { color: grpColor }, line: { color: grpColor } });
      s.addText(t.name, { x: gc.x + 0.14, y: ty + 0.06, w: gc.w - 0.22, h: 0.32, fontSize: 11, bold: true, color: C.navy, fontFace: "Courier New", margin: 0 });
      s.addText(`PK: ${t.pk}`, { x: gc.x + 0.14, y: ty + 0.38, w: gc.w - 0.22, h: 0.24, fontSize: 10, color: grpColor, margin: 0 });
      s.addText(t.desc, { x: gc.x + 0.14, y: ty + 0.62, w: gc.w - 0.22, h: 0.33, fontSize: 9.5, color: C.darkGray, margin: 0 });
    });
  });

  // Footer
  s.addShape(pres.shapes.RECTANGLE, { x: 0.35, y: 6.65, w: W - 0.7, h: 0.55, fill: { color: "EBF5FF" }, line: { color: "C0D8F0" } });
  s.addText("Hot-path p99 < 15ms via B-tree index on imsi2sim.imsi  |  SKIP LOCKED prevents duplicate IP allocation  |  Pool resolution: APN override → slot pool → parent pool",
    { x: 0.5, y: 6.68, w: W - 1.0, h: 0.48, fontSize: 10, color: C.navy, valign: "middle", margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 12 — OBSERVABILITY — PROMETHEUS, GRAFANA & SLA ALERTS
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "Observability — Prometheus, Grafana & SLA Alerts");

  const metrics = [
    { svc: "Lookup", name: "aaa_lookup_requests_total",      note: "Total lookups by result (resolved|suspended|not_found)" },
    { svc: "Lookup", name: "aaa_lookup_duration_seconds",    note: "Latency histogram p50/p95/p99 — SLA target p99 < 15ms" },
    { svc: "Lookup", name: "first_connection_requests_total",note: "DB miss rate — triggers Stage-2 allocation" },
    { svc: "Lookup", name: "pool_exhausted_total",           note: "IP pool exhaustion events — any value is critical" },
    { svc: "RADIUS", name: "radius_access_requests_total",   note: "Incoming Access-Request packets" },
    { svc: "RADIUS", name: "radius_request_duration_ms",     note: "End-to-end RADIUS latency histogram" },
    { svc: "RADIUS", name: "radius_responses_total",         note: "Responses labelled by result (accept|reject)" },
    { svc: "API",    name: "bulk_job_duration_seconds",      note: "Bulk job processing time percentiles" },
    { svc: "DB",     name: "pg_up",                          note: "PostgreSQL primary availability (0/1)" },
  ];

  const svcColors = { Lookup: C.blue, RADIUS: "0CA678", API: C.amber, DB: C.red };
  const colW = [1.0, 4.2, 5.0];
  const rowH = 0.44;
  const tX = 0.35;
  const tY = 1.05;

  // Header
  const hdrs = ["Service", "Metric Name", "Description"];
  let cx = tX;
  hdrs.forEach((h, hi) => {
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: tY, w: colW[hi], h: rowH, fill: { color: C.navy }, line: { color: C.navy } });
    s.addText(h, { x: cx + 0.06, y: tY + 0.04, w: colW[hi] - 0.12, h: rowH - 0.08, fontSize: 11, bold: true, color: C.white, valign: "middle", margin: 0 });
    cx += colW[hi];
  });

  metrics.forEach((m, mi) => {
    const ry  = tY + rowH * (mi + 1);
    const bg  = mi % 2 === 0 ? C.white : "F3F5FB";
    const sc  = svcColors[m.svc] || C.dark;
    let cx2 = tX;
    [m.svc, m.name, m.note].forEach((cell, ci) => {
      s.addShape(pres.shapes.RECTANGLE, { x: cx2, y: ry, w: colW[ci], h: rowH, fill: { color: bg }, line: { color: "D0D8EC", width: 0.5 } });
      s.addText(cell, {
        x: cx2 + 0.06, y: ry + 0.04, w: colW[ci] - 0.12, h: rowH - 0.08,
        fontSize: ci === 1 ? 9.5 : 10.5,
        bold: ci === 0, color: ci === 0 ? sc : (ci === 1 ? C.dark : C.darkGray),
        fontFace: ci === 1 ? "Courier New" : "Calibri",
        valign: "middle", margin: 0,
      });
      cx2 += colW[ci];
    });
  });

  // Alerting rules box
  const alertX = 10.45, alertY = 1.05, alertW = 2.65;
  s.addShape(pres.shapes.RECTANGLE, { x: alertX, y: alertY, w: alertW, h: 5.5, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
  s.addShape(pres.shapes.RECTANGLE, { x: alertX, y: alertY, w: alertW, h: 0.42, fill: { color: C.red }, line: { color: C.red } });
  s.addText("Alerting Rules", { x: alertX + 0.1, y: alertY, w: alertW - 0.2, h: 0.42, fontSize: 12, bold: true, color: C.white, valign: "middle", margin: 0 });
  const alerts = [
    { name: "SLABreach",      cond: "p99 > 15ms for 2m" },
    { name: "PoolExhausted",  cond: "pool_exhausted_total > 0" },
    { name: "PrimaryDown",    cond: "pg_up == 0 for 1m" },
    { name: "HighMissRate",   cond: "first_conn_rate > 5%" },
    { name: "BulkJobSlow",    cond: "p99 > 30min for job" },
  ];
  alerts.forEach((a, ai) => {
    const ay = alertY + 0.54 + ai * 0.92;
    s.addShape(pres.shapes.RECTANGLE, { x: alertX + 0.1, y: ay, w: alertW - 0.2, h: 0.82, fill: { color: "FFF5F5" }, line: { color: "FFD0D0", width: 0.5 } });
    s.addText(a.name, { x: alertX + 0.18, y: ay + 0.06, w: alertW - 0.36, h: 0.3,  fontSize: 10, bold: true, color: C.red, fontFace: "Courier New", margin: 0 });
    s.addText(`Condition: ${a.cond}`, { x: alertX + 0.18, y: ay + 0.38, w: alertW - 0.36, h: 0.34, fontSize: 9, color: C.darkGray, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 13 — KUBERNETES DEPLOYMENT — HELM UMBRELLA CHART
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightBg(s);
  hdr(s, "Kubernetes Deployment — Helm Umbrella Chart");

  // Helm tree (left side)
  const treeX = 0.35, treeY = 1.1;
  s.addShape(pres.shapes.RECTANGLE, { x: treeX, y: treeY, w: 5.5, h: 5.7, fill: { color: C.white }, line: { color: "D0D8EC", width: 0.75 }, shadow: mkSdw() });
  s.addShape(pres.shapes.RECTANGLE, { x: treeX, y: treeY, w: 5.5, h: 0.44, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText("Helm Charts Structure", { x: treeX + 0.12, y: treeY, w: 5.3, h: 0.44, fontSize: 12, bold: true, color: C.white, valign: "middle", margin: 0 });

  const tree = [
    { indent: 0, name: "aaa-platform",          desc: "Umbrella chart — deploys full stack",         color: C.amber },
    { indent: 1, name: "├─ aaa-database",        desc: "CloudNativePG cluster + PgBouncer",          color: C.blue  },
    { indent: 1, name: "├─ aaa-lookup-service",  desc: "C++ hot-path service",                       color: C.blue  },
    { indent: 1, name: "├─ aaa-radius-server",   desc: "C++ RADIUS server",                          color: C.blue  },
    { indent: 1, name: "├─ subscriber-profile-api","desc": "Python/FastAPI provisioning API",          color: C.blue  },
    { indent: 1, name: "├─ aaa-management-ui",   desc: "React web UI",                               color: C.blue  },
    { indent: 1, name: "├─ aaa-regression-tester","desc": "pytest K8s Job (enabled via make test)",   color: C.blue  },
    { indent: 1, name: "└─ kube-prometheus-stack","desc": "Prometheus + Grafana + Alertmanager",      color: C.green },
  ];
  tree.forEach((item, i) => {
    const ty = treeY + 0.56 + i * 0.6;
    const ix = item.indent * 0.35;
    s.addText(item.name, { x: treeX + 0.16 + ix, y: ty,        w: 2.8, h: 0.28, fontSize: 10.5, bold: true, color: item.color, fontFace: "Courier New", margin: 0 });
    s.addText(item.desc, { x: treeX + 0.16 + ix, y: ty + 0.28, w: 5.1 - ix, h: 0.26, fontSize: 9.5, color: C.darkGray, margin: 0 });
  });

  // Environments (right top)
  const envs = [
    { env: "Dev",  tech: "Docker Desktop or k3d", cmd: "make setup (≈10min)",  color: C.amber },
    { env: "CI",   tech: "k3d cluster",           cmd: "make bootstrap",        color: C.blue  },
    { env: "Prod", tech: "EKS / GKE / OCI",       cmd: "values.yaml (HA)",     color: C.green },
  ];
  s.addText("Environments", { x: 6.2, y: 1.1, w: 6.8, h: 0.36, fontSize: 14, bold: true, color: C.navy, margin: 0 });
  envs.forEach((e, i) => {
    const ex = 6.2 + i * 2.3;
    const ey = 1.58;
    s.addShape(pres.shapes.RECTANGLE, { x: ex, y: ey, w: 2.1, h: 1.4, fill: { color: C.white }, line: { color: "D0D8EC" }, shadow: mkSdw() });
    s.addShape(pres.shapes.RECTANGLE, { x: ex, y: ey, w: 2.1, h: 0.07, fill: { color: e.color }, line: { color: e.color } });
    s.addText(e.env,  { x: ex + 0.1, y: ey + 0.12, w: 1.9, h: 0.34, fontSize: 16, bold: true, color: C.navy, align: "center", margin: 0 });
    s.addText(e.tech, { x: ex + 0.1, y: ey + 0.52, w: 1.9, h: 0.26, fontSize: 10, color: C.darkGray, align: "center", margin: 0 });
    s.addText(e.cmd,  { x: ex + 0.1, y: ey + 0.80, w: 1.9, h: 0.52, fontSize: 10, italic: true, color: e.color, align: "center", fontFace: "Courier New", margin: 0 });
  });

  // Quick Start commands
  s.addShape(pres.shapes.RECTANGLE, { x: 6.2, y: 3.2, w: 6.75, h: 3.5, fill: { color: "0D1117" }, line: { color: "30363D" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.2, y: 3.2, w: 0.08, h: 3.5, fill: { color: C.amber }, line: { color: C.amber } });
  s.addText("Quick Start", { x: 6.4, y: 3.26, w: 4, h: 0.32, fontSize: 12, bold: true, color: C.amber, margin: 0 });
  const cmds = [
    "# Clone and deploy",
    "git clone https://github.com/org/aaa-cloud-native",
    "cd aaa-cloud-native",
    "",
    "# Local (k3d / Docker Desktop)",
    "make setup",
    "",
    "# Build & push images",
    "make build-all REGISTRY=myregistry TAG=v1.0",
    "",
    "# Deploy to Kubernetes",
    "make deploy",
    "",
    "# Run regression suite",
    "make test",
  ];
  cmds.forEach((cmd, ci) => {
    if (cmd === "") return;
    const isComment = cmd.startsWith("#");
    s.addText(cmd, {
      x: 6.4, y: 3.65 + ci * 0.21, w: 6.3, h: 0.22,
      fontSize: 9.5,
      color: isComment ? "6A737D" : "E6EDF3",
      fontFace: "Courier New",
      margin: 0,
    });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 14 — KEY TAKEAWAYS
// USER-APPROVED: card title=16pt bold  card body=14pt
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkBg(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.08, fill: { color: C.amber }, line: { color: C.amber } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.08, w: W, h: 0.72, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("Key Takeaways", { x: 0.45, y: 0.08, w: 10, h: 0.72, fontSize: 26, bold: true, color: C.white, valign: "middle", margin: 0 });

  const CW = 6.2, CH = 2.8;
  const takeaways = [
    {
      color: C.blue,
      title: "Real-Time Performance Guaranteed",
      body:  "Separated read/write paths ensure RADIUS authentication always stays below 15ms p99 — even as the subscriber base grows to 8M+.",
    },
    {
      color: C.green,
      title: "Zero-Touch First-Connection",
      body:  "Unknown IMSIs are auto-provisioned on first RADIUS attach. Multi-IMSI SIM cards get all slots provisioned atomically in a single transaction.",
    },
    {
      color: C.iceBlue,
      title: "Cloud-Native from the Ground Up",
      body:  "Kubernetes-native with Helm charts, CloudNativePG, PgBouncer, Prometheus, and Grafana. Scales independently per-region, per-service.",
    },
    {
      color: C.amber,
      title: "Enterprise-Scale Operations",
      body:  "443 regression tests, bulk provisioning of 100K profiles per job, per-row error accumulation, and full audit trail for compliance.",
    },
  ];

  takeaways.forEach((t, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.4  + col * (CW + 0.5);
    const y = 1.05 + row * (CH + 0.2);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: CH, fill: { color: C.bgDark }, line: { color: t.color, width: 1.2 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: CW, h: 0.07, fill: { color: t.color }, line: { color: t.color } });
    // USER-APPROVED: title=16pt bold  body=14pt
    s.addText(t.title, { x: x + 0.18, y: y + 0.16, w: CW - 0.3, h: 0.46, fontSize: 16, bold: true, color: C.white, margin: 0 });
    s.addText(t.body,  { x: x + 0.18, y: y + 0.72, w: CW - 0.3, h: CH - 0.88, fontSize: 14, color: C.iceBlue, margin: 0 });
  });

  s.addShape(pres.shapes.LINE, { x: 0.4, y: 7.1, w: W - 0.8, h: 0, line: { color: C.darkGray, width: 0.5 } });
  s.addText("aaa-cloud-native  |  Platform Engineering  |  April 2026", { x: 0.4, y: 7.13, w: W - 0.8, h: 0.25, fontSize: 9, color: C.muted, align: "center", margin: 0 });
}

// ── Write file ────────────────────────────────────────────────────────────────
const OUT = process.argv[2] || "docs/aaa-platform-presentation.pptx";
pres.writeFile({ fileName: OUT }).then(() => {
  console.log(`✓  ${OUT}  (14 slides)`);
});
