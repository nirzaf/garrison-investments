# Database Schema - Current Implementation

This document is generated from the current SQLAlchemy model metadata in `backend/app/models` and should be treated as the current implementation reference. The per-table files in [`schema/`](schema/README.md) contain relationship details for each table.

## Overview

- Total modeled tables: 31
- Primary database: PostgreSQL via SQLAlchemy 2 async models and Alembic migrations.
- Common conventions: UUID primary keys, timestamp mixins, soft-delete mixins for user-facing historical records, object-storage keys for private files, and polymorphic request/reference fields where workflows span modules.

## Table Groups

| Area | Tables |
|---|---|
| Identity and access | [`auth_otp_challenges`](schema/auth_otp_challenges.md), [`auth_refresh_tokens`](schema/auth_refresh_tokens.md), [`users`](schema/users.md) |
| Projects and planning | [`boq_items`](schema/boq_items.md), [`project_members`](schema/project_members.md), [`project_milestones`](schema/project_milestones.md), [`projects`](schema/projects.md) |
| Daily reporting | [`daily_report_approval_history`](schema/daily_report_approval_history.md), [`daily_reports`](schema/daily_reports.md), [`report_equipment`](schema/report_equipment.md), [`report_exports`](schema/report_exports.md), [`report_manpower`](schema/report_manpower.md), [`report_material_consumption`](schema/report_material_consumption.md), [`supervisor_updates`](schema/supervisor_updates.md) |
| Inventory and stores | [`inventory_assets`](schema/inventory_assets.md), [`inventory_items`](schema/inventory_items.md), [`inventory_location_stock`](schema/inventory_location_stock.md), [`inventory_movements`](schema/inventory_movements.md), [`material_request_lines`](schema/material_request_lines.md), [`material_requests`](schema/material_requests.md), [`storage_locations`](schema/storage_locations.md), [`suppliers`](schema/suppliers.md) |
| Documents and media | [`document_versions`](schema/document_versions.md), [`documents`](schema/documents.md), [`photos`](schema/photos.md) |
| Workflow and communication | [`approvals`](schema/approvals.md), [`notifications`](schema/notifications.md) |
| Accounts and finance | [`invoices`](schema/invoices.md), [`payments`](schema/payments.md) |
| Data import and governance | [`activity_log`](schema/activity_log.md), [`import_batches`](schema/import_batches.md) |

## Current Tables

