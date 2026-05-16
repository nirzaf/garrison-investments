# Authentication, 2FA, and Session Security

## Title
Authentication, 2FA, and Session Security

## User Story
As an authorized employee,
I want to sign in securely with company-controlled authentication,
so that portal data is protected from unauthorized access.

## Description
Build login, logout, secure session handling, email OTP two-factor authentication, first-login password change, account lockout, and password reset support.

## Acceptance Criteria
1. Given I have an active user account,
   When I enter valid credentials,
   Then I am prompted for email OTP before entering the portal.

2. Given I enter a valid OTP,
   When verification succeeds,
   Then I am signed in with a one-day session.

3. Given I fail login three times,
   When I try again,
   Then the account is temporarily locked according to security policy.

4. Given this is my first login,
   When authentication succeeds,
   Then I must change my password before using protected pages.

5. Given I am inactive or my session expires,
   When I access a protected route,
   Then I am redirected to login without data loss where possible.

## Business Rules
- Two-factor authentication is required for MVP.
- MVP 2FA uses email OTP.
- Admin creates user accounts.
- Users must change password on first login.
- Account lockout occurs after 3 failed login attempts.
- Sessions remain active for 1 day using secure refresh behavior.
- Password reset must happen through Admin or OTP.

## UI/UX Notes
- Login, OTP, forced password change, and reset screens must be mobile-friendly.
- Errors must not reveal whether an account exists.
- Validation messages must be clear and field-level.
- Loading states must be visible during OTP verification and login.

## Technical Notes
- Implement secure password hashing.
- Use short-lived access tokens with refresh behavior supporting a one-day session.
- Store refresh tokens or session records server-side so logout can invalidate them.
- Rate-limit auth and OTP endpoints more strictly than normal API endpoints.
- Audit login success, failed login, lockout, logout, and password reset events.
- Follow `ARCHITECTURE.md` auth flow: access token is kept in memory, refresh token is HttpOnly Secure SameSite=Strict cookie, refresh tokens rotate and are stored hashed server-side.
- Implement authentication through FastAPI dependencies and RBAC dependencies, not route-local business logic.
- Return errors using the architecture error envelope with `detail`, `error_code`, and field errors where applicable.

## Priority
High

## Dependencies
- Email service configuration.
- User model and migration baseline.
- Final security policy for lockout duration and password rules.

## Definition of Done
- Login, logout, OTP, lockout, first-login change, and reset flows work.
- Auth APIs and UI states are tested.
- Security events are audited.
- Tokens are stored safely on the client.
- Protected routes cannot be accessed anonymously.
