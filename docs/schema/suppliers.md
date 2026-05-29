# suppliers

Defined in `backend/app/models/supplier.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `name` | String(200) | NOT NULL | — | — | — |
| `category` | String(80) | NOT NULL | — | — | — |
| `rating` | String(20) | NOT NULL | — | — | — |
| `payment_terms` | String(120) | NOT NULL | — | — | — |
| `contact_person` | String(150) | NOT NULL | — | — | — |
| `phone` | String(32) | NOT NULL | — | — | — |
| `email` | String(255) | NOT NULL | — | — | — |
| `address` | Text | NOT NULL | — | — | — |
| `tax_registration_number` | String(80) | NOT NULL | — | — | — |
| `tds_certificate_number` | String(120) | NULL | — | — | — |
| `tds_expiry_date` | Date | NULL | — | — | — |
| `tds_document_key` | String(500) | NULL | — | — | — |
| `compliance_status` | String(30) | NOT NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
