# Plan 5 — Management UI

## Overview

A browser-based management UI for operators to manage SIM profiles,
IP pools, IMSI range configs, and bulk imports. It talks exclusively to
the `subscriber-profile-api` REST endpoints — no direct DB access.

**Technology:** React + TypeScript + Tailwind CSS (custom theme)
**Deployment:** Static build served via Nginx or CDN, same domain as API
**Auth:** OAuth 2.0 / OIDC login (SSO); JWT stored in memory (not localStorage)
**Target users:** Telecoms operators and platform administrators

---

## Visual Design System

### Design Principles

- **Operator-grade density:** data tables are primary UI elements; prioritise information per viewport over whitespace
- **Amber-on-navy identity:** dark sidebar with a warm amber accent — professional, readable in low-light NOC environments
- **Status at a glance:** every entity (SIM, pool, job) has a colour-coded status dot or badge, never colour-only
- **Progressive disclosure:** summary list → detail page → inline action form — no full-page redirects for routine edits

---

### Colour Tokens

```css
/* === Primary Palette === */
--color-primary:        #F5A623;   /* amber — buttons, active nav, progress bars */
--color-primary-hover:  #E09518;   /* darker amber on hover */
--color-primary-light:  #FEF3DC;   /* tinted amber — selected row, highlight bg */

/* === Sidebar === */
--color-sidebar-bg:     #1C2340;   /* deep navy */
--color-sidebar-active: #F5A623;   /* amber bg for active nav item */
--color-sidebar-text:   #FFFFFF;   /* white labels */
--color-sidebar-muted:  #8892B0;   /* inactive / secondary nav text */
--color-sidebar-hover:  #252D4A;   /* subtle hover row in sidebar */

/* === Top Bar === */
--color-topbar-accent:  #F5A623;   /* 3px top border strip across the full viewport */
--color-topbar-bg:      #FFFFFF;

/* === Content Area === */
--color-bg-page:        #F4F6F9;   /* very light grey page background */
--color-bg-card:        #FFFFFF;   /* card / panel background */
--color-bg-row-hover:   #F8F9FC;   /* table row hover */
--color-border:         #E2E8F0;   /* dividers, table borders */

/* === Typography === */
--color-text-primary:   #1A202C;   /* headings, table values */
--color-text-secondary: #718096;   /* labels, captions, breadcrumbs */
--color-text-disabled:  #A0AEC0;

/* === Semantic Status === */
--color-status-active:       #38A169;   /* green */
--color-status-inactive:     #A0AEC0;   /* grey */
--color-status-suspended:    #F5A623;   /* amber */
--color-status-terminated:   #E53E3E;   /* red */
--color-status-running:      #3182CE;   /* blue — bulk job in progress */
--color-status-queued:       #A0AEC0;   /* grey */
--color-status-completed:    #38A169;   /* green */
--color-status-failed:       #E53E3E;   /* red */
```

---

### Typography

```css
/* Font stack — no custom font download required; system sans-serif */
--font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

--font-size-xs:   11px;   /* table sub-labels, timestamps */
--font-size-sm:   13px;   /* table body, form labels */
--font-size-base: 14px;   /* default body */
--font-size-md:   16px;   /* section headings */
--font-size-lg:   20px;   /* page titles */
--font-size-xl:   28px;   /* stat card numbers */

--font-weight-normal:    400;
--font-weight-medium:    500;
--font-weight-semibold:  600;
--font-weight-bold:      700;

/* Table column headers: uppercase, letter-spacing, --color-text-secondary */
.table-header { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
```

---

### Layout Shell

```
┌──────────────────────────────────────────────────────────────────────┐
│ ████████████████ amber top bar strip (3px)  ████████████████████████ │
├──────────┬───────────────────────────────────────────────────────────┤
│          │ [Search SIM ...]           🔔  ?  [ Avatar ▾ ]            │
│  Sidebar │───────────────────────────────────────────────────────────│
│  192px   │ Breadcrumb > Path                                         │
│  navy bg │                                                           │
│          │  Page Title                                   [Action Btn]│
│ ─────── │                                                           │
│ ● Dashboard     │  Content area (white cards on light-grey page bg)  │
│   SIMs          │                                                     │
│   IP Pools      │                                                     │
│   Range Configs ▸│                                                   │
│   Bulk Jobs     │                                                     │
│   Documentation │                                                     │
│                 │                                                     │
│  [≡ collapse]   │                                                     │
└──────────┴───────────────────────────────────────────────────────────┘
```

