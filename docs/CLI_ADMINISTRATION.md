# Garrisons administration CLI

`garrisonctl` uses the portal's FastAPI endpoints for account, project, finance, workforce and import operations. The authenticated account's permissions and project scope apply. The same API audit records identify the actor. Host commands use the existing deployment, recovery and monitoring tools.

## Install and connect

Use Python 3.14 on macOS or Linux and the backend dependencies. Run commands from `backend/`.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.garrisonctl --version
python -m scripts.garrisonctl --help
python -m scripts.garrisonctl capabilities --json
```

Set `GARRISON_API_BASE_URL` to the intended HTTPS origin. The local default is `http://127.0.0.1:8000`. `--base-url` overrides it. Plain HTTP is limited to loopback. `GARRISON_ENVIRONMENT` or `--environment` labels the response and has no effect on permissions or the destination.

```bash
python -m scripts.garrisonctl auth login --email director@example.com
python -m scripts.garrisonctl auth whoami --json
python -m scripts.garrisonctl roles permissions --json
python -m scripts.garrisonctl auth logout --json
```

Login prompts privately for the password and delivered OTP. An origin-bound, owner-only session file under `~/.config/garrisonctl/` stores the access token and rotating refresh token. Use `--session-file` to select another file in a private directory. An expired access token is refreshed before a command sends its request. If the refresh session has expired, use `auth logout --local-only` to remove the unusable file, then sign in again. The local-only option leaves server revocation to the session's expiry or the normal account revocation process.

For automation, provide an already issued short-lived bearer through `GARRISON_ACCESS_TOKEN` or `--token-file`. The token file must be a regular, owner-only file. A short-lived bearer alone has no refresh or server logout capability. Use secure terminal prompts for account creation and password resets. Keep sessions, tokens, user import files and reconciliation inputs out of Git and shared logs.

## Commands

| Group | Commands | Required access |
| --- | --- | --- |
| Identity | `auth login`, `auth whoami`, `auth logout`, `roles list`, `roles permissions` | Own session. Role directory and another role's permissions require `users:read` |
| Users | `users list`, `show`, `create`, `update`, `set-role`, `activate`, `deactivate`, `reset-password` | `users:read` or `users:manage` as shown by capabilities |
| Projects | `projects list`, `show`, `members list`, `members assign`, `members revoke` | Scoped `projects:read` or `projects:manage` |
| Policy | `config show`, `config validate`, `config plan`, `config apply`, `config verify`, `finance policy show`, `finance policy validate`, `finance policy reconciliation` | Local validation, authenticated API, director finance access, or root host operator |
| Finance | `finance invoices list`, `show`, `finance budget show`, `finance reconcile` | Dataset-specific permissions, including `financial:view` and project scope |
| Imports | `imports templates`, `preview`, `run`, `batches`, `status` | `users:manage` |
| Diagnostics | `health check`, `logs search`, `logs tail`, `audit search` | Public readiness or `audit:view` |
| Operations | `backup status`, `backup verify`, `release status` | Host-only, with existing file, policy and credential access |

Each command has `--help` and `--json`. Capabilities lists commands, argument requirements, permissions, execution scope, preview support and whether approval is required. Project membership labels are project context. Company permissions come from the user's account role.

### Workforce administration

Use the existing portal session with the HR permissions assigned to your account.
`hr employees list`, `hr employees get`, `hr leave requests list`,
`hr compliance expiring`, and `hr reports summary` use the same restricted API as
the HR workspace. Mutations use the command's `--dry-run` and
`--apply --expect` options. Treat workbook previews and document links as
restricted records. See the [workforce guide](HR_WORKFORCE.md) for the account
handoff and activation flow.

The current remote workforce command groups are listed below. For exact
arguments and preview support, run `garrisonctl capabilities --json` or the
subcommand's `--help`.

| Prefix | Registered subcommands | Access boundary |
| --- | --- | --- |
| `hr employees` | `list`, `get`, `create`, `update`, `transition`, `link-account` | HR read, manage or sensitive permissions for employee actions. Linking uses `users:manage`. |
| `hr departments`, `hr positions` | `list`, `create` | Employee read or manage permission. |
| `hr access-requests` | `list`, `create`, `decide` | Request stage and actor determine HR versus director access. |
| `hr attendance` | `list`, `correction` | Attendance recording permission. |
| `hr documents` | `list`, `upload` | HR document management and category checks. |
| `hr leave` | `policy show`, `requests list`, `requests submit`, `requests decide`, `balances` | Leave management or leave approval. |
| `hr compliance` | `expiring` | Compliance management. |
| `hr offboarding` | `list`, `initiate`, `complete` | Offboarding management and case preconditions. |
| `hr` | `workbook-reconcile`, `summary`, `reports summary`, `reports sites` | Employee management for workbook reconciliation. Report viewing for summaries and sites. |

