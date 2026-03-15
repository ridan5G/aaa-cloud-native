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
        bullet("aaa-radius-server — RADIUS authentication frontend. Receives Access-Requests from network equipment and routes them to the appropriate backend service."),
        bullet("aaa-lookup-service — High-performance read-only IMSI lookup (C++17, port 8081). Called by aaa-radius-server on every Access-Request."),
        bullet("subscriber-profile-api — Provisioning REST API (Python/FastAPI, port 8080). Called by aaa-radius-server when a subscriber is seen for the first time (404 from lookup)."),
        bullet("aaa-management-ui — Operator web dashboard for managing pools, profiles, and bulk jobs."),
        spacer(80),

        hdr("1.1 Prerequisites", HeadingLevel.HEADING_2),
        bullet("Access to the provisioning API (subscriber-profile-api)"),
        bullet("A valid OAuth 2.0 Bearer JWT token (or JWT_SKIP_VERIFY=true for dev/test)"),
        bullet("At least one IP pool created and active"),
        bullet("IMSI range configs defined for any subscriber segments that use first-connection auto-provisioning"),
        bullet("aaa-radius-server configured with the aaa-lookup-service endpoint and subscriber-profile-api endpoint"),
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
        code("POST /v1/iccid-range-configs"),
        code("{"),
        code("  \"account_name\": \"Melita\","),
        code("  \"f_iccid\": \"8944501010000000000\","),
        code("  \"t_iccid\": \"8944501010000999999\","),
        code("  \"pool_id\": \"a1b2c3d4-...\","),
        code("  \"ip_resolution\": \"imsi\","),
        code("  \"imsi_count\": 2,"),
        code("  \"status\": \"active\""),
        code("}"),
        code(""),
        code("Response 201: {\"id\": 42, \"f_iccid\": \"8944501010000000000\", ...}"),
        spacer(80),

        hdr("Step B: Add IMSI slot ranges (one per physical slot)", HeadingLevel.HEADING_3),
        code("POST /v1/iccid-range-configs/42/imsi-slots"),
        code("{"),
        code("  \"f_imsi\": \"278770000000000\","),
        code("  \"t_imsi\": \"278770000999999\","),
        code("  \"imsi_slot\": 1"),
        code("}"),
        spacer(60),
        code("POST /v1/iccid-range-configs/42/imsi-slots"),
        code("{"),
        code("  \"f_imsi\": \"278771000000000\","),
        code("  \"t_imsi\": \"278771000999999\","),
        code("  \"imsi_slot\": 2"),
        code("}"),
        spacer(60),
        noteBox("Cardinality Rule", "Each IMSI slot range must span the same number of addresses as the parent ICCID range. For the example above: 278770000999999 - 278770000000000 = 999999 = 8944501010000999999 - 8944501010000000000."),

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
        code("Response 201: {\"device_id\": \"550e8400-...\", \"created_at\": \"2026-03-13T10:00:00Z\"}"),
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

        // ── 7. First-Connection Monitoring ──────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("7. Monitoring First-Connection Allocation"),
        para("When auto-provisioning is enabled via range configs, subscribers self-register on first network attach. No manual action is required. However, you should monitor the following to detect problems early."),
        spacer(80),

        hdr("7.1 What Happens at First Connection", HeadingLevel.HEADING_2),
        numbered("Device attaches to the mobile network"),
        numbered("aaa-radius-server receives the RADIUS Access-Request and sends GET /lookup?imsi={imsi}&apn={apn} to aaa-lookup-service"),
        numbered("aaa-lookup-service queries the read-replica — returns 404 (IMSI not yet provisioned)"),
        numbered("aaa-radius-server falls through to Stage 2: sends POST /v1/first-connection to subscriber-profile-api"),
        numbered("subscriber-profile-api matches IMSI to a range config, claims an IP, and creates the profile"),
        numbered("subscriber-profile-api returns 200 with device_id and static_ip"),
        numbered("aaa-radius-server sets Framed-IP-Address and issues RADIUS Access-Accept"),
        numbered("On next connect: aaa-lookup-service returns 200 immediately — Stage 2 is skipped entirely"),
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
        code("GET /v1/profiles/{device_id}/imsis/278773000002042"),
        code(""),
        code("# Check pool utilization"),
        code("GET /v1/pools/{pool_id}/stats"),
        spacer(80),

        hdr("7.4 aaa-radius-server Integration Points", HeadingLevel.HEADING_2),
        para("aaa-radius-server is the entry point for all subscriber authentication events. It must be configured with the addresses of both backend services:"),
        spacer(40),
        table(
          ["Backend Service", "Called When", "Endpoint", "Protocol"],
          [
            ["aaa-lookup-service", "Every RADIUS Access-Request (Stage 1 — hot path)", "GET http://aaa-lookup-service:8081/lookup?imsi={imsi}&apn={apn}", "HTTP/1.1 + Bearer JWT"],
            ["subscriber-profile-api", "Only when aaa-lookup-service returns 404 (Stage 2 — first connection)", "POST http://subscriber-profile-api:8080/v1/first-connection", "HTTP/1.1 + Bearer JWT"],
          ],
          [2200, 2200, 3200, 1760]
        ),
        spacer(60),
        para("Response handling by aaa-radius-server:"),
        bullet("aaa-lookup-service 200 OK → extract static_ip, set Framed-IP-Address, send Access-Accept"),
        bullet("aaa-lookup-service 404 → fall through to subscriber-profile-api (Stage 2)"),
        bullet("aaa-lookup-service 403 (suspended) → send Access-Reject"),
        bullet("subscriber-profile-api 200 OK → extract static_ip from first-connection response, send Access-Accept"),
        bullet("subscriber-profile-api 404 (no range config) → send Access-Reject"),
        bullet("Any 5xx or timeout from either service → send Access-Reject and alert"),
        spacer(60),
        noteBox("Tip", "aaa-radius-server adds a Bearer JWT to all requests to both backend services. Ensure the JWT signing key is configured consistently across all three services. In development, set JWT_SKIP_VERIFY=true on both backend services to bypass token validation."),
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
            ["404 Not Found", "Resource not found", "Wrong device_id, IMSI not in DB, range config missing"],
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
        code("SELECT COUNT(*) FROM subscriber_profiles;"),
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
