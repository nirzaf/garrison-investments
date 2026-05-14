# Database Schema — Construction Internal Portal

## Overview

PostgreSQL 16 schema designed for a construction company's internal operations. Uses UUIDs for security, JSONB for flexible report fields, and includes a comprehensive audit trail system.

---

## Entity Relationship Diagram (Key Tables)

```
┌───────────┐     ┌───────────────┐     ┌──────────────────┐
│   users   │────▶│  user_roles   │     │  audit_log       │
└─────┬─────┘     └───────────────┘     └──────────────────┘
      │
      ├────▶┌────────────────┐
      │     │  notifications  │
      │     └────────────────┘
      │
      ├────▶┌────────────────────┐
      │     │  daily_reports     │◀────┐
      │     └─────────┬──────────┘     │
      │               │                │
      │               ├──▶ report_photos    (photos table)
      │               ├──▶ report_material  (material_consumption)
      │               └──▶ report_manpower  (manpower_entries)
      │
      ├────▶┌────────────────┐
      │     │  projects       │
      │     └────────┬───────┘
      │              ├──▶ project_members
      │              └──▶ project_photos
      │
      ├────▶┌────────────────┐
      │     │  materials      │◀── material_transactions
      │     └────────┬───────┘
      │              └── material_suppliers
      │
      ├────▶┌────────────────┐
      │     │  documents      │◀── document_versions
      │     └────────────────┘
      │
      └────▶┌────────────────┐
            │  approvals      │
            └────────────────┘
```

---

## Core Tables

### 1. users

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(20),
    employee_code VARCHAR(20) UNIQUE,
    role VARCHAR(50) NOT NULL CHECK (role IN (
        'admin', 'operation_manager', 'project_manager',
        'civil_engineer', 'civil_supervisor',
        'store_keeper', 'accounts'
    )),
    designation VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    refresh_token_hash VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ           -- soft delete
);

CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_role ON users(role) WHERE deleted_at IS NULL;
```

### 2. projects

```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    code VARCHAR(20) UNIQUE NOT NULL,
    location TEXT,
    description TEXT,
    status VARCHAR(30) DEFAULT 'active' CHECK (status IN (
        'planning', 'active', 'on_hold', 'completed', 'cancelled'
    )),
    budget_amount DECIMAL(15,2),
    start_date DATE,
    target_end_date DATE,
    actual_end_date DATE,
    client_name VARCHAR(200),
    contract_number VARCHAR(50),
    progress_percentage DECIMAL(5,2) DEFAULT 0,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_projects_status ON projects(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_code ON projects(code);
```

### 3. project_members

```sql
CREATE TABLE project_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_in_project VARCHAR(50),     -- e.g. "lead_engineer", "supervisor"
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, user_id)
);

CREATE INDEX idx_project_members_project ON project_members(project_id);
CREATE INDEX idx_project_members_user ON project_members(user_id);
```

### 4. daily_reports

```sql
CREATE TABLE daily_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id),
    report_date DATE NOT NULL,
    submitted_by UUID NOT NULL REFERENCES users(id),
    
    -- Report Content
    weather_condition VARCHAR(30),
    temperature DECIMAL(4,1),
    work_completed TEXT NOT NULL,
    progress_percentage DECIMAL(5,2),
    issues_delays TEXT,
    next_day_plan TEXT,
    notes TEXT,
    
    -- Flexible extra fields (custom form questions per project)
    extra_fields JSONB DEFAULT '{}',
    
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN (
        'draft', 'submitted', 'approved', 'rejected'
    )),
    
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,
    
    -- Draft sync for offline mobile
    is_synced BOOLEAN DEFAULT TRUE,
    local_created_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    
    -- One report per project per day
    UNIQUE(project_id, report_date, deleted_at)
);

