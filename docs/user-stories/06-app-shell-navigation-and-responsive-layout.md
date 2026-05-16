# App Shell, Navigation, and Responsive Layout

## Title
App Shell, Navigation, and Responsive Layout

## User Story
As a portal user,
I want a clear responsive layout with role-aware navigation,
so that I can quickly reach the work relevant to my role on desktop or mobile.

## Description
Implement the protected application shell, desktop sidebar, header, breadcrumbs, notification entry point, user menu, mobile navigation, offline indicator placeholder, and route-level layout.

## Acceptance Criteria
1. Given I am signed in,
   When I open the portal on desktop,
   Then I see a sidebar, header, user menu, and route content area.

2. Given I am signed in on a phone,
   When I open the portal,
   Then I see mobile-friendly navigation with touch-safe controls.

3. Given my role cannot access a module,
   When the navigation renders,
   Then that module is not shown and direct URL access is still blocked by API permissions.

4. Given the app is offline or reconnecting,
   When network status changes,
   Then the shell shows a clear indicator.

## Business Rules
- Role-based menu visibility must match server permissions.
- Mobile MVP must support supervisor updates, engineer reports, photo upload, document view, approvals if confirmed, and notifications.
- Desktop is prioritized for admin, accounts, documents, and management screens.
- UI must be English in the first release.
- Arabic/RTL should be design-ready but not implemented in MVP.

## UI/UX Notes
- Use a desktop sidebar and mobile bottom navigation pattern.
- Maintain clear touch targets on mobile.
- Avoid exposing unavailable actions to users.
- Validation and error messaging must be non-technical.

## Technical Notes
- Implement protected routes with an auth guard.
- Add shared layout components for sidebar, header, mobile navigation, status badges, loading states, and error boundaries.
- Use role/permission metadata from the authenticated user.
- Keep route structure aligned with the UI component tree.
- Follow `../ARCHITECTURE.md` frontend composition: QueryClientProvider, AuthProvider, ThemeProvider, BrowserRouter, RequireAuth, AppLayout, Sidebar, Header, MobileNav, OfflineIndicator, and Outlet.
- Use React Context for auth, TanStack Query for server state, local state for UI state, and no Redux.
- Every route-level component must handle loading, empty, and error states.

## Priority
High

## Dependencies
- Authentication.
- Role permission model.
- Branding assets such as logo, colors, and typography.

## Definition of Done
- Protected shell renders on desktop and mobile.
- Navigation is role-aware.
- Offline indicator exists.
- Core route placeholders are connected.
- Basic responsive checks pass for desktop, tablet, and phone sizes.