**Sidebar details:**
- Width: 192px expanded, 56px icon-only collapsed (hamburger toggle top-left)
- Active nav item: amber background `--color-sidebar-active`, white text, rounded-r-md pill
- Sub-menu items indented 16px, revealed on parent click (accordion)
- Bottom: user avatar + name + account badge (collapsible with sidebar)

**Top bar:**
- 3px amber strip across full viewport top
- Height 56px; white background
- Left: logo mark (32×32 SVG — no brand wordmark, just a geometric icon)
- Centre: global SIM/ICCID search input (magnifier icon, placeholder "Search SIM or ICCID…")
- Right: notification bell badge, help icon, user avatar dropdown

---

### Component Patterns

#### Stat Card (Dashboard)
```
┌────────────────────────────────┐
│  Active SIMs            [icon] │
│                                │
│  12,329,921                    │
│  ── ── ── ── ── ── ── ── ──    │
│  ▲ 1.4% vs yesterday           │
└────────────────────────────────┘
```
- White card, 8px border-radius, subtle box-shadow
- Icon: 40px circle, amber bg at 15% opacity, amber icon inside
- Number: `--font-size-xl`, `--font-weight-bold`
- Trend: green (up) or red (down) with tiny arrow

#### Data Table
- Header row: `--color-bg-page` background, uppercase labels
- Body rows: white, 44px height, `1px solid --color-border` bottom
- Hover: `--color-bg-row-hover`
- Selected (checkbox): `--color-primary-light` background tint
- Pagination: bottom-right, "Rows per page" select + `1–50 of N` counter + prev/next arrows
- Column visibility toggle: icon button top-right of table (grid icon)
- Export button: outlined amber button, top-right of list pages

#### Status Badge
```
● Active      — green dot + "Active" text
● Suspended   — amber dot + "Suspended" text
● Terminated  — red dot + "Terminated" text
● Running     — pulsing blue dot + "Running" text (CSS animation)
```
Badge is a `<span>` with dot + text; never colour-only.

