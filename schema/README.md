# PostgreSQL Schema Implementation Intent

This folder documents the intended PostgreSQL schema for the Construction Internal Portal. It is organized as one file per table so engineers can review relationships and implementation behavior without reading one long schema file.

The schema is designed for PostgreSQL 16 with UUID primary keys, soft deletes on user-facing records, audit logging, approval routing, document/media storage metadata, location-aware inventory, and project-level finance.

## Table Groups

| Area | Tables |
|---|---|
| Identity and access | [users](users.md) |
| Projects and planning | [projects](projects.md), [project_members](project_members.md), [project_milestones](project_milestones.md), [boq_items](boq_items.md) |
| Daily reporting | [daily_reports](daily_reports.md), [report_manpower](report_manpower.md), [report_equipment](report_equipment.md), [report_material_consumption](report_material_consumption.md) |
| Inventory and stores | [suppliers](suppliers.md), [storage_locations](storage_locations.md), [inventory_items](inventory_items.md), [inventory_location_stock](inventory_location_stock.md), [inventory_assets](inventory_assets.md), [inventory_movements](inventory_movements.md) |
| Documents and media | [documents](documents.md), [document_versions](document_versions.md), [photos](photos.md) |
| Workflow and communication | [approvals](approvals.md), [notifications](notifications.md) |
| Accounts and finance | [invoices](invoices.md), [payments](payments.md) |
| Governance | [activity_log](activity_log.md) |

## Relationship Map

```mermaid
erDiagram
  users ||--o{ projects : creates
  users ||--o{ project_members : assigned
  projects ||--o{ project_members : has
  projects ||--o{ project_milestones : plans
  projects ||--o{ boq_items : budgets
  projects ||--o{ daily_reports : receives
  projects ||--o{ storage_locations : may_have_site_store
  projects ||--o{ documents : stores
  projects ||--o{ invoices : costs

  daily_reports ||--o{ report_manpower : records
  daily_reports ||--o{ report_equipment : records
  daily_reports ||--o{ report_material_consumption : records
  inventory_items ||--o{ report_material_consumption : consumed

  suppliers ||--o{ inventory_items : supplies
  inventory_items ||--o{ inventory_location_stock : stocked_at
  storage_locations ||--o{ inventory_location_stock : holds
  inventory_items ||--o{ inventory_assets : serialized_as
  storage_locations ||--o{ inventory_assets : current_location
  inventory_items ||--o{ inventory_movements : moves
  inventory_assets ||--o{ inventory_movements : asset_moves
  storage_locations ||--o{ inventory_movements : from_or_to

  documents ||--o{ document_versions : versions
  users ||--o{ documents : uploads
  users ||--o{ photos : uploads

  users ||--o{ approvals : requests
  users ||--o{ approvals : decides
  approvals ||--o{ inventory_movements : authorizes
  approvals ||--o{ invoices : authorizes

  invoices ||--o{ payments : paid_by
  users ||--o{ notifications : receives
  users ||--o{ activity_log : performs
```

## Cross-Cutting Rules

- Every table uses `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()` unless noted.
- User-facing records use `deleted_at TIMESTAMPTZ` for soft delete where historical traceability matters.
- Records with mutable business state use `created_at` and `updated_at`.
- Approval-controlled records store the workflow in [approvals](approvals.md) and keep the business record immutable after approval unless an audited override is used.
- Files are stored in object storage; PostgreSQL stores metadata and object keys only.
- Inventory current location is warehouse/site only. Person and vehicle custody are intentionally out of scope for this version.
