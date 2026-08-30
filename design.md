# Yuno-inspired Product UI — Design Specification

## 1. Purpose

This document defines the **visual language, composition, hierarchy, spacing, interaction appearance, and brand direction** for a payments / financial-operations dashboard inspired by the supplied Yuno product screenshots and aligned with Yuno's public brand guidelines.

It is intentionally limited to **design and UI direction only**. It does not prescribe programming languages, frameworks, libraries, component architecture, implementation patterns, or technical stack decisions.

The objective is to give a design agent enough visual context to create new screens that feel consistent with the reference product without copying any one screenshot literally.

The interface should feel:

- Enterprise-grade
- Minimal and calm
- Operational rather than promotional
- Data-dense but not crowded
- Precise and trustworthy
- Modern fintech / payments SaaS
- Neutral-first, with a controlled use of Yuno Blue
- Built visually around tables, KPI blocks, filters, tabs, cards, and monitoring views

Primary visual references supplied:

- Insights / Volume dashboard
- Payments / Payouts table
- Reconciliations / conflict transactions

---

# 2. Brand Foundation

The product UI should combine two sources of truth:

1. **Yuno's public brand language** for brand colors, naming, and logo treatment.
2. **The supplied dashboard screenshots** for layout density, spacing, cards, tables, navigation, and interaction styling.

Official brand reference: https://y.uno/en/brand-guidelines

## 2.1 Core palette

### Yuno Blue — `#3E4FE0`

This is the primary accent color.

Use it selectively for:

- Active tabs
- Selected navigation items
- Important KPI values
- Links and high-value text actions
- Active toggles
- Focus / selected states
- Small icon accents
- Primary actions when a strong action is actually needed

The interface should **not become blue-heavy**. Yuno Blue works best as an attention signal inside a mostly neutral environment.

### White — `#FFFFFF`

White is the dominant surface color.

Use it for:

- Main cards
- Tables
- Sidebar
- Top navigation/header
- Search fields
- Buttons
- Dropdowns
- Modal surfaces
- Data panels

### Product Off-white — `#FAFAFA`

Use `#FAFAFA` as the main application background and for subtle grouping surfaces.

Typical uses:

- Overall workspace background
- Soft KPI highlight areas
- Quiet hover surfaces
- Secondary content grouping
- Very subtle table header or section differentiation

This should remain visually close to white.

### Unity Black — `#000000`

Use black for the strongest moments of visual hierarchy:

- Main page titles
- Strong numeric values
- High-emphasis labels
- Monochrome brand applications

For longer interface text, a near-black may be visually softer than pure black.

### Harmony Lilac — `#E8EAF5`

Use Harmony Lilac as a soft branded tint.

Good uses:

- Selected sidebar items
- Soft informational highlights
- Light active states
- Selected filter surfaces
- Quiet branded callouts

Avoid using it as the main page background.

---

# 3. Supporting Neutral Colors

The interface should remain predominantly grayscale.

Recommended visual neutrals:

- Primary text: `#161616`
- Secondary text: `#6F6F73`
- Tertiary / placeholder text: `#98989D`
- Subtle border: `#EDEDF0`
- Default border: `#E3E3E7`
- Stronger divider: `#D6D6DC`
- Hover surface: `#F6F6F8`

Most visual separation should come from **spacing, typography, thin dividers, and white space**, not from heavy filled backgrounds.

---

# 4. Typography

## 4.1 Font family

Use **Geist Sans** throughout the product UI.

The overall typographic character should feel:

- Clean
- Contemporary
- Neutral
- Highly legible at small sizes
- Suitable for numbers and operational data

Avoid decorative typefaces inside the product interface.

## 4.2 Page titles

Recommended visual treatment:

- Approximately `32–36px`
- Bold, around `700`
- Tight line-height
- Slightly tightened letter spacing
- Black or near-black

Examples:

- Insights
- Payments
- Reconciliations

The page title should be one of the strongest visual anchors on the screen.

## 4.3 Section headings

Recommended:

