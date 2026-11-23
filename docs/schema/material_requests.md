# material_requests

Project material requests, including the source storage location and estimated cost.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `request_number` | `varchar(60)` | No | — |
| `project_id` | `uuid` | No | — |
| `requester_id` | `uuid` | Yes | — |
| `from_location_id` | `uuid` | Yes | — |
| `status` | `varchar(30)` | No | `'requested'` |
| `revision` | `integer` | No | `1` |
| `submission_revision` | `integer` | Yes | — |
| `total_estimated_cost` | `numeric(14, 2)` | No | `0` |
| `notes` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_material_requests` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_material_requests_from_location_id_storage_locations` | `(from_location_id)` | [`storage_locations(id)`](storage_locations.md) | `SET NULL` |
| `fk_material_requests_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |
| `fk_material_requests_requester_id_users` | `(requester_id)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_material_requests_project` | `btree` | `project_id, status` | No | — |
| `uq_material_requests_number` | `btree` | `request_number` | Yes | — |

## Submitted requirements

`material_request_submissions` keeps immutable requirements and line quantities
keyed by `(request_id, submission_revision)`, with submitter and optional
administrative processor. Approval stages refer to this key. Stock mutations
advance `material_requests.revision`; corrected submissions advance
`submission_revision` and start both approval stages again. Legacy rows keep a
null submission revision until they enter the staged workflow.
[Migration 102](../../backend/alembic/versions/202605310102_material_submission_revisions.py)