#### Primary Button
```
[  + New Profile  ]
```
- Background: `--color-primary` (#F5A623)
- Text: white, semibold, 14px
- Border-radius: 6px
- Hover: `--color-primary-hover`
- Destructive variant: red background (`#E53E3E`)
- Outlined variant: amber border + amber text, transparent bg (for secondary actions)

#### Inline Form (add row in detail page)
- Appears as a highlighted row at the top of the sub-table
- Inputs: 36px height, 1px border, 4px radius, focus ring amber
- Save: small amber button; Cancel: text link

#### Modal / Drawer
- Backdrop: `rgba(0,0,0,0.4)`
- Modal max-width 560px, centered, 12px radius
- Drawer: slides from right, 480px wide (for job detail / error list)
- Header: title + ✕ close button
- Footer: [Cancel] text link + [Save / Submit] amber button, right-aligned

#### Toast Notifications
- Position: bottom-right, stacked
- Success: green left-border + check icon
- Error: red left-border + ✕ icon
- Info: amber left-border + ℹ icon
- Auto-dismiss: 5s; manual dismiss ✕

#### Progress Bar (pool utilisation, bulk job)
- Track: `--color-border`
- Fill: amber (0–75%), orange-red (`#E07B39`) (75–90%), red (>90%)
- Shows `used / total` label at right end

---

### Login Page Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│               │                                                      │
│  Login form   │   Full-height illustration panel (navy bg)           │
│  (left 42%)   │   Geometric network/globe SVG                        │
│               │   Tagline: "One Platform · Multiple Services"        │
│  Logo mark    │   (right 58%)                                        │
│  Email input  │                                                      │
│  Password     │                                                      │
│  [Sign In]    │                                                      │
│               │                                                      │
└───────────────┴──────────────────────────────────────────────────────┘
```
- Left panel: white, vertically centred form, logo mark above inputs
- Right panel: `--color-sidebar-bg` (#1C2340), decorative SVG illustration (no brand imagery)
- Sign In button: full-width amber, 48px height

---

### Tailwind Theme Extension

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#F5A623', hover: '#E09518', light: '#FEF3DC' },
        sidebar: { bg: '#1C2340', active: '#F5A623', text: '#FFFFFF', muted: '#8892B0' },
        status: {
          active:     '#38A169',
          suspended:  '#F5A623',
          terminated: '#E53E3E',
          running:    '#3182CE',
          inactive:   '#A0AEC0',
        },
        border: '#E2E8F0',
        page:   '#F4F6F9',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
      borderRadius: {
        card: '8px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
      },
    },
  },
};
```

---

## Screen Map

```
Login
  └── Dashboard (account overview)
        ├── SIMs
        │     ├── List / Search
        │     ├── Profile Detail
        │     │     ├── Edit Profile
        │     │     └── IMSI Manager (add / remove / suspend / set priority)
        │     ├── New SIM Profile (form)
        │     └── Bulk Import (CSV upload)
        ├── IP Pools
        │     ├── Pool List
        │     ├── Pool Detail + Stats
        │     └── New Pool (form)
        ├── Range Configs
        │     ├── IMSI Range Configs
        │     │     ├── Range Config List
        │     │     ├── Range Config Detail
        │     │     │     └── APN Pool Manager (inline: add / remove APN→Pool overrides)
        │     │     ├── New Range Config (form)
        │     │     └── Edit Range Config
        │     └── ICCID Range Configs (Multi-IMSI SIM)
        │           ├── ICCID Range Config List
        │           ├── ICCID Range Config Detail
        │           │     └── IMSI Slot Manager (inline: add / edit / remove slots)
        │           ├── New ICCID Range Config (form)
        │           └── Edit ICCID Range Config
        ├── Bulk Jobs
        │     └── Job List + Status / Progress
        └── Documentation
              └── SIM Profile Types reference
```

> **Implementation note:** The codebase contains two routes beyond the planned screen map:
> - `/sim-profile-types` → `SimProfileTypes.tsx`
> - `/documentation` → `SimProfileTypesDoc.tsx`
>
> These pages document SIM profile type variants. Per the project decision that **no additional
> SIM profile types are needed**, these pages are informational only and are not part of the
> operator workflow. They are kept in the codebase as reference material but are not linked
> from the main navigation.

---

## Screen Specifications

### 1. Dashboard

**Purpose:** Account-level overview — quick health check before drilling into detail.

**Content:**
- Active SIM count (GET /profiles?status=active count)
- Pool utilization summary (per pool: used / total as progress bar)
- Recent bulk jobs (last 5, with status badges)
- Quick links: New Profile, Bulk Import, New Pool, New ICCID Range Config

---

### 2. SIM List / Search

**Purpose:** Find SIM profiles by IMSI, ICCID, account name, or status.

**Search bar:** Single text field. Auto-detects:
- 15-digit string → searches by IMSI (`GET /profiles?imsi={v}`)
- 19–20-digit string → searches by ICCID (`GET /profiles?iccid={v}`)
- Anything else → searches by account_name (`GET /profiles?account_name={v}`)

**Table columns:** SIM ID (truncated UUID), ICCID, Account, Status badge, ip_resolution, IMSI count, Actions (View / Edit / Suspend / Delete)

**Filters:** Status (All / Active / Suspended / Terminated), ip_resolution type

**Pagination:** 50 rows per page, next/previous. Displays `total` from API response.

**Bulk actions:** Select multiple rows → Suspend all / Terminate all (sends individual PATCH per row, shows progress toast)

---

### 3. Profile Detail

**Purpose:** Read-only summary of one SIM profile, with inline actions.

**Layout:**
```
┌─────────────────────────────────────────────┐
│ SIM Profile                                  │
│ sim_id: 550e8400-...  [Copy]                │
│ ICCID: 8944501012345678901  (or "Not set")  │
│ Account: Melita                             │
│ Status: ● Active    [Suspend] [Terminate]   │
│ IP Resolution: imsi                         │
│ Created: 2026-01-15  Updated: 2026-02-26   │
├─────────────────────────────────────────────┤
│ IMSIs                                        │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ IMSI          │ Priority │ Status  │ Static IP    │   │
│ │ 2787730000... │ 1        │ Active  │ 100.65.120.5 │   │
│ │ 2787730000... │ 2        │ Suspend │ 101.65.120.5 │   │
│ └─────────────────────────────────────────────────────┘   │
│ [+ Add IMSI]                                │
├─────────────────────────────────────────────┤
│ Metadata                                     │
│ IMEI: 8659140301783797                      │
│ Tags: iot, nova-project                     │
└─────────────────────────────────────────────┘
```

**Actions from this screen:**
- Suspend / Reactivate / Terminate the SIM
- Set/update ICCID (PATCH with `{iccid: "..."}`)
- Open Edit Profile (full form)
- Add IMSI: inline form with IMSI (15 digits), Priority (integer ≥ 1), APN/IP rows → POST `/profiles/{sim_id}/imsis`
- Suspend / Reactivate / Remove individual IMSIs → PATCH or DELETE `/profiles/{sim_id}/imsis/{imsi}`
- Edit IMSI priority inline → PATCH `/profiles/{sim_id}/imsis/{imsi}` with `{priority: N}`

---

### 4. Edit Profile Form

**Purpose:** Edit any field on an existing profile via PATCH (JSON Merge Patch).

**Form fields (all pre-populated from GET /profiles/{sim_id}):**
- ICCID (text, optional, 19–20 digits, validated client-side)
- Account Name (text, optional)
- Status (select: active / suspended / terminated)
- ip_resolution (select: iccid / iccid_apn / imsi / imsi_apn)
- Metadata: IMEI, Tags (comma-separated)

**ip_resolution change handling:**
- Changing from `imsi` to `iccid` shows a warning: "This will clear per-IMSI IP assignments"
- Changing to `imsi_apn` adds an APN field to each IMSI row

**Save:** PATCH /profiles/{sim_id} with only changed fields.

---

### 5. New SIM Profile Form

**Purpose:** Create a single SIM profile via POST /profiles.

**Step 1 — Basic info:**
- ICCID (optional)
- Account Name (optional)
- ip_resolution (required) — selecting a value changes which fields appear below

**Step 2 — IP configuration (adapts to ip_resolution):**

| ip_resolution | Fields shown |
|---|---|
| `iccid` | Single IP row: Static IP + Pool (no APN field) |
| `iccid_apn` | Multiple APN→IP rows: APN text + Static IP + Pool |
| `imsi` | IMSI list; each IMSI has one IP row (no APN) |
| `imsi_apn` | IMSI list; each IMSI has multiple APN→IP rows |

IMSI rows have [+ Add IMSI] / [× Remove] controls.
APN→IP rows have [+ Add APN mapping] / [× Remove] controls.

**Step 3 — Metadata:**
- IMEI (optional)
- Tags (optional, comma-separated)

**Validation:** Client-side before submit. Shows inline field errors.
On conflict (409), shows which ICCID or IMSI is already in use.

---

### 6. Bulk Import — CSV Upload

**Purpose:** Upsert up to 100K profiles in one operation via POST /profiles/bulk with a CSV file.

#### Layout

```
┌─────────────────────────────────────────────────┐
│  Bulk Import                                     │
│                                                  │
│  Step 1: Download template                       │
│  [↓ Download CSV Template]                       │
│                                                  │
│  Step 2: Upload your file                        │
│  ┌──────────────────────────────────────────┐   │
│  │  Drag & drop CSV here, or click to browse│   │
│  │                                          │   │
│  │  Max 100,000 rows · .csv only            │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  Step 3: Preview (first 5 rows)                  │
│  [table preview appears here after file upload]  │
│                                                  │
│  [Cancel]                    [Upload & Import]   │
└─────────────────────────────────────────────────┘
```

#### CSV Template

The template is generated dynamically by the UI (no server round-trip needed).
Filename: `sim-profiles-template.csv`

```csv
sim_id,iccid,account_name,status,ip_resolution,imsi_1,static_ip_1,pool_id_1,apn_1,imsi_2,static_ip_2,pool_id_2,apn_2
(leave blank for new),8944501012345678901,Melita,active,imsi,278773000002002,100.65.120.5,pool-uuid-abc,,278773000002003,101.65.120.5,pool-uuid-abc,
```

**Column rules:**
- `sim_id`: leave blank for new profiles; fill in to update existing (upsert by sim_id)
- `iccid`: optional; blank = null
- `apn_N`: blank = null (APN-agnostic); required for `ip_resolution=imsi_apn`
- Up to 10 IMSI columns (`imsi_1`…`imsi_10`)
- Additional IMSIs beyond 10: use JSON bulk endpoint instead

**Download link** includes a sample row for each ip_resolution type as comment rows prefixed with `#`.

#### Upload Flow

```
1. User selects/drops file
2. UI reads file client-side, counts rows, validates CSV headers
   If headers don't match template → show error, block upload
3. Show 5-row preview table
4. User clicks "Upload & Import"
5. UI sends: POST /profiles/bulk (multipart/form-data, file attachment)
6. API returns 202 { job_id, status_url }
7. UI navigates to Bulk Jobs screen → shows this job at the top, auto-polling
```

#### Error display (in job detail)

```
Import completed with errors:

● 99,997 profiles imported successfully
✗ 3 profiles failed:

Row 142: IMSI "27877300000200" is 14 digits (must be 15)
Row 891: ICCID "894450101" is 9 digits (must be 19-20)
Row 4502: IMSI "278773000002002" is already assigned to another device
            → sim_id: 661f9511-f3ac-52e5-b827-557766551111

[↓ Download Error Report (CSV)]
```

The error CSV contains the original row data + error column for the operator to fix and re-upload.

---

### 7. IP Pools

**Pool List:** Table of all pools for the account. Columns: Pool Name, Routing Domain, Subnet, Total / Allocated / Available (progress bar), Status, Actions.

Filter bar above the table includes a **Routing Domain** dropdown (populated from `GET /routing-domains`) to filter pools by domain.

**Pool Detail + Stats:**
- Subnet, start_ip, end_ip, routing_domain, status
- Utilization gauge: used/total with % label
- Recent allocations (last 10 auto-allocated profiles from this pool)
- [Suspend Pool] / [Delete Pool] (delete blocked with tooltip if allocated > 0)
- Routing Domain shown as a read-only badge (immutable after creation)

**New Pool Form:**
- Pool Name (required)
- Account Name (optional)
- Routing Domain (optional text field with autocomplete from `GET /routing-domains`; defaults to `"default"`)
  - Helper text: "Pools in the same routing domain cannot have overlapping IP ranges."
- Subnet in CIDR notation (required, e.g. `100.65.120.0/24`)
- Start IP (auto-derived from subnet, editable)
- End IP (auto-derived from subnet, editable)
- Client-side validation: start_ip and end_ip must be within the subnet

On POST /pools success, show a toast: "Pool created. 253 IPs are now available."

**Overlap error (409 pool_overlap):** Show an inline error banner directly below the Subnet field:
```
┌──────────────────────────────────────────────────────────────────┐
│ ⚠ Subnet conflict — 10.0.0.128/25 overlaps with pool            │
│   "VPN-North-A" (10.0.0.0/24) in routing domain "vpn-north".    │
│   Use a different subnet, or assign this pool to a different     │
│   routing domain.                                                │
└──────────────────────────────────────────────────────────────────┘
```
The Subnet and Routing Domain fields are highlighted with an error border. No toast is shown for this error.

---

### 8. IMSI Range Configs

**Range Config List:** Table. Columns: ID, Account, f_imsi, t_imsi, Pool Name, ip_resolution, APN Overrides count, Status, Actions (View / Edit / Delete).

**Range Config Detail:**
- Header: ID, Account, f_imsi → t_imsi, Pool Name, ip_resolution, Status
- **APN Pool Manager** (inline table — only shown when ip_resolution is `imsi_apn` or `iccid_apn`):
  ```
  ┌──────────────────────────────────────────────────────┐
  │ APN → Pool Overrides              [+ Add Override]   │
  │ ┌──────────────────────────────────────────────────┐ │
  │ │ APN                    │ Pool Name   │ Actions   │ │
  │ │ internet.operator.com  │ Pool-A      │ [Delete]  │ │
  │ │ ims.operator.com       │ Pool-B      │ [Delete]  │ │
  │ └──────────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────────┘
  ```
  - **Add Override:** inline form with APN text field + Pool select → POST `/range-configs/{id}/apn-pools`
  - **Delete:** confirmation popover → DELETE `/range-configs/{id}/apn-pools/{apn}`
  - When ip_resolution is `imsi` or `iccid`, the APN Pool Manager section is hidden with a note:
    "APN overrides apply only when ip_resolution is imsi_apn or iccid_apn."
- [Edit Range Config] / [Delete Range Config] buttons

**New / Edit Range Config Form:**
- Account Name (optional)
- From IMSI (15 digits, validated)
- To IMSI (15 digits, validated; must be ≥ From IMSI)
- Pool (select from pools for this account; optional — can be null if slots define their own pools)
- ip_resolution (select: imsi / imsi_apn / iccid / iccid_apn; default=imsi)
- Description (optional)
- Status (active / suspended)

---

### 9. ICCID Range Configs (Multi-IMSI SIM)

**Purpose:** Manage batches of physical SIM cards that carry multiple IMSIs. Each ICCID Range Config
is a parent that owns one or more IMSI Slot ranges, one per IMSI slot on the card.

**ICCID Range Config List:** Table. Columns: ID, Account, f_iccid → t_iccid, Pool (fallback), ip_resolution, IMSI count, Slot count, Status, Actions (View / Edit / Delete).

**ICCID Range Config Detail:**
```
┌──────────────────────────────────────────────────────────┐
│ ICCID Range Config #1                                     │
│ Account: Melita                                           │
│ ICCID range: 8944501010000000000 → 8944501010000999999   │
│ Fallback Pool: Pool-A   ip_resolution: imsi   IMSIs: 2   │
│ Status: ● Active    [Edit] [Delete]                       │
├──────────────────────────────────────────────────────────┤
│ IMSI Slots                            [+ Add Slot]        │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Slot │ f_imsi          │ t_imsi          │ Pool  │ ✓ │  │
│ │ 1    │ 278770000000000 │ 278770000999999 │Pool-A │ ✓ │  │
│ │ 2    │ 278771000000000 │ 278771000999999 │Pool-B │ ✓ │  │
│ └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```
- **✓ column:** cardinality check — green tick if `t_imsi - f_imsi = t_iccid - f_iccid`, red warning otherwise.
- **Add Slot:** opens inline form (see below).
- **Edit Slot:** inline row editing.
- **Delete Slot:** only allowed when no profiles are allocated from this slot; otherwise shows tooltip "Profiles allocated from this slot — cannot delete".

**New / Edit ICCID Range Config Form:**
- Account Name (optional)
- From ICCID (19–20 digits, validated)
- To ICCID (19–20 digits, validated; must be ≥ From ICCID)
- Fallback Pool (select; optional — may be null if each slot defines its own)
- ip_resolution (select: imsi / imsi_apn / iccid / iccid_apn; default=imsi)
- IMSI Count (number 1–10)
- Description (optional)

**Add / Edit IMSI Slot form (inline in Detail):**
- Slot number (read-only on edit; auto-filled next available on add)
- From IMSI (15 digits, validated)
- To IMSI (15 digits, validated; must be ≥ From IMSI)
- Slot Pool (select; optional — overrides parent fallback pool)
- ip_resolution: read-only, inherited from parent (shown informational)
- Description (optional)
- Cardinality check shown live as user types: "Cardinality: 1,000,000 ✓ matches ICCID range" or "⚠ mismatch"

**Conflict display on save:**
- Cardinality mismatch → inline error: "IMSI range has 100,000 entries; ICCID range has 1,000,000. They must match."
- Duplicate slot number → "Slot 2 already exists on this ICCID range."
- ip_resolution mismatch → "Slot ip_resolution must match parent (imsi)."

---

### 10. Bulk Jobs

**Job List:** Polling table (auto-refreshes every 5s while any job has status=running).
Columns: Job ID, Submitted, Status badge, Processed, Failed, Duration, Actions.

**Status badges:** `queued` (grey) / `running` (blue, animated) / `completed` (green) / `failed` (red)

**Job Detail (drawer/modal):**
- Summary: submitted / processed / failed
- Progress bar (processed / submitted)
- Error table (if failed > 0): row number, field, message, value
- [↓ Download Error Report] button

---

## State Management & API Integration

All API calls go through a thin client wrapper (`apiClient.ts`):

```typescript
// apiClient.ts
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

apiClient.interceptors.request.use(config => {
  config.headers.Authorization = `Bearer ${getAccessToken()}`;
  return config;
});

// Auto-retry on 429 (rate limit) with exponential backoff
apiClient.interceptors.response.use(null, retryHandler);
```

JWT is stored in memory only (React context / Zustand store) — never in localStorage or cookies.
On page refresh, the user is redirected to the OIDC login page to re-authenticate.

**Polling for bulk jobs:**
```typescript
// useBulkJobPoller.ts
useEffect(() => {
  if (job.status === 'running' || job.status === 'queued') {
    const timer = setInterval(() => fetchJob(job.id), 5000);
    return () => clearInterval(timer);
  }
}, [job.status]);
```

---

## CSV Template Download (client-side)

No server endpoint needed — the template is generated in the browser:

```typescript
function downloadTemplate() {
  const headers = [
    'sim_id','iccid','account_name','status','ip_resolution',
    'imsi_1','static_ip_1','pool_id_1','apn_1',
    'imsi_2','static_ip_2','pool_id_2','apn_2',
    // ... up to imsi_10
  ].join(',');

  const example = [
    '','8944501012345678901','Melita','active','imsi',
    '278773000002002','100.65.120.5','pool-uuid-abc','',
    '278773000002003','101.65.120.5','pool-uuid-abc','',
  ].join(',');

  const csv = [headers, example].join('\n');
  triggerDownload(csv, 'sim-profiles-template.csv');
}
```

---

## Error Handling

| API response | UI behaviour |
|---|---|
| 400 validation_failed | Highlight the specific field(s) with inline error message |
| 409 iccid_conflict | Banner: "ICCID already in use by [link to existing profile]" |
| 409 imsi_conflict | Banner: "IMSI already assigned to [link to existing profile]" |
| 401 | Redirect to OIDC login |
| 403 | Toast: "You don't have permission to access this account" |
| 404 | "Profile not found" placeholder within the current screen |
| 429 | Auto-retry with backoff; toast if still failing after 3 attempts |
| 500 | Toast: "Server error — please try again"; log to error tracker |
| Network timeout | Toast: "Request timed out"; keep form state so user doesn't lose input |

---

## Accessibility & UX Notes

- All form fields have visible labels and `aria-label` / `aria-describedby`
- Status badges use both colour and text (not colour-only)
- Destructive actions (Terminate, Delete Pool) require a confirmation modal
- Bulk import shows row count and estimated time before confirming upload
- Long-running jobs show a progress bar; the user can navigate away and return
- CSV download and upload work without any browser extensions
- Table pagination uses URL query params so links are shareable

---

## Kubernetes & Helm Deployment

> **Dev environment:** Deployed via the `aaa-platform` umbrella chart (Plan 7) with
> `values-dev.yaml` on **k3d / WSL2**. Runs as **1 replica**, TLS off.
> `appConfig.apiBaseUrl` points to `http://provisioning.aaa.localhost/v1`.
> Accessible at `http://ui.aaa.localhost`.
> Production target: generic k8s or OCI/OKE, 2 replicas.

### Overview

The Management UI is a **stateless static React build** served by an Nginx container.
It runs as a **Kubernetes Deployment** with 2 replicas in the `aaa-platform` namespace.
The build artefact (HTML/JS/CSS) is baked into the container image at build time.
Nginx serves the SPA and proxies `/v1/` API calls to `subscriber-profile-api` (eliminating CORS issues).
Each Pod exposes an Nginx stub-status metrics endpoint scraped by `nginx-prometheus-exporter`.

---

### Helm Chart Structure

```
charts/aaa-management-ui/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml       # nginx.conf with proxy_pass to subscriber-profile-api
│   ├── servicemonitor.yaml  # Prometheus Operator ServiceMonitor
│   └── networkpolicy.yaml   # allow only browser ingress (via Ingress controller)
```

**Chart.yaml**
```yaml
apiVersion: v2
name: aaa-management-ui
description: React management UI for the AAA platform
type: application
version: 1.0.0
appVersion: "1.0.0"
```

**values.yaml**
```yaml
replicaCount: 2

image:
  repository: registry.example.com/aaa-management-ui
  tag: "latest"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80
  metricsPort: 9113          # nginx-prometheus-exporter default port

ingress:
  enabled: true
  className: nginx
  host: ui.aaa-platform.example.com
  tls:
    enabled: true
    secretName: aaa-ui-tls

# Runtime environment injected as window.APP_CONFIG via config.js (served at /config.js)
appConfig:
  apiBaseUrl: "https://provisioning.aaa-platform.example.com/v1"
  oidcAuthority: "https://auth.example.com/realms/aaa"
  oidcClientId: "aaa-management-ui"

resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "256Mi"

autoscaling:
  enabled: false            # static assets; CPU-based scaling rarely needed

nodeSelector: {}
tolerations: []
```

---

### Pod Specification

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "aaa-management-ui.fullname" . }}
  namespace: aaa-platform
  labels:
    app.kubernetes.io/name: aaa-management-ui
    app.kubernetes.io/component: management-ui
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/name: aaa-management-ui
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: aaa-management-ui
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9113"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: nginx
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: 80
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            httpGet:
              path: /health
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 3
            periodSeconds: 5
          volumeMounts:
            - name: nginx-config
              mountPath: /etc/nginx/conf.d
              readOnly: true
            - name: app-config
              mountPath: /usr/share/nginx/html/config.js
              subPath: config.js
              readOnly: true

        # Sidecar: nginx-prometheus-exporter scrapes nginx stub_status
        - name: nginx-exporter
          image: nginx/nginx-prometheus-exporter:1.1
          args:
            - -nginx.scrape-uri=http://localhost/nginx_status
          ports:
            - name: metrics
              containerPort: 9113
          resources:
            requests:
              cpu: "10m"
              memory: "16Mi"
            limits:
              cpu: "50m"
              memory: "32Mi"

      volumes:
        - name: nginx-config
          configMap:
            name: {{ include "aaa-management-ui.fullname" . }}-nginx
        - name: app-config
          configMap:
            name: {{ include "aaa-management-ui.fullname" . }}-appconfig