- Around `20px`
- Semi-bold to bold
- Near-black
- Compact line-height

Use for larger content groupings such as:

- Total volume
- Conflict transactions by provider
- Payment performance

## 4.4 Card titles

Recommended:

- Around `16px`
- Semi-bold
- Near-black

These should feel important but clearly subordinate to the page title.

## 4.5 Body and table text

Recommended:

- Around `14px`
- Regular weight
- Comfortable line-height
- Primary or secondary gray depending on hierarchy

This is the dominant text size across the interface.

## 4.6 Metadata and helper text

Recommended:

- Around `12px`
- Regular weight
- Secondary or tertiary gray

Use for:

- Currency suffixes
- Secondary status information
- Helper labels
- Timestamps
- Minor metadata

## 4.7 KPI values

Recommended:

- Approximately `32–38px`
- Semi-bold / bold
- Tight line-height
- Slightly tightened letter spacing

Only one or a small number of KPIs should use Yuno Blue for emphasis. Most numerical values should remain black.

---

# 6. Overall Application Shell

The interface uses a classic enterprise dashboard structure:

- Narrow vertical sidebar on the far left
- Horizontal top header
- Large main content canvas

The shell should feel stable and persistent while page content changes inside it.

The background relationship should generally be:

- Sidebar: white
- Top header: white
- Main workspace: `#FAFAFA`
- Cards and tables: white

This contrast should be extremely subtle.

---

# 7. Left Sidebar

Recommended width: approximately `56px`.

Visual characteristics:

- Full-height vertical rail
- White background
- Thin right divider
- Compact icon-only navigation
- Yuno logomark near the top
- Evenly spaced navigation items
- Minimal decoration

## Active navigation state

An active sidebar item should use:

- Yuno Blue icon
- Harmony Lilac or similarly soft branded background
- Approximately `8px` corner radius

The active state should be noticeable but not visually loud.

## Inactive navigation state

Inactive icons should remain:

- Dark gray or charcoal
- Thin
- Monochrome
- Visually consistent in weight

Hover states may introduce a very subtle off-white or lilac-tinted surface.

---

# 8. Top Header

Recommended height: approximately `72–76px`.

Visual treatment:

- White background
- Thin bottom divider
- Module/page area on the left
- Utilities aligned to the far right
- Large amount of horizontal breathing room
- No heavy shadow

Typical right-side utilities may visually include:

- Test mode toggle
- Search
- Secondary utility icon
- Notifications
- User avatar
- Profile chevron

The topbar should visually disappear into the shell rather than compete with the page content.

---

# 9. Main Content Area

The main workspace should use nearly the full available width.

Recommended page padding:

- Top: about `32px`
- Left/right: about `28–40px`
- Bottom: about `48px`

Avoid placing operational content inside a narrow marketing-style centered container.

The layout should feel horizontal, spacious, and optimized for data scanning on desktop screens.

---

# 11. Tabs

Tabs should be visually understated.

## Default tab

- Around `14px`
- Medium/regular weight
- Secondary gray
- No filled background

## Active tab

- Darker text
- Slightly stronger weight
- Thin Yuno Blue underline

The underline is the main active indicator.

Recommended horizontal space between labels: roughly `24px` or more.

Avoid pill-shaped top-level tabs in this UI language.

---

# 12. Buttons

Buttons should feel compact and operational.

## Secondary actions

Typical appearance:

- White background
- Thin light-gray border
- Approximately `38px` height
- Around `10px` corner radius
- Dark label
- Optional small icon
- Very subtle or nearly invisible shadow

Examples:

- Add filter
- Add chart
- Customize
- Download
- Export
- Refresh
- View all

## Primary action

Use Yuno Blue only when there is a genuinely dominant action.

Primary buttons may use:

- Yuno Blue background
- White label
- Same compact sizing as other controls

Do not turn every action into a blue button.

## Hover appearance

Hover states should remain subtle:

- Slightly darker border
- Very light off-white background
- No dramatic movement or glow

---

# 13. Search Fields and Inputs