Use `hr reports sites` to page through primary site IDs and
`hr reports summary --project-id ID --department-id ID --date-from YYYY-MM-DD --date-to YYYY-MM-DD`
to filter the report. Both dates are required when applying a date range.

### Inspect identities, roles and projects

```bash
python -m scripts.garrisonctl auth whoami --json
python -m scripts.garrisonctl roles list --json
python -m scripts.garrisonctl roles permissions --role quantity_surveyor --json
python -m scripts.garrisonctl users list --active --role quantity_surveyor \
  --limit 50 --offset 0 --json
python -m scripts.garrisonctl users show --email qs@example.com --json
python -m scripts.garrisonctl projects list --status active --search warehouse --json
python -m scripts.garrisonctl projects show --project-id "$PROJECT_ID" --json
python -m scripts.garrisonctl projects members list --project-id "$PROJECT_ID" --json
```

Use the IDs returned by these reads as `USER_ID` and `PROJECT_ID` in the examples below. Review a member's company role with `users show --user-id "$USER_ID"` if you have user directory access. Compare the role permissions with project memberships to check assignment scope. List commands use `--limit` and `--offset` where supported.

### Account and project changes

```bash
python -m scripts.garrisonctl users create --email qs@example.com \
  --full-name "Quantity Surveyor" --employee-code QS-001 --phone 5550100 \
  --role quantity_surveyor --designation "Quantity Surveyor" --dry-run --json
python -m scripts.garrisonctl users update --user-id "$USER_ID" \
  --phone 5550110 --dry-run --json
python -m scripts.garrisonctl users update --user-id "$USER_ID" \
  --clear-designation --dry-run --json
python -m scripts.garrisonctl users activate --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users deactivate --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users reset-password --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users set-role --email qs@example.com \
  --role quantity_surveyor --dry-run --json
python -m scripts.garrisonctl users set-role --email qs@example.com \
  --role quantity_surveyor --apply --expect "$PLAN_SHA256" --json
python -m scripts.garrisonctl projects members assign --project-id "$PROJECT_ID" \
  --user-id "$USER_ID" --role-in-project "Quantity Surveyor" --dry-run --json
python -m scripts.garrisonctl projects members revoke --project-id "$PROJECT_ID" \
  --user-id "$USER_ID" --dry-run --json
```

Set `PLAN_SHA256` to the returned hash after reviewing the target, actor, current state and intended change. Repeat the same command with `--apply --expect "$PLAN_SHA256"` only after authorization. User mutations use the current update timestamp and project mutations use the current project revision. The API serializes access changes, preserves at least one usable director account, and revokes the target's sessions and pending authentication challenges on access changes or password reset. Account resets preserve the existing password workflow. Project revocation preserves membership history.

Apply uses the same target, identity and arguments as the preview. A stale plan returns exit 4. Read the updated user or membership afterward and keep the write request ID for the audit record. Create and password-reset apply commands prompt for the temporary password at that point.

### Inspect or propose finance policy

```json
{
  "business_currency": "USD",
  "business_timezone": "Asia/Qatar",
  "material_approval_threshold": "1000.00"
}
```

```bash
python -m scripts.garrisonctl config show --json
python -m scripts.garrisonctl finance policy show --json
python -m scripts.garrisonctl config validate --file proposed-business-config.json --json
python -m scripts.garrisonctl finance policy validate --file proposed-business-config.json --json
python -m scripts.garrisonctl config plan --file proposed-business-config.json --json
python -m scripts.garrisonctl finance policy reconciliation --json
```

The three values come from the application's environment settings. These are the existing defaults. Supported codes are `USD`, `LKR`, and `QAR`. Deployed environments currently require `USD`. Obtain owner approval and reconcile unlabeled money rows and historical approval labels before enabling another operating currency. The director finance access view reports counts and stored currency labels. It never converts or rewrites historical amounts.

The material estimate is routed with a strict greater-than comparison, so exactly `1000.00` follows the existing lower route. The threshold must fit two decimal places and `Numeric(14,2)`. The business timezone uses IANA identifiers. Production Compose supplies the same timezone to backend processes and the frontend build. Database instants and technical events retain UTC. Invoice total is amount plus the entered nonnegative tax amount, subject to the existing two-decimal limit. Confirm the operating currency, threshold, reporting timezone, and accounting conventions with the owner before changing them.

