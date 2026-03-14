const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  ExternalHyperlink, Bookmark, InternalHyperlink, TableOfContents
} = require('docx');
const fs = require('fs');

// ── helpers ──────────────────────────────────────────────────────────────────
const BRAND_BLUE   = "1F497D";
const LIGHT_BLUE   = "D5E8F0";
const HEADER_BLUE  = "2E75B6";
const LIGHT_GRAY   = "F2F2F2";
const DARK_GRAY    = "404040";
const WHITE        = "FFFFFF";
const GREEN        = "375623";
const GREEN_BG     = "E2EFDA";
const ORANGE_BG    = "FCE4D6";
const ORANGE_TXT   = "833C00";

const PAGE_W = 12240; // US Letter width DXA
const PAGE_H = 15840;
const MARGIN = 1440;
const CONTENT_W = PAGE_W - MARGIN * 2; // 9360

const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
const cellPad = { top: 80, bottom: 80, left: 120, right: 120 };

function hdr(text, lvl = HeadingLevel.HEADING_1) {
  return new Paragraph({
    heading: lvl,
    children: [new TextRun({ text, bold: lvl === HeadingLevel.HEADING_1 })],
  });
}

function para(text, opts = {}) {
  const { bold, italic, size, color, spacing, alignment, indent } = opts;
  return new Paragraph({
    alignment,
    spacing: spacing || { after: 120 },
    indent,
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

function numbered(text) {
  return new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    spacing: { after: 80 },
    children: [new TextRun({ text })],
  });
}

function divider(color = "CCCCCC") {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color, space: 1 } },
    children: [],
  });
}

function spacer(after = 200) {
  return new Paragraph({ spacing: { after }, children: [] });
}

function codeBlock(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    shading: { fill: "F0F0F0", type: ShadingType.CLEAR },
    border: {
      top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 1 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 1 },
    },
    indent: { left: 360, right: 0 },
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "1E1E1E" })],
  });
}

function twoColTable(col1, col2, w1 = 2400, w2 = CONTENT_W - 2400) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [w1, w2],
    rows: [new TableRow({
      children: [
        new TableCell({ borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } }, width: { size: w1, type: WidthType.DXA }, margins: { top: 0, bottom: 0, left: 0, right: 200 }, verticalAlign: VerticalAlign.TOP, children: col1 }),
        new TableCell({ borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } }, width: { size: w2, type: WidthType.DXA }, margins: cellPad, verticalAlign: VerticalAlign.TOP, children: col2 }),
      ],
    })],
  });
}

function infoBox(label, text, bg = LIGHT_BLUE) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: cellBorder, bottom: cellBorder, left: { style: BorderStyle.SINGLE, size: 8, color: HEADER_BLUE }, right: cellBorder },
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