CREATE INDEX idx_reports_project ON daily_reports(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_reports_date ON daily_reports(report_date DESC);
CREATE INDEX idx_reports_status ON daily_reports(status);
CREATE INDEX idx_reports_extra ON daily_reports USING GIN (extra_fields);

COMMENT ON COLUMN daily_reports.extra_fields IS 'Flexible JSON:{"soil_condition":"wet","safety_incidents":0}';
```

### 5. report_manpower

```sql
CREATE TABLE report_manpower (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id UUID NOT NULL REFERENCES daily_reports(id) ON DELETE CASCADE,
    labor_type VARCHAR(50) NOT NULL,     -- 'skilled', 'unskilled', 'operator', 'technician'
    trade VARCHAR(100),                   -- 'mason', 'carpenter', 'electrician', 'plumber'
    count INT NOT NULL CHECK (count > 0),
    hours_worked DECIMAL(4,1),
    overtime_hours DECIMAL(4,1) DEFAULT 0,
    notes TEXT
);

CREATE INDEX idx_manpower_report ON report_manpower(report_id);
```

### 6. report_equipment

```sql
CREATE TABLE report_equipment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id UUID NOT NULL REFERENCES daily_reports(id) ON DELETE CASCADE,
    equipment_name VARCHAR(100) NOT NULL,
    quantity INT DEFAULT 1,
    hours_used DECIMAL(5,1),
    status VARCHAR(20) DEFAULT 'operational',
    notes TEXT
);

CREATE INDEX idx_equipment_report ON report_equipment(report_id);
```

### 7. report_material_consumption

```sql
CREATE TABLE report_material_consumption (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id UUID NOT NULL REFERENCES daily_reports(id) ON DELETE CASCADE,
    material_id UUID REFERENCES materials(id),
    material_name VARCHAR(150) NOT NULL,
    quantity DECIMAL(10,3) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    wastage DECIMAL(10,3) DEFAULT 0,
    notes TEXT
);

