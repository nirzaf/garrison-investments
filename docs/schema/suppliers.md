# suppliers

Defined in `backend/app/models/supplier.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `address` | Text | NOT NULL | — | — | — |
| `category` | String(80) | NOT NULL | — | — | — |
| `compliance_status` | String(30) | NOT NULL | — | — | — |
| `contact_person` | String(150) | NOT NULL | — | — | — |
| `email` | String(255) | NOT NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
| `name` | String(200) | NOT NULL | — | — | — |
| `payment_terms` | String(120) | NOT NULL | — | — | — |
| `phone` | String(32) | NOT NULL | — | — | — |
| `rating` | String(20) | NOT NULL | — | — | — |
| `tax_registration_number` | String(80) | NOT NULL | — | — | — |
| `tds_certificate_number` | String(120) | NULL | — | — | — |
| `tds_document_key` | String(500) | NULL | — | — | — |
| `tds_expiry_date` | Date | NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