```

**Nginx ConfigMap (nginx.conf):**
```nginx
# templates/configmap.yaml — nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing: all paths serve index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy (avoids CORS, hides backend URL from browser)
    location /v1/ {
        proxy_pass http://subscriber-profile-api:8080/v1/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Nginx stub_status for prometheus exporter
    location /nginx_status {
        stub_status on;
        allow 127.0.0.1;
        deny all;
    }

    # Health check endpoint
    location /health {
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }
}
```

---

### Prometheus Metrics (via nginx-prometheus-exporter sidecar)

| Metric | Type | Labels | Description |
|---|---|---|---|
| `nginx_connections_active` | Gauge | — | Currently active connections |
| `nginx_connections_accepted_total` | Counter | — | Total accepted connections |
| `nginx_connections_handled_total` | Counter | — | Total handled connections (drop = `accepted - handled`) |
| `nginx_http_requests_total` | Counter | — | Total HTTP requests served |
| `nginx_connections_reading` | Gauge | — | Connections reading request headers |
| `nginx_connections_writing` | Gauge | — | Connections writing responses |
| `nginx_connections_waiting` | Gauge | — | Keep-alive connections idle |

In addition, application-level metrics are captured via the browser using a lightweight
**Real User Monitoring (RUM)** beacon flushed periodically to a Prometheus Pushgateway.

**Implementation** (`src/apiClient.ts`):
- Every axios request is stamped with `performance.now()` via a request interceptor.
- On response (success or error), duration is recorded into an in-memory bucket keyed by
  a path template (dynamic segments like UUIDs are collapsed to `:id`).
- Every 30 s (and on `beforeunload`) the buckets are flushed via `POST` to
  `APP_CONFIG.pushgatewayUrl/metrics/job/aaa-management-ui` in Prometheus text format.
- If `APP_CONFIG.pushgatewayUrl` is not set, flushing is skipped (safe for dev/staging).

| Metric (Prometheus text format, pushed to Pushgateway) | Type | Description |
|---|---|---|
| `ui_api_call_requests_total{endpoint}` | Counter | Total API calls by endpoint template |
| `ui_api_call_duration_ms_total{endpoint}` | Counter | Total milliseconds spent per endpoint |
| `ui_api_call_errors_total{endpoint}` | Counter | API call errors (non-2xx or network) per endpoint |

> **Note:** `ui_page_load_duration_ms`, `ui_bulk_upload_duration_ms`, and `ui_error_total` are
> not yet implemented. Only API call timing is tracked in `apiClient.ts`. Page-level metrics
> can be added per-page using `performance.now()` measurements posted to the same Pushgateway.

**ServiceMonitor:**
```yaml
# templates/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: aaa-management-ui
  namespace: aaa-platform
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: aaa-management-ui
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
```

---

### Grafana Dashboard — Management UI

**Dashboard UID:** `aaa-management-ui`

| Panel | Type | Query | Description |
|---|---|---|---|
| Active Connections | Time series | `nginx_connections_active{job="aaa-management-ui"}` | Current Nginx active connections |
| Request Throughput | Time series | `rate(nginx_http_requests_total{job="aaa-management-ui"}[1m])` | Requests per second to UI pods |
| Connection Drop Rate | Time series | `rate(nginx_connections_accepted_total[1m]) - rate(nginx_connections_handled_total[1m])` | Dropped connections (should be 0) |
| Waiting (Keep-alive) | Time series | `nginx_connections_waiting` | Idle keep-alive connections |
| Pod Count | Stat | `count(up{job="aaa-management-ui"})` | Active UI pods |
| Page Load Time (p95) | Time series | `histogram_quantile(0.95, rate(ui_page_load_duration_ms_bucket[5m]))` | Real-user load time |
| API Latency (frontend view) | Time series | `histogram_quantile(0.99, rate(ui_api_call_duration_ms_bucket[5m])) by (endpoint)` | Frontend-observed API calls |
| Client JS Error Rate | Time series | `rate(ui_error_total[5m]) by (type)` | Browser-side errors |

**Alerts:**
```yaml
groups:
  - name: aaa-management-ui
    rules:
      - alert: UIPodsDown
        expr: count(up{job="aaa-management-ui"}) < 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Management UI has no running pods — operators cannot access the platform"

      - alert: UIHighConnectionDropRate
        expr: |
          rate(nginx_connections_accepted_total{job="aaa-management-ui"}[5m])
          - rate(nginx_connections_handled_total{job="aaa-management-ui"}[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Nginx is dropping connections on UI pods"

      - alert: UIHighPageLoadTime
        expr: |
          histogram_quantile(0.95,
            rate(ui_page_load_duration_ms_bucket{job="aaa-management-ui"}[5m])
          ) > 3000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "UI p95 page load time {{ $value }}ms exceeds 3s threshold"
```
