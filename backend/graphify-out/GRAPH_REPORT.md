# Graph Report - backend  (2026-05-26)

## Corpus Check
- 112 files · ~31,455 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1194 nodes · 6505 edges · 40 communities (37 shown, 3 thin omitted)
- Extraction: 49% EXTRACTED · 51% INFERRED · 0% AMBIGUOUS · INFERRED: 3290 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `19843b47`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]

## God Nodes (most connected - your core abstractions)
1. `User` - 347 edges
2. `AppException` - 291 edges
3. `DbSession` - 204 edges
4. `AuditService` - 159 edges
5. `NotFoundException` - 140 edges
6. `InventoryService` - 99 edges
7. `ApprovalService` - 91 edges
8. `ReportService` - 84 edges
9. `NotificationService` - 78 edges
10. `DailyReport` - 75 edges

## Surprising Connections (you probably didn't know these)
- `_queue_export()` --calls--> `str`  [INFERRED]
  app/api/v1/analytics.py → /Users/qts/Repos/garrison-investments/backend/app/services/exception_reporter.py
- `get_batch_status()` --calls--> `str`  [INFERRED]
  app/api/v1/imports.py → /Users/qts/Repos/garrison-investments/backend/app/services/exception_reporter.py
- `run_import_async_endpoint()` --calls--> `str`  [INFERRED]
  app/api/v1/imports.py → /Users/qts/Repos/garrison-investments/backend/app/services/exception_reporter.py
- `escape_xml()` --calls--> `str`  [INFERRED]
  app/services/analytics_service.py → /Users/qts/Repos/garrison-investments/backend/app/services/exception_reporter.py
- `_enqueue_pending_notification_emails()` --calls--> `str`  [INFERRED]
  app/services/notification_service.py → /Users/qts/Repos/garrison-investments/backend/app/services/exception_reporter.py

## Communities (40 total, 3 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (70): CurrentUser, DailyReportCreateRequest, DailyReportUpdateRequest, DbSession, ge, le, Query, Response (+62 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (66): CurrentUser, DashboardSummaryResponse, DbSession, DbSession, ge, le, max_length, ProjectCreateRequest (+58 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (45): ActivityLog, CurrentUser, DbSession, ge, le, Query, SupervisorUpdateCreateRequest, UUID (+37 more)