**Host-only configuration preparation.** The root operator runs both commands from a reviewed checkout on the host with access to its protected deployment state.

```bash
python -m scripts.garrisonctl config plan --file proposed-business-config.json \
  --host-state /opt/garrison-portal/deploy --json
python -m scripts.garrisonctl config apply --file proposed-business-config.json \
  --host-state /opt/garrison-portal/deploy --expect "$PLAN_SHA256" \
  --approval-reference "$APPROVAL_REFERENCE" --apply --json
```

The command holds the deployment lock, rechecks the current environment bytes, and prepares an owner-only `production.env` candidate plus an audit receipt. The approval reference records the operator's approval evidence. Review the candidate on the host and activate it using the existing release procedure. Keep the prior approved environment for rollback and use the runbook to restore it if needed. Currency transitions are blocked pending a reviewed reconciliation and migration. [Production procedure](OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions).

After activation, verify the policy against the intended API origin:

```bash
python -m scripts.garrisonctl config verify --file proposed-business-config.json --json
```

### Imports and reconciliation

```bash
python -m scripts.garrisonctl imports templates --type opening_stock --json
python -m scripts.garrisonctl imports preview --type opening_stock --file stock.csv --json
python -m scripts.garrisonctl imports run --type opening_stock --file stock.csv \
  --operation-id "$IMPORT_UUID" --dry-run --json
python -m scripts.garrisonctl imports run --type opening_stock --file stock.csv \
  --operation-id "$IMPORT_UUID" --apply --expect "$PLAN_SHA256" --json
python -m scripts.garrisonctl imports batches --json
python -m scripts.garrisonctl imports status --batch-id "$BATCH_ID" --json
python -m scripts.garrisonctl finance invoices list --project-id "$PROJECT_ID" \
  --status approved --limit 50 --offset 0 --json
python -m scripts.garrisonctl finance invoices show --invoice-id "$INVOICE_ID" --json
python -m scripts.garrisonctl finance budget show --project-id "$PROJECT_ID" --json
python -m scripts.garrisonctl finance reconcile --project-id "$PROJECT_ID" \
  --expected-file expected.json --json
```

Choose a UUID once for each intended import. Reuse the same UUID and unchanged file on retry. The API scopes the key to the actor and rejects changed file bytes, file names or templates under the same key. Save the preview and batch reference. Inspect batch status after an uncertain connection or partial result before retrying. User import files can contain temporary passwords and must be owner-only. [Import templates and required columns](import_templates/README.md).

The supported import templates are `users`, `projects`, `suppliers`, `materials`, `documents`, `boq`, and `opening_stock`. `imports templates` returns the CSV header. The preview reports invalid row numbers and fields without echoing file contents. Use the batch ID from apply for `imports status`. The invoice list and detail provide `INVOICE_ID`, totals and recorded payments for reconciliation.

Reconciliation accepts a JSON object with the datasets to compare. Replace IDs and values with approved controls. For example:

```json
{
  "members": {"7c764ad1-c6e1-4ad1-a286-84bdd525b7ed": {"role_in_project": "Site engineer"}},
  "budget": {"budget_amount": "1200.00", "remaining_budget": "1000.00"},
  "invoice_totals": {"amount": "180.00", "tax_amount": "20.00", "total_amount": "200.00"}
}
```

- `users` maps user IDs to `role` and/or `is_active`. It compares the authorized directory.
- `members`, `invoices` and `payments` map user, invoice and payment IDs respectively to expected fields. These use `--project-id`. Invoice fields include `amount`, `tax_amount`, `total_amount`, `paid_total`, `outstanding_amount`, `status` and `payment_status`. Payment fields include `amount`, `payment_date` and `method`.
- `budget` compares `budget_amount`, `invoiced_total`, `paid_total` and `remaining_budget` for the project. `invoice_totals` sums the specified invoice money fields over the authorized project invoice list.
- `batches` maps known import batch IDs to `row_count`, `error_count`, `status`, `template_type`, `created` and/or `skipped`. It checks only supplied batch IDs.
- `stock` maps location IDs to `on_hand_qty`, `reserved_qty` and/or `available_qty`. Set `--item-id`. For opening balance controls, compare in an environment where the expected opening balances still represent the stock at the chosen reconciliation point.

