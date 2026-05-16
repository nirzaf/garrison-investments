# Garrisons Portal Prototype

Animated Next.js prototype for explaining the internal portal requirements with dummy operational data.

## Run Locally

```bash
bun install
bun run dev -- --port 3007
```

Open:

```text
http://127.0.0.1:3007
```

## Build

```bash
bun run build
```

## Main Files

- `prototype/app/page.tsx` - route entrypoint.
- `prototype/components/portal-prototype.tsx` - interactive shell, grouped navigation, and screen switching.
- `prototype/components/screens/overview.tsx` - stakeholder-first story: project setup, daily report, approval, dashboard record.
- `prototype/components/screens/*.tsx` - one file per overview/module screen, with `module-screens.tsx` as a small export barrel.
- `prototype/components/tour-overlay.tsx` - guided tour behavior.
- `prototype/components/shared.tsx` - reusable cards, tables, lists, status pills, and visual helpers.
- `prototype/app/styles/*.css` - visual system split by foundation, shell, overview, shared components, tour, supporting widgets, and responsive rules.
- `prototype/lib/portal-data.ts` - typed data bridge between JSON content and UI components.
- `prototype/lib/data/*.json` - editable dummy requirements data, roles, modules, workflows, and decisions.

## Prototype Map

Open the prototype on `Overview` first. The intended stakeholder story is:

```text
Project setup -> Daily report -> Approval -> Dashboard record
```

The sidebar is grouped so the first pass stays simple:

- `Core Flow` - the main MVP operating story.
- `Management` - documents, photos, notifications, access, admin, and security.
- `Phase 2` - inventory, accounts, and mobile/offline expansion.
- `Delivery` - rollout, hosting, migration, and acceptance planning.

Use `Guided walkthrough` for the executive demo. Use module navigation only when a stakeholder asks for more detail about a specific area. Secondary overview details such as API surfaces, sample files, remaining inputs, and full requirements coverage are behind `More details`.