Search fields should be visually simple and wide.

Recommended appearance:

- Approximately `40–42px` height
- White background
- Thin light-gray border
- Approximately `9–10px` radius
- Around `14px` text
- Small search icon on the left

On list-heavy pages, the search field may occupy approximately `360–400px` on desktop.

Placeholder text should use tertiary gray.

Selected/focused fields may use a subtle Yuno Blue outline or halo, but this should remain restrained.

---

# 14. Filter Controls

Filters should visually resemble compact secondary buttons.

Typical labels:

- Add filter
- Last 3 days
- Daily
- Provider
- Country
- Status

Inactive filters should remain mostly white.

Selected filters may use:

- Harmony Lilac background
- Yuno Blue text/icon
- Soft branded border

Avoid bright, highly saturated filter pills.

---

# 15. Cards

Cards are large white content surfaces with minimal elevation.

Recommended visual treatment:

- White background
- Thin subtle border
- Approximately `12–14px` corner radius
- Little to no shadow
- Internal padding around `24–28px`

Cards should feel anchored to the page rather than floating above it.

## Card headers

A typical card header may contain:

- Small info icon
- Card title on the left
- Text action such as “View more” on the right

Example:

```text
ⓘ  Total volume                                      View more
```

Use Yuno Blue for text actions.

---

# 16. KPI and Metric Blocks

The reference UI favors **one large parent card containing multiple metrics** rather than many unrelated standalone cards.

Example visual structure:

```text
┌───────────────────────────────────────────────────────────────┐
│ Total volume                                         View more │
│                                                               │
│  Total sales volume     Total refunds      Chargebacks        │
│  $18.62M USD            $3.74K USD         $1.63K USD         │
│                                                               │
│  Successful payments    Successful refunds Total chargebacks  │
│  1,530,721              1,463              68                  │
└───────────────────────────────────────────────────────────────┘
```

## Primary KPI emphasis

The strongest KPI may use:

- Yuno Blue value
- Very light off-white highlight region
- Larger typography

Secondary KPI values should generally remain black.

Labels should be smaller and darker than ordinary helper text but clearly subordinate to the value.

---

# 17. Tables

Tables are one of the most important visual patterns in this product.

## Table container

Recommended appearance:

- White surface
- Thin border
- Approximately `12px` outer radius
- No heavy shadow

## Header row

Recommended:

- Approximately `52–56px` height
- White or extremely subtle off-white background
- Secondary gray text
- Around `13px`
- Medium/regular weight
- Thin bottom divider

## Data rows

Recommended:

- Approximately `60–68px` height
- Around `14px` text
- Thin row separators
- Generous horizontal padding, around `24–28px`

Avoid zebra striping unless readability genuinely requires it.

## Numeric values

Important amounts may use slightly stronger weight.

Currency suffixes can be smaller and lighter than the numeric amount.

## Long identifiers

Long IDs should visually truncate rather than wrap onto multiple lines.

Example:

`5291abc8-763d-4b5...`

This helps preserve consistent row height.

## Row actions

Row actions should remain low-emphasis and generally sit at the far right.

Examples:

- Eye / view icon
- Overflow dots
- Right chevron

---

# 18. Status Badges

Statuses should use small rounded pills.

Recommended proportions:

- Around `24px` height
- Compact horizontal padding
- Small text around `12px`
- Fully rounded pill shape
- Optional tiny icon

## Suggested state language

### Created / informational

- Blue text
- Very light blue/lilac background

### Pending / in progress

- Amber/gold text
- Pale warm-yellow background

### Successful

- Green text
- Pale green background

### Error / failed

- Red text
- Pale red background

Status colors are functional and should remain secondary to Yuno Blue as the brand accent.

---

# 20. Reconciliation / Comparison Cards

Operational reconciliation views may use two side-by-side cards on large screens.

Each card can contain:

- Small icon
- Card title
- Right-aligned text actions
- Compact provider table

Example conceptual structure:

```text
Status conflict                         View all   Export
────────────────────────────────────────────────────────
Provider        Conflict tx        Conflict amount
PayPal          21                 $1,390 USD
Unlimint        13                 $190 USD
Apple Pay       74                 $18,190 USD
```

The visual emphasis should remain on the data, not on decorative card treatments.

---

# 21. Spacing System

Use a consistent 4px / 8px visual rhythm.

Recommended scale:

- `4px` — micro spacing
- `8px` — icon-to-label spacing
- `12px` — compact internal spacing
- `16px` — standard control gap
- `20px` — medium gap
- `24px` — card content spacing
- `28px` — common table horizontal padding
- `32px` — page block spacing
- `40px` — large section separation
- `48px` — major page separation

Consistency matters more than pixel-perfect reproduction.

---

# 22. Corner Radius

The visual system should use restrained rounding.

Recommended values:

- `6–8px` for small icon backgrounds and compact controls
- `9–10px` for buttons and inputs
- `12px` for tables
- `14px` for larger cards
- Fully rounded only for status badges and toggles

Avoid the oversized `20–30px` rounded-card aesthetic common in more playful SaaS products.

---

# 23. Iconography

Icons should be:

- Thin
- Simple
- Mostly outline-based
- Visually consistent
- Neutral gray by default
- Yuno Blue when active

Recommended sizes:

- `16px` for inline actions
- `18–20px` for sidebar navigation

Use a consistent stroke weight across the interface.

Avoid mixing filled, outlined, playful, and highly detailed icon styles.

---

# 24. Toggle Switches

The Test mode toggle should be compact and neutral.

Approximate size:

- `42px` wide
- `24px` high

Inactive state:

- Light gray track
- White thumb

Active state:

- Yuno Blue track
- White thumb

The toggle should not be visually larger than nearby utility controls.

---

# 25. Interaction Appearance

## Hover

Hover states should be subtle.

Preferred effects:

- Slight off-white background
- Slightly stronger border
- Yuno Blue text for interactive links

Avoid:

- Large shadows
- Scaling effects
- Strong animation
- Bright glow

## Focus / selected

Use Yuno Blue to communicate focus or selection.

A very soft blue halo may be used around fields or controls when necessary.

## Disabled

Disabled items should feel muted through lower contrast rather than a dramatic styling change.

---

# 26. Data Density

The product should support large amounts of financial and operational information without feeling cramped.

Guidelines:

- Use `14px` as the dominant data size
- Keep table rows around `56–68px`
- Use whitespace around groups instead of adding excessive padding inside every cell
- Keep headers concise
- Truncate long technical IDs visually
- Align comparable amounts consistently
- Use badges only where status semantics matter
- Reserve Yuno Blue for actions, selection, or high-value emphasis

The product should feel optimized for scanning hundreds or thousands of records.

---

# 27. Responsive Visual Behavior

The references are clearly desktop-first.

## Large desktop

Prioritize layouts from approximately `1280px` to `1920px` wide.

Use:

- Wide tables
- Horizontal toolbars
- Multi-column KPI layouts
- Side-by-side analytical cards

## Tablet

At narrower widths:

- Reduce outer padding
- Allow action rows to wrap
- Stack two-column analytical cards
- Give search controls more horizontal priority

## Mobile

On mobile:

- Preserve strong page title hierarchy
- Keep tabs accessible
- Stack KPI groups vertically
- Move secondary actions into compact overflow patterns when necessary
- Allow data-heavy tables to scroll horizontally or transform into readable row groups

Do not reduce text to unreadably small sizes simply to fit the desktop composition.

---

# 28. Visual Rules for Design Agents

When creating a new screen in this visual system:

1. Start from a predominantly white and `#FAFAFA` shell.
2. Use **Geist Sans** throughout.
3. Keep the visual hierarchy neutral-first.
4. Use **Yuno Blue `#3E4FE0`** sparingly for active, selected, linked, or high-value elements.
5. Use **Harmony Lilac `#E8EAF5`** for soft branded states.
6. Use bold, large page titles and compact operational labels.
7. Prefer thin borders over visible shadows.
8. Keep cards white and spacious.
9. Use restrained `10–14px` radii for major surfaces.
10. Keep table rows comfortable but information-dense.
11. Use status pills only for semantic status information.
12. Keep controls compact and horizontally aligned when space permits.
13. Maintain strict alignment between title, tabs, toolbar, cards, and tables.
14. Use muted gray text to establish secondary hierarchy.
15. Preserve generous whitespace between page sections.
16. Avoid gradients.
17. Avoid glassmorphism.
18. Avoid dark dashboard cards unless specifically required.
19. Avoid decorative illustration in normal operational views.
20. Avoid marketing-style hero sections.
21. Avoid excessive animation.
22. Avoid overly colorful charts or cards.
23. Treat `#FAFAFA` as a product surface, not as an official brand color.
24. Status colors may use green, amber, or red, but these remain functional colors rather than brand colors.

---

# 29. Reference Screen Interpretation

## 29.1 Insights / Volume

Important traits to preserve:

- Large `Insights` heading
- Horizontal subsection tabs
- Filter controls below the tabs
- Utility actions aligned to the right
- Large white analytical card
- Multiple KPI blocks inside one parent surface
- One important KPI emphasized in Yuno Blue
- Large amount of white space
- Minimal decoration

The visual focus is **performance monitoring**.

## 29.2 Payments / Payouts

Important traits to preserve:

- Large `Payments` title
- Four horizontal navigation tabs
- Wide search field
- Compact filter control
- Utility actions on the right
- Large bordered data table
- Small status badges
- Provider logos/icons
- Clear amount + currency formatting
- Subtle row-level actions at the far right

The visual focus is **fast transaction scanning and operations**.

## 29.3 Reconciliations

Important traits to preserve:

- Strong section heading
- Two-column analytical layout on desktop
- Each card contains its own table
- Compact actions such as `View all` and `Export`
- Provider names paired with small logos
- Monetary values emphasized through weight rather than excessive color
- Very restrained use of brand color

The visual focus is **comparison and anomaly diagnosis**.

---

# 30. Anti-patterns

Do not introduce these unless explicitly requested:

- Large blue gradients
- Bright multicolor card backgrounds
- Heavy drop shadows
- Oversized body typography
- Extremely rounded cards
- Floating glass panels
- Neon effects
- Heavy borders
- Dense sidebar labels
- Marketing landing-page sections
- Decorative charts with unnecessary colors
- Excessive animation
- Excessive blue usage
- Huge primary buttons
- Oversized icons
- Strong visual textures
- Cartoonish or playful UI elements

---

# 31. Overall Visual Summary

The final product should resemble a modern payment orchestration and fintech operations console.

The intended visual hierarchy is:

```text
Neutral Yuno-branded shell
    ↓
Strong page title
    ↓
Thin horizontal tab navigation
    ↓
Compact filters and utility actions
    ↓
Large white analytical surfaces
    ↓
Tables, KPIs, statuses, and provider data
    ↓
Yuno Blue only where attention is needed
```

The experience should feel:

- Reliable
- Fast
- Precise
- Calm
- Sophisticated
- Operational
- Suitable for monitoring millions of transactions

The strongest visual principle is **restraint**: white space, typography, borders, and alignment should do most of the work, while color is reserved for meaning.

---

# 32. Source of Truth / Precedence

When interpreting this visual system, use the following precedence:

1. **Official Yuno brand guidelines** for naming, logo treatment, brand assets, and official colors.
2. **The supplied dashboard screenshots** for product-shell composition, density, spacing, cards, tables, controls, and information hierarchy.
3. **This `design.md`** as the normalized visual specification for creating consistent new screens.

Official brand palette referenced in this document:

- Yuno Blue — `#3E4FE0`
- Unity Black — `#000000`
- White — `#FFFFFF`
- Harmony Lilac — `#E8EAF5`

Product UI surface:

- Off-white — `#FAFAFA`

Use approved Yuno brand assets whenever the logo is required; do not redraw or synthesize it.