Use decimal strings for money and quantities. The command reports matched, missing, unexpected and field mismatches. Run multi-page comparisons against a stable dataset. The API does not supply a shared snapshot across these reads. Reconciliation makes no data corrections.

### Diagnose the portal

```bash
python -m scripts.garrisonctl health check --json
python -m scripts.garrisonctl logs search --severity ERROR --limit 20 --json
python -m scripts.garrisonctl logs tail --seconds 15 --max-events 10 --json
python -m scripts.garrisonctl audit search --action users.updated --json
```

Log reads use the existing audit-logged API. Tail returns a bounded batch of events. Output includes event metadata and omits comments and event payloads. The backup and release commands use protected host artifacts.

```bash
python -m scripts.garrisonctl backup status --monitor-profile "$PROFILE" \
  --profile-sha256 "$PROFILE_SHA256" --json
python -m scripts.garrisonctl backup verify --directory "$RECOVERY_SET" \
  --policy "$RECOVERY_POLICY" --require-authenticated --json
python -m scripts.garrisonctl release status --host-state /opt/garrison-portal/deploy --json
```

Backup status checks the independent backup receipts using the approved monitor profile. Verification checks artifacts without restoring them. Release status reads the current deployment receipt. Use readiness for live database connectivity and follow the incident and restore procedures for recovery. [Operations runbook](OPERATIONS_AND_DEPLOYMENT.md) · [Logging guide](LOGGING_AND_REMOTE_CLI.md).

### Tasks handled by existing tools

| Task | Terminal procedure |
| --- | --- |
| Review CI or deployment | Use `gh run list --branch main` and `gh run view "$RUN_ID"` in the GitHub checkout. Compare the intended commit and run result with `garrisonctl release status` and `health check`. [Production deployment and retry](OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions). |
| Inspect live services or bootstrap the first Managing Director | Use the production Compose helper on the authorized host. First-director bootstrap is for an empty installation. Routine account management uses `garrisonctl users`. [Host setup and maintenance](OPERATIONS_AND_DEPLOYMENT.md#host-bootstrap-and-runner-maintenance) · [Post-deploy verification](OPERATIONS_AND_DEPLOYMENT.md#post-deploy-verification). |
| Update mail, ingress, credentials or service settings | Follow the protected host configuration procedure. `garrisonctl config` manages only the three business policy settings. [Environment and configuration](OPERATIONS_AND_DEPLOYMENT.md#environment-and-configuration). |
| Capture, publish or restore backups | Use the recovery scripts with the approved destination, policy, keys and isolated restore target. Verify artifacts before attempting recovery. [Backup and restore](OPERATIONS_AND_DEPLOYMENT.md#backup-and-restore). |
| Diagnose historical data or prepare repairs | Use the named report and repair scripts for the specific defect. Reconcile using the relevant business owner's expected values. [Data checks and repairs](OPERATIONS_AND_DEPLOYMENT.md#data-checks-and-repairs). |
| Review or reverse an activation | Use the existing deployment workflow and verify schema, rollback generation, assets, and readiness from the host. [Rollback](OPERATIONS_AND_DEPLOYMENT.md#rollback). |

Reports, document uploads and approvals, and stock fulfillment remain portal workflows. The active role policy blocks invoice writes and payment entry. The CLI exposes authorized finance reads, project access and approved imports.

## Output and agent use

JSON writes one envelope to stdout with `format_version`, `command`, `environment`, `outcome`, `changed`, `data`, `errors` and `request_id` where available. A preview has `changed: false`. A null change value indicates that the CLI cannot prove whether a mutation committed or was replayed. Read back the resource, batch or audit record before retrying. Check the exit code even when the envelope contains data.

| Exit | Meaning |
| --- | --- |
| 0 | Successful read, preview, verified operation, or unchanged result |
| 2 | Invalid command, configuration, input or API validation failure |
| 3 | Authentication or authorization failure |
| 4 | Missing record, stale plan or other conflict |
| 5 | Connection, readiness or server failure |
| 6 | Failed or partial operation, interrupted command, or failed verification |
| 7 | Reconciliation found differences |

Agents start with `capabilities --json`, confirm the target and caller with `auth whoami`, then inspect the needed records and prepare a dry run. Production writes require the user's explicit authorization. Keep the returned request ID for audit follow-up. If an access change needs reversing, plan a new authorized change against the current state. For binary rollback after changing access, retain the additive access revision migration and coordinate session invalidation because older binaries did not enforce the access revision claim.