// ── DOCUMENT ──────────────────────────────────────────────────────────────────
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
    default: {
      document: { run: { font: "Arial", size: 22 } },
    },
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
    // ── Cover page ─────────────────────────────────────────────────────────
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
          children: [new TextRun({ text: "Product Description & Message Flow Reference", size: 32, color: HEADER_BLUE, font: "Arial" })],
        }),
        divider(HEADER_BLUE),
        spacer(80),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 40 },
          children: [new TextRun({ text: "High-Performance Telecom Subscriber Provisioning & AAA", size: 24, italic: true, color: DARK_GRAY })],
        }),
        spacer(1800),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Version 1.0   |   March 2026", size: 22, color: DARK_GRAY })],
        }),
        new Paragraph({ children: [new PageBreak()] }),
      ],
    },
    // ── Main body ──────────────────────────────────────────────────────────
    {
      properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE } },
            spacing: { after: 80 },
            children: [
              new TextRun({ text: "AAA Cloud-Native Platform  |  Product Description", color: HEADER_BLUE, size: 18 }),
            ],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: HEADER_BLUE } },
            spacing: { before: 80 },
            children: [
              new TextRun({ text: "Confidential  |  Page ", size: 18, color: DARK_GRAY }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, color: DARK_GRAY }),
              new TextRun({ text: " of ", size: 18, color: DARK_GRAY }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: DARK_GRAY }),
            ],
          })],
        }),
      },
      children: [
        // ── TOC ──────────────────────────────────────────────────────────
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({ children: [new PageBreak()] }),

        // ── 1. Executive Summary ─────────────────────────────────────────
        hdr("1. Executive Summary", HeadingLevel.HEADING_1),
        para("The AAA Cloud-Native Platform is a production-grade, Kubernetes-native telecom infrastructure system designed to deliver Authentication, Authorization, and Accounting (AAA) services for mobile networks. It enables mobile operators to provision subscriber SIM cards, manage IP address pools, and provide real-time RADIUS/Diameter authentication with an industry-leading sub-15ms p99 hot-path latency SLA."),
        spacer(80),
        infoBox("Key Value Proposition", "The platform separates the high-frequency read path (RADIUS hot-path, millions of requests/day) from the low-frequency write path (subscriber provisioning), enabling each to be independently scaled, optimized, and deployed. A single unknown IMSI triggers a one-time dynamic allocation that auto-provisions all sibling SIM slots in a single atomic transaction."),
        spacer(120),
        hdr("Key Capabilities", HeadingLevel.HEADING_2),
        bullet("Sub-15ms p99 IMSI lookup latency for real-time RADIUS Access-Requests", "Performance: "),
        bullet("Dynamic first-connection allocation with automatic Multi-IMSI SIM provisioning in one atomic transaction", "Zero-touch provisioning: "),
        bullet("Full subscriber lifecycle management via RESTful provisioning API", "Lifecycle management: "),
        bullet("CIDR-based IP pool management with race-safe concurrent allocation", "IP pool management: "),
        bullet("Async bulk operations supporting up to 100,000 profiles per job", "Bulk operations: "),
        bullet("CloudNativePG PostgreSQL with PgBouncer, Prometheus metrics, and Grafana dashboards", "Observability: "),

        // ── 2. Platform Architecture ────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("2. Platform Architecture", HeadingLevel.HEADING_1),
        para("The platform is composed of four runtime services backed by a PostgreSQL 15 database cluster deployed on Kubernetes using Helm charts."),
        spacer(80),

        table(
          ["Component", "Technology", "Role", "Port"],
          [
            ["aaa-radius-server", "RADIUS / Diameter stack", "Authentication frontend; routes Access-Requests to aaa-lookup-service; calls subscriber-profile-api on first connection", "1812 UDP"],
            ["aaa-lookup-service", "C++17 / Drogon", "RADIUS hot-path IMSI lookup (read-only); called by aaa-radius-server on every Access-Request", "8081"],
            ["subscriber-profile-api", "Python 3.11 / FastAPI", "Subscriber provisioning & first-connection allocation; called by aaa-radius-server when aaa-lookup-service returns 404", "8080"],
            ["PostgreSQL (CloudNativePG)", "PostgreSQL 15", "Primary + read replicas via PgBouncer", "5432"],
            ["aaa-management-ui", "React / Node.js", "Operator web dashboard", "80"],
            ["aaa-regression-tester", "Python / pytest", "End-to-end regression test suite (K8s Job)", "N/A"],
          ],
          [2200, 2100, 3460, 1400]
        ),
        spacer(120),
        hdr("2.1 aaa-radius-server — RADIUS Frontend", HeadingLevel.HEADING_2),
        para("aaa-radius-server is the RADIUS authentication gateway for the platform. It receives RADIUS Access-Request messages from network equipment (e.g., PGW, ePDG) and orchestrates the two-stage authentication flow:"),
        bullet("Stage 1 — Hot path: On every Access-Request, aaa-radius-server sends a GET /lookup request to aaa-lookup-service with the subscriber IMSI and APN. If the lookup succeeds (HTTP 200), aaa-radius-server extracts the Framed-IP-Address from the response and issues a RADIUS Access-Accept immediately. End-to-end latency target: <15ms p99."),
        bullet("Stage 2 — First connection: If aaa-lookup-service returns HTTP 404 (IMSI not yet provisioned), aaa-radius-server falls through to a POST /v1/first-connection call on subscriber-profile-api. The API dynamically allocates an IP address, creates the subscriber profile, and returns a device_id and static_ip. aaa-radius-server then issues an Access-Accept with the assigned IP."),
        bullet("Reject path: If subscriber-profile-api returns 404 (no matching range config) or the subscriber is suspended (HTTP 403), aaa-radius-server issues a RADIUS Access-Reject."),
        spacer(80),

        hdr("2.2 Architecture Principles", HeadingLevel.HEADING_2),
        bullet("Read/Write path separation: aaa-lookup-service reads from a local read-replica; subscriber-profile-api writes to the primary only."),
        bullet("Idempotency by design: /first-connection returns the same result for repeated calls for the same IMSI."),
        bullet("Atomic multi-IMSI provisioning: all sibling SIM slots are provisioned in a single database transaction to guarantee consistency."),
        bullet("Race-safe IP allocation: SELECT FOR UPDATE SKIP LOCKED prevents concurrent threads from claiming the same IP address."),
        bullet("Horizontal scalability: each service scales independently; aaa-lookup-service can be co-located with RADIUS servers per region."),
        spacer(120),

        hdr("2.3 Deployment Topology", HeadingLevel.HEADING_2),
        para("All components run in the aaa-platform Kubernetes namespace. The umbrella Helm chart aaa-platform orchestrates all sub-charts. aaa-radius-server is deployed per-region and co-located with network access nodes to minimise round-trip latency."),
        spacer(60),
        table(
          ["Service", "Dev Replicas", "Prod Replicas", "RAM", "CPU"],
          [
            ["aaa-radius-server", "1 per region", "2-6 per region", "256 Mi", "500m"],
            ["aaa-lookup-service", "1", "3-6 per region", "256 Mi", "500m"],
            ["subscriber-profile-api", "1", "2-4", "512 Mi", "1000m"],
            ["PostgreSQL (primary)", "1", "1 primary + 2 standbys", "512 Mi", "250m"],
            ["PgBouncer", "1", "1 per pool", "64 Mi", "100m"],
            ["aaa-management-ui", "1", "1-2", "128 Mi", "200m"],
          ],
          [2500, 1500, 2200, 1580, 1480]
        ),

        // ── 3. Data Model ────────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("3. Data Model", HeadingLevel.HEADING_1),
        para("The platform uses 8 PostgreSQL tables organized into three logical groups: subscriber data, IP pool management, and configuration."),
        spacer(80),

        hdr("3.1 Subscriber Tables", HeadingLevel.HEADING_2),
        table(
          ["Table", "Primary Key", "Description"],
          [
            ["subscriber_profiles", "device_id (UUID)", "One row per physical SIM card. Stores ICCID, account, status, and ip_resolution mode."],
            ["subscriber_imsis", "imsi (TEXT, 15 digits)", "One row per IMSI. Multiple IMSIs may share the same device_id (Multi-IMSI SIM)."],
            ["subscriber_apn_ips", "id (BIGINT)", "Per-IMSI static IP assignments. APN may be NULL for wildcard (any APN)."],
            ["subscriber_iccid_ips", "id (BIGINT)", "Card-level static IP assignments shared by all IMSIs on the card."],
          ],
          [2400, 2000, 4960]
        ),
        spacer(80),

        hdr("3.2 IP Pool Tables", HeadingLevel.HEADING_2),
        table(
          ["Table", "Description"],
          [
            ["ip_pools", "One row per subnet. Stores CIDR, start/end IP, account, and status."],
            ["ip_pool_available", "Work-queue of unallocated IPs. Pre-populated at pool creation. Rows deleted when allocated."],
          ],
          [3000, 6360]
        ),
        spacer(80),

        hdr("3.3 Configuration Tables", HeadingLevel.HEADING_2),
        table(
          ["Table", "Description"],
          [
            ["imsi_range_configs", "Defines IMSI ranges eligible for dynamic first-connection allocation. Links to an IP pool."],
            ["iccid_range_configs", "Parent table for Multi-IMSI SIM ranges. Each ICCID range has 1-10 child IMSI slot ranges."],
          ],
          [3000, 6360]
        ),
        spacer(80),

        hdr("3.4 IP Resolution Modes", HeadingLevel.HEADING_2),
        para("The ip_resolution field on subscriber_profiles controls how the lookup service selects the IP address for an Access-Request:"),
        spacer(60),
        table(
          ["Mode", "IP Storage Table", "Description"],
          [
            ["imsi", "subscriber_apn_ips", "One IP per IMSI, APN-agnostic. All APNs get the same IP."],
            ["imsi_apn", "subscriber_apn_ips", "One IP per IMSI per APN. Different APNs may have different IPs."],
            ["iccid", "subscriber_iccid_ips", "One IP per SIM card, APN-agnostic. All IMSIs on the card share one IP."],
            ["iccid_apn", "subscriber_iccid_ips", "One IP per SIM card per APN."],
          ],
          [1600, 2400, 5360]
        ),

        // ── 4. API Reference ─────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("4. API Reference", HeadingLevel.HEADING_1),
        para("The subscriber-profile-api exposes a RESTful HTTP API. All endpoints require a Bearer JWT token (OAuth 2.0 client_credentials). Development mode can bypass JWT by setting JWT_SKIP_VERIFY=true."),
        spacer(60),
        para("Base URL: https://provisioning.aaa-platform.example.com/v1", { bold: true }),
        spacer(100),

        hdr("4.1 Subscriber Profiles", HeadingLevel.HEADING_2),
        table(
          ["Method", "Path", "Description", "Status"],
          [
            ["POST", "/v1/profiles", "Create a new subscriber profile with IMSIs and IP assignments", "201 Created"],
            ["GET", "/v1/profiles/{device_id}", "Get profile by UUID", "200 OK"],
            ["GET", "/v1/profiles?iccid={iccid}", "Find profile by ICCID", "200 / 404"],
            ["GET", "/v1/profiles?account_name={name}", "Paginated list by account (max 1000/page)", "200 OK"],
            ["PUT", "/v1/profiles/{device_id}", "Replace full profile", "200 OK"],
            ["PATCH", "/v1/profiles/{device_id}", "Partial update (JSON Merge Patch)", "200 OK"],
            ["DELETE", "/v1/profiles/{device_id}", "Soft-delete (sets status=terminated)", "204 No Content"],
          ],
          [900, 2900, 3860, 1700]
        ),
        spacer(80),

        hdr("4.2 IMSI Operations", HeadingLevel.HEADING_2),
        table(
          ["Method", "Path", "Description", "Status"],
          [
            ["GET", "/v1/profiles/{id}/imsis", "List all IMSIs on the device", "200 OK"],
            ["POST", "/v1/profiles/{id}/imsis", "Add an IMSI with APN-IP assignments", "201 Created"],
            ["PATCH", "/v1/profiles/{id}/imsis/{imsi}", "Update IMSI status, priority, or APN-IPs", "200 OK"],
            ["DELETE", "/v1/profiles/{id}/imsis/{imsi}", "Remove IMSI and all its IP assignments", "204 No Content"],
          ],
          [900, 2900, 3860, 1700]
        ),
        spacer(80),

        hdr("4.3 IP Pools", HeadingLevel.HEADING_2),
        table(
          ["Method", "Path", "Description", "Status"],
          [
            ["POST", "/v1/pools", "Create pool and pre-populate available IP work-queue (synchronous)", "201 Created"],
            ["GET", "/v1/pools/{pool_id}", "Get pool definition", "200 OK"],
            ["GET", "/v1/pools/{pool_id}/stats", "Get {total, allocated, available} counts", "200 OK"],
            ["PATCH", "/v1/pools/{pool_id}", "Update pool name or status", "200 OK"],
            ["DELETE", "/v1/pools/{pool_id}", "Delete pool (409 if allocated IPs > 0)", "204 / 409"],
          ],
          [900, 2900, 3860, 1700]
        ),
        spacer(80),

        hdr("4.4 Range Configurations", HeadingLevel.HEADING_2),
        table(
          ["Method", "Path", "Description"],
          [
            ["POST/GET/PATCH/DELETE", "/v1/range-configs", "Standalone IMSI range configs for single-IMSI provisioning"],
            ["POST/GET/PATCH/DELETE", "/v1/iccid-range-configs", "Parent ICCID ranges for Multi-IMSI SIM provisioning"],
            ["POST/PATCH/DELETE", "/v1/iccid-range-configs/{id}/imsi-slots", "Child IMSI slot ranges (1-10 per ICCID range)"],
          ],
          [2400, 2700, 4260]
        ),
        spacer(80),

        hdr("4.5 Special Endpoints", HeadingLevel.HEADING_2),
        table(
          ["Method", "Path", "Description"],
          [
            ["POST", "/v1/first-connection", "Dynamic IMSI allocation triggered by aaa-radius-server on unknown IMSI (idempotent)"],
            ["POST", "/v1/profiles/bulk", "Async bulk upsert up to 100K profiles (JSON or CSV), returns job_id"],
            ["GET", "/v1/jobs/{job_id}", "Poll bulk job status: queued / processing / completed"],
            ["GET", "/health", "Liveness probe"],
            ["GET", "/health/db", "DB primary connectivity check (503 if unreachable)"],
          ],
          [900, 2900, 5560]
        ),

        // ── 5. Message Flows ─────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("5. Supported Message Flows", HeadingLevel.HEADING_1),

        // Flow 1
        hdr("5.1 RADIUS Hot-Path Lookup (Happy Path)", HeadingLevel.HEADING_2),
        para("This is the primary steady-state flow, executed on every RADIUS Access-Request. The aaa-lookup-service handles this path exclusively with a read-replica database query."),
        spacer(80),
        infoBox("SLA", "p99 end-to-end latency < 15ms. Achieved via single-query hot-path on an indexed read-replica with near 100% cache hit rate at steady state.", LIGHT_BLUE),
        spacer(120),

        hdr("Step-by-Step", HeadingLevel.HEADING_3),
        numbered("aaa-radius-server sends: GET /lookup?imsi={imsi}&apn={apn} with Bearer JWT"),
        numbered("aaa-lookup-service validates the JWT (RS256) and queries the READ_REPLICA using the core lookup SQL"),
        numbered("Resolver applies ip_resolution logic: for mode 'imsi', returns subscriber_apn_ips.static_ip; for 'iccid', returns subscriber_iccid_ips.static_ip"),
        numbered("Response 200 {\"static_ip\": \"100.65.120.5\"} is returned"),
        numbered("aaa-radius-server sets Framed-IP-Address attribute and sends Access-Accept"),
        spacer(80),

        hdr("Response Codes", HeadingLevel.HEADING_3),
        table(
          ["HTTP Status", "RADIUS Action", "Meaning"],
          [
            ["200 OK", "Access-Accept + Framed-IP-Address", "Subscriber active, IP found"],
            ["403 Forbidden", "Access-Reject (suspended)", "Subscriber or IMSI status = suspended"],
            ["404 Not Found", "Triggers Stage 2 (first-connection)", "IMSI not in database"],
            ["503 Service Unavailable", "Access-Reject (temporary)", "Database unavailable"],
          ],
          [1800, 3200, 4360]
        ),
        spacer(80),

        hdr("Core Lookup SQL (executed on every RADIUS request)", HeadingLevel.HEADING_3),
        codeBlock("SELECT sp.device_id, sp.status AS sim_status, sp.ip_resolution,"),
        codeBlock("       si.status AS imsi_status,"),
        codeBlock("       sa.apn AS imsi_apn,    sa.static_ip AS imsi_static_ip,"),
        codeBlock("       ci.apn AS iccid_apn,   ci.static_ip AS iccid_static_ip"),
        codeBlock("FROM   subscriber_imsis si"),
        codeBlock("JOIN   subscriber_profiles sp ON sp.device_id = si.device_id"),
        codeBlock("LEFT JOIN subscriber_apn_ips  sa ON sa.imsi = si.imsi"),
        codeBlock("LEFT JOIN subscriber_iccid_ips ci ON ci.device_id = sp.device_id"),
        codeBlock("WHERE  si.imsi = $1;"),
        spacer(60),
        para("Performance: Index seek on subscriber_imsis.imsi (PK) -> nested loop on subscriber_profiles (PK) -> left-joins on low-cardinality IP tables. Typical: p50 1-3ms, p99 3-8ms on a warm replica.", { italic: true, color: DARK_GRAY }),

        // Flow 2
        new Paragraph({ children: [new PageBreak()] }),
        hdr("5.2 Two-Stage First-Connection Allocation", HeadingLevel.HEADING_2),
        para("When aaa-lookup-service returns 404, aaa-radius-server falls through to Stage 2: calling subscriber-profile-api to dynamically allocate and register the unknown IMSI. This flow is rare once the network is warm."),
        spacer(80),

        hdr("Stage 1 (aaa-lookup-service) -> 404", HeadingLevel.HEADING_3),
        numbered("aaa-radius-server sends: GET /lookup?imsi=278773000002042&apn=internet.operator.com"),
        numbered("Query returns 0 rows: IMSI not in subscriber_imsis"),
        numbered("aaa-lookup-service responds: 404 {\"error\": \"not_found\"}"),
        numbered("aaa-radius-server falls through to Stage 2"),
        spacer(80),

        hdr("Stage 2 (subscriber-profile-api) - Single-IMSI Path", HeadingLevel.HEADING_3),
        numbered("aaa-radius-server sends: POST /v1/first-connection {\"imsi\": \"278773000002042\", \"apn\": \"internet.operator.com\", \"imei\": \"...\"}"),
        numbered("Idempotency check: SELECT from subscriber_imsis WHERE imsi=$1. If found, return existing IP immediately."),
        numbered("Range config lookup: SELECT from imsi_range_configs WHERE $imsi BETWEEN f_imsi AND t_imsi AND status='active'"),
        numbered("If no range config found: return 404 (IMSI not authorized for auto-provisioning)"),
        numbered("BEGIN TRANSACTION on PRIMARY"),
        numbered("Claim IP (atomic, race-safe): DELETE FROM ip_pool_available WHERE ip = (SELECT ip ... FOR UPDATE SKIP LOCKED) RETURNING ip"),
        numbered("If pool empty: ROLLBACK, return 503 {\"error\": \"pool_exhausted\"}"),
        numbered("INSERT subscriber_profiles, subscriber_imsis, subscriber_apn_ips (or iccid_ips based on ip_resolution mode)"),
        numbered("COMMIT"),
        numbered("Return 200 {\"device_id\": \"...\", \"static_ip\": \"100.65.120.5\"}"),
        numbered("aaa-radius-server issues Access-Accept with Framed-IP-Address"),
        spacer(80),

        infoBox("Idempotency Guarantee", "If aaa-radius-server retries the POST /first-connection call (e.g., on timeout), the second call detects the already-provisioned IMSI in step 2 and returns the same device_id and static_ip without creating duplicates.", GREEN_BG),
        spacer(120),

        // Flow 3
        hdr("5.3 Multi-IMSI SIM First-Connection", HeadingLevel.HEADING_2),
        para("Physical SIM cards can carry 2-10 distinct IMSIs (slots). When the first slot connects, the platform provisions all sibling slots atomically, ensuring subsequent slot connections are served from the fast hot-path immediately."),
        spacer(80),

        hdr("How ICCID-to-IMSI Mapping Works", HeadingLevel.HEADING_3),
        para("The platform uses numeric offset arithmetic: the IMSI number within its range maps to the same position in the ICCID range. This allows the platform to derive the ICCID from any IMSI without needing an explicit lookup table."),
        spacer(60),
        codeBlock("ICCID range: 8944501010000000000 to 8944501010000999999"),
        codeBlock("Slot 1 IMSI range: 278770000000000 to 278770000999999"),
        codeBlock("Slot 2 IMSI range: 278771000000000 to 278771000999999"),
        codeBlock(""),
        codeBlock("IMSI = 278770000000042  (offset = 42)"),
        codeBlock("Derived ICCID = 8944501010000000000 + 42 = 8944501010000000042"),
        codeBlock("Slot 2 sibling = 278771000000000 + 42 = 278771000000042"),
        spacer(80),

        hdr("Multi-IMSI Allocation Sequence", HeadingLevel.HEADING_3),
        numbered("Stage 1: GET /lookup for slot-1 IMSI returns 404"),
        numbered("Stage 2: POST /first-connection with slot-1 IMSI"),
        numbered("Range config matched to an iccid_range_config (iccid_range_id IS NOT NULL)"),
        numbered("Compute offset and derive ICCID"),
        numbered("Lock: SELECT FROM subscriber_profiles WHERE iccid=$derived_iccid FOR UPDATE"),
        numbered("Profile does not exist yet (first slot to connect):"),
        sub_bullet("Allocate ONE IP from pool (covers all slots on the card)"),
        sub_bullet("INSERT subscriber_profiles with derived ICCID"),
        sub_bullet("For each sibling IMSI slot range: compute sibling IMSI (same offset), INSERT subscriber_imsis + IP assignment"),
        sub_bullet("All inserts in one COMMIT"),
        numbered("Return 200 with allocated IP"),
        numbered("Next time slot 2 IMSI connects: Stage 1 returns 200 immediately (pre-provisioned)"),
        spacer(80),

        infoBox("Key Benefit", "Only ONE IP is allocated per physical SIM card regardless of how many IMSI slots it carries. All slots share the same IP, and only one first-connection transaction ever runs per card.", LIGHT_BLUE),

        // Flow 4
        new Paragraph({ children: [new PageBreak()] }),
        hdr("5.4 Manual Subscriber Provisioning", HeadingLevel.HEADING_2),
        para("Operators can pre-provision subscribers via the REST API before they connect to the network. This bypasses the two-stage flow entirely."),
        spacer(80),

        hdr("Profile B: IMSI-Level IP Assignment", HeadingLevel.HEADING_3),
        codeBlock("POST /v1/profiles"),
        codeBlock("{"),
        codeBlock("  \"account_name\": \"Melita\","),
        codeBlock("  \"status\": \"active\","),
        codeBlock("  \"ip_resolution\": \"imsi\","),
        codeBlock("  \"imsis\": [{"),
        codeBlock("    \"imsi\": \"278773000002002\","),
        codeBlock("    \"apn_ips\": [{\"static_ip\": \"100.65.120.5\", \"pool_id\": \"<uuid>\"}]"),
        codeBlock("  }]"),
        codeBlock("}"),
        codeBlock(""),
        codeBlock("Response 201:"),
        codeBlock("{\"device_id\": \"550e8400-e29b-41d4-a716-446655440000\", \"created_at\": \"2026-03-13T10:00:00Z\"}"),
        spacer(60),
        para("The API validates all fields (15 validation rules), runs the INSERT in a single atomic transaction, and returns the auto-generated device_id UUID."),
        spacer(80),

        hdr("Adding ICCID to an Existing Profile", HeadingLevel.HEADING_3),
        codeBlock("PATCH /v1/profiles/550e8400-e29b-41d4-a716-446655440000"),
        codeBlock("{\"iccid\": \"8944501012345678901\"}"),
        codeBlock(""),
        codeBlock("Response 200: full updated profile"),
        spacer(80),

        hdr("Suspending a Subscriber", HeadingLevel.HEADING_3),
        codeBlock("PATCH /v1/profiles/550e8400-e29b-41d4-a716-446655440000"),
        codeBlock("{\"status\": \"suspended\"}"),
        codeBlock(""),
        codeBlock("Effect: Next RADIUS Access-Request for any IMSI on this device returns 403 Forbidden"),

        // Flow 5
        new Paragraph({ children: [new PageBreak()] }),
        hdr("5.5 Bulk Provisioning Flow", HeadingLevel.HEADING_2),
        para("For batch provisioning of large subscriber datasets (migrations, initial deployments), the bulk API accepts up to 100,000 profiles per job."),
        spacer(80),

        hdr("Submit a Bulk Job", HeadingLevel.HEADING_3),
        codeBlock("POST /v1/profiles/bulk"),
        codeBlock("Content-Type: application/json"),
        codeBlock("{"),
        codeBlock("  \"mode\": \"upsert\","),
        codeBlock("  \"profiles\": [{ ... }, { ... }, ...]  // up to 100,000"),
        codeBlock("}"),
        codeBlock(""),
        codeBlock("Response 202 Accepted:"),
        codeBlock("{\"job_id\": \"abc123\", \"submitted\": 50000, \"status_url\": \"/v1/jobs/abc123\"}"),
        spacer(80),

        hdr("Poll Job Status", HeadingLevel.HEADING_3),
        codeBlock("GET /v1/jobs/abc123"),
        codeBlock(""),
        codeBlock("Response 200:"),
        codeBlock("{"),
        codeBlock("  \"job_id\": \"abc123\","),
        codeBlock("  \"status\": \"processing\","),
        codeBlock("  \"processed\": 25000,"),
        codeBlock("  \"failed\": 3,"),
        codeBlock("  \"errors\": [{\"row\": 42, \"field\": \"imsi\", \"message\": \"Invalid IMSI length\", \"value\": \"1234\"}]"),
        codeBlock("}"),
        spacer(80),

        infoBox("Error Handling", "Failed rows are accumulated in the errors array without aborting the job. The platform continues processing remaining rows and reports a full summary at completion.", ORANGE_BG),
        spacer(120),

        hdr("Bulk Processing Internals", HeadingLevel.HEADING_3),
        bullet("Returns 202 immediately; processing is asynchronous via a configurable thread pool (BULK_WORKER_THREADS, default 2)"),
        bullet("Processes in batches of BULK_BATCH_SIZE (default 1,000) with INSERT ON CONFLICT (upsert semantics)"),
        bullet("CSV upload is also supported via multipart/form-data file upload"),
        bullet("Final status shows processed count, failed count, and per-row error details"),

        // ── 6. Security ──────────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("6. Security & Authentication", HeadingLevel.HEADING_1),

        hdr("6.1 API Authentication", HeadingLevel.HEADING_2),
        bullet("All API endpoints require Authorization: Bearer {JWT} header"),
        bullet("JWT tokens use RS256 (RSA + SHA-256) signed by your OAuth 2.0 Authorization Server"),
        bullet("Public key is configured via JWT_PUBLIC_KEY environment variable (PEM format)"),
        bullet("Development mode: JWT_SKIP_VERIFY=true bypasses signature verification"),
        bullet("Invalid or expired tokens return 401 Unauthorized"),
        spacer(80),

        hdr("6.2 Database Security", HeadingLevel.HEADING_2),
        bullet("aaa-lookup-service connects ONLY to the read-replica (no write access)"),
        bullet("subscriber-profile-api connects to the primary for all operations (reads use primary to avoid stale post-write data)"),
        bullet("Credentials are stored in Kubernetes Secrets (not in Helm values or ConfigMaps)"),
        bullet("PgBouncer enforces connection pooling limits to prevent database overload"),
        spacer(80),

        hdr("6.3 Data Privacy", HeadingLevel.HEADING_2),
        bullet("IMSI values are NEVER logged in raw form; structured logs use SHA-256(imsi)[0:8] as an anonymous identifier"),
        bullet("IMEI is stored in the profile metadata JSONB field (optional, operator-controlled)"),

        // ── 7. Observability ─────────────────────────────────────────────
        hdr("7. Observability", HeadingLevel.HEADING_1),

        hdr("7.1 Prometheus Metrics", HeadingLevel.HEADING_2),
        table(
          ["Metric", "Type", "Description"],
          [
            ["lookup_latency_ms", "Histogram", "aaa-lookup-service end-to-end latency by result label"],
            ["lookup_result_total", "Counter", "Lookup results: resolved, not_found, suspended, apn_not_found"],
            ["first_connection_total", "Counter", "First-connection outcomes: allocated, reused, not_found, pool_exhausted"],
            ["pool_exhausted_total", "Counter", "Pool exhaustion events by pool_id (alert if rate > 0)"],
            ["bulk_job_duration_seconds", "Histogram", "End-to-end bulk job processing time"],
            ["api_request_duration_ms", "Histogram", "All API endpoints by method and path"],
          ],
          [3000, 1400, 4960]
        ),
        spacer(80),

        hdr("7.2 Key Alerts", HeadingLevel.HEADING_2),
        table(
          ["Alert", "Condition", "Action"],
          [
            ["aaa_lookup_p99_high", "lookup_latency_ms p99 > 15ms for > 2 minutes", "Page on-call; check DB replica lag"],
            ["aaa_pool_exhausted", "pool_exhausted_total rate > 0", "Alert ops; expand IP pool"],
            ["aaa_not_found_spike", "not_found rate > 5x baseline", "Alert ops; check range configs"],
            ["db_primary_unavailable", "Primary connection lost", "Page on-call; check CNPG operator"],
          ],
          [2400, 3500, 3460]
        ),

        // ── 8. Configuration Reference ────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("8. Configuration Reference", HeadingLevel.HEADING_1),

        hdr("8.1 subscriber-profile-api", HeadingLevel.HEADING_2),
        table(
          ["Environment Variable", "Default", "Description"],
          [
            ["PRIMARY_URL", "(required)", "PostgreSQL primary connection string (postgresql://user:pw@host:5432/aaa)"],
            ["HTTP_PORT", "8080", "HTTP listener port"],
            ["METRICS_PORT", "9091", "Prometheus metrics port (separate thread)"],
            ["JWT_SKIP_VERIFY", "false", "Set to 'true' to bypass JWT verification in development"],
            ["JWT_PUBLIC_KEY", "(required in prod)", "RS256 public key in PEM format"],
            ["BULK_WORKER_THREADS", "2", "Thread pool size for async bulk job processing"],
            ["BULK_BATCH_SIZE", "1000", "Number of profiles per database batch in bulk operations"],
          ],
          [2800, 1600, 4960]
        ),
        spacer(80),

        hdr("8.2 aaa-lookup-service", HeadingLevel.HEADING_2),
        table(
          ["Environment Variable", "Default", "Description"],
          [
            ["HTTP_PORT", "8081", "HTTP listener port"],
            ["METRICS_PORT", "9090", "Prometheus metrics port"],
            ["DB_HOST", "(required)", "PostgreSQL read-replica hostname"],
            ["DB_POOL_SIZE", "10", "Database connection pool size"],
            ["DB_TIMEOUT", "5", "Query timeout in seconds"],
            ["THREAD_COUNT", "0", "Worker threads; 0 = auto-detect (logical CPU count)"],
            ["JWT_SKIP_VERIFY", "false", "Set to 'true' to bypass JWT verification in development"],
          ],
          [2800, 1600, 4960]
        ),

        // ── Back matter ──────────────────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        hdr("9. Glossary", HeadingLevel.HEADING_1),
        table(
          ["Term", "Definition"],
          [
            ["AAA", "Authentication, Authorization, Accounting — the three functions of RADIUS/Diameter in mobile networks"],
            ["IMSI", "International Mobile Subscriber Identity — 15-digit identifier stored on a SIM card"],
            ["ICCID", "Integrated Circuit Card Identifier — unique 19-20 digit identifier of a physical SIM card"],
            ["APN", "Access Point Name — the gateway identifier used by a device to connect to a specific data service"],
            ["RADIUS", "Remote Authentication Dial-In User Service — protocol used by network equipment to authenticate subscribers"],
            ["ip_resolution", "Platform concept: the rule that determines which IP table and APN matching logic to use for a given profile"],
            ["first-connection", "The one-time event when an unknown IMSI first connects; triggers dynamic provisioning"],
            ["Multi-IMSI SIM", "A physical SIM card that contains multiple IMSIs (up to 10), one per logical slot"],
            ["CloudNativePG", "Kubernetes operator that manages PostgreSQL clusters with automated failover and replication"],
            ["PgBouncer", "Connection pooler for PostgreSQL; reduces per-connection overhead in high-concurrency environments"],
          ],
          [2000, 7360]
        ),
      ],
    },
  ],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("docs/aaa-platform-product-description.docx", buf);
  console.log("Created: docs/aaa-platform-product-description.docx");
});
