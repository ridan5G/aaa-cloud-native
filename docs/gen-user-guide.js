const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TableOfContents
} = require('docx');
const fs = require('fs');

const BRAND_BLUE   = "1F497D";
const LIGHT_BLUE   = "D5E8F0";
const HEADER_BLUE  = "2E75B6";
const LIGHT_GRAY   = "F2F2F2";
const DARK_GRAY    = "404040";
const WHITE        = "FFFFFF";
const GREEN_BG     = "E2EFDA";
const ORANGE_BG    = "FCE4D6";
const WARN_BG      = "FFF2CC";
const PAGE_W = 12240;
const PAGE_H = 15840;
const MARGIN = 1440;
const CONTENT_W = PAGE_W - MARGIN * 2;

const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
const cellPad = { top: 80, bottom: 80, left: 120, right: 120 };

function hdr(text, lvl = HeadingLevel.HEADING_1) {
  return new Paragraph({ heading: lvl, children: [new TextRun({ text })] });
}

function para(text, opts = {}) {
  const { bold, italic, size, color, spacing, alignment } = opts;
  return new Paragraph({
    alignment,
    spacing: spacing || { after: 120 },
    children: [new TextRun({ text, bold, italic, size, color })],
  });
}

function bullet(text, bold_prefix) {
  const children = bold_prefix
    ? [new TextRun({ text: bold_prefix, bold: true }), new TextRun({ text })]
    : [new TextRun({ text })];
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 60 },
    children,
  });
}

function sub_bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 1 },
    spacing: { after: 40 },
    children: [new TextRun({ text })],
  });
}

function numbered(text, bold_prefix) {
  const children = bold_prefix
    ? [new TextRun({ text: bold_prefix, bold: true }), new TextRun({ text })]
    : [new TextRun({ text })];
  return new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    spacing: { after: 80 },
    children,
  });
}

function divider() {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE, space: 1 } },
    children: [],
  });
}

function spacer(after = 200) {
  return new Paragraph({ spacing: { after }, children: [] });
}

function code(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    shading: { fill: "F0F0F0", type: ShadingType.CLEAR },
    border: {
      top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 1 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 1 },
    },
    indent: { left: 360 },
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "1E1E1E" })],
  });
}

function noteBox(label, text, bg = LIGHT_BLUE) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [new TableRow({
      children: [new TableCell({
        borders: {
          top: cellBorder, bottom: cellBorder, right: cellBorder,
          left: { style: BorderStyle.SINGLE, size: 8, color: HEADER_BLUE },
        },
        width: { size: CONTENT_W, type: WidthType.DXA },
        shading: { fill: bg, type: ShadingType.CLEAR },
        margins: cellPad,
        children: [
          ...(label ? [new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: label, bold: true, color: BRAND_BLUE })] })] : []),
          new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text })] }),
        ],
      })],
    })],
  });
}

function headerRow(cells, widths) {
  return new TableRow({
    tableHeader: true,
    children: cells.map((text, i) => new TableCell({
      borders: cellBorders,
      width: { size: widths[i], type: WidthType.DXA },
      shading: { fill: HEADER_BLUE, type: ShadingType.CLEAR },
      margins: cellPad,
      children: [new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text, bold: true, color: WHITE, size: 18 })] })],
    })),
  });
}

function dataRow(cells, widths, bg = WHITE) {
  return new TableRow({
    children: cells.map((text, i) => new TableCell({
      borders: cellBorders,
      width: { size: widths[i], type: WidthType.DXA },
      shading: { fill: bg, type: ShadingType.CLEAR },
      margins: cellPad,
      children: [new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text, size: 18 })] })],
    })),
  });
}

function table(headers, rows, widths) {
  const alt = rows.map((r, i) => dataRow(r, widths, i % 2 === 0 ? WHITE : LIGHT_GRAY));
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: [headerRow(headers, widths), ...alt],
  });
}

function stepBox(step, title, description) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [800, CONTENT_W - 800],
    rows: [new TableRow({
      children: [
        new TableCell({
          borders: cellBorders,
          width: { size: 800, type: WidthType.DXA },
          shading: { fill: HEADER_BLUE, type: ShadingType.CLEAR },
          margins: cellPad,
          verticalAlign: VerticalAlign.CENTER,
          children: [new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 }, children: [new TextRun({ text: `Step ${step}`, bold: true, color: WHITE, size: 22 })] })],
        }),
        new TableCell({
          borders: cellBorders,
          width: { size: CONTENT_W - 800, type: WidthType.DXA },
          shading: { fill: LIGHT_BLUE, type: ShadingType.CLEAR },
          margins: cellPad,
          children: [
            new Paragraph({ spacing: { after: 20 }, children: [new TextRun({ text: title, bold: true, size: 22 })] }),
            new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: description, size: 20 })] }),
          ],
        }),
      ],
    })],
  });
}