### `activity_log`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | Yes | `` | users.id |
| `action` | `VARCHAR(64)` | No | `` |  |
| `entity_type` | `VARCHAR(64)` | Yes | `` |  |
| `entity_id` | `UUID` | Yes | `` |  |
| `ip_address` | `VARCHAR(64)` | Yes | `` |  |
| `user_agent` | `VARCHAR(512)` | Yes | `` |  |
| `comments` | `TEXT` | Yes | `` |  |
| `old_values` | `JSONB` | Yes | `` |  |
| `new_values` | `JSONB` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `approvals`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_type` | `VARCHAR(60)` | No | `` |  |
| `request_id` | `UUID` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `submitter_id` | `UUID` | Yes | `` | users.id |
| `approver_id` | `UUID` | Yes | `` | users.id |
| `delegated_to_id` | `UUID` | Yes | `` | users.id |
| `escalation_user_id` | `UUID` | Yes | `` | users.id |
| `status` | `VARCHAR(30)` | No | `'pending'` |  |
| `step_order` | `INTEGER` | No | `1` |  |
| `amount` | `NUMERIC(14, 2)` | Yes | `` |  |
| `currency` | `VARCHAR(3)` | Yes | `` |  |
| `title` | `VARCHAR(200)` | No | `` |  |
| `submitter_comments` | `TEXT` | Yes | `` |  |
| `decision_comments` | `TEXT` | Yes | `` |  |
| `delegation_reason` | `TEXT` | Yes | `` |  |
| `override_reason` | `TEXT` | Yes | `` |  |
| `submitted_at` | `DATETIME` | No | `` |  |
| `due_at` | `DATETIME` | No | `` |  |
| `reminded_at` | `DATETIME` | Yes | `` |  |
| `escalated_at` | `DATETIME` | Yes | `` |  |
| `decided_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `auth_otp_challenges`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `purpose` | `VARCHAR(32)` | No | `'login'` |  |
| `otp_hash` | `VARCHAR(255)` | No | `` |  |
| `expires_at` | `DATETIME` | No | `` |  |
| `consumed_at` | `DATETIME` | Yes | `` |  |
| `attempts` | `INTEGER` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `auth_refresh_tokens`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `token_hash` | `VARCHAR(255)` | No | `` |  |
| `expires_at` | `DATETIME` | No | `` |  |
| `revoked_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `boq_items`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `milestone_id` | `UUID` | Yes | `` | project_milestones.id |
| `item_code` | `VARCHAR(50)` | No | `` |  |
| `description` | `TEXT` | No | `` |  |
| `discipline` | `VARCHAR(50)` | Yes | `` |  |
| `phase` | `VARCHAR(100)` | Yes | `` |  |
| `unit` | `VARCHAR(20)` | No | `` |  |
| `planned_quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `approved_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_rate` | `NUMERIC(14, 2)` | No | `` |  |
| `planned_amount` | `NUMERIC(15, 2)` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `daily_report_approval_history`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `actor_id` | `UUID` | Yes | `` | users.id |
| `decision` | `VARCHAR(20)` | No | `` |  |
| `previous_status` | `VARCHAR(20)` | No | `` |  |
| `comments` | `TEXT` | Yes | `` |  |
| `decided_at` | `DATETIME` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `daily_reports`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `engineer_id` | `UUID` | No | `` | users.id |
| `report_number` | `VARCHAR(60)` | Yes | `` |  |
| `report_date` | `DATE` | No | `` |  |
| `work_location` | `VARCHAR(255)` | No | `` |  |
| `manpower_total` | `INTEGER` | No | `0` |  |
| `overtime_hours` | `NUMERIC(5, 2)` | No | `0` |  |
| `work_completed` | `TEXT` | No | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `` |  |
| `safety_incidents` | `INTEGER` | No | `0` |  |
| `safety_notes` | `TEXT` | Yes | `` |  |
| `wir_status` | `VARCHAR(50)` | No | `` |  |
| `inspection_status` | `VARCHAR(50)` | No | `` |  |
| `delay_notes` | `TEXT` | Yes | `` |  |
| `next_day_plan` | `TEXT` | No | `` |  |
| `supervisor_update_ids` | `JSONB` | No | `` |  |
| `photo_refs` | `JSONB` | No | `` |  |
| `attachment_refs` | `JSONB` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'draft'` |  |
| `submitted_at` | `DATETIME` | Yes | `` |  |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `rejection_comments` | `TEXT` | Yes | `` |  |
| `extra_fields` | `JSONB` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `document_versions`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `document_id` | `UUID` | No | `` | documents.id |
| `version` | `INTEGER` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'pending_approval'` |  |
| `storage_path` | `VARCHAR(500)` | No | `` |  |
| `original_name` | `VARCHAR(255)` | No | `` |  |
| `mime_type` | `VARCHAR(80)` | No | `` |  |
| `size_bytes` | `BIGINT` | No | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `approval_comments` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `documents`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `title` | `VARCHAR(255)` | No | `` |  |
| `document_type` | `VARCHAR(30)` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `status` | `VARCHAR(20)` | No | `'pending_approval'` |  |
| `active_version` | `INTEGER` | Yes | `` |  |
| `metadata` | `JSONB` | No | `` |  |
| `expiry_date` | `DATE` | Yes | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `import_batches`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `template_type` | `VARCHAR(40)` | No | `` |  |
| `file_name` | `VARCHAR(255)` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `row_count` | `INTEGER` | No | `0` |  |
| `error_count` | `INTEGER` | No | `0` |  |
| `summary` | `JSONB` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `inventory_assets`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `asset_tag` | `VARCHAR(80)` | No | `` |  |
| `current_location_id` | `UUID` | No | `` | storage_locations.id |
| `condition` | `VARCHAR(40)` | No | `'good'` |  |
| `status` | `VARCHAR(30)` | No | `'active'` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `inventory_items`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(180)` | No | `` |  |
| `item_code` | `VARCHAR(60)` | Yes | `` |  |
| `category` | `VARCHAR(80)` | No | `` |  |
| `item_type` | `VARCHAR(30)` | No | `` |  |
| `unit` | `VARCHAR(20)` | No | `` |  |
| `minimum_stock` | `NUMERIC(14, 3)` | No | `0` |  |
| `reorder_level` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_cost` | `NUMERIC(14, 2)` | Yes | `` |  |
| `supplier_id` | `UUID` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `inventory_location_stock`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `location_id` | `UUID` | No | `` | storage_locations.id |
| `on_hand_qty` | `NUMERIC(14, 3)` | No | `0` |  |
| `reserved_qty` | `NUMERIC(14, 3)` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `inventory_movements`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `asset_id` | `UUID` | Yes | `` | inventory_assets.id |
| `movement_type` | `VARCHAR(30)` | No | `` |  |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `from_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `to_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `reference_type` | `VARCHAR(40)` | Yes | `` |  |
| `reference_id` | `UUID` | Yes | `` |  |
| `handled_by` | `UUID` | Yes | `` | users.id |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `invoices`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `invoice_number` | `VARCHAR(80)` | No | `` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `supplier_id` | `UUID` | Yes | `` | suppliers.id |
| `invoice_date` | `DATE` | No | `` |  |
| `due_date` | `DATE` | No | `` |  |
| `amount` | `NUMERIC(14, 2)` | No | `` |  |
| `tax_amount` | `NUMERIC(14, 2)` | No | `0` |  |
| `total_amount` | `NUMERIC(14, 2)` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `'draft'` |  |
| `payment_status` | `VARCHAR(30)` | No | `'unpaid'` |  |
| `attachment_key` | `VARCHAR(500)` | Yes | `` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `material_request_lines`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_id` | `UUID` | No | `` | material_requests.id |
| `item_id` | `UUID` | No | `` | inventory_items.id |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `reserved_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `issued_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_cost` | `NUMERIC(14, 2)` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `material_requests`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_number` | `VARCHAR(60)` | No | `` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `requester_id` | `UUID` | Yes | `` | users.id |
| `from_location_id` | `UUID` | Yes | `` | storage_locations.id |
| `status` | `VARCHAR(30)` | No | `'requested'` |  |
| `total_estimated_cost` | `NUMERIC(14, 2)` | No | `0` |  |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `notifications`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `user_id` | `UUID` | No | `` | users.id |
| `title` | `VARCHAR(200)` | No | `` |  |
| `body` | `TEXT` | No | `` |  |
| `notification_type` | `VARCHAR(30)` | No | `` |  |
| `reference_type` | `VARCHAR(30)` | Yes | `` |  |
| `reference_id` | `UUID` | Yes | `` |  |
| `is_read` | `BOOLEAN` | No | `false` |  |
| `muted` | `BOOLEAN` | No | `false` |  |
| `email_status` | `VARCHAR(20)` | Yes | `` |  |
| `read_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `payments`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `invoice_id` | `UUID` | No | `` | invoices.id |
| `payment_date` | `DATE` | No | `` |  |
| `amount` | `NUMERIC(14, 2)` | No | `` |  |
| `method` | `VARCHAR(50)` | No | `` |  |
| `reference_number` | `VARCHAR(100)` | Yes | `` |  |
| `recorded_by` | `UUID` | Yes | `` | users.id |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `photos`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `filename` | `VARCHAR(255)` | No | `` |  |
| `original_name` | `VARCHAR(255)` | No | `` |  |
| `storage_path` | `VARCHAR(500)` | No | `` |  |
| `compressed_path` | `VARCHAR(500)` | Yes | `` |  |
| `thumbnail_path` | `VARCHAR(500)` | Yes | `` |  |
| `mime_type` | `VARCHAR(80)` | No | `` |  |
| `size_bytes` | `BIGINT` | No | `` |  |
| `width` | `INTEGER` | Yes | `` |  |
| `height` | `INTEGER` | Yes | `` |  |
| `entity_type` | `VARCHAR(30)` | No | `` |  |
| `entity_id` | `UUID` | No | `` |  |
| `kind` | `VARCHAR(20)` | No | `'photo'` |  |
| `caption` | `TEXT` | Yes | `` |  |
| `taken_at` | `DATETIME` | Yes | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `processing_status` | `VARCHAR(20)` | No | `'ready'` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `project_members`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `user_id` | `UUID` | No | `` | users.id |
| `role_in_project` | `VARCHAR(50)` | Yes | `` |  |
| `assigned_at` | `DATETIME` | No | `now()` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `project_milestones`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `name` | `VARCHAR(150)` | No | `` |  |
| `discipline` | `VARCHAR(50)` | Yes | `` |  |
| `planned_start_date` | `DATE` | Yes | `` |  |
| `planned_end_date` | `DATE` | Yes | `` |  |
| `actual_start_date` | `DATE` | Yes | `` |  |
| `actual_end_date` | `DATE` | Yes | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `0` |  |
| `status` | `VARCHAR(30)` | No | `'not_started'` |  |
| `sort_order` | `INTEGER` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `projects`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(200)` | No | `` |  |
| `code` | `VARCHAR(20)` | No | `` |  |
| `location` | `TEXT` | Yes | `` |  |
| `description` | `TEXT` | Yes | `` |  |
| `scope_of_work` | `TEXT` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `'planning'` |  |
| `budget_amount` | `NUMERIC(15, 2)` | Yes | `` |  |
| `start_date` | `DATE` | Yes | `` |  |
| `target_end_date` | `DATE` | No | `` |  |
| `actual_end_date` | `DATE` | Yes | `` |  |
| `client_name` | `VARCHAR(200)` | Yes | `` |  |
| `contract_number` | `VARCHAR(50)` | Yes | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `0` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `report_equipment`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `equipment_name` | `VARCHAR(120)` | No | `` |  |
| `quantity` | `INTEGER` | No | `` |  |
| `hours_used` | `NUMERIC(6, 2)` | No | `0` |  |
| `remarks` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `report_exports`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `generated_by` | `UUID` | Yes | `` | users.id |
| `file_name` | `VARCHAR(255)` | No | `` |  |
| `object_key` | `VARCHAR(512)` | No | `` |  |
| `content_type` | `VARCHAR(120)` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'ready'` |  |
| `error_message` | `TEXT` | Yes | `` |  |
| `email_status` | `VARCHAR(20)` | Yes | `` |  |
| `email_error` | `TEXT` | Yes | `` |  |
| `emailed_at` | `DATETIME` | Yes | `` |  |
| `generated_at` | `DATETIME` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `report_manpower`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `trade` | `VARCHAR(100)` | No | `` |  |
| `count` | `INTEGER` | No | `` |  |
| `overtime_hours` | `NUMERIC(5, 2)` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `report_material_consumption`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `report_id` | `UUID` | No | `` | daily_reports.id |
| `boq_item_id` | `UUID` | Yes | `` | boq_items.id |
| `material_name` | `VARCHAR(160)` | No | `` |  |
| `unit` | `VARCHAR(30)` | No | `` |  |
| `quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `remarks` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `storage_locations`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(160)` | No | `` |  |
| `code` | `VARCHAR(40)` | No | `` |  |
| `location_type` | `VARCHAR(30)` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `address` | `TEXT` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `supervisor_updates`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `supervisor_id` | `UUID` | No | `` | users.id |
| `update_date` | `DATE` | No | `` |  |
| `day_type` | `VARCHAR(20)` | No | `'weekday'` |  |
| `work_location` | `VARCHAR(255)` | No | `` |  |
| `attendance_count` | `INTEGER` | No | `` |  |
| `overtime_hours` | `NUMERIC(5, 2)` | No | `0` |  |
| `progress_notes` | `TEXT` | No | `` |  |
| `delay_notes` | `TEXT` | Yes | `` |  |
| `required_notes` | `TEXT` | No | `` |  |
| `attachment_refs` | `JSONB` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'draft'` |  |
| `submitted_at` | `DATETIME` | Yes | `` |  |
| `verified_by` | `UUID` | Yes | `` | users.id |
| `verified_at` | `DATETIME` | Yes | `` |  |
| `verification_notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `suppliers`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(200)` | No | `` |  |
| `category` | `VARCHAR(80)` | No | `` |  |
| `rating` | `VARCHAR(20)` | No | `` |  |
| `payment_terms` | `VARCHAR(120)` | No | `` |  |
| `contact_person` | `VARCHAR(150)` | No | `` |  |
| `phone` | `VARCHAR(32)` | No | `` |  |
| `email` | `VARCHAR(255)` | No | `` |  |
| `address` | `TEXT` | No | `` |  |
| `tax_registration_number` | `VARCHAR(80)` | No | `` |  |
| `tds_certificate_number` | `VARCHAR(120)` | Yes | `` |  |
| `tds_expiry_date` | `DATE` | Yes | `` |  |
| `tds_document_key` | `VARCHAR(500)` | Yes | `` |  |
| `compliance_status` | `VARCHAR(30)` | No | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

### `users`

Primary key: `id`

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `email` | `VARCHAR(255)` | No | `` |  |
| `full_name` | `VARCHAR(255)` | No | `` |  |
| `role` | `VARCHAR(64)` | No | `` |  |
| `employee_code` | `VARCHAR(64)` | Yes | `` |  |
| `phone` | `VARCHAR(32)` | Yes | `` |  |
| `designation` | `VARCHAR(100)` | Yes | `` |  |
| `password_hash` | `VARCHAR(255)` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `must_change_password` | `BOOLEAN` | No | `true` |  |
| `failed_login_attempts` | `INTEGER` | No | `0` |  |
| `locked_until` | `DATETIME` | Yes | `` |  |
| `last_login_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Notes

- This document intentionally follows the implemented model names, even where they differ from earlier planning terminology.
- Query/index details that are migration-specific should be checked in `backend/alembic/versions` when preparing database changes.
- Production launch evidence and sign-off requirements are tracked in `09_Production_Readiness_Evidence.md`.