CREATE INDEX idx_consumption_report ON report_material_consumption(report_id);
```

### 8. materials

```sql
CREATE TABLE materials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(150) NOT NULL,
    code VARCHAR(30) UNIQUE,
    category VARCHAR(50) NOT NULL,       -- 'cement', 'steel', 'aggregate', 'electrical', 'plumbing'
    unit VARCHAR(20) NOT NULL,           -- 'kg', 'ton', 'm3', 'pcs', 'bags'
    current_stock DECIMAL(12,3) DEFAULT 0,
    minimum_stock DECIMAL(12,3) DEFAULT 0,
    reorder_point DECIMAL(12,3),
    unit_price DECIMAL(12,2),
    supplier_id UUID REFERENCES suppliers(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_materials_category ON materials(category) WHERE deleted_at IS NULL;
CREATE INDEX idx_materials_low_stock ON materials(current_stock, minimum_stock)
    WHERE deleted_at IS NULL AND current_stock <= minimum_stock;
```

### 9. material_transactions

```sql
CREATE TABLE material_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    material_id UUID NOT NULL REFERENCES materials(id),
    transaction_type VARCHAR(10) NOT NULL CHECK (transaction_type IN ('in', 'out')),
    quantity DECIMAL(10,3) NOT NULL CHECK (quantity > 0),
    reference_type VARCHAR(30),         -- 'purchase', 'consumption', 'return', 'transfer', 'adjustment'
    reference_id UUID,                   -- ID from related table (PO, report, etc.)
    performed_by UUID NOT NULL REFERENCES users(id),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_transactions_material ON material_transactions(material_id);
CREATE INDEX idx_transactions_date ON material_transactions(created_at DESC);
```

### 10. suppliers

```sql
CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(150),
    phone VARCHAR(20),
    email VARCHAR(255),
    address TEXT,
    gst_number VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
```

### 11. photos

```sql
CREATE TABLE photos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(255) NOT NULL,
    original_name VARCHAR(255),
    storage_path VARCHAR(500) NOT NULL,      -- MinIO object key
    thumbnail_path VARCHAR(500),
    mime_type VARCHAR(50),
    size_bytes BIGINT,
    width INT,
    height INT,
    
    -- Polymorphic association
    entity_type VARCHAR(30) NOT NULL,        -- 'daily_report', 'project', 'material', 'document'
    entity_id UUID NOT NULL,
    
    caption TEXT,
    taken_at TIMESTAMPTZ,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_photos_entity ON photos(entity_type, entity_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_photos_date ON photos(created_at DESC);
```

### 12. documents

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL,
    document_type VARCHAR(30) NOT NULL CHECK (document_type IN (
        'drawing', 'boq', 'contract', 'wir', 'invoice', 'other'
    )),
    project_id UUID REFERENCES projects(id),
    storage_path VARCHAR(500) NOT NULL,
    mime_type VARCHAR(50),
    size_bytes BIGINT,
    version INT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN (
        'draft', 'active', 'superseded', 'archived'
    )),
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_documents_project ON documents(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_type ON documents(document_type) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_search ON documents
    USING GIN (to_tsvector('english', title));
```

### 13. document_versions

```sql
CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INT NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    size_bytes BIGINT,
    change_notes TEXT,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_doc_version ON document_versions(document_id, version);
```

### 14. approvals

```sql
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_type VARCHAR(30) NOT NULL,       -- 'daily_report', 'material_request', 'document', 'leave'
    request_id UUID NOT NULL,                 -- ID from the source table
    requested_by UUID NOT NULL REFERENCES users(id),
    approver_id UUID NOT NULL REFERENCES users(id),
    approval_level INT DEFAULT 1,            -- Multi-level: level 1, 2, 3
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'cancelled'
    )),
    comments TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_approvals_approver ON approvals(approver_id, status);
CREATE INDEX idx_approvals_request ON approvals(request_type, request_id);
```

### 15. notifications

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    body TEXT,
    notification_type VARCHAR(30),       -- 'approval', 'alert', 'reminder', 'announcement'
    reference_type VARCHAR(30),
    reference_id UUID,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_user ON notifications(user_id, is_read, created_at DESC);
```

### 16. activity_log (Audit Trail)

```sql
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(30) NOT NULL,         -- 'create', 'update', 'delete', 'login', 'logout', 'approve'
    entity_type VARCHAR(30) NOT NULL,    -- 'user', 'project', 'daily_report', 'material', etc.
    entity_id UUID,
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_user ON activity_log(user_id, created_at DESC);
CREATE INDEX idx_audit_entity ON activity_log(entity_type, entity_id);
CREATE INDEX idx_audit_date ON activity_log(created_at DESC);

-- Auto-partition by month for large installations (optional)
-- CREATE TABLE activity_log PARTITION BY RANGE (created_at);
```

---

## Index Strategy Summary

| Table | Index | Type | Reason |
|-------|-------|------|--------|
| `users` | `email` | B-tree (partial) | Login lookup |
| `users` | `role` | B-tree (partial) | Role-based filtering |
| `daily_reports` | `project_id, report_date` | Composite unique | One report per project per day |
| `daily_reports` | `extra_fields` | GIN | Querying JSONB custom fields |
| `documents` | `title` | GIN (tsvector) | Full-text search |
| `materials` | `current_stock, minimum_stock` | B-tree (partial) | Low-stock alerts query |
| `activity_log` | `created_at` | B-tree (DESC) | Time-range audit queries |
| `notifications` | `user_id, is_read, created_at` | Composite | Unread notification count |
| `approvals` | `approver_id, status` | Composite | Pending approvals inbox |

---

## Trigger Functions

### update_timestamp

```sql
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Applied to all tables with updated_at column
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
-- (repeat for projects, daily_reports, materials, documents)
```

### audit_trigger

```sql
CREATE OR REPLACE FUNCTION fn_audit_trigger()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO activity_log (user_id, action, entity_type, entity_id, old_values, new_values)
    VALUES (
        current_setting('app.current_user_id', TRUE)::UUID,
        TG_ARGV[0],
        TG_TABLE_NAME,
        NEW.id,
        CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) ELSE NULL END,
        to_jsonb(NEW)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```
