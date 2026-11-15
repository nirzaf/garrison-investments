# Import templates

Use the [portal import screen](../../frontend/src/pages/admin/ImportPage.tsx) at `/admin/imports` to download templates, preview CSV or XLSX files, and submit a batch. The screen and [import API](../../backend/app/api/v1/imports.py) require `users:manage`.

The [import service](../../backend/app/services/import_service.py) also checks
the template's own permission. Suppliers require `suppliers:manage`. Materials
and opening stock require `inventory:manage`. Document metadata requires
`documents:manage`. Project and priced BOQ imports require
`projects:manage` and a director role. Queued imports recheck the submitting
account and template access when processing begins.

| Template | Records | Required references |
| --- | --- | --- |
| [Users](users.csv) | Accounts with an assigned role and temporary password | Role from the [permission reference](../ROLES_AND_PERMISSIONS.md) |
| [Projects](projects.csv) | Project details, schedule, and budget | |
| [Suppliers](suppliers.csv) | Supplier contact, tax, and compliance details | |
| [Materials](materials.csv) | Inventory catalog, cost, and reorder settings | Existing supplier by name |
| [Bill of quantities](boq.csv) | Project line items with quantities and rates | Existing project by code |
| [Opening stock](opening_stock.csv) | Positive stock quantities by location | Existing item and storage location by code |
| [Documents](documents.csv) | Document metadata for a project | Existing project by code. Upload actual files through the document library. |

Keep every template header, including columns that can have blank values. Put XLSX headers in the first row of the first worksheet. Use `YYYY-MM-DD` for dates. Keep real import files, especially user passwords, outside the repository.

From the repository root, run the [source validator](../../backend/scripts/validate_import_sources.py) with the backend environment from the [setup guide](../../README.md#getting-started). The first command checks the supplied templates. The second checks a specific file.

```bash
cd backend
.venv/bin/python scripts/validate_import_sources.py --check
.venv/bin/python scripts/validate_import_sources.py --source projects=/absolute/path/projects.csv --check
```

The CLI checks file structure and row values. The portal preview also checks references against the target database. Resolve preview errors before running the import, then review the batch status and summary for created and skipped records. The [import service](../../backend/app/services/import_service.py) defines field validation and duplicate handling.

If an import response is lost, retry with the file still selected or check Recent imports for the batch before selecting it again. The portal reuses the same submission key for the selected file and template. Selecting a file again or changing the template starts a new submission. API clients can retry either run endpoint with the same `Idempotency-Key`, template, filename and bytes to recover the existing batch.
