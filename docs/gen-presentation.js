// AAA Cloud-Native Platform - Executive Presentation
// Palette: Midnight Executive - Navy primary, Ice blue secondary
const pptxgen = require("pptxgenjs");
const NODE_MOD = "/c/Users/rony.idan/AppData/Roaming/npm/node_modules";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.title = "AAA Cloud-Native Platform";
pres.author = "Platform Engineering";

// ── Color palette ──────────────────────────────────────────────────────────
const C = {
  navy:     "1E2761",   // Primary dark bg
  blue:     "2E75B6",   // Mid blue
  iceBlue:  "CADCFC",   // Light accent
  skyBlue:  "7EA8E8",   // Softer blue
  white:    "FFFFFF",
  offWhite: "F4F7FE",
  gray:     "8FA1BD",
  darkGray: "3C4D6B",
  green:    "2ECC8C",   // Success / positive
  amber:    "F5A623",   // Warning / highlight
  coral:    "E05C5C",   // Danger / critical
  bgLight:  "EEF3FB",   // Light slide bg
  cardBg:   "FFFFFF",
  accent:   "4FC3F7",   // Bright accent
};

// ── Helpers ────────────────────────────────────────────────────────────────
const W = 10, H = 5.625;

function darkSlide(slide) {
  slide.background = { color: C.navy };
}

function lightSlide(slide) {
  slide.background = { color: C.bgLight };
}

// Title bar on light slides
function titleBar(slide, text, sub) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.85, fill: { color: C.navy }, line: { color: C.navy } });
  slide.addText(text, { x: 0.4, y: 0, w: W - 0.8, h: 0.85, fontSize: 22, bold: true, color: C.white, valign: "middle", margin: 0 });
  if (sub) {
    slide.addText(sub, { x: 0.4, y: 0.85, w: W - 0.8, h: 0.38, fontSize: 13, color: C.blue, italic: true });
  }
}

// Small decorative pill label
function pill(slide, text, x, y, w, bg, textColor) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: w || 1.4, h: 0.26, fill: { color: bg || C.blue }, rectRadius: 0.13, line: { color: bg || C.blue } });
  slide.addText(text, { x, y, w: w || 1.4, h: 0.26, fontSize: 9, bold: true, color: textColor || C.white, align: "center", valign: "middle", margin: 0 });
}

// Card with left accent border
function accentCard(slide, x, y, w, h, title, body, accentColor) {
  const ac = accentColor || C.blue;
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.white }, shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.08 }, line: { color: "E2E8F0", width: 0.5 } });
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color: ac }, line: { color: ac } });
  if (title) slide.addText(title, { x: x + 0.14, y: y + 0.1, w: w - 0.2, h: 0.28, fontSize: 12, bold: true, color: C.navy, margin: 0 });
  if (body) slide.addText(body, { x: x + 0.14, y: y + (title ? 0.38 : 0.12), w: w - 0.2, h: h - (title ? 0.48 : 0.24), fontSize: 11, color: C.darkGray, margin: 0 });
}

// Stat callout box
function statBox(slide, x, y, value, label, bg, textColor) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w: 1.9, h: 1.2, fill: { color: bg || C.blue }, line: { color: bg || C.blue }, shadow: { type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.12 } });
  slide.addText(value, { x, y: y + 0.1, w: 1.9, h: 0.65, fontSize: 36, bold: true, color: textColor || C.white, align: "center", valign: "middle", margin: 0 });
  slide.addText(label, { x, y: y + 0.75, w: 1.9, h: 0.35, fontSize: 10, color: textColor || C.iceBlue, align: "center", valign: "middle", margin: 0 });
}

// Flow step arrow
function flowStep(slide, x, y, w, h, num, label, detail, bg) {
  const fillColor = bg || C.blue;
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fillColor }, line: { color: fillColor }, shadow: { type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
  slide.addShape(pres.shapes.OVAL, { x: x + 0.08, y: y + 0.08, w: 0.3, h: 0.3, fill: { color: C.white }, line: { color: C.white } });
  slide.addText(num, { x: x + 0.08, y: y + 0.08, w: 0.3, h: 0.3, fontSize: 10, bold: true, color: fillColor, align: "center", valign: "middle", margin: 0 });
  if (label) slide.addText(label, { x: x + 0.08, y: y + 0.44, w: w - 0.16, h: 0.26, fontSize: 10, bold: true, color: C.white, align: "center", margin: 0 });
  if (detail) slide.addText(detail, { x: x + 0.08, y: y + 0.7, w: w - 0.16, h: h - 0.78, fontSize: 9, color: C.iceBlue, align: "center", margin: 0 });
}