### Community 3 - "Community 3"
Cohesion: 0.14
Nodes (55): AssetCreateRequest, DbSession, InventoryItemCreateRequest, InventoryLocationStock, LocationCreateRequest, MaterialRequestCreateRequest, max_length, MovementCreateRequest (+47 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (47): get_current_user(), require_permission(), User, alias, ApprovalCreateRequest, CurrentUser, DbSession, ge (+39 more)

### Community 5 - "Community 5"
Cohesion: 0.15
Nodes (44): alias, DbSession, File, ge, InvoiceCreateRequest, InvoiceUpdateRequest, le, max_length (+36 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (37): DbSession, File, Form, ge, le, Query, UploadFile, UUID (+29 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (39): date, DbSession, File, Form, Query, UploadFile, UUID, AsyncSession (+31 more)

### Community 8 - "Community 8"
Cohesion: 0.14
Nodes (46): DbSession, ge, le, max_length, Query, UUID, DbSession, File (+38 more)

### Community 9 - "Community 9"
Cohesion: 0.13
Nodes (34): DbSession, File, ImportPreviewResponse, ImportRunResponse, Response, UploadFile, UUID, AsyncSession (+26 more)

### Community 10 - "Community 10"
Cohesion: 0.11
Nodes (30): CurrentUser, DbSession, UUID, AsyncSession, datetime, Notification, UUID, AsyncSession (+22 more)

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (31): alias, AnalyticsSummaryResponse, CurrentUser, date, DbSession, max_length, Query, Response (+23 more)

### Community 12 - "Community 12"
Cohesion: 0.21
Nodes (27): DbSession, ge, le, max_length, Query, UserCreateRequest, UserUpdateRequest, UUID (+19 more)

### Community 13 - "Community 13"
Cohesion: 0.47
Nodes (33): DbSession, alias, CurrentUser, DbSession, Response, User, AuthUserResponse, Cookie (+25 more)

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (20): UUID, T, check_low_stock(), _low_stock_recipients(), process_approval_reminders(), _recent_notification_exists(), run_async_task(), _run_with_fresh_pool() (+12 more)

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (14): get_request_meta(), Request, User, UUID, RequestMeta, OtpChallengeResult, RequestMeta, SessionResult (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.15
Nodes (15): check_database(), get_db(), AsyncSession, create_app(), lifespan(), Request, Response, UUID (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.20
Nodes (14): BaseModel, ApprovalCreateRequest, ApprovalDecisionRequest, ApprovalDelegationRequest, ApprovalListResponse, ApprovalOverrideRequest, ApprovalResponse, DailyReportApprovalHistoryResponse (+6 more)

### Community 18 - "Community 18"
Cohesion: 0.16
Nodes (7): AsyncSession, UUID, AsyncSession, AuthOtpChallenge, AuthRefreshToken, AuthRepository, EmailService

### Community 19 - "Community 19"
Cohesion: 0.14
Nodes (14): BoqItemCreateRequest, BoqItemResponse, MilestoneCreateRequest, MilestoneResponse, ProjectCreateRequest, ProjectDetailResponse, ProjectListResponse, ProjectMemberCreateRequest (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.23
Nodes (11): Any, BaseException, _authenticated_subject(), _format_value(), _redact_headers(), _redact_mapping(), report_celery_task_failure(), report_unhandled_exception() (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.18
Nodes (11): AuthUserResponse, LoginChallengeResponse, LoginRequest, MessageResponse, PasswordChangeRequest, PasswordResetChallengeResponse, PasswordResetConfirmRequest, PasswordResetRequest (+3 more)

### Community 22 - "Community 22"
Cohesion: 0.18
Nodes (11): AssetCreateRequest, AssetResponse, InventoryItemCreateRequest, InventoryItemResponse, LocationCreateRequest, LocationResponse, MaterialRequestCreateRequest, MaterialRequestLineCreate (+3 more)

### Community 23 - "Community 23"
Cohesion: 0.56
Nodes (8): UUID, str, approval_inbox_url(), build_frontend_url(), daily_report_url(), document_url(), finance_invoice_url(), material_request_url()

### Community 26 - "Community 26"
Cohesion: 0.50
Nodes (8): get_settings(), datetime, UUID, ErrorDetail, create_access_token(), _jwt_private_key(), _jwt_public_key(), _read_key_file()

### Community 27 - "Community 27"
Cohesion: 0.40
Nodes (4): BaseOrmModel, ErrorItem, ErrorResponse, PaginatedResponse

### Community 28 - "Community 28"
Cohesion: 0.40
Nodes (4): AttachmentRef, SupervisorUpdateListResponse, SupervisorUpdateResponse, SupervisorUpdateSubmitRequest

### Community 29 - "Community 29"
Cohesion: 0.50
Nodes (3): PhotoListResponse, PhotoResponse, ProtectedFileUrlResponse

### Community 30 - "Community 30"
Cohesion: 0.50
Nodes (3): AnalyticsSummaryResponse, MaterialUsageRow, ProjectAnalyticsRow

## Knowledge Gaps
- **5 isolated node(s):** `AsyncSession`, `UUIDPrimaryKeyMixin`, `AsyncSession`, `BaseException`, `Request`
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `User` connect `Community 8` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 15`, `Community 18`, `Community 23`?**
  _High betweenness centrality (0.329) - this node is a cross-community bridge._
- **Why does `AppException` connect `Community 4` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`, `Community 12`, `Community 13`, `Community 15`, `Community 16`, `Community 18`, `Community 20`, `Community 23`, `Community 26`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Why does `DbSession` connect `Community 13` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 15`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Are the 311 inferred relationships involving `User` (e.g. with `TimestampMixin` and `SoftDeleteMixin`) actually correct?**
  _`User` has 311 INFERRED edges - model-reasoned connections that need verification._
- **Are the 185 inferred relationships involving `AppException` (e.g. with `FastAPI` and `Request`) actually correct?**
  _`AppException` has 185 INFERRED edges - model-reasoned connections that need verification._
- **Are the 203 inferred relationships involving `DbSession` (e.g. with `User` and `AuthService`) actually correct?**
  _`DbSession` has 203 INFERRED edges - model-reasoned connections that need verification._
- **Are the 125 inferred relationships involving `AuditService` (e.g. with `CanViewAudit` and `DbSession`) actually correct?**
  _`AuditService` has 125 INFERRED edges - model-reasoned connections that need verification._