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

- `app/page.tsx` - prototype page layout.
- `app/globals.css` - visual system, responsive layout, and animations.
- `lib/portal-data.ts` - dummy requirements data, roles, modules, workflows, and decisions.