// Section divider line
function sectionLine(slide, y) {
  slide.addShape(pres.shapes.LINE, { x: 0.4, y, w: W - 0.8, h: 0, line: { color: C.iceBlue, width: 0.5 } });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 1 — TITLE
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkSlide(s);

  // Large geometric background shapes
  s.addShape(pres.shapes.RECTANGLE, { x: 6.5, y: -0.3, w: 4.5, h: H + 0.6, fill: { color: "172055", transparency: 40 }, line: { color: "172055" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.2, y: -0.3, w: 3.5, h: H + 0.6, fill: { color: "0D1844", transparency: 40 }, line: { color: "0D1844" } });

  // Accent corner bar (top-left)
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.12, h: H, fill: { color: C.accent }, line: { color: C.accent } });

  // Top tag
  pill(s, "TELECOM  |  AAA  |  CLOUD-NATIVE", 0.3, 0.4, 3.5, C.darkGray, C.iceBlue);

  // Title
  s.addText("AAA Cloud-Native", { x: 0.3, y: 1.1, w: 6.5, h: 1.0, fontSize: 42, bold: true, color: C.white, fontFace: "Calibri" });
  s.addText("Platform", { x: 0.3, y: 1.95, w: 6.5, h: 0.9, fontSize: 42, bold: true, color: C.accent, fontFace: "Calibri" });

  // Subtitle
  s.addText("High-Performance Subscriber Provisioning\n& Real-Time RADIUS Authentication", { x: 0.3, y: 2.9, w: 6.2, h: 0.8, fontSize: 16, color: C.skyBlue, fontFace: "Calibri" });

  // Three pillars
  const pillars = [
    { label: "< 15ms", sub: "p99 Lookup SLA" },
    { label: "100K+", sub: "Bulk Profiles/Job" },
    { label: "Multi-IMSI", sub: "Auto-Provisioning" },
  ];
  pillars.forEach((p, i) => {
    const x = 0.3 + i * 2.1;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 4.0, w: 1.9, h: 0.9, fill: { color: "142050" }, line: { color: C.blue } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 4.0, w: 1.9, h: 0.06, fill: { color: C.accent }, line: { color: C.accent } });
    s.addText(p.label, { x, y: 4.1, w: 1.9, h: 0.4, fontSize: 16, bold: true, color: C.white, align: "center", margin: 0 });
    s.addText(p.sub, { x, y: 4.5, w: 1.9, h: 0.35, fontSize: 9, color: C.skyBlue, align: "center", margin: 0 });
  });

  // Right side - floating tech labels
  const labels = ["C++17 / Drogon", "Python / FastAPI", "PostgreSQL 15", "Kubernetes / Helm", "Prometheus / Grafana"];
  labels.forEach((l, i) => {
    s.addText(l, { x: 7.4, y: 1.0 + i * 0.62, w: 2.4, h: 0.35, fontSize: 12, color: C.iceBlue, italic: true, align: "left", margin: 0 });
    s.addShape(pres.shapes.LINE, { x: 7.3, y: 1.175 + i * 0.62, w: 0.08, h: 0, line: { color: C.accent, width: 2 } });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 2 — THE PROBLEM
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkSlide(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.7, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("The Challenge", { x: 0.4, y: 0, w: 6, h: 0.7, fontSize: 22, bold: true, color: C.white, valign: "middle", margin: 0 });

  const probs = [
    { t: "Speed vs. Scale", d: "RADIUS must authenticate subscribers in <15ms while serving millions of requests per day — but provisioning writes are slower and less frequent." },
    { t: "Unknown IMSIs at First Attach", d: "Network equipment cannot predict when a new SIM activates. Operators need dynamic, zero-touch provisioning on first connection — no manual intervention." },
    { t: "Multi-IMSI SIM Complexity", d: "A single physical SIM card can carry up to 10 distinct IMSIs. Provisioning one slot must automatically provision all sibling slots in a single atomic step." },
    { t: "IP Pool Race Conditions", d: "Concurrent first-connection events can race to claim the same IP address. A safe, lock-free allocation mechanism is critical for correctness at scale." },
  ];

  probs.forEach((p, i) => {
    const col = i < 2 ? 0 : 1;
    const row = i % 2;
    const x = 0.4 + col * 4.8;
    const y = 0.95 + row * 2.05;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.8, fill: { color: "172055" }, line: { color: C.blue, width: 0.5 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h: 1.8, fill: { color: C.amber }, line: { color: C.amber } });
    s.addText(p.t, { x: x + 0.14, y: y + 0.1, w: 4.1, h: 0.3, fontSize: 13, bold: true, color: C.white, margin: 0 });
    s.addText(p.d, { x: x + 0.14, y: y + 0.42, w: 4.1, h: 1.25, fontSize: 11.5, color: C.skyBlue, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 3 — SOLUTION OVERVIEW
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Solution: Three-Service Architecture", "aaa-radius-server orchestrates two independent backend services optimized for their workloads");

  // ── Top: aaa-radius-server entry-point box ──
  s.addShape(pres.shapes.RECTANGLE, { x: 2.7, y: 1.05, w: 4.6, h: 0.82, fill: { color: C.navy }, line: { color: C.navy }, shadow: { type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.12 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 2.7, y: 1.05, w: 4.6, h: 0.06, fill: { color: C.amber }, line: { color: C.amber } });
  s.addText("aaa-radius-server", { x: 2.7, y: 1.11, w: 4.6, h: 0.42, fontSize: 18, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
  s.addText("RADIUS Frontend  |  Receives Access-Requests from network equipment", { x: 2.7, y: 1.53, w: 4.6, h: 0.3, fontSize: 10, color: C.iceBlue, align: "center", margin: 0 });

  // Arrow down-left to lookup
  s.addShape(pres.shapes.LINE, { x: 3.15, y: 1.87, w: 0, h: 0.48, line: { color: C.blue, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: 1.9, y: 2.35, w: 1.25, h: 0, line: { color: C.blue, width: 1.5 } });
  s.addText("Stage 1: GET /lookup (every request)", { x: 0.4, y: 2.1, w: 2.6, h: 0.35, fontSize: 8.5, color: C.blue, italic: true, align: "center" });

  // Arrow down-right to profile-api
  s.addShape(pres.shapes.LINE, { x: 6.85, y: 1.87, w: 0, h: 0.48, line: { color: C.amber, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: 6.85, y: 2.35, w: 1.25, h: 0, line: { color: C.amber, width: 1.5 } });
  s.addText("Stage 2: POST /first-connection (on 404 only)", { x: 7.0, y: 2.1, w: 2.8, h: 0.35, fontSize: 8.5, color: C.amber, italic: true, align: "center" });

  // Central separator below the top box
  s.addShape(pres.shapes.LINE, { x: W / 2, y: 2.4, w: 0, h: H - 2.7, line: { color: C.iceBlue, width: 1, dashType: "dash" } });

  // Left side — READ PATH
  s.addText("READ PATH", { x: 0.4, y: 2.45, w: 4.4, h: 0.32, fontSize: 10, bold: true, color: C.blue, charSpacing: 2 });
  s.addText("aaa-lookup-service", { x: 0.4, y: 2.77, w: 4.4, h: 0.4, fontSize: 18, bold: true, color: C.navy });
  s.addText("C++17 / Drogon — Port 8081", { x: 0.4, y: 3.17, w: 4.4, h: 0.28, fontSize: 11, color: C.blue, italic: true });

  const readFeats = [
    "Sub-15ms p99 hot-path (called on every Access-Request)",
    "Reads from local read-replica only (no writes)",
    "Single-query IMSI lookup, index-only seek",
    "JWT RS256 verification with caching",
    "Returns 404 to trigger first-connection flow",
  ];
  s.addText(readFeats.map(f => ({ text: f, options: { bullet: true, breakLine: true } })), { x: 0.4, y: 3.5, w: 4.4, h: 1.85, fontSize: 11, color: C.darkGray, paraSpaceAfter: 3 });

  // Right side — WRITE PATH
  s.addText("WRITE PATH", { x: 5.2, y: 2.45, w: 4.4, h: 0.32, fontSize: 10, bold: true, color: C.blue, charSpacing: 2 });
  s.addText("subscriber-profile-api", { x: 5.2, y: 2.77, w: 4.4, h: 0.4, fontSize: 16, bold: true, color: C.navy });
  s.addText("Python 3.11 / FastAPI — Port 8080", { x: 5.2, y: 3.17, w: 4.4, h: 0.28, fontSize: 11, color: C.blue, italic: true });

  const writeFeats = [
    "First-connection: allocates IP + creates profile on 404",
    "Full subscriber lifecycle CRUD",
    "Multi-IMSI atomic provisioning",
    "Race-safe IP pool claiming (FOR UPDATE SKIP LOCKED)",
    "Async bulk operations up to 100K profiles/job",
  ];
  s.addText(writeFeats.map(f => ({ text: f, options: { bullet: true, breakLine: true } })), { x: 5.2, y: 3.5, w: 4.4, h: 1.85, fontSize: 11, color: C.darkGray, paraSpaceAfter: 3 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 4 — PERFORMANCE NUMBERS
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkSlide(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.7, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("Performance at a Glance", { x: 0.4, y: 0, w: 9, h: 0.7, fontSize: 22, bold: true, color: C.white, valign: "middle", margin: 0 });

  // Big stats row
  const stats = [
    { v: "< 15ms", l: "p99 Lookup Latency", bg: C.blue },
    { v: "1-3ms", l: "p50 Typical Latency", bg: "1A5C9E" },
    { v: "100K", l: "Profiles per Bulk Job", bg: "155A8A" },
    { v: "253", l: "IPs per /24 Pool", bg: "114C75" },
    { v: "10", l: "Max IMSIs per SIM", bg: "0D3D60" },
  ];
  stats.forEach((st, i) => {
    const x = 0.35 + i * 1.88;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 0.95, w: 1.75, h: 1.35, fill: { color: st.bg }, line: { color: st.bg }, shadow: { type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.2 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 0.95, w: 1.75, h: 0.06, fill: { color: C.accent }, line: { color: C.accent } });
    s.addText(st.v, { x, y: 1.05, w: 1.75, h: 0.7, fontSize: 28, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(st.l, { x, y: 1.75, w: 1.75, h: 0.45, fontSize: 9.5, color: C.iceBlue, align: "center", margin: 0 });
  });

  // Performance details
  s.addText("How we achieve < 15ms", { x: 0.4, y: 2.55, w: 9, h: 0.35, fontSize: 14, bold: true, color: C.accent, margin: 0 });

  const perf = [
    { t: "Index-only B-tree seek", d: "subscriber_imsis.imsi is a PK — single-page lookup, no full-table scan" },
    { t: "Near 100% cache hit", d: "~80MB index fits entirely in PostgreSQL shared_buffers at steady state" },
    { t: "Async C++ Drogon", d: "Non-blocking I/O with coroutines; zero context-switching overhead per request" },
    { t: "Read replica isolation", d: "Lookup never competes with write transactions on the primary" },
  ];
  perf.forEach((p, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * 4.8;
    const y = 3.0 + row * 1.05;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 0.88, fill: { color: "172055" }, line: { color: C.blue, width: 0.5 } });
    s.addText(p.t, { x: x + 0.14, y: y + 0.05, w: 4.1, h: 0.28, fontSize: 11, bold: true, color: C.white, margin: 0 });
    s.addText(p.d, { x: x + 0.14, y: y + 0.33, w: 4.1, h: 0.48, fontSize: 10.5, color: C.skyBlue, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 5 — RADIUS HOT PATH FLOW
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "RADIUS Hot-Path Flow (Happy Path)", "Steady-state: every Access-Request handled entirely by aaa-lookup-service");

  // Actors
  const actors = [
    { label: "aaa-radius-server", x: 0.25 },
    { label: "aaa-lookup-\nservice\n(C++, port 8081)", x: 2.7 },
    { label: "Read Replica\n(PostgreSQL)", x: 5.15 },
  ];

  actors.forEach(a => {
    s.addShape(pres.shapes.RECTANGLE, { x: a.x, y: 1.1, w: 1.85, h: 0.8, fill: { color: C.navy }, line: { color: C.navy }, shadow: { type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.15 } });
    s.addText(a.label, { x: a.x, y: 1.1, w: 1.85, h: 0.8, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.LINE, { x: a.x + 0.925, y: 1.9, w: 0, h: 3.2, line: { color: C.blue, width: 0.5, dashType: "dash" } });
  });

  // Arrows and labels
  const arrows = [
    { fx: 0.25 + 0.925, tx: 2.7 + 0.925, y: 2.1, label: "GET /lookup?imsi=278773000002002&apn=internet.op.com", above: true },
    { fx: 2.7 + 0.925, tx: 5.15 + 0.925, y: 2.65, label: "SELECT ... WHERE imsi = $1  (index seek)", above: true },
    { fx: 5.15 + 0.925, tx: 2.7 + 0.925, y: 3.15, label: "Row: static_ip = 100.65.120.5", above: true, dashed: true },
    { fx: 2.7 + 0.925, tx: 0.25 + 0.925, y: 3.65, label: "200 OK  {\"static_ip\": \"100.65.120.5\"}", above: true, dashed: true },
  ];

  arrows.forEach(a => {
    const dir = a.tx > a.fx;
    s.addShape(pres.shapes.LINE, { x: Math.min(a.fx, a.tx), y: a.y, w: Math.abs(a.tx - a.fx), h: 0, line: { color: dir ? C.blue : C.green, width: 1.5, dashType: a.dashed ? "dash" : "solid" } });
    // Arrowhead approximation
    const arrowX = dir ? a.tx - 0.04 : a.tx + 0.04;
    s.addText(dir ? "▶" : "◀", { x: arrowX - 0.1, y: a.y - 0.14, w: 0.2, h: 0.28, fontSize: 9, color: dir ? C.blue : C.green, align: "center", margin: 0 });
    s.addText(a.label, { x: Math.min(a.fx, a.tx) + 0.05, y: a.y - 0.32, w: Math.abs(a.tx - a.fx) - 0.1, h: 0.28, fontSize: 9.5, color: dir ? C.navy : C.blue, italic: !dir, align: "center", margin: 0 });
  });

  // Right side result cards
  const results = [
    { code: "200", txt: "Access-Accept + Framed-IP-Address", bg: C.green, tc: C.white },
    { code: "403", txt: "Access-Reject (suspended)", bg: C.amber, tc: C.white },
    { code: "404", txt: "Triggers Stage 2 first-connection", bg: C.coral, tc: C.white },
  ];
  s.addText("Possible Outcomes", { x: 7.2, y: 1.05, w: 2.5, h: 0.3, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  results.forEach((r, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 7.2, y: 1.4 + i * 0.72, w: 2.5, h: 0.6, fill: { color: r.bg }, line: { color: r.bg } });
    s.addText(r.code, { x: 7.2, y: 1.4 + i * 0.72, w: 0.55, h: 0.6, fontSize: 14, bold: true, color: r.tc, align: "center", valign: "middle", margin: 0 });
    s.addText(r.txt, { x: 7.75, y: 1.4 + i * 0.72, w: 1.95, h: 0.6, fontSize: 9.5, color: r.tc, valign: "middle", margin: 0 });
  });

  s.addText("SLA: p99 < 15ms end-to-end", { x: 7.2, y: 3.62, w: 2.5, h: 0.32, fontSize: 11, bold: true, color: C.blue, align: "center", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.2, y: 3.62, w: 2.5, h: 0.32, fill: { color: C.bgLight }, line: { color: C.blue, width: 1 } });
  s.addText("SLA: p99 < 15ms end-to-end", { x: 7.2, y: 3.62, w: 2.5, h: 0.32, fontSize: 11, bold: true, color: C.blue, align: "center", margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 6 — FIRST-CONNECTION ALLOCATION
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Two-Stage First-Connection Allocation", "Unknown IMSI → auto-provisioned in a single atomic transaction");

  // Stage 1 box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.05, w: 4.4, h: 1.75, fill: { color: C.navy }, line: { color: C.navy }, shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
  pill(s, "STAGE 1", 0.4, 1.1, 1.2, C.blue, C.white);
  s.addText("aaa-lookup-service", { x: 0.4, y: 1.42, w: 4.1, h: 0.32, fontSize: 13, bold: true, color: C.white, margin: 0 });
  s.addText([
    { text: "GET /lookup?imsi={imsi}&apn={apn}", options: { breakLine: true } },
    { text: "→ Queries READ REPLICA", options: { breakLine: true } },
    { text: "→ IMSI not found in subscriber_imsis", options: { breakLine: true } },
    { text: "→ Returns 404 {\"error\": \"not_found\"}", options: {} },
  ], { x: 0.4, y: 1.78, w: 4.1, h: 0.9, fontSize: 10.5, color: C.iceBlue, fontFace: "Courier New", margin: 0 });

  // Arrow down
  s.addText("▼  aaa-radius-server falls through to Stage 2", { x: 0.4, y: 2.88, w: 4.4, h: 0.3, fontSize: 10.5, bold: true, color: C.amber, align: "center", margin: 0 });

  // Stage 2 box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.22, w: 4.4, h: 2.1, fill: { color: C.navy }, line: { color: C.navy }, shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
  pill(s, "STAGE 2", 0.4, 3.27, 1.2, C.green, C.white);
  s.addText("subscriber-profile-api", { x: 0.4, y: 3.59, w: 4.1, h: 0.32, fontSize: 13, bold: true, color: C.white, margin: 0 });
  s.addText([
    { text: "POST /v1/first-connection {imsi, apn, imei}", options: { breakLine: true } },
    { text: "1. Idempotency check: IMSI already exists?", options: { breakLine: true } },
    { text: "2. Match range config (f_imsi <= $imsi <= t_imsi)", options: { breakLine: true } },
    { text: "3. Claim IP:  DELETE FROM ip_pool_available", options: { breakLine: true } },
    { text: "   FOR UPDATE SKIP LOCKED", options: { breakLine: true } },
    { text: "4. INSERT profile + IMSI + IP  (atomic COMMIT)", options: {} },
  ], { x: 0.4, y: 3.95, w: 4.1, h: 1.3, fontSize: 9.5, color: C.iceBlue, fontFace: "Courier New", margin: 0 });

  // Right side — outcome cards (Stage 2 results from subscriber-profile-api)
  s.addText("Stage 2 Outcomes  (subscriber-profile-api)", { x: 5.1, y: 1.05, w: 4.5, h: 0.28, fontSize: 10, bold: true, color: C.blue, margin: 0 });

  const cards = [
    { title: "200 OK — IP Allocated", body: "subscriber-profile-api creates device_id\n(gen_random_uuid). static_ip returned.\naaa-radius-server issues Access-Accept.", bg: "E8F5E9", border: C.green },
    { title: "200 OK — Idempotent Return", body: "IMSI already existed in DB.\nSame device_id & IP returned.\nSafe to retry — no duplicates.", bg: "E3F2FD", border: C.blue },
    { title: "404 — No Range Config", body: "IMSI not in any active range config.\naaa-radius-server issues Access-Reject.", bg: "FFF3E0", border: C.amber },
    { title: "503 — Pool Exhausted", body: "No available IPs remaining.\nCreate a new pool.\nAlert fires automatically.", bg: "FFEBEE", border: C.coral },
  ];
  cards.forEach((c, i) => {
    const y = 1.38 + i * 1.05;
    s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y, w: 4.5, h: 0.95, fill: { color: c.bg }, line: { color: c.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y, w: 0.06, h: 0.95, fill: { color: c.border }, line: { color: c.border } });
    s.addText(c.title, { x: 5.22, y: y + 0.05, w: 4.25, h: 0.28, fontSize: 11.5, bold: true, color: C.navy, margin: 0 });
    s.addText(c.body, { x: 5.22, y: y + 0.33, w: 4.25, h: 0.56, fontSize: 10, color: C.darkGray, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 7 — MULTI-IMSI SIM PROVISIONING
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Multi-IMSI SIM: Zero-Touch Provisioning", "One IP allocated per card; all sibling slots pre-provisioned in a single transaction");

  // SIM card visual (left)
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.3, y: 1.15, w: 2.5, h: 3.5, fill: { color: C.navy }, rectRadius: 0.15, line: { color: C.blue } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 1.55, w: 2.0, h: 0.4, fill: { color: "D4AF37" }, line: { color: "D4AF37" } }); // Gold chip
  s.addText("SIM Card", { x: 0.3, y: 2.05, w: 2.5, h: 0.3, fontSize: 11, bold: true, color: C.white, align: "center", margin: 0 });
  const slots = ["Slot 1: IMSI 278770...042", "Slot 2: IMSI 278771...042"];
  slots.forEach((sl, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.45, y: 2.45 + i * 0.65, w: 2.2, h: 0.52, fill: { color: C.darkGray }, line: { color: C.accent, width: 0.5 } });
    s.addText(sl, { x: 0.45, y: 2.45 + i * 0.65, w: 2.2, h: 0.52, fontSize: 9, color: C.white, align: "center", valign: "middle", margin: 0 });
  });
  s.addText("ICCID: 8944...042", { x: 0.3, y: 4.0, w: 2.5, h: 0.3, fontSize: 9, color: C.skyBlue, align: "center", italic: true, margin: 0 });

  // Steps
  const steps = [
    { num: "1", title: "Slot 1 First Attach", detail: "GET /lookup → 404\nPOST /first-connection\n{imsi: \"278770...042\"}" },
    { num: "2", title: "Compute Offset", detail: "offset = 278770...042\n       - 278770...000\n= 42" },
    { num: "3", title: "Derive ICCID", detail: "8944...000\n+ 42\n= 8944...042" },
    { num: "4", title: "Atomic Transaction", detail: "1 IP allocated from pool\nSlot 1 + Slot 2 both INSERTed\nSingle COMMIT" },
    { num: "5", title: "Slot 2 Connects Later", detail: "GET /lookup → 200\n(pre-provisioned!)\nStage 2 never runs" },
  ];
  steps.forEach((st, i) => {
    const x = 3.1 + i * 1.35;
    const bgColors = [C.blue, "1A5C9E", "155A8A", C.green, "28A870"];
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.15, w: 1.2, h: 3.5, fill: { color: bgColors[i] }, line: { color: bgColors[i] }, shadow: { type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.45, y: 1.22, w: 0.3, h: 0.3, fill: { color: C.white }, line: { color: C.white } });
    s.addText(st.num, { x: x + 0.45, y: 1.22, w: 0.3, h: 0.3, fontSize: 11, bold: true, color: bgColors[i], align: "center", valign: "middle", margin: 0 });
    s.addText(st.title, { x: x + 0.06, y: 1.6, w: 1.08, h: 0.5, fontSize: 10, bold: true, color: C.white, align: "center", margin: 0 });
    s.addText(st.detail, { x: x + 0.06, y: 2.16, w: 1.08, h: 2.35, fontSize: 8.5, color: C.iceBlue, align: "center", fontFace: "Courier New", margin: 0 });
  });

  // Key insight
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 4.85, w: W - 0.6, h: 0.52, fill: { color: C.navy }, line: { color: C.accent, width: 1 } });
  s.addText("Key: ONE IP allocated per physical card, regardless of IMSI count. All slots share the same IP address.", { x: 0.5, y: 4.85, w: W - 1.0, h: 0.52, fontSize: 11.5, bold: true, color: C.white, valign: "middle", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 4.85, w: 0.06, h: 0.52, fill: { color: C.accent }, line: { color: C.accent } });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 8 — DATA MODEL
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Data Model: 8 PostgreSQL Tables", "Three logical groups — subscriber data, IP pools, and range configurations");

  // Group 1 — Subscriber
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.1, w: 3.1, h: 0.32, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText("SUBSCRIBER DATA", { x: 0.3, y: 1.1, w: 3.1, h: 0.32, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, charSpacing: 2 });

  const subTables = [
    { name: "subscriber_profiles", pk: "device_id (UUID)", desc: "One row per SIM card" },
    { name: "subscriber_imsis", pk: "imsi (15 digits)", desc: "One row per IMSI" },
    { name: "subscriber_apn_ips", pk: "id (BIGINT)", desc: "IMSI-level IP assignments" },
    { name: "subscriber_iccid_ips", pk: "id (BIGINT)", desc: "Card-level IP assignments" },
  ];
  subTables.forEach((t, i) => {
    const y = 1.48 + i * 0.72;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y, w: 3.1, h: 0.62, fill: { color: i % 2 === 0 ? C.white : C.bgLight }, line: { color: "D0D8E8", width: 0.5 } });
    s.addText(t.name, { x: 0.42, y: y + 0.04, w: 2.86, h: 0.24, fontSize: 10, bold: true, color: C.navy, fontFace: "Courier New", margin: 0 });
    s.addText(`PK: ${t.pk}  |  ${t.desc}`, { x: 0.42, y: y + 0.3, w: 2.86, h: 0.22, fontSize: 9, color: C.gray, margin: 0 });
  });

  // Group 2 — IP Pools
  s.addShape(pres.shapes.RECTANGLE, { x: 3.65, y: 1.1, w: 2.9, h: 0.32, fill: { color: "155A8A" }, line: { color: "155A8A" } });
  s.addText("IP POOLS", { x: 3.65, y: 1.1, w: 2.9, h: 0.32, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, charSpacing: 2 });

  const poolTables = [
    { name: "ip_pools", pk: "pool_id (UUID)", desc: "Pool definition (CIDR, bounds)" },
    { name: "ip_pool_available", pk: "(pool_id, ip)", desc: "Available IP work-queue" },
  ];
  poolTables.forEach((t, i) => {
    const y = 1.48 + i * 0.72;
    s.addShape(pres.shapes.RECTANGLE, { x: 3.65, y, w: 2.9, h: 0.62, fill: { color: i % 2 === 0 ? C.white : C.bgLight }, line: { color: "D0D8E8", width: 0.5 } });
    s.addText(t.name, { x: 3.77, y: y + 0.04, w: 2.66, h: 0.24, fontSize: 10, bold: true, color: C.navy, fontFace: "Courier New", margin: 0 });
    s.addText(`PK: ${t.pk}  |  ${t.desc}`, { x: 3.77, y: y + 0.3, w: 2.66, h: 0.22, fontSize: 9, color: C.gray, margin: 0 });
  });

  // Group 3 — Configs
  s.addShape(pres.shapes.RECTANGLE, { x: 6.8, y: 1.1, w: 2.9, h: 0.32, fill: { color: "0D3D60" }, line: { color: "0D3D60" } });
  s.addText("RANGE CONFIGS", { x: 6.8, y: 1.1, w: 2.9, h: 0.32, fontSize: 10, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, charSpacing: 2 });

  const confTables = [
    { name: "imsi_range_configs", pk: "id (BIGINT)", desc: "IMSI ranges for auto-prov" },
    { name: "iccid_range_configs", pk: "id (BIGINT)", desc: "Multi-IMSI SIM parent" },
    { name: "bulk_jobs", pk: "job_id (UUID)", desc: "Async bulk job tracking" },
  ];
  confTables.forEach((t, i) => {
    const y = 1.48 + i * 0.72;
    s.addShape(pres.shapes.RECTANGLE, { x: 6.8, y, w: 2.9, h: 0.62, fill: { color: i % 2 === 0 ? C.white : C.bgLight }, line: { color: "D0D8E8", width: 0.5 } });
    s.addText(t.name, { x: 6.92, y: y + 0.04, w: 2.66, h: 0.24, fontSize: 10, bold: true, color: C.navy, fontFace: "Courier New", margin: 0 });
    s.addText(`PK: ${t.pk}  |  ${t.desc}`, { x: 6.92, y: y + 0.3, w: 2.66, h: 0.22, fontSize: 9, color: C.gray, margin: 0 });
  });

  // IP resolution box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 4.4, w: W - 0.6, h: 0.95, fill: { color: C.bgLight }, line: { color: C.blue, width: 0.8 } });
  s.addText("ip_resolution modes:", { x: 0.5, y: 4.45, w: 2.0, h: 0.28, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const modes = [
    { m: "imsi", d: "IP per IMSI, all APNs" },
    { m: "imsi_apn", d: "IP per IMSI per APN" },
    { m: "iccid", d: "IP per card, all APNs" },
    { m: "iccid_apn", d: "IP per card per APN" },
  ];
  modes.forEach((m, i) => {
    const x = 2.0 + i * 1.95;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 4.45, w: 1.8, h: 0.82, fill: { color: C.navy }, line: { color: C.blue, width: 0.5 } });
    s.addText(m.m, { x, y: 4.48, w: 1.8, h: 0.32, fontSize: 10, bold: true, color: C.accent, align: "center", fontFace: "Courier New", margin: 0 });
    s.addText(m.d, { x, y: 4.8, w: 1.8, h: 0.4, fontSize: 9, color: C.iceBlue, align: "center", margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 9 — API OVERVIEW
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "subscriber-profile-api: REST API Surface", "Full lifecycle management with JWT authentication (OAuth 2.0 Bearer)");

  const groups = [
    {
      title: "Subscriber Profiles", color: C.blue,
      endpoints: ["POST /v1/profiles", "GET /v1/profiles/{id}", "GET /v1/profiles?iccid={}", "PATCH /v1/profiles/{id}", "DELETE /v1/profiles/{id}"],
    },
    {
      title: "IMSI Operations", color: "155A8A",
      endpoints: ["GET /v1/profiles/{id}/imsis", "POST /v1/profiles/{id}/imsis", "PATCH .../imsis/{imsi}", "DELETE .../imsis/{imsi}"],
    },
    {
      title: "IP Pools", color: "0D3D60",
      endpoints: ["POST /v1/pools", "GET /v1/pools/{id}/stats", "PATCH /v1/pools/{id}", "DELETE /v1/pools/{id}"],
    },
    {
      title: "Range Configs", color: "1A5C9E",
      endpoints: ["POST /v1/range-configs", "POST /v1/iccid-range-configs", ".../imsi-slots (multi-IMSI)", "PATCH / DELETE both types"],
    },
    {
      title: "First-Connection", color: C.green,
      endpoints: ["POST /v1/first-connection", "→ Idempotent allocation", "→ Returns device_id + IP", "→ 503 if pool exhausted"],
    },
    {
      title: "Bulk & Jobs", color: C.amber,
      endpoints: ["POST /v1/profiles/bulk (JSON)", "POST /v1/profiles/bulk (CSV)", "GET /v1/jobs/{job_id}", "→ queued / processing / done"],
    },
  ];

  groups.forEach((g, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 0.3 + col * 3.2;
    const y = 1.1 + row * 2.15;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 3.0, h: 0.32, fill: { color: g.color }, line: { color: g.color } });
    s.addText(g.title, { x, y, w: 3.0, h: 0.32, fontSize: 10.5, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    g.endpoints.forEach((ep, j) => {
      const ey = y + 0.38 + j * 0.38;
      s.addShape(pres.shapes.RECTANGLE, { x, y: ey, w: 3.0, h: 0.34, fill: { color: j % 2 === 0 ? C.white : C.bgLight }, line: { color: "D0D8E8", width: 0.5 } });
      s.addText(ep, { x: x + 0.1, y: ey + 0.02, w: 2.8, h: 0.3, fontSize: 9.5, color: C.navy, fontFace: "Courier New", valign: "middle", margin: 0 });
    });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 10 — BULK OPERATIONS
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Bulk Provisioning: Async Job Processing", "Up to 100,000 profiles per job — JSON or CSV, never blocks the API");

  // Flow steps
  const steps = [
    { n: "1", t: "Submit", d: "POST /v1/profiles/bulk\nJSON array or CSV file\n(up to 100K profiles)" },
    { n: "2", t: "202 Accepted", d: "Returns job_id immediately\nNo waiting — fully async\nstatus_url provided" },
    { n: "3", t: "Thread Pool", d: "BULK_WORKER_THREADS (default 2)\nProcesses in batches of 1,000\nINSERT ON CONFLICT (upsert)" },
    { n: "4", t: "Poll Status", d: "GET /v1/jobs/{job_id}\nqueued → processing → completed\nprocessed + failed + errors[]" },
  ];
  const stepColors = [C.blue, "155A8A", "0D3D60", C.green];
  steps.forEach((st, i) => {
    const x = 0.3 + i * 2.3;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.1, w: 2.1, h: 2.1, fill: { color: stepColors[i] }, line: { color: stepColors[i] }, shadow: { type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.9, y: 1.18, w: 0.3, h: 0.3, fill: { color: C.white }, line: { color: C.white } });
    s.addText(st.n, { x: x + 0.9, y: 1.18, w: 0.3, h: 0.3, fontSize: 11, bold: true, color: stepColors[i], align: "center", valign: "middle", margin: 0 });
    s.addText(st.t, { x: x + 0.08, y: 1.56, w: 1.94, h: 0.32, fontSize: 13, bold: true, color: C.white, align: "center", margin: 0 });
    s.addText(st.d, { x: x + 0.08, y: 1.92, w: 1.94, h: 1.15, fontSize: 10.5, color: C.iceBlue, align: "center", margin: 0 });
    if (i < 3) {
      s.addText("→", { x: x + 2.1, y: 1.95, w: 0.2, h: 0.35, fontSize: 16, bold: true, color: C.blue, align: "center", margin: 0 });
    }
  });

  // Error handling highlight
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.42, w: 4.5, h: 1.85, fill: { color: C.bgLight }, line: { color: C.blue, width: 0.8 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.42, w: 0.06, h: 1.85, fill: { color: C.amber }, line: { color: C.amber } });
  s.addText("Error Handling", { x: 0.44, y: 3.5, w: 4.25, h: 0.3, fontSize: 12, bold: true, color: C.navy, margin: 0 });
  s.addText([
    { text: "Failed rows do not abort the job — errors are accumulated", options: { bullet: true, breakLine: true } },
    { text: "Each error contains: row number, field, message, bad value", options: { bullet: true, breakLine: true } },
    { text: "Job completes with processed=N, failed=M, errors=[...]", options: { bullet: true } },
  ], { x: 0.44, y: 3.85, w: 4.25, h: 1.3, fontSize: 11, color: C.darkGray, paraSpaceAfter: 6 });

  // Response example
  s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y: 3.42, w: 4.7, h: 1.85, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText("Example response (GET /v1/jobs/{id})", { x: 5.1, y: 3.5, w: 4.5, h: 0.28, fontSize: 9.5, color: C.skyBlue, margin: 0 });
  const codeLines = ['{"job_id": "abc123",', ' "status": "completed",', ' "processed": 4997,', ' "failed": 3,', ' "errors": [{', '   "row": 42, "field": "imsi",', '   "message": "Must be 15 digits"}]}'];
  codeLines.forEach((l, i) => {
    s.addText(l, { x: 5.1, y: 3.84 + i * 0.2, w: 4.5, h: 0.22, fontSize: 9, color: C.iceBlue, fontFace: "Courier New", margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 11 — OBSERVABILITY
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Observability & Monitoring", "Prometheus metrics, structured JSON logs, Grafana dashboards, auto-alerting");

  // Metrics table
  s.addText("Key Prometheus Metrics", { x: 0.3, y: 1.05, w: 4.5, h: 0.32, fontSize: 13, bold: true, color: C.navy, margin: 0 });

  const metrics = [
    ["lookup_latency_ms", "Histogram", "p50/p95/p99 per result label"],
    ["lookup_result_total", "Counter", "resolved / not_found / suspended"],
    ["first_connection_total", "Counter", "allocated / reused / pool_exhausted"],
    ["pool_exhausted_total", "Counter", "By pool_id — alert if rate > 0"],
    ["bulk_job_duration_seconds", "Histogram", "End-to-end bulk job time"],
    ["api_request_duration_ms", "Histogram", "All endpoints by method+path"],
  ];
  const mw = [2.8, 1.2, 2.4];
  const mHeaders = ["Metric Name", "Type", "Description"];
  s.addTable([
    mHeaders.map((h, i) => ({ text: h, options: { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, align: "center" } })),
    ...metrics.map((row, ri) => row.map((c, ci) => ({
      text: c,
      options: { fill: { color: ri % 2 === 0 ? C.white : C.bgLight }, color: C.navy, fontSize: 9.5, fontFace: ci === 0 ? "Courier New" : "Calibri" },
    }))),
  ], { x: 0.3, y: 1.4, w: 6.4, colW: mw, border: { pt: 0.5, color: "D0D8E8" } });

  // Alerts
  s.addText("Alerting Rules", { x: 6.8, y: 1.05, w: 2.9, h: 0.32, fontSize: 13, bold: true, color: C.navy, margin: 0 });

  const alerts = [
    { name: "p99 Latency High", cond: "> 15ms for 2+ min", sev: "PAGE", bg: C.coral },
    { name: "Pool Exhausted", cond: "rate > 0", sev: "ALERT", bg: C.amber },
    { name: "Not-Found Spike", cond: "> 5x baseline", sev: "ALERT", bg: C.amber },
    { name: "DB Primary Down", cond: "connection lost", sev: "PAGE", bg: C.coral },
  ];
  alerts.forEach((a, i) => {
    const y = 1.4 + i * 0.85;
    s.addShape(pres.shapes.RECTANGLE, { x: 6.8, y, w: 2.9, h: 0.75, fill: { color: C.bgLight }, line: { color: "D0D8E8", width: 0.5 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 9.5, y, w: 0.2, h: 0.75, fill: { color: a.bg }, line: { color: a.bg } });
    s.addText(a.name, { x: 6.9, y: y + 0.04, w: 2.5, h: 0.26, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
    s.addText(`Condition: ${a.cond}`, { x: 6.9, y: y + 0.32, w: 2.5, h: 0.35, fontSize: 9.5, color: C.darkGray, margin: 0 });
  });

  // Logging
  s.addText("Structured JSON Logging", { x: 0.3, y: 4.05, w: 9.4, h: 0.3, fontSize: 12, bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 4.4, w: 9.4, h: 0.92, fill: { color: C.navy }, line: { color: C.navy } });
  const logLine = '{ "ts":"2026-03-13T14:00:00Z", "imsi_hash":"278773..", "apn":"internet.op.com", "result":"resolved", "latency_ms":2.4, "ip_resolution":"imsi" }';
  s.addText(logLine, { x: 0.45, y: 4.5, w: 9.1, h: 0.72, fontSize: 9.5, color: C.iceBlue, fontFace: "Courier New", valign: "middle", margin: 0 });
  s.addText("Note: Raw IMSI is NEVER logged — SHA-256(imsi)[0:8] is used instead", { x: 0.45, y: 5.1, w: 9.1, h: 0.25, fontSize: 9, color: C.amber, italic: true, margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 12 — DEPLOYMENT
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Kubernetes Deployment Architecture", "Helm umbrella chart — all components in aaa-platform namespace");

  // K8s namespace box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.05, w: W - 0.6, h: 4.15, fill: { color: "F8FAFF" }, line: { color: C.blue, width: 1 } });
  s.addText("aaa-platform  (Kubernetes Namespace)", { x: 0.45, y: 1.1, w: 4.0, h: 0.28, fontSize: 10, color: C.blue, italic: true, margin: 0 });

  // Services
  const srvs = [
    { n: "aaa-lookup-service\n(C++, 3-6 replicas)", p: "8081", bg: C.blue },
    { n: "subscriber-profile-api\n(Python, 2-4 replicas)", p: "8080", bg: "155A8A" },
    { n: "aaa-management-ui\n(React, 1-2 replicas)", p: "80", bg: "0D3D60" },
    { n: "Prometheus\n+ Grafana", p: "9090/3000", bg: C.darkGray },
  ];
  srvs.forEach((sv, i) => {
    const x = 0.5 + i * 2.3;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.52, w: 2.1, h: 1.0, fill: { color: sv.bg }, line: { color: sv.bg }, shadow: { type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.1 } });
    s.addText(sv.n, { x, y: 1.55, w: 2.1, h: 0.65, fontSize: 9.5, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(`port ${sv.p}`, { x, y: 2.2, w: 2.1, h: 0.25, fontSize: 8.5, color: C.iceBlue, align: "center", italic: true, margin: 0 });
  });

  // Vertical connection to DB
  s.addShape(pres.shapes.LINE, { x: 1.55, y: 2.52, w: 0, h: 0.4, line: { color: C.blue, width: 1, dashType: "dash" } });
  s.addShape(pres.shapes.LINE, { x: 3.85, y: 2.52, w: 0, h: 0.4, line: { color: C.blue, width: 1, dashType: "dash" } });

  // DB layer
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 2.92, w: 5.5, h: 1.0, fill: { color: C.navy }, line: { color: C.blue, width: 0.5 } });
  const dbComponents = ["PostgreSQL Primary (CNPG)", "PgBouncer RW (pooler)", "PgBouncer RO (pooler)", "Read Replica(s)"];
  dbComponents.forEach((d, i) => {
    const x = 0.6 + i * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 3.0, w: 1.25, h: 0.75, fill: { color: "1A3566" }, line: { color: C.skyBlue, width: 0.5 } });
    s.addText(d, { x, y: 3.0, w: 1.25, h: 0.75, fontSize: 8.5, color: C.white, align: "center", valign: "middle", margin: 0 });
  });

  // Ingress
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.15, w: 5.5, h: 0.7, fill: { color: C.bgLight }, line: { color: "B0C4D8", width: 0.5 } });
  s.addText("nginx-ingress  |  lookup.aaa.localhost → :8081  |  provisioning.aaa.localhost → :8080", { x: 0.55, y: 4.15, w: 5.4, h: 0.7, fontSize: 9.5, color: C.navy, valign: "middle", margin: 0 });

  // Right side — Helm + Storage
  s.addShape(pres.shapes.RECTANGLE, { x: 6.3, y: 1.52, w: 3.3, h: 1.75, fill: { color: C.bgLight }, line: { color: "B0C4D8" } });
  s.addText("Helm Charts", { x: 6.4, y: 1.58, w: 3.1, h: 0.3, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const charts = ["aaa-platform (umbrella)", "  aaa-database (CNPG)", "  aaa-lookup-service", "  subscriber-profile-api", "  aaa-management-ui"];
  charts.forEach((c, i) => {
    s.addText(c, { x: 6.4, y: 1.93 + i * 0.25, w: 3.1, h: 0.24, fontSize: 9.5, color: C.navy, fontFace: "Courier New", margin: 0 });
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 6.3, y: 3.38, w: 3.3, h: 1.47, fill: { color: C.bgLight }, line: { color: "B0C4D8" } });
  s.addText("Storage", { x: 6.4, y: 3.44, w: 3.1, h: 0.3, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const storage = [
    ["Dev", "local-path (k3d)", "5 Gi"],
    ["Prod", "gp3-encrypted (EBS)", "100 Gi"],
    ["Prometheus", "local-path / gp3", "5-50 Gi"],
  ];
  storage.forEach((r, i) => {
    s.addText(`${r[0]}: ${r[1]} (${r[2]})`, { x: 6.4, y: 3.82 + i * 0.32, w: 3.1, h: 0.28, fontSize: 9.5, color: C.darkGray, margin: 0 });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 13 — DEVELOPER WORKFLOW
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  lightSlide(s);
  titleBar(s, "Developer Workflow", "Makefile-driven local development with k3d + hot-reload");

  // Bootstrap flow
  s.addText("Bootstrap (first time):", { x: 0.3, y: 1.05, w: 5.0, h: 0.3, fontSize: 12, bold: true, color: C.navy, margin: 0 });

  const bootstrap = [
    { c: "make bootstrap", d: "cluster-up + hosts + build-all + push-all + deploy" },
    { c: "make status", d: "Show all pod statuses in aaa-platform namespace" },
    { c: "make test", d: "Run 11-module regression suite as K8s Job (~15 min)" },
  ];
  bootstrap.forEach((b, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.42 + i * 0.55, w: 5.0, h: 0.48, fill: { color: C.navy }, line: { color: C.blue, width: 0.5 } });
    s.addText(b.c, { x: 0.4, y: 1.46 + i * 0.55, w: 1.9, h: 0.4, fontSize: 10, color: C.accent, fontFace: "Courier New", valign: "middle", margin: 0 });
    s.addText(b.d, { x: 2.4, y: 1.46 + i * 0.55, w: 2.8, h: 0.4, fontSize: 10, color: C.iceBlue, valign: "middle", margin: 0 });
  });

  // Port-forward
  s.addText("Port-Forward (local dev):", { x: 0.3, y: 3.12, w: 5.0, h: 0.3, fontSize: 12, bold: true, color: C.navy, margin: 0 });
  const ports = [
    { c: "make port-forward-api", d: "→ localhost:8080 (subscriber-profile-api)" },
    { c: "make port-forward-lookup", d: "→ localhost:8081 (aaa-lookup-service)" },
    { c: "make port-forward-db", d: "→ localhost:5432 (psql, DBeaver)" },
    { c: "make port-forward-grafana", d: "→ localhost:3000 (admin/dev-grafana)" },
  ];
  ports.forEach((p, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.5 + i * 0.47, w: 5.0, h: 0.4, fill: { color: i % 2 === 0 ? C.bgLight : C.white }, line: { color: "D0D8E8", width: 0.5 } });
    s.addText(p.c, { x: 0.42, y: 3.53 + i * 0.47, w: 2.3, h: 0.34, fontSize: 9.5, color: C.navy, fontFace: "Courier New", margin: 0 });
    s.addText(p.d, { x: 2.82, y: 3.53 + i * 0.47, w: 2.38, h: 0.34, fontSize: 9.5, color: C.darkGray, margin: 0 });
  });

  // Right — regression tests
  s.addShape(pres.shapes.RECTANGLE, { x: 5.6, y: 1.05, w: 4.1, h: 4.25, fill: { color: C.bgLight }, line: { color: C.blue, width: 0.8 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.6, y: 1.05, w: 4.1, h: 0.36, fill: { color: C.blue }, line: { color: C.blue } });
  s.addText("Regression Test Suite (11 Modules)", { x: 5.65, y: 1.05, w: 4.0, h: 0.36, fontSize: 10.5, bold: true, color: C.white, valign: "middle", margin: 0 });

  const tests = [
    "test_01_pools.py — IP pool CRUD & exhaustion",
    "test_02_range_configs.py — IMSI range CRUD",
    "test_03/04/05 — Profiles A / B / C modes",
    "test_06_imsi_ops.py — IMSI add/remove/update",
    "test_07_dynamic_alloc.py — Two-stage flow",
    "test_08_bulk.py — JSON + CSV bulk upsert",
    "test_09_migration.py — MariaDB → PostgreSQL",
    "test_10_errors.py — Validation & conflicts",
    "test_11_performance.py — Latency & stress",
  ];
  tests.forEach((t, i) => {
    s.addText(t, { x: 5.72, y: 1.5 + i * 0.42, w: 3.9, h: 0.38, fontSize: 9.5, color: C.navy, margin: 0 });
    s.addShape(pres.shapes.LINE, { x: 5.72, y: 1.88 + i * 0.42, w: 3.9, h: 0, line: { color: "D0D8E8", width: 0.5 } });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 14 — SUMMARY / KEY TAKEAWAYS
// ══════════════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  darkSlide(s);

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 0.8, fill: { color: "142050" }, line: { color: "142050" } });
  s.addText("Key Takeaways", { x: 0.4, y: 0, w: 9, h: 0.8, fontSize: 26, bold: true, color: C.white, valign: "middle", margin: 0 });

  const takeaways = [
    { icon: "<<15ms>>", title: "Real-Time Performance Guaranteed", body: "Separated read/write paths ensure RADIUS authentication always stays below 15ms p99 — even as the subscriber base grows.", color: C.accent },
    { icon: "<<0>>", title: "Zero-Touch First-Connection", body: "Unknown IMSIs are detected and auto-provisioned on first RADIUS attach. Multi-IMSI SIM cards get all slots provisioned atomically in a single transaction.", color: C.green },
    { icon: "<<K8s>>", title: "Cloud-Native from the Ground Up", body: "Kubernetes-native with Helm charts, CloudNativePG, PgBouncer, Prometheus, and Grafana. Scales independently per-region, per-service.", color: C.skyBlue },
    { icon: "<<100K>>", title: "Enterprise-Scale Operations", body: "Bulk provisioning of 100K profiles per job, async processing, per-row error accumulation, and full audit trail for compliance.", color: C.amber },
  ];

  takeaways.forEach((t, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.3 + col * 4.85;
    const y = 1.05 + row * 2.1;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.5, h: 1.9, fill: { color: "172055" }, line: { color: t.color, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.5, h: 0.06, fill: { color: t.color }, line: { color: t.color } });
    s.addText(t.title, { x: x + 0.14, y: y + 0.14, w: 4.2, h: 0.36, fontSize: 13, bold: true, color: C.white, margin: 0 });
    s.addText(t.body, { x: x + 0.14, y: y + 0.55, w: 4.2, h: 1.25, fontSize: 11.5, color: C.skyBlue, margin: 0 });
  });

  s.addShape(pres.shapes.LINE, { x: 0.3, y: 5.22, w: W - 0.6, h: 0, line: { color: C.darkGray, width: 0.5 } });
  s.addText("aaa-cloud-native  |  Platform Engineering  |  March 2026", { x: 0.3, y: 5.26, w: W - 0.6, h: 0.25, fontSize: 9, color: C.gray, align: "center", margin: 0 });
}

// ══════════════════════════════════════════════════════════════════════════════
// WRITE FILE
// ══════════════════════════════════════════════════════════════════════════════
pres.writeFile({ fileName: "docs/aaa-platform-presentation.pptx" }).then(() => {
  console.log("Created: docs/aaa-platform-presentation.pptx");
});
