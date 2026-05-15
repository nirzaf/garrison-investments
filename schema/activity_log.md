# activity_log

Stores audit trail entries for sensitive and business-critical actions.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique audit log identifier. |
| `user_id` | `UUID` | FK | User who performed the action. References [users](users.md). |
| `action` | `VARCHAR(30)` |  | Action such as create, update, delete, login, logout, approve, reject, download. |
| `entity_type` | `VARCHAR(30)` |  | Table/business entity affected. |
| `entity_id` | `UUID` |  | Affected record id. Polymorphic by `entity_type`. |
| `old_values` | `JSONB` |  | Previous values for updates/deletes. |
| `new_values` | `JSONB` |  | New values for creates/updates. |
| `ip_address` | `INET` |  | Request IP address. |
| `user_agent` | `TEXT` |  | Browser/app user agent. |
| `created_at` | `TIMESTAMPTZ` |  | Audit timestamp. |

## Relations

- Belongs to [users](users.md) when actor is known.
- Polymorphic relation to the affected business record through `entity_type/entity_id`.

## Indexes

- `idx_audit_user` on `(user_id, created_at DESC)`.
- `idx_audit_entity` on `(entity_type, entity_id)`.
- `idx_audit_date` on `created_at DESC`.

## Retention

Implementation intent is long retention for audit records. Large installations can partition this table by `created_at`.
