# Graph Report - backend  (2026-05-26)

## Corpus Check
- 162 files · ~52,290 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1712 nodes · 8832 edges · 67 communities
- Extraction: 52% EXTRACTED · 48% INFERRED · 0% AMBIGUOUS · INFERRED: 4230 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Dashboard & Activity Logging|Dashboard & Activity Logging]]
- [[_COMMUNITY_Daily Reporting Module|Daily Reporting Module]]
- [[_COMMUNITY_Auth & Audit Dependencies|Auth & Audit Dependencies]]
- [[_COMMUNITY_Approval Workflow|Approval Workflow]]
- [[_COMMUNITY_Project Management|Project Management]]
- [[_COMMUNITY_Photo Management|Photo Management]]
- [[_COMMUNITY_Document Management|Document Management]]
- [[_COMMUNITY_Data Import Pipeline|Data Import Pipeline]]
- [[_COMMUNITY_Supplier Management|Supplier Management]]
- [[_COMMUNITY_Notification System|Notification System]]
- [[_COMMUNITY_Analytics & Reporting|Analytics & Reporting]]
- [[_COMMUNITY_Health Monitoring & Scripts|Health Monitoring & Scripts]]
- [[_COMMUNITY_Daily Reports Test Suite|Daily Reports Test Suite]]
- [[_COMMUNITY_Supervisor Updates API|Supervisor Updates API]]
- [[_COMMUNITY_Core Models & Utilities|Core Models & Utilities]]
- [[_COMMUNITY_User Repository|User Repository]]
- [[_COMMUNITY_RequestRoute Dependencies|Request/Route Dependencies]]
- [[_COMMUNITY_Email & Exception Handling|Email & Exception Handling]]
- [[_COMMUNITY_Inventory Schemas|Inventory Schemas]]
- [[_COMMUNITY_Auth Service|Auth Service]]
- [[_COMMUNITY_Database & Config Settings|Database & Config Settings]]
- [[_COMMUNITY_Auth Tests & Config|Auth Tests & Config]]
- [[_COMMUNITY_Finance Test Suite|Finance Test Suite]]
- [[_COMMUNITY_Exceptions & Permissions|Exceptions & Permissions]]
- [[_COMMUNITY_Auth Repository|Auth Repository]]
- [[_COMMUNITY_Backup Scripts|Backup Scripts]]
- [[_COMMUNITY_Async Tasks & Email|Async Tasks & Email]]
- [[_COMMUNITY_Database Health & Supplier Tests|Database Health & Supplier Tests]]
- [[_COMMUNITY_Inventory API|Inventory API]]
- [[_COMMUNITY_Analytics Test Suite|Analytics Test Suite]]
- [[_COMMUNITY_App Bootstrap & Health Tests|App Bootstrap & Health Tests]]
- [[_COMMUNITY_Supervisor Updates Test Suite|Supervisor Updates Test Suite]]
- [[_COMMUNITY_Approvals Test Suite|Approvals Test Suite]]
- [[_COMMUNITY_Inventory Test Suite|Inventory Test Suite]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_Projects Test Suite|Projects Test Suite]]
- [[_COMMUNITY_Rate Limiting Middleware|Rate Limiting Middleware]]
- [[_COMMUNITY_Database Backup Tasks|Database Backup Tasks]]
- [[_COMMUNITY_Inventory Items Schemas|Inventory Items Schemas]]
- [[_COMMUNITY_Alembic Environment|Alembic Environment]]
- [[_COMMUNITY_Migration Daily Reports|Migration: Daily Reports]]
- [[_COMMUNITY_Migration Report Exports|Migration: Report Exports]]
- [[_COMMUNITY_Migration Photos|Migration: Photos]]
- [[_COMMUNITY_Inventory Stock API|Inventory Stock API]]
- [[_COMMUNITY_Migration Projects BOQ|Migration: Projects BOQ]]
- [[_COMMUNITY_Migration Supervisor Updates|Migration: Supervisor Updates]]
- [[_COMMUNITY_Migration Daily Report Approvals|Migration: Daily Report Approvals]]
- [[_COMMUNITY_Migration Documents|Migration: Documents]]
- [[_COMMUNITY_Image Processing Tasks|Image Processing Tasks]]

## God Nodes (most connected - your core abstractions)
1. `User` - 503 edges
2. `AppException` - 342 edges
3. `DbSession` - 233 edges
4. `AuditService` - 203 edges
5. `NotFoundException` - 173 edges
6. `UserRepository` - 138 edges
7. `Project` - 120 edges
8. `ProjectMember` - 117 edges
9. `InventoryService` - 116 edges
10. `ApprovalService` - 110 edges

