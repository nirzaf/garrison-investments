# Garrison Investments — Brand Color Theme

## Overview

The Garrison Investments brand palette is built around a **dark premium finance** aesthetic: charcoal and gunmetal backgrounds, platinum silver typography, and deep emerald as the primary action color. This aligns with the metallic silver logo and positions the product as a serious, corporate investment and construction management platform.

---

## Brand Palette

| Role | Name | Hex |
|------|------|-----|
| Primary Dark | Carbon Black | `#0E1317` |
| Secondary Dark | Gunmetal | `#171E25` |
| Main Text / Logo Silver | Platinum | `#D7DDE3` |
| Muted Text | Steel Grey | `#8A96A3` |
| Primary Accent | Deep Emerald | `#0F766E` |
| Accent Hover | Bright Emerald | `#14A085` |
| Border / Divider | Slate Border | `#2A333D` |
| Warning | Muted Gold | `#C9A227` |
| Error | Deep Red | `#B42318` |
| Success | Emerald Green | `#16A34A` |

---

## Dark Mode Theme

Best for dashboards, construction portals, project analytics, and admin systems.

| UI Element | Color |
|------------|-------|
| App Background | `#0E1317` |
| Sidebar / Topbar | `#111820` |
| Cards / Panels | `#171E25` |
| Elevated Cards | `#1D2630` |
| Primary Text | `#E5E9ED` |
| Secondary Text | `#A7B0BA` |
| Muted Text | `#6F7A86` |
| Primary Button | `#0F766E` |
| Button Hover | `#14A085` |
| Borders | `#2A333D` |
| Active Menu Item | `#0F766E` with light text |
| Logo Color | Silver / Platinum `#D7DDE3` |

### CSS Variables — Dark Mode

```css
:root[data-theme="dark"] {
  --bg-main: #0E1317;
  --bg-sidebar: #111820;
  --bg-card: #171E25;
  --bg-card-elevated: #1D2630;

  --text-primary: #E5E9ED;
  --text-secondary: #A7B0BA;
  --text-muted: #6F7A86;

  --brand-primary: #0F766E;
  --brand-primary-hover: #14A085;

  --border: #2A333D;
  --success: #16A34A;
  --warning: #C9A227;
  --error: #B42318;
}
```

---

## Light Mode Theme

Use a soft warm-grey background so the silver/charcoal brand retains its premium character.

| UI Element | Color |
|------------|-------|
| App Background | `#F5F7F8` |
| Sidebar / Topbar | `#FFFFFF` |
| Cards / Panels | `#FFFFFF` |
| Elevated Cards | `#F9FAFB` |
| Primary Text | `#111820` |
| Secondary Text | `#4B5563` |
| Muted Text | `#7A8490` |
| Primary Button | `#0F766E` |
| Button Hover | `#0B5F59` |
| Borders | `#D8DEE4` |
| Active Menu Item Background | `#E6F4F1` |
| Active Menu Item Text | `#0F766E` |
| Logo Color | Charcoal `#111820` or Metallic Silver |

### CSS Variables — Light Mode

```css
:root[data-theme="light"] {
  --bg-main: #F5F7F8;
  --bg-sidebar: #FFFFFF;
  --bg-card: #FFFFFF;
  --bg-card-elevated: #F9FAFB;

  --text-primary: #111820;
  --text-secondary: #4B5563;
  --text-muted: #7A8490;

  --brand-primary: #0F766E;
  --brand-primary-hover: #0B5F59;

  --border: #D8DEE4;
  --success: #16A34A;
  --warning: #B08900;
  --error: #B42318;
}
```

---

## Dashboard Chart Colors

| Chart Purpose | Color |
|---------------|-------|
| Positive Growth | `#16A34A` |
| Negative Movement | `#DC2626` |
| Main Portfolio / Project Line | `#0F766E` |
| Secondary Line | `#64748B` |
| Highlight / Premium Metric | `#C9A227` |
| Benchmark / Index | `#2563EB` |

---

## Logo Usage

### Dark Mode
- Use the silver or platinum logo on a charcoal background.
- A slight metallic gradient is acceptable.
- Avoid placing the logo on pure black (`#000`).
- Preferred backgrounds: `#0E1317` or `#111820`.

### Light Mode
- Use the charcoal logo on white or soft grey.
- Or use the silver logo inside a dark sidebar panel.
- Preferred light background: `#F5F7F8`.

---

## Design Philosophy

> **Dark premium interface + platinum typography + emerald action color.**

Emerald is used exclusively as the action accent — for buttons, selected/active states, positive metrics, chart lines, and CTAs. Avoid using it as a decorative color. Keep backgrounds and surfaces in the charcoal/gunmetal family to maintain the premium finance feel.