const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1080, hanging: 360 } } } },
        ],
      },
      {
        reference: "numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        ],
      },
    ],
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: BRAND_BLUE },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE, space: 1 } } },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: HEADER_BLUE },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial", color: DARK_GRAY },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 },
      },
    ],
  },
  sections: [
    // Cover
    {
      properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
      children: [
        spacer(1800),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "AAA Cloud-Native Platform", size: 56, bold: true, color: BRAND_BLUE, font: "Arial" })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 60 },
          children: [new TextRun({ text: "Operator User Guide", size: 36, color: HEADER_BLUE, font: "Arial" })],
        }),
        divider(),
        spacer(80),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 40 },
          children: [new TextRun({ text: "Provisioning, IP Pool Management, and Day-2 Operations", size: 24, italic: true, color: DARK_GRAY })],
        }),
        spacer(1800),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Version 1.0   |   March 2026", size: 22, color: DARK_GRAY })],
        }),
        new Paragraph({ children: [new PageBreak()] }),
      ],
    },
    // Body
    {
      properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE } },
            spacing: { after: 80 },
            children: [new TextRun({ text: "AAA Cloud-Native Platform  |  Operator User Guide", color: HEADER_BLUE, size: 18 })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE } },
            spacing: { before: 80 },
            children: [
              new TextRun({ text: "Page ", size: 18, color: DARK_GRAY }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, color: DARK_GRAY }),
              new TextRun({ text: " of ", size: 18, color: DARK_GRAY }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: DARK_GRAY }),
            ],
          })],
        }),
      },
      children: [
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({ children: [new PageBreak()] }),

        // ── 1. Getting Started ─────────────────────────────────────────
        hdr("1. Getting Started"),
        para("This guide covers day-to-day operations for provisioning subscribers, managing IP address pools, and monitoring the AAA Cloud-Native Platform. It is intended for telecom network engineers and operations teams."),
        spacer(60),
        para("The platform consists of four runtime services that work together to authenticate subscribers and manage their profiles:"),
        bullet("aaa-radius-server — RADIUS authentication frontend. Receives Access-Requests from network equipment and makes a single REST call to aaa-lookup-service for each request."),
        bullet("aaa-lookup-service — High-performance IMSI lookup (C++17, port 8081). Called by aaa-radius-server on every Access-Request; handles first-connection allocation internally when the IMSI is not yet in the database."),
        bullet("subscriber-profile-api — Provisioning REST API (Python/FastAPI, port 8080). Called by aaa-lookup-service when a subscriber is seen for the first time (IMSI not in DB)."),
        bullet("aaa-management-ui — Operator web dashboard for managing pools, profiles, and bulk jobs."),
        spacer(80),

        hdr("1.1 Prerequisites", HeadingLevel.HEADING_2),
        bullet("Access to the provisioning API (subscriber-profile-api)"),
        bullet("A valid OAuth 2.0 Bearer JWT token (or JWT_SKIP_VERIFY=true for dev/test)"),
        bullet("At least one IP pool created and active"),
        bullet("IMSI range configs defined for any subscriber segments that use first-connection auto-provisioning"),
        bullet("aaa-radius-server configured with the aaa-lookup-service endpoint (LOOKUP_URL)"),
        spacer(80),

        hdr("1.2 API Access", HeadingLevel.HEADING_2),
        para("All requests must include the Authorization header:"),
        code("Authorization: Bearer <your-jwt-token>"),
        code("Content-Type: application/json"),
        spacer(60),
        table(
          ["Environment", "Base URL"],
          [
            ["Development (k3d)", "http://provisioning.aaa.localhost/v1"],
            ["Production", "https://provisioning.aaa-platform.example.com/v1"],
          ],
          [2800, 6560]
        ),
        spacer(80),

        hdr("1.3 Health Check", HeadingLevel.HEADING_2),
        para("Verify the service is running before performing operations:"),
        code("curl http://provisioning.aaa.localhost/health"),
        code("# Expected: {\"status\": \"ok\"}"),
        spacer(60),
        code("curl http://provisioning.aaa.localhost/health/db"),
        code("# Expected: {\"status\": \"ok\"}  or  503 if DB unavailable"),

        // ── 2. IP Pool Management ─────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("2. IP Pool Management"),
        para("IP pools are the foundation of the platform. Every subscriber needs an IP pool to allocate addresses from. Create pools before creating subscriber profiles or range configurations."),
        spacer(80),

        hdr("2.1 Create an IP Pool", HeadingLevel.HEADING_2),
        para("Creating a pool automatically pre-populates all usable IPs in the pool's available work-queue. For a /24 subnet, this is 253 IPs (excludes network address .0 and broadcast .255)."),
        spacer(80),
        stepBox("1", "Define your subnet", "Decide on the CIDR block (e.g., 100.65.120.0/24). The start_ip is the first usable address (.1), end_ip is the broadcast address (.255)."),
        spacer(60),
        stepBox("2", "POST to /v1/pools", "Send the create request with your subnet details."),
        spacer(60),
        code("POST /v1/pools"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"pool_name\": \"CGNAT-Block-1\","),
        code("  \"subnet\": \"100.65.120.0/24\","),
        code("  \"start_ip\": \"100.65.120.1\","),
        code("  \"end_ip\": \"100.65.120.255\","),
        code("  \"status\": \"active\""),
        code("}"),
        code(""),
        code("Response 201:"),
        code("{\"pool_id\": \"a1b2c3d4-...\", \"pool_name\": \"CGNAT-Block-1\", \"subnet\": \"100.65.120.0/24\"}"),
        spacer(60),
        noteBox("Note", "Pool creation is synchronous. The API pre-populates all 253 available IPs before returning. For large subnets this may take a few seconds."),
        spacer(120),

        hdr("2.2 Check Pool Statistics", HeadingLevel.HEADING_2),
        code("GET /v1/pools/a1b2c3d4-.../stats"),
        code(""),
        code("Response 200:"),
        code("{"),
        code("  \"pool_id\": \"a1b2c3d4-...\","),
        code("  \"total\": 253,"),
        code("  \"allocated\": 47,"),
        code("  \"available\": 206"),
        code("}"),
        spacer(80),

        hdr("2.3 Suspend and Reactivate a Pool", HeadingLevel.HEADING_2),
        para("Suspending a pool prevents new allocations but does not affect existing subscribers."),
        code("PATCH /v1/pools/a1b2c3d4-..."),
        code("{\"status\": \"suspended\"}"),
        spacer(60),
        noteBox("Warning", "You cannot delete a pool that has allocated IPs. First terminate all subscriber profiles using this pool, then delete.", WARN_BG),

        // ── 3. Range Configurations ────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("3. Range Configurations"),
        para("Range configurations define which IMSI ranges are eligible for automatic first-connection provisioning. You must create range configs before subscribers can self-register on first network attach."),
        spacer(80),

        hdr("3.1 Single-IMSI Range Config", HeadingLevel.HEADING_2),
        para("Use this for SIM cards with a single IMSI per card."),
        spacer(60),
        code("POST /v1/range-configs"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"f_imsi\": \"278770000000000\","),
        code("  \"t_imsi\": \"278770000999999\","),
        code("  \"pool_id\": \"a1b2c3d4-...\","),
        code("  \"ip_resolution\": \"imsi\","),
        code("  \"status\": \"active\","),
        code("  \"description\": \"Melita IoT fleet batch 1\""),
        code("}"),
        spacer(60),
        table(
          ["ip_resolution value", "When to use"],
          [
            ["imsi", "One IP per IMSI, same IP for all APNs"],
            ["imsi_apn", "One IP per IMSI per APN (different APNs get different IPs)"],
            ["iccid", "One IP per SIM card, shared by all IMSIs, same for all APNs"],
            ["iccid_apn", "One IP per SIM card per APN"],
          ],
          [2800, 6560]
        ),
        spacer(80),

        hdr("3.2 Multi-IMSI SIM Range Config", HeadingLevel.HEADING_2),
        para("Use this when each physical SIM card carries multiple IMSIs (slots). First create the parent ICCID range, then add child IMSI slot ranges."),
        spacer(80),

        hdr("Step A: Create the parent ICCID range", HeadingLevel.HEADING_3),
        para("Option 1 — shared pool (all slots draw from the same pool):"),
        code("POST /v1/iccid-range-configs"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"f_iccid\": \"8944501010000000000\","),
        code("  \"t_iccid\": \"8944501010000999999\","),
        code("  \"pool_id\": \"a1b2c3d4-...\",   // optional — omit if each slot has its own pool"),
        code("  \"ip_resolution\": \"imsi\","),
        code("  \"imsi_count\": 2,"),
        code("  \"status\": \"active\""),
        code("}"),
        code(""),
        code("Response 201: {\"id\": 42, \"f_iccid\": \"8944501010000000000\", ...}"),
        spacer(60),
        noteBox("Per-Slot Pool Routing", "To give each IMSI slot its own IP pool (e.g., IMSI1 from 10.10.10.0/24, IMSI2 from 11.10.10.0/24), omit pool_id on the parent (set to null) and specify pool_id on each imsi-slot instead. The platform resolves: slot pool_id first, then parent pool_id as fallback."),
        spacer(80),

        hdr("Step B: Add IMSI slot ranges (one per physical slot)", HeadingLevel.HEADING_3),
        para("Each slot can optionally specify its own pool_id to override the parent:"),
        code("POST /v1/iccid-range-configs/42/imsi-slots"),
        code("{"),
        code("  \"f_imsi\": \"278770000000000\","),
        code("  \"t_imsi\": \"278770000999999\","),
        code("  \"pool_id\": \"<pool1-uuid>\",    // slot-specific pool (overrides parent)"),
        code("  \"imsi_slot\": 1"),
        code("}"),
        spacer(60),
        code("POST /v1/iccid-range-configs/42/imsi-slots"),
        code("{"),
        code("  \"f_imsi\": \"278771000000000\","),
        code("  \"t_imsi\": \"278771000999999\","),
        code("  \"pool_id\": \"<pool2-uuid>\",    // different pool for this slot"),
        code("  \"imsi_slot\": 2"),
        code("}"),
        spacer(60),
        noteBox("Cardinality Rule", "Each IMSI slot range must span the same number of addresses as the parent ICCID range. For the example above: 278770000999999 - 278770000000000 = 999999 = 8944501010000999999 - 8944501010000000000."),
        spacer(80),

        hdr("3.3 Per-APN Pool Overrides", HeadingLevel.HEADING_2),
        para("When ip_resolution is imsi_apn or iccid_apn, different APNs can draw IPs from different pools. Configure this using the APN Pool Overrides sub-resource on a range config."),
        spacer(60),
        code("# List current APN pool overrides for range config 7"),
        code("GET /v1/range-configs/7/apn-pools"),
        spacer(60),
        code("# Route 'internet.melita.com' to pool-A"),
        code("POST /v1/range-configs/7/apn-pools"),
        code("{"),
        code("  \"apn\": \"internet.melita.com\","),
        code("  \"pool_id\": \"<pool-A-uuid>\""),
        code("}"),
        spacer(60),
        code("# Route 'm2m.melita.com' to pool-B"),
        code("POST /v1/range-configs/7/apn-pools"),
        code("{"),
        code("  \"apn\": \"m2m.melita.com\","),
        code("  \"pool_id\": \"<pool-B-uuid>\""),
        code("}"),
        spacer(60),
        code("# Remove an APN override"),
        code("DELETE /v1/range-configs/7/apn-pools/m2m.melita.com"),
        spacer(60),
        noteBox("Pool Resolution Order", "At first-connection, the platform resolves the pool in this order:\n1. APN pool override for this range config + APN (range_config_apn_pools)\n2. Slot pool_id (imsi_range_configs.pool_id, for multi-IMSI SIM)\n3. Parent ICCID range pool_id (iccid_range_configs.pool_id, for multi-IMSI SIM)\nIf none is found, the request returns 503."),
        spacer(80),

        // ── 3.4 Auto-Allocation Scenarios ────────────────────────────────
        hdr("3.4 Auto-Allocation Scenarios", HeadingLevel.HEADING_2),
        para("All scenarios below are triggered by POST /v1/first-connection, called automatically by aaa-radius-server when a subscriber's IMSI is not yet provisioned. The platform selects the scenario based on ip_resolution mode and whether the range config belongs to an ICCID group (multi-IMSI)."),
        spacer(60),
        para("IPs provisioned per SIM card:", { bold: true }),
        table(
          ["Mode", "Single-IMSI", "Multi-IMSI (M slots)", "Storage"],
          [
            ["imsi",      "1",          "M (1 per slot)",        "imsi_apn_ips (apn=NULL)"],
            ["imsi_apn",  "N per IMSI", "M × N",                 "imsi_apn_ips (apn=APN)"],
            ["iccid",     "1",          "1 (shared card IP)",    "sim_apn_ips (apn=NULL)"],
            ["iccid_apn", "N per card", "N (shared card IPs)",   "sim_apn_ips (apn=APN)"],
          ],
          [1800, 1600, 2400, 3560]
        ),
        spacer(40),
        para("N = APN entries in range_config_apn_pools for the range config.  M = number of active IMSI slots.", { italic: true, color: DARK_GRAY }),
        spacer(80),

        hdr("Scenario S1 — imsi: 1 IP per IMSI", HeadingLevel.HEADING_3),
        para("One static IP per IMSI, same IP regardless of APN. Simplest single-IMSI configuration."),
        table(
          ["Step", "Action"],
          [
            ["1. Create range config", "POST /v1/range-configs  { ip_resolution: \"imsi\", pool_id: <pool>, ... }"],
            ["2. APN catalog", "Not required"],
            ["On first connect", "1 IP allocated from pool, stored in imsi_apn_ips with apn=NULL. Returns 201."],
            ["Subsequent connects", "Idempotency: returns same IP from imsi_apn_ips."],
          ],
          [2600, 6760]
        ),
        spacer(80),

        hdr("Scenario S2 — imsi_apn: N IPs per IMSI (one per APN)", HeadingLevel.HEADING_3),
        para("Each IMSI gets a separate IP per APN. Define the APN catalog on the range config — all listed APNs are provisioned in one atomic transaction on first connect."),
        table(
          ["Step", "Action"],
          [
            ["1. Create range config", "POST /v1/range-configs  { ip_resolution: \"imsi_apn\", pool_id: <default-pool>, ... }"],
            ["2. Add APN catalog", "POST /v1/range-configs/{id}/apn-pools  { apn: \"internet\", pool_id: <pool-A> }\nPOST /v1/range-configs/{id}/apn-pools  { apn: \"corporate\", pool_id: <pool-B> }\n(repeat for each APN — each can use same or different pool)"],
            ["On first connect", "N IPs allocated (1 per APN entry), all stored in imsi_apn_ips. Response returns IP for the connecting APN."],
            ["Subsequent connects", "Any APN: idempotency returns the pre-provisioned IP for that APN."],
          ],
          [2600, 6760]
        ),
        spacer(60),
        noteBox("APN catalog = provisioning list + pool router", "Each range_config_apn_pools entry does two things: (1) adds the APN to the list provisioned at first-connect, and (2) routes that APN to a specific pool. If all APNs share one pool, use the same pool_id on every entry. If no entries exist, only the connecting APN is provisioned (fallback — backward compatible)."),
        spacer(80),

        hdr("Scenario S3 — iccid: 1 IP per SIM card", HeadingLevel.HEADING_3),
        para("One IP for the whole physical SIM card. All IMSIs on the card return the same IP regardless of APN."),
        table(
          ["Step", "Action"],
          [
            ["1. Create range config", "POST /v1/range-configs  { ip_resolution: \"iccid\", pool_id: <pool>, ... }"],
            ["2. APN catalog", "Not required"],
            ["On first connect", "1 IP allocated, stored in sim_apn_ips with apn=NULL. All IMSIs share this sim_id."],
            ["Subsequent connects", "Any IMSI, any APN: returns same IP."],
          ],
          [2600, 6760]
        ),
        spacer(80),

        hdr("Scenario S4 — iccid_apn: N IPs per SIM card (one per APN)", HeadingLevel.HEADING_3),
        para("One IP per APN for the whole physical SIM card. All IMSIs on the card share the per-APN IPs."),
        table(
          ["Step", "Action"],
          [
            ["1. Create range config", "POST /v1/range-configs  { ip_resolution: \"iccid_apn\", pool_id: <default-pool>, ... }"],
            ["2. Add APN catalog", "POST /v1/range-configs/{id}/apn-pools  { apn: \"internet\", pool_id: <pool-A> }\nPOST /v1/range-configs/{id}/apn-pools  { apn: \"corporate\", pool_id: <pool-B> }"],
            ["On first connect", "N IPs allocated, stored in sim_apn_ips (one row per APN). All IMSIs on the card share these IPs."],
            ["Subsequent connects", "Any IMSI + APN combination returns the pre-provisioned card-level IP."],
          ],
          [2600, 6760]
        ),
        spacer(80),

        hdr("Scenario M1 — Multi-IMSI + imsi: M IPs per card (one per slot)", HeadingLevel.HEADING_3),
        para("Multi-IMSI SIM, each slot gets its own IP. All slots provisioned atomically on first connect of any slot."),
        table(
          ["Step", "Action"],
          [
            ["1. Create ICCID range", "POST /v1/iccid-range-configs  { ip_resolution: \"imsi\", pool_id: <shared-pool>, imsi_count: M, ... }"],
            ["2. Add IMSI slots", "POST /v1/iccid-range-configs/{id}/imsi-slots (×M) — each slot can override pool_id for per-slot routing"],
            ["3. APN catalog", "Not required"],
            ["On first connect", "M IPs allocated (1 per slot), each from its slot pool. All M imsi2sim rows inserted in one transaction."],
            ["Subsequent connects", "Any slot IMSI returns its pre-provisioned IP immediately from the hot path."],
          ],
          [2600, 6760]
        ),
        spacer(80),

        hdr("Scenario M2 — Multi-IMSI + imsi_apn: M×N IPs per card", HeadingLevel.HEADING_3),
        para("Maximum flexibility: each slot gets N IPs (one per APN) from its own per-slot pools. All M×N IPs provisioned atomically on first connect of any slot."),
        table(
          ["Step", "Action"],
          [
            ["1. Create ICCID range", "POST /v1/iccid-range-configs  { ip_resolution: \"imsi_apn\", imsi_count: M }  (pool_id optional — omit if each slot has its own)"],
            ["2. Add IMSI slots", "POST /v1/iccid-range-configs/{id}/imsi-slots (×M) with per-slot pool_id"],
            ["3. Add APN catalog per slot", "POST /v1/range-configs/{slot-range-config-id}/apn-pools for each APN on EACH slot separately\n(slots can have different APN→pool mappings)"],
            ["On first connect", "M × N IPs in one COMMIT: slot-1 gets N IPs from its pools, slot-2 gets N IPs from its pools, etc."],
            ["Subsequent connects", "Any slot IMSI + any APN: returns pre-provisioned IP. Zero writes at steady state."],
          ],
          [2600, 6760]
        ),
        spacer(60),
        noteBox("Example: 2 slots × 2 APNs = 4 IPs per SIM", "ICCID range: ip_resolution=imsi_apn, imsi_count=2. Slot 1 (rc_id=10): add apn-pools for \"internet\"→pool-A and \"corporate\"→pool-B. Slot 2 (rc_id=11): same. On first attach: 4 IPs in one COMMIT — slot1/internet, slot1/corporate, slot2/internet, slot2/corporate."),
        spacer(80),

        hdr("Scenario M3 — Multi-IMSI + iccid: 1 IP per card", HeadingLevel.HEADING_3),
        para("Multi-IMSI SIM, all slots share a single card-level IP. Simplest multi-IMSI configuration."),
        table(
          ["Step", "Action"],
          [
            ["1. Create ICCID range", "POST /v1/iccid-range-configs  { ip_resolution: \"iccid\", pool_id: <pool>, imsi_count: M }"],
            ["2. Add IMSI slots", "POST /v1/iccid-range-configs/{id}/imsi-slots (×M)"],
            ["3. APN catalog", "Not required"],
            ["On first connect", "1 IP allocated. All M slots share the same sim_id and return the same IP."],
          ],
          [2600, 6760]
        ),
        spacer(80),

        hdr("Scenario M4 — Multi-IMSI + iccid_apn: N IPs per card", HeadingLevel.HEADING_3),
        para("Multi-IMSI SIM, all slots share card-level IPs (one per APN). APN catalog defined on the connecting slot's range config."),
        table(
          ["Step", "Action"],
          [
            ["1. Create ICCID range", "POST /v1/iccid-range-configs  { ip_resolution: \"iccid_apn\", pool_id: <default-pool>, imsi_count: M }"],
            ["2. Add IMSI slots", "POST /v1/iccid-range-configs/{id}/imsi-slots (×M)"],
            ["3. Add APN catalog", "POST /v1/range-configs/{any-slot-rc-id}/apn-pools for each APN"],
            ["On first connect", "N IPs allocated as card-level sim_apn_ips rows. All M slots share these N IPs."],
            ["Subsequent connects", "Any slot IMSI + any defined APN: returns the shared card-level IP for that APN."],
          ],
          [2600, 6760]
        ),
        spacer(60),
        noteBox("Idempotency applies to all scenarios", "If the same IMSI re-connects on any APN, the platform finds it in imsi2sim and returns the existing IP with no allocation. All sibling IMSIs pre-provisioned in the original transaction are served instantly from the hot-path on every subsequent connection — zero write pressure at steady state."),

        // ── 4. Subscriber Provisioning ──────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("4. Subscriber Provisioning"),
        para("Subscribers can be provisioned manually (pre-provisioning) or automatically via first-connection. This chapter covers manual provisioning via the REST API."),
        spacer(80),

        hdr("4.1 Create a Profile (Profile Mode B - IMSI-level IP)", HeadingLevel.HEADING_2),
        para("Profile Mode B: One static IP per IMSI, APN-agnostic. This is the most common mode."),
        spacer(60),
        code("POST /v1/profiles"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"iccid\": \"8944501012345678901\","),
        code("  \"status\": \"active\","),
        code("  \"ip_resolution\": \"imsi\","),
        code("  \"imsis\": ["),
        code("    {"),
        code("      \"imsi\": \"278773000002002\","),
        code("      \"apn_ips\": [{\"static_ip\": \"100.65.120.5\", \"pool_id\": \"a1b2c3d4-...\"}]"),
        code("    }"),
        code("  ]"),
        code("}"),
        code(""),
        code("Response 201: {\"sim_id\": \"550e8400-...\", \"created_at\": \"2026-03-13T10:00:00Z\"}"),
        spacer(80),

        hdr("4.2 Create a Profile (Profile Mode C - APN-specific IP)", HeadingLevel.HEADING_2),
        para("Profile Mode C: One static IP per IMSI per APN. Different APNs receive different IPs."),
        spacer(60),
        code("POST /v1/profiles"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"status\": \"active\","),
        code("  \"ip_resolution\": \"imsi_apn\","),
        code("  \"imsis\": ["),
        code("    {"),
        code("      \"imsi\": \"278773000002003\","),
        code("      \"apn_ips\": ["),
        code("        {\"apn\": \"internet.melita.com\", \"static_ip\": \"100.65.120.6\", \"pool_id\": \"...\"},"),
        code("        {\"apn\": \"m2m.melita.com\",      \"static_ip\": \"10.0.0.100\",    \"pool_id\": \"...\"}"),
        code("      ]"),
        code("    }"),
        code("  ]"),
        code("}"),
        spacer(80),

        hdr("4.3 Create a Profile (Profile Mode A - Card-level IP)", HeadingLevel.HEADING_2),
        para("Profile Mode A: One IP per SIM card, shared by all IMSIs. Use ip_resolution: iccid."),
        spacer(60),
        code("POST /v1/profiles"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"iccid\": \"8944501012345678902\","),
        code("  \"status\": \"active\","),
        code("  \"ip_resolution\": \"iccid\","),
        code("  \"iccid_ips\": [{\"static_ip\": \"100.65.120.7\", \"pool_id\": \"a1b2c3d4-...\"}],"),
        code("  \"imsis\": ["),
        code("    {\"imsi\": \"278773000002010\"},"),
        code("    {\"imsi\": \"278773000002011\"}"),
        code("  ]"),
        code("}"),
        spacer(80),

        hdr("4.4 Look Up an Existing Profile", HeadingLevel.HEADING_2),
        code("# By device UUID"),
        code("GET /v1/profiles/550e8400-..."),
        code(""),
        code("# By ICCID"),
        code("GET /v1/profiles?iccid=8944501012345678901"),
        code(""),
        code("# By IMSI (admin use)"),
        code("GET /v1/profiles?imsi=278773000002002"),
        code(""),
        code("# List all for an account (paginated)"),
        code("GET /v1/profiles?account_name=Melita&page=1&page_size=100"),
        spacer(80),

        hdr("4.5 Update a Profile", HeadingLevel.HEADING_2),
        para("Use PATCH for partial updates (JSON Merge Patch semantics)."),
        code("# Add ICCID to an existing profile"),
        code("PATCH /v1/profiles/550e8400-..."),
        code("{\"iccid\": \"8944501012345678901\"}"),
        code(""),
        code("# Add tags to metadata"),
        code("PATCH /v1/profiles/550e8400-..."),
        code("{\"metadata\": {\"tags\": [\"iot\", \"fleet-1\"]}}"),

        // ── 5. Subscriber Lifecycle ──────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("5. Subscriber Lifecycle Management"),

        hdr("5.1 Suspend a Subscriber", HeadingLevel.HEADING_2),
        para("Suspending a profile causes all IMSI lookups for that device to return 403 Forbidden, which triggers an Access-Reject."),
        code("PATCH /v1/profiles/550e8400-..."),
        code("{\"status\": \"suspended\"}"),
        spacer(60),
        noteBox("Effect", "Suspension takes effect on the next RADIUS Access-Request. Existing active sessions are not affected until they re-authenticate. To immediately terminate sessions, coordinate with the RADIUS server."),
        spacer(80),

        hdr("5.2 Reactivate a Subscriber", HeadingLevel.HEADING_2),
        code("PATCH /v1/profiles/550e8400-..."),
        code("{\"status\": \"active\"}"),
        spacer(80),

        hdr("5.3 Terminate a Subscriber", HeadingLevel.HEADING_2),
        para("DELETE performs a soft-delete: the profile status is set to 'terminated'. The record is retained in the database for audit purposes."),
        code("DELETE /v1/profiles/550e8400-..."),
        code("# Response: 204 No Content"),
        spacer(60),
        noteBox("Important", "Deleting a profile does NOT release the subscriber's IP back to the pool. The IP remains allocated. If you need to reclaim IPs, you must manually update the ip_pool_available table or contact platform engineering.", WARN_BG),
        spacer(80),

        hdr("5.4 Manage IMSIs on a Profile", HeadingLevel.HEADING_2),
        code("# List IMSIs on a device"),
        code("GET /v1/profiles/550e8400-.../imsis"),
        code(""),
        code("# Add a new IMSI to an existing profile"),
        code("POST /v1/profiles/550e8400-.../imsis"),
        code("{"),
        code("  \"imsi\": \"278773000002099\","),
        code("  \"apn_ips\": [{\"static_ip\": \"100.65.120.99\", \"pool_id\": \"...\"}]"),
        code("}"),
        code(""),
        code("# Suspend a single IMSI (profile remains active)"),
        code("PATCH /v1/profiles/550e8400-.../imsis/278773000002099"),
        code("{\"status\": \"suspended\"}"),
        code(""),
        code("# Remove an IMSI (and all its IP assignments)"),
        code("DELETE /v1/profiles/550e8400-.../imsis/278773000002099"),

        // ── 6. Bulk Operations ───────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("6. Bulk Provisioning"),
        para("For large-scale provisioning (migrations, fleet deployments), use the bulk API. It accepts up to 100,000 profiles per job and processes them asynchronously."),
        spacer(80),

        hdr("6.1 JSON Bulk Upload", HeadingLevel.HEADING_2),
        code("POST /v1/profiles/bulk"),
        code("Content-Type: application/json"),
        code("{"),
        code("  \"mode\": \"upsert\","),
        code("  \"profiles\": ["),
        code("    {\"account_name\": \"Melita\", \"iccid\": \"...\", \"status\": \"active\","),
        code("     \"ip_resolution\": \"imsi\", \"imsis\": [{\"imsi\": \"...\", \"apn_ips\": [...]}]},"),
        code("    ..."),
        code("  ]"),
        code("}"),
        code(""),
        code("Response 202 Accepted:"),
        code("{\"job_id\": \"abc123\", \"submitted\": 5000, \"status_url\": \"/v1/jobs/abc123\"}"),
        spacer(80),

        hdr("6.2 CSV Bulk Upload", HeadingLevel.HEADING_2),
        para("CSV format is supported for simpler bulk imports. Upload as multipart/form-data."),
        code("curl -X POST /v1/profiles/bulk \\"),
        code("  -H 'Authorization: Bearer <token>' \\"),
        code("  -F 'file=@subscribers.csv'"),
        spacer(80),

        hdr("6.3 Monitor a Bulk Job", HeadingLevel.HEADING_2),
        code("GET /v1/jobs/abc123"),
        code(""),
        code("Response (while processing):"),
        code("{\"job_id\": \"abc123\", \"status\": \"processing\", \"processed\": 2500, \"failed\": 0}"),
        code(""),
        code("Response (completed):"),
        code("{"),
        code("  \"job_id\": \"abc123\","),
        code("  \"status\": \"completed\","),
        code("  \"processed\": 4997,"),
        code("  \"failed\": 3,"),
        code("  \"errors\": ["),
        code("    {\"row\": 42, \"field\": \"imsi\", \"message\": \"IMSI must be 15 digits\", \"value\": \"1234\"},"),
        code("    ..."),
        code("  ]"),
        code("}"),
        spacer(60),
        noteBox("Polling Recommendation", "Poll GET /v1/jobs/{job_id} every 5 seconds. Most jobs complete within 1-2 minutes for 10,000 profiles. Very large jobs (100K) may take up to 10 minutes."),

        // ── 6.4 Profile Structure by Scenario ───────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("6.4 Profile Structure by Scenario", HeadingLevel.HEADING_2),
        para("The JSON profile object inside the profiles array differs depending on ip_resolution mode and SIM type. The table below maps each scenario to its required bulk profile structure."),
        spacer(80),

        table(
          ["Scenario", "Mode", "IPs / SIM", "Key fields in profile object"],
          [
            ["S1 — Single-IMSI", "imsi",      "1",   "imsis[].apn_ips[{static_ip, pool_id}] — no apn field"],
            ["S2 — Single-IMSI", "imsi_apn",  "N",   "imsis[].apn_ips[{apn, static_ip, pool_id}] × N APNs"],
            ["S3 — Single-IMSI", "iccid",     "1",   "iccid_ips[{static_ip, pool_id}]  +  imsis[{imsi}]"],
            ["S4 — Single-IMSI", "iccid_apn", "N",   "iccid_ips[{apn, static_ip, pool_id}] × N  +  imsis[{imsi}]"],
            ["M1 — Multi-IMSI",  "imsi",      "M",   "iccid  +  imsis[{imsi, priority, apn_ips[{static_ip, pool_id}]}] × M"],
            ["M2 — Multi-IMSI",  "imsi_apn",  "M×N", "iccid  +  imsis[{imsi, priority, apn_ips[{apn, static_ip, pool_id}]}] × M slots × N APNs"],
            ["M3 — Multi-IMSI",  "iccid",     "1",   "iccid  +  iccid_ips[{static_ip, pool_id}]  +  imsis[{imsi, priority}] × M"],
            ["M4 — Multi-IMSI",  "iccid_apn", "N",   "iccid  +  iccid_ips[{apn, static_ip, pool_id}] × N  +  imsis[{imsi, priority}] × M"],
          ],
          [1900, 1100, 900, 5460],
        ),
        spacer(80),

        hdr("S1 — Single-IMSI, mode: imsi  (1 IP per IMSI)", HeadingLevel.HEADING_3),
        code('{ "account_name": "Acme", "iccid": "8931001...", "status": "active",'),
        code('  "ip_resolution": "imsi",'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001",'),
        code('      "apn_ips": [{ "static_ip": "10.0.1.5", "pool_id": "<pool-uuid>" }] }'),
        code('  ]'),
        code('}'),
        spacer(60),

        hdr("S2 — Single-IMSI, mode: imsi_apn  (N IPs — one per APN)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "imsi_apn",'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001",'),
        code('      "apn_ips": ['),
        code('        { "apn": "internet", "static_ip": "10.0.1.5", "pool_id": "<internet-pool>" },'),
        code('        { "apn": "ims",      "static_ip": "10.1.0.5", "pool_id": "<ims-pool>"      }'),
        code('      ] }'),
        code('  ]'),
        code('}'),
        spacer(60),

        hdr("S3 — Single-IMSI, mode: iccid  (1 IP per card)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "iccid",'),
        code('  "iccid_ips": [{ "static_ip": "10.0.1.5", "pool_id": "<pool-uuid>" }],'),
        code('  "imsis": [{ "imsi": "310150000000001" }]'),
        code('}'),
        spacer(60),

        hdr("S4 — Single-IMSI, mode: iccid_apn  (N IPs — per APN, shared by card)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "iccid_apn",'),
        code('  "iccid_ips": ['),
        code('    { "apn": "internet", "static_ip": "10.0.1.5", "pool_id": "<internet-pool>" },'),
        code('    { "apn": "ims",      "static_ip": "10.1.0.5", "pool_id": "<ims-pool>"      }'),
        code('  ],'),
        code('  "imsis": [{ "imsi": "310150000000001" }]'),
        code('}'),
        spacer(80),

        hdr("M1 — Multi-IMSI, mode: imsi  (M IPs — 1 per slot)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "imsi",'),
        code('  "iccid": "8931001...",'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001", "priority": 1,'),
        code('      "apn_ips": [{ "static_ip": "10.0.1.5", "pool_id": "<slot1-pool>" }] },'),
        code('    { "imsi": "310150000000002", "priority": 2,'),
        code('      "apn_ips": [{ "static_ip": "10.0.1.6", "pool_id": "<slot2-pool>" }] }'),
        code('  ]'),
        code('}'),
        spacer(60),

        hdr("M2 — Multi-IMSI, mode: imsi_apn  (M×N IPs — per slot per APN)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "imsi_apn",'),
        code('  "iccid": "8931001...",'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001", "priority": 1,'),
        code('      "apn_ips": [{ "apn": "internet", "static_ip": "10.0.1.5", "pool_id": "<uuid>" },'),
        code('                  { "apn": "ims",      "static_ip": "10.1.0.5", "pool_id": "<uuid>" }] },'),
        code('    { "imsi": "310150000000002", "priority": 2,'),
        code('      "apn_ips": [{ "apn": "internet", "static_ip": "10.0.1.6", "pool_id": "<uuid>" },'),
        code('                  { "apn": "ims",      "static_ip": "10.1.0.6", "pool_id": "<uuid>" }] }'),
        code('  ]'),
        code('}'),
        spacer(60),

        hdr("M3 — Multi-IMSI, mode: iccid  (1 shared IP for the card)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "iccid",'),
        code('  "iccid": "8931001...",'),
        code('  "iccid_ips": [{ "static_ip": "10.0.1.5", "pool_id": "<pool-uuid>" }],'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001", "priority": 1 },'),
        code('    { "imsi": "310150000000002", "priority": 2 }'),
        code('  ]'),
        code('}'),
        spacer(60),

        hdr("M4 — Multi-IMSI, mode: iccid_apn  (N shared IPs per card, per APN)", HeadingLevel.HEADING_3),
        code('{ "ip_resolution": "iccid_apn",'),
        code('  "iccid": "8931001...",'),
        code('  "iccid_ips": ['),
        code('    { "apn": "internet", "static_ip": "10.0.1.5", "pool_id": "<internet-pool>" },'),
        code('    { "apn": "ims",      "static_ip": "10.1.0.5", "pool_id": "<ims-pool>"      }'),
        code('  ],'),
        code('  "imsis": ['),
        code('    { "imsi": "310150000000001", "priority": 1 },'),
        code('    { "imsi": "310150000000002", "priority": 2 }'),
        code('  ]'),
        code('}'),
        spacer(60),

        noteBox("Pre-provisioned vs Auto-Allocated", "When static_ip and pool_id are supplied in apn_ips / iccid_ips the profile is fully pre-provisioned — no range config is needed. To use auto-allocation instead, omit static_ip and pool_id from the IP entries and ensure the relevant range config (with matching ip_resolution) is in place. The structure of the profile object (which fields are present) stays the same for both approaches."),
        spacer(80),

        // ── 7. First-Connection Monitoring ──────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("7. Monitoring First-Connection Allocation"),
        para("When auto-provisioning is enabled via range configs, subscribers self-register on first network attach. No manual action is required. However, you should monitor the following to detect problems early."),
        spacer(80),

        hdr("7.1 What Happens at First Connection", HeadingLevel.HEADING_2),
        numbered("Device attaches to the mobile network"),
        numbered("aaa-radius-server receives the RADIUS Access-Request and sends GET /lookup?imsi={imsi}&apn={apn}&imei={imei} to aaa-lookup-service"),
        numbered("aaa-lookup-service queries the read-replica — 0 rows returned (IMSI not yet provisioned)"),
        numbered("aaa-lookup-service calls POST /v1/first-connection on subscriber-profile-api (internally, no involvement of aaa-radius-server)"),
        numbered("subscriber-profile-api matches IMSI to a range config, resolves pool (APN override → slot pool → parent pool), claims an IP atomically"),
        numbered("For Multi-IMSI SIM configs: ALL sibling IMSI slots are pre-provisioned in the same transaction, each drawing from their own pool — subsequent slot connections return instantly from the hot path"),
        numbered("subscriber-profile-api returns 201 with sim_id and static_ip to aaa-lookup-service"),
        numbered("aaa-lookup-service returns 200 with static_ip to aaa-radius-server"),
        numbered("aaa-radius-server sets Framed-IP-Address and issues RADIUS Access-Accept"),
        numbered("On next connect: aaa-lookup-service returns 200 immediately from the DB hot-path"),
        spacer(80),

        hdr("7.2 Key Metrics to Watch", HeadingLevel.HEADING_2),
        table(
          ["Metric", "Grafana Panel", "Action if High"],
          [
            ["first_connection_total{result=not_found}", "First-Connection Results", "IMSI is outside all range configs; check range config coverage"],
            ["first_connection_total{result=pool_exhausted}", "Pool Exhaustion Events", "Create new IP pool and expand range config immediately"],
            ["lookup_latency_ms{quantile=0.99}", "Lookup p99 Latency", "Alert fires at 15ms; check DB replica lag and query performance"],
            ["lookup_result_total{result=not_found}", "Not-Found Rate", "Spike indicates range misconfiguration or new IMSI batch not in ranges"],
          ],
          [3000, 2600, 3760]
        ),
        spacer(80),

        hdr("7.3 Verify a Provisioned Subscriber After First Connection", HeadingLevel.HEADING_2),
        code("# Find the subscriber by IMSI"),
        code("GET /v1/profiles?imsi=278773000002042"),
        code(""),
        code("# Check the assigned IP"),
        code("GET /v1/profiles/{sim_id}/imsis/278773000002042"),
        code(""),
        code("# Check pool utilization"),
        code("GET /v1/pools/{pool_id}/stats"),
        spacer(80),

        hdr("7.4 aaa-radius-server Integration Points", HeadingLevel.HEADING_2),
        para("aaa-radius-server is the entry point for all subscriber authentication events. It makes a single upstream call to aaa-lookup-service, which handles first-connection allocation internally when needed:"),
        spacer(40),
        table(
          ["Backend Service", "Called When", "Endpoint", "Protocol"],
          [
            ["aaa-lookup-service", "Every RADIUS Access-Request", "GET http://aaa-lookup-service:8081/lookup?imsi={imsi}&apn={apn}&imei={imei}&use_case_id={id}", "HTTP/1.1 + Bearer JWT"],
          ],
          [2200, 2200, 3200, 1760]
        ),
        spacer(60),
        para("Response handling by aaa-radius-server:"),
        bullet("200 OK → extract static_ip, set Framed-IP-Address, send Access-Accept"),
        bullet("403 Forbidden (suspended) → send Access-Reject"),
        bullet("404 Not Found (no range config for IMSI) → send Access-Reject"),
        bullet("503 Service Unavailable (pool exhausted) → send Access-Reject"),
        bullet("Any curl error or unexpected status → send Access-Reject and alert"),
        spacer(60),
        noteBox("Tip", "aaa-radius-server adds a Bearer JWT to its request to aaa-lookup-service. In development, set JWT_SKIP_VERIFY=true on both aaa-lookup-service and subscriber-profile-api to bypass token validation."),
        spacer(40),
        noteBox("RADIUS_SECRET", "aaa-radius-server requires RADIUS_SECRET to be explicitly set — there is no default value. Configure it via a Kubernetes Secret (secretKeyRef) or the .env file when running locally. The secret must match the shared secret configured on all NAS devices that send Access-Requests to the server.", ORANGE_BG),

        // ── 8. Common Tasks ─────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("8. Common Operational Tasks"),

        hdr("8.1 List All Pools for an Account", HeadingLevel.HEADING_2),
        code("GET /v1/pools?account_name=Melita"),

        hdr("8.2 Find a Profile by ICCID", HeadingLevel.HEADING_2),
        code("GET /v1/profiles?iccid=8944501012345678901"),
        spacer(80),

        hdr("8.3 Update a Range Config Pool", HeadingLevel.HEADING_2),
        para("If a range config needs to draw from a different pool (e.g., the original pool is nearly exhausted):"),
        code("PATCH /v1/range-configs/{id}"),
        code("{\"pool_id\": \"new-pool-uuid\"}"),
        spacer(60),
        noteBox("Note", "Changing the pool_id on a range config only affects new first-connection allocations. Already-provisioned subscribers keep their original IP."),
        spacer(80),

        hdr("8.4 Expand IP Capacity for a Subscriber Segment", HeadingLevel.HEADING_2),
        numbered("Create a new pool with additional IP subnet"),
        numbered("PATCH the range config to reference the new pool_id"),
        numbered("Verify with GET /v1/pools/{new_pool_id}/stats"),
        numbered("Monitor first_connection_total{result=pool_exhausted} drops to zero"),
        spacer(80),

        hdr("8.5 Perform a Migration Import", HeadingLevel.HEADING_2),
        numbered("Export subscribers from source system to JSON or CSV"),
        numbered("Ensure each profile has: account_name, status, ip_resolution, IMSI(s), and IP assignment(s)"),
        numbered("Submit via POST /v1/profiles/bulk with mode=upsert"),
        numbered("Monitor GET /v1/jobs/{job_id} until status=completed"),
        numbered("Verify failed count and review errors[] for any rejected rows"),
        numbered("Spot-check: GET /v1/profiles?imsi={sample_imsi} for a few known subscribers"),

        // ── 9. Error Reference ──────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("9. Error Reference"),
        para("All error responses follow this format:"),
        code("{\"detail\": \"<error message>\"}"),
        spacer(80),
        table(
          ["HTTP Status", "Meaning", "Common Causes"],
          [
            ["400 Bad Request", "Validation error", "Invalid IMSI length, unknown ip_resolution, CIDR overlaps, missing required field"],
            ["401 Unauthorized", "Invalid or missing JWT", "Token expired, wrong public key, JWT_SKIP_VERIFY not set in dev"],
            ["404 Not Found", "Resource not found", "Wrong sim_id, IMSI not in DB, range config missing"],
            ["409 Conflict", "Duplicate resource", "IMSI already assigned to another profile, ICCID already exists"],
            ["422 Unprocessable", "Semantic validation failure", "IP not in pool range, pool status suspended"],
            ["503 Service Unavailable", "Pool exhausted or DB down", "IP pool has no available IPs; DB primary unreachable"],
          ],
          [1800, 2200, 5360]
        ),
        spacer(80),

        hdr("9.1 Common Validation Rules", HeadingLevel.HEADING_2),
        table(
          ["Field", "Rule"],
          [
            ["imsi", "Exactly 15 decimal digits"],
            ["iccid", "19 or 20 decimal digits"],
            ["status", "Must be one of: active, suspended, terminated"],
            ["ip_resolution", "Must be one of: imsi, imsi_apn, iccid, iccid_apn"],
            ["static_ip", "Must be a valid IPv4 address within the referenced pool's subnet"],
            ["subnet (pool)", "Valid CIDR notation; start_ip must be within subnet; end_ip must be broadcast"],
          ],
          [2400, 6960]
        ),

        // ── 10. Developer / Local Setup ──────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("10. Local Development Setup"),

        hdr("10.1 Bootstrap the Full Stack", HeadingLevel.HEADING_2),
        para("Requirements: Docker Desktop, k3d, kubectl, helm, and make."),
        code("# Clone the repository"),
        code("git clone https://github.com/your-org/aaa-cloud-native && cd aaa-cloud-native"),
        code(""),
        code("# Bootstrap: creates k3d cluster, builds all images, deploys everything"),
        code("make bootstrap"),
        code(""),
        code("# Verify all pods are running"),
        code("make status"),
        spacer(60),
        noteBox("First-time setup", "Before bootstrapping, copy the example env files and fill in the required secrets:\n  cp aaa-regression-tester/.env.example aaa-regression-tester/.env\n  cp subscriber-profile-api/.env.example subscriber-profile-api/.env\nAt minimum, set DB_PASSWORD and RADIUS_SECRET (RADIUS_SECRET has no default and is required for aaa-radius-server and the regression tests)."),
        spacer(80),

        hdr("10.2 Useful Make Targets", HeadingLevel.HEADING_2),
        table(
          ["Command", "Description"],
          [
            ["make deploy", "Deploy or upgrade all Helm charts"],
            ["make test", "Run the full regression test suite as a K8s Job"],
            ["make port-forward-api", "Forward subscriber-profile-api to localhost:8080"],
            ["make port-forward-lookup", "Forward aaa-lookup-service to localhost:8081"],
            ["make port-forward-db", "Forward PostgreSQL to localhost:5432"],
            ["make port-forward-grafana", "Forward Grafana to localhost:3000 (admin/dev-grafana)"],
            ["make logs-api", "Tail subscriber-profile-api logs"],
            ["make logs-lookup", "Tail aaa-lookup-service logs"],
            ["make status", "Show all pod statuses in aaa-platform namespace"],
          ],
          [3200, 6160]
        ),
        spacer(80),

        hdr("10.3 Connect to the Database Directly", HeadingLevel.HEADING_2),
        code("make port-forward-db"),
        code("# In another terminal (uses DB_URL from Makefile, override via env vars):"),
        code("make psql"),
        code("# Or connect directly:"),
        code("psql \"postgres://aaa_app:devpassword@localhost:5432/aaa\""),
        code("# Override for non-local environments:"),
        code("DB_HOST=prod-db.example.com DB_PASSWORD=secret make psql"),
        code(""),
        code("-- Check subscriber count"),
        code("SELECT COUNT(*) FROM sim_profiles;"),
        code(""),
        code("-- Check pool availability"),
        code("SELECT p.pool_name, COUNT(a.ip) AS available"),
        code("FROM ip_pools p"),
        code("LEFT JOIN ip_pool_available a ON a.pool_id = p.pool_id"),
        code("GROUP BY p.pool_name;"),
        spacer(80),

        hdr("10.4 Development Auth (JWT Skip)", HeadingLevel.HEADING_2),
        para("In development mode (JWT_SKIP_VERIFY=true), any Bearer token is accepted. Use:"),
        code("curl -H 'Authorization: Bearer dev-token' http://provisioning.aaa.localhost/health"),
        spacer(60),
        para("In production, configure the JWT algorithm and key on both backend services:"),
        table(
          ["Service", "Env Var", "Value"],
          [
            ["subscriber-profile-api", "JWT_ALGORITHM", "RS256 (default) or HS256 — must match your token issuer"],
            ["subscriber-profile-api", "JWT_PUBLIC_KEY", "RS256 public key in PEM format (required when JWT_SKIP_VERIFY=false)"],
            ["aaa-lookup-service", "jwt.secretName (Helm)", "Name of a Kubernetes Secret with key 'public-key' (RS256 PEM)"],
          ],
          [2800, 2200, 4360]
        ),
        spacer(60),
        noteBox("Security Warning", "Never deploy with JWT_SKIP_VERIFY=true in production. Always configure a proper RS256 public key. Both aaa-lookup-service and subscriber-profile-api must use the same algorithm and key as the issuer.", ORANGE_BG),
        spacer(80),

        hdr("10.5 Run Regression Tests Locally (Docker Compose)", HeadingLevel.HEADING_2),
        para("You can run the full regression suite without k3d using docker-compose:"),
        code("cd aaa-regression-tester"),
        code(""),
        code("# 1. Create and edit the env file"),
        code("cp .env.example .env"),
        code("# Edit .env: set DB_PASSWORD and RADIUS_SECRET (both required)"),
        code(""),
        code("# 2. Start the stack"),
        code("docker compose -f docker-compose.test.yml up -d"),
        code(""),
        code("# 3. Run the tests"),
        code("docker compose -f docker-compose.test.yml run --rm tester"),
        code(""),
        code("# 4. Tear down"),
        code("docker compose -f docker-compose.test.yml down --volumes"),
        spacer(60),
        noteBox("RADIUS_SECRET required", "RADIUS_SECRET has no default value. The docker-compose stack will refuse to start if RADIUS_SECRET is not set in .env. This prevents accidental deployment with a known-insecure shared secret."),
      ],
    },
  ],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("docs/aaa-platform-user-guide.docx", buf);
  console.log("Created: docs/aaa-platform-user-guide.docx");
});