## Surprising Connections (you probably didn't know these)
- `str` --uses--> `Settings`  [INFERRED]
  tests/test_daily_reports.py → app/config.py
- `AsyncClient` --uses--> `Settings`  [INFERRED]
  tests/test_daily_reports.py → app/config.py
- `test_unhandled_exception_email_respects_disabled_config()` --calls--> `FastAPI`  [INFERRED]
  tests/test_exception_reporting.py → app/main.py
- `Namespace` --uses--> `Request`  [INFERRED]
  scripts/health_monitor.py → app/utils/request.py
- `int` --uses--> `Request`  [INFERRED]
  scripts/launch_evidence.py → app/utils/request.py

## Communities (67 total, 0 thin omitted)

### Community 0 - "Dashboard & Activity Logging"
Cohesion: 0.05
Nodes (138): CurrentUser, DashboardSummaryResponse, DbSession, AsyncSession, Select, str, AsyncSession, bool (+130 more)

### Community 1 - "Daily Reporting Module"
Cohesion: 0.06
Nodes (83): CurrentUser, DailyReportCreateRequest, DailyReportUpdateRequest, DbSession, ge, int, le, Query (+75 more)

### Community 2 - "Auth & Audit Dependencies"
Cohesion: 0.06
Nodes (120): ActivityLog, get_current_user(), require_permission(), DbSession, str, User, DbSession, ge (+112 more)

### Community 3 - "Approval Workflow"
Cohesion: 0.08
Nodes (70): alias, ApprovalCreateRequest, CurrentUser, DbSession, ge, int, le, max_length (+62 more)

### Community 4 - "Project Management"
Cohesion: 0.16
Nodes (56): DbSession, ge, int, le, max_length, ProjectCreateRequest, ProjectMemberCreateRequest, ProjectTaskCreateRequest (+48 more)

### Community 5 - "Photo Management"
Cohesion: 0.09
Nodes (46): DbSession, File, Form, ge, int, le, Query, str (+38 more)

### Community 6 - "Document Management"
Cohesion: 0.11
Nodes (45): date, DbSession, File, Form, Query, str, UploadFile, UUID (+37 more)

### Community 7 - "Data Import Pipeline"
Cohesion: 0.09
Nodes (43): DbSession, File, ImportPreviewResponse, ImportRunResponse, Response, str, UploadFile, UUID (+35 more)

### Community 8 - "Supplier Management"
Cohesion: 0.16
Nodes (41): bool, DbSession, File, ge, int, le, max_length, Query (+33 more)

### Community 9 - "Notification System"
Cohesion: 0.10
Nodes (36): CurrentUser, DbSession, int, str, UUID, AsyncSession, datetime, int (+28 more)

### Community 10 - "Analytics & Reporting"
Cohesion: 0.17
Nodes (36): alias, AnalyticsSummaryResponse, bool, CurrentUser, date, DbSession, max_length, Query (+28 more)

### Community 11 - "Health Monitoring & Scripts"
Cohesion: 0.11
Nodes (40): Request, check_url(), HealthCheckResult, main(), parse_args(), parse_recipients(), int, Namespace (+32 more)

### Community 12 - "Daily Reports Test Suite"
Cohesion: 0.16
Nodes (31): create_test_client(), create_user(), login_for_token(), project_payload(), AsyncClient, str, report_payload(), setup_project_team() (+23 more)

### Community 13 - "Supervisor Updates API"
Cohesion: 0.20
Nodes (27): CurrentUser, DbSession, ge, int, le, Query, str, SupervisorUpdateCreateRequest (+19 more)

### Community 14 - "Core Models & Utilities"
Cohesion: 0.09
Nodes (31): BaseModel, AuditLogListResponse, AuditLogResponse, AuthUserResponse, LoginChallengeResponse, LoginRequest, MessageResponse, PasswordChangeRequest (+23 more)

### Community 15 - "User Repository"
Cohesion: 0.12
Nodes (18): AsyncSession, bool, int, Select, str, User, UUID, UserRepository (+10 more)

### Community 16 - "Request/Route Dependencies"
Cohesion: 0.13
Nodes (21): get_request_meta(), Request, str, lifespan(), Request, Response, str, UUID (+13 more)

### Community 17 - "Email & Exception Handling"
Cohesion: 0.16
Nodes (19): int, str, Any, Exception, Request, str, BaseException, EmailService (+11 more)

### Community 18 - "Inventory Schemas"
Cohesion: 0.16
Nodes (24): AssetCreateRequest, DbSession, LocationCreateRequest, MaterialRequestCreateRequest, MovementCreateRequest, UUID, AssetResponse, CanManageInventory (+16 more)

### Community 19 - "Auth Service"
Cohesion: 0.29
Nodes (9): str, User, UUID, RequestMeta, SessionResult, generate_otp(), hash_password(), hash_secret() (+1 more)

### Community 20 - "Database & Config Settings"
Cohesion: 0.22
Nodes (16): get_settings(), get_db(), AsyncSession, bool, datetime, str, UUID, ErrorDetail (+8 more)

### Community 21 - "Auth Tests & Config"
Cohesion: 0.31
Nodes (16): Settings, BaseSettings, create_test_client(), create_test_user(), AsyncClient, bool, str, skip_if_database_unavailable() (+8 more)

### Community 22 - "Finance Test Suite"
Cohesion: 0.24
Nodes (14): create_project_and_supplier(), create_test_client(), create_user(), FakeMinioClient, login_for_token(), AsyncClient, MonkeyPatch, Project (+6 more)

### Community 23 - "Exceptions & Permissions"
Cohesion: 0.20
Nodes (11): int, str, bool, str, User, test_accounts_permissions_match_finance_scope(), BusinessRuleException, PermissionDeniedException (+3 more)

### Community 24 - "Auth Repository"
Cohesion: 0.26
Nodes (11): AsyncSession, bool, str, UUID, AsyncSession, AuthOtpChallenge, AuthRefreshToken, AuthOtpChallenge (+3 more)

### Community 25 - "Backup Scripts"
Cohesion: 0.30
Nodes (16): cleanup_retention(), create_dump(), encrypt_file(), ensure_bucket(), get_minio_client(), main(), monthly_retention_days(), normalize_pg_url() (+8 more)

### Community 26 - "Async Tasks & Email"
Cohesion: 0.21
Nodes (14): str, T, run_async_task(), _run_with_fresh_pool(), send_email_notification(), send_report_email(), _business_now(), check_late_reports() (+6 more)

### Community 27 - "Database Health & Supplier Tests"
Cohesion: 0.23
Nodes (13): check_database(), bool, create_test_client(), create_user(), FakeMinioClient, login_for_token(), AsyncClient, MonkeyPatch (+5 more)

### Community 28 - "Inventory API"
Cohesion: 0.25
Nodes (12): AssetCreateRequest, AssetResponse, InventoryItemCreateRequest, InventoryItemResponse, LocationCreateRequest, LocationResponse, MaterialRequestCreateRequest, MaterialRequestLineCreate (+4 more)

### Community 29 - "Analytics Test Suite"
Cohesion: 0.27
Nodes (12): generate_excel_export(), create_test_client(), create_user(), login_for_token(), AsyncClient, str, User, skip_if_database_unavailable() (+4 more)

### Community 30 - "App Bootstrap & Health Tests"
Cohesion: 0.29
Nodes (11): create_app(), test_api_root(), test_health_returns_status(), create_test_client(), create_user(), login_for_token(), AsyncClient, str (+3 more)

### Community 31 - "Supervisor Updates Test Suite"
Cohesion: 0.41
Nodes (12): create_test_client(), create_user(), login_for_token(), project_payload(), AsyncClient, str, setup_assigned_supervisor_project(), skip_if_database_unavailable() (+4 more)

### Community 32 - "Approvals Test Suite"
Cohesion: 0.32
Nodes (10): create_project(), create_test_client(), create_user(), login_for_token(), AsyncClient, str, User, skip_if_database_unavailable() (+2 more)

### Community 33 - "Inventory Test Suite"
Cohesion: 0.36
Nodes (11): create_project(), create_test_client(), create_user(), login_for_token(), AsyncClient, Project, str, User (+3 more)

### Community 34 - "App Configuration"
Cohesion: 0.27
Nodes (11): cors_origins_list(), exception_email_recipients_list(), minio_signed_url_endpoint(), minio_signed_url_secure(), normalized_frontend_base_url(), bool, str, should_expose_dev_otp() (+3 more)

### Community 35 - "Projects Test Suite"
Cohesion: 0.42
Nodes (10): create_test_client(), create_user(), login_for_token(), project_payload(), AsyncClient, str, skip_if_database_unavailable(), test_assigned_engineer_can_read_assigned_project_only() (+2 more)

### Community 36 - "Rate Limiting Middleware"
Cohesion: 0.39
Nodes (5): bool, int, Request, str, AuthRateLimiter

### Community 37 - "Database Backup Tasks"
Cohesion: 0.39
Nodes (5): bool, str, backup_command(), run_database_backup(), test_backup_command_uses_current_python_and_monthly_flag()

### Community 38 - "Inventory Items Schemas"
Cohesion: 0.29
Nodes (7): InventoryItemCreateRequest, max_length, Query, str, InventoryItemResponse, create_item(), list_items()

### Community 39 - "Alembic Environment"
Cohesion: 0.43
Nodes (5): get_url(), str, run_async_migrations(), run_migrations_offline(), run_migrations_online()

### Community 40 - "Migration: Daily Reports"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 41 - "Migration: Report Exports"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 42 - "Migration: Photos"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 43 - "Inventory Stock API"
Cohesion: 0.60
Nodes (5): InventoryLocationStock, StockResponse, list_item_stock(), low_stock(), stock_response()

### Community 44 - "Migration: Projects BOQ"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 45 - "Migration: Supervisor Updates"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 46 - "Migration: Daily Report Approvals"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 47 - "Migration: Documents"
Cohesion: 0.60
Nodes (3): Column, timestamp_columns(), upgrade()

### Community 48 - "Image Processing Tasks"
Cohesion: 0.67
Nodes (3): str, compress_photo(), generate_thumbnail()

## Knowledge Gaps
- **17 isolated node(s):** `AsyncSession`, `bool`, `str`, `int`, `AsyncSession` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `Auth & Audit Dependencies` to `Dashboard & Activity Logging`, `Daily Reporting Module`, `Approval Workflow`, `Project Management`, `Photo Management`, `Document Management`, `Data Import Pipeline`, `Supplier Management`, `Notification System`, `Analytics & Reporting`, `Daily Reports Test Suite`, `Supervisor Updates API`, `User Repository`, `Request/Route Dependencies`, `Inventory Schemas`, `Auth Service`, `Auth Tests & Config`, `Finance Test Suite`, `Exceptions & Permissions`, `Auth Repository`, `Async Tasks & Email`, `Database Health & Supplier Tests`, `Inventory API`, `Analytics Test Suite`, `App Bootstrap & Health Tests`, `Supervisor Updates Test Suite`, `Approvals Test Suite`, `Inventory Test Suite`, `Projects Test Suite`, `Inventory Items Schemas`, `Alembic Environment`, `Inventory Stock API`?**
  _High betweenness centrality (0.343) - this node is a cross-community bridge._
- **Why does `AppException` connect `Approval Workflow` to `Dashboard & Activity Logging`, `Daily Reporting Module`, `Auth & Audit Dependencies`, `Project Management`, `Photo Management`, `Document Management`, `Data Import Pipeline`, `Supplier Management`, `Analytics & Reporting`, `Supervisor Updates API`, `Request/Route Dependencies`, `Email & Exception Handling`, `Auth Service`, `Database & Config Settings`, `Exceptions & Permissions`, `Auth Repository`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `DbSession` connect `Auth & Audit Dependencies` to `Dashboard & Activity Logging`, `Daily Reporting Module`, `Approval Workflow`, `Project Management`, `Photo Management`, `Document Management`, `Data Import Pipeline`, `Supplier Management`, `Notification System`, `Analytics & Reporting`, `Inventory Stock API`, `Inventory Items Schemas`, `Supervisor Updates API`, `Inventory Schemas`, `Auth Service`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 440 inferred relationships involving `User` (e.g. with `TimestampMixin` and `SoftDeleteMixin`) actually correct?**
  _`User` has 440 INFERRED edges - model-reasoned connections that need verification._
- **Are the 236 inferred relationships involving `AppException` (e.g. with `FastAPI` and `Request`) actually correct?**
  _`AppException` has 236 INFERRED edges - model-reasoned connections that need verification._
- **Are the 232 inferred relationships involving `DbSession` (e.g. with `User` and `AuthService`) actually correct?**
  _`DbSession` has 232 INFERRED edges - model-reasoned connections that need verification._
- **Are the 166 inferred relationships involving `AuditService` (e.g. with `Request` and `str`) actually correct?**
  _`AuditService` has 166 INFERRED edges - model-reasoned connections that need verification._