# UI Component Tree — Construction Internal Portal

## Component Hierarchy

```
<App>
├── <AuthProvider>                           // Context: user, tokens, login/logout
│   ├── <ThemeProvider>                      // Context: light/dark (future)
│   │   ├── <Router>
│   │   │   ├── Public Routes
│   │   │   │   ├── <LoginPage />
│   │   │   │   └── <ForgotPasswordPage />
│   │   │   │
│   │   │   └── Protected Routes (wraps with <RequireAuth>)
│   │   │       └── <AppLayout>
│   │   │           ├── <Sidebar>            // Desktop: fixed left nav
│   │   │           │   ├── <UserProfileCard />  // Avatar, name, role
│   │   │           │   ├── <NavMenu />          // Role-filtered links
│   │   │           │   └── <VersionBadge />
│   │   │           │
│   │   │           ├── <Header>
│   │   │           │   ├── <Breadcrumbs />
│   │   │           │   ├── <SearchBar />        // Global search (future)
│   │   │           │   ├── <NotificationBell />
│   │   │           │   │   └── <NotificationDropdown />
│   │   │           │   └── <UserMenu />
│   │   │           │
│   │   │           ├── <MobileNav>          // Fixed bottom nav (mobile)
│   │   │           │   └── <BottomNavItems />
│   │   │           │
│   │   │           ├── <OfflineIndicator /> // Banner when offline
│   │   │           │
│   │   │           └── <main>               // Route outlet
│   │   │               │
│   │   │               ├── Dashboard/
│   │   │               │   └── <DashboardPage>
│   │   │               │       ├── <StatCardGrid>
│   │   │               │       │   └── <StatCard /> (x4-6)
│   │   │               │       ├── <RecentActivityFeed>
│   │   │               │       ├── <ProjectProgressChart />
│   │   │               │       └── <PendingApprovalsWidget />
│   │   │               │
│   │   │               ├── Projects/
│   │   │               │   ├── <ProjectListPage>
│   │   │               │   │   └── <DataTable>
│   │   │               │   │       ├── <TableFilters />
│   │   │               │   │       ├── <TablePagination />
│   │   │               │   │       └── <StatusBadge /> (per row)
│   │   │               │   └── <ProjectTimelinePage>
│   │   │               │       └── <GanttChart />
│   │   │               │
│   │   │               ├── Reports/
│   │   │               │   ├── <DailyReportListPage>
│   │   │               │   │   └── <DataTable>
│   │   │               │   │       ├── <DateRangeFilter />
│   │   │               │   │       └── <StatusBadge />
│   │   │               │   ├── <DailyReportFormPage>
│   │   │               │   │   ├── <FormStepper />          // Optional: multi-step
│   │   │               │   │   ├── <ReportHeaderSection>
│   │   │               │   │   │   ├── <ProjectSelect />
│   │   │               │   │   │   ├── <DatePicker />
│   │   │               │   │   │   └── <WeatherInput />
│   │   │               │   │   ├── <WorkDetailsSection>
│   │   │               │   │   │   ├── <RichTextEditor />   // Work completed
│   │   │               │   │   │   ├── <ProgressSlider />   // Progress %
│   │   │               │   │   │   └── <TextArea />         // Issues, next day plan
│   │   │               │   │   ├── <ManpowerSection>
│   │   │               │   │   │   └── <DynamicRowTable>    // Add/remove rows
│   │   │               │   │   │       ├── <LaborTypeSelect />
│   │   │               │   │   │       ├── <NumberInput />  // Count, hours
│   │   │               │   │   │       └── <RemoveRowButton />
│   │   │               │   │   ├── <EquipmentSection>
│   │   │               │   │   │   └── <DynamicRowTable />
│   │   │               │   │   ├── <MaterialConsumptionSection>
│   │   │               │   │   │   └── <DynamicRowTable />
│   │   │               │   │   ├── <PhotoUploadSection>
│   │   │               │   │   │   ├── <FileUpload />       // Drag-drop + camera
│   │   │               │   │   │   │   └── <PhotoPreview /> (grid of thumbnails)
│   │   │               │   │   │   └── <ProgressBar />      // Upload progress
│   │   │               │   │   └── <FormActions>
│   │   │               │   │       ├── <Button variant="outline">Save Draft</Button>
│   │   │               │   │       └── <Button variant="primary">Submit</Button>
│   │   │               │   └── <DailyReportDetailPage>
│   │   │               │       ├── <ReportStatusBanner />   // Approved/Rejected/Pending
│   │   │               │       ├── <ReportSectionRenderer /> // Read-only sections
│   │   │               │       ├── <PhotoGallery />
│   │   │               │       └── <ApprovalHistoryTimeline />
│   │   │               │
│   │   │               ├── Materials / Inventory & Stores/
│   │   │               │   ├── <InventoryDashboardPage>
│   │   │               │   │   ├── <StorageLocationCards />       // warehouse/site stores
│   │   │               │   │   ├── <InventoryStockMatrix />       // item x location
│   │   │               │   │   ├── <LowStockByLocationPanel />
│   │   │               │   │   └── <CurrentToolLocationPanel />
│   │   │               │   ├── <InventoryItemDetailPage>
│   │   │               │   │   ├── <InventoryItemInfoCard />
│   │   │               │   │   ├── <LocationStockBreakdown />
│   │   │               │   │   └── <MovementTimeline />
│   │   │               │   ├── <ToolAssetDetailPage>
│   │   │               │   │   ├── <CurrentLocationBanner />
│   │   │               │   │   ├── <ConditionStatusCard />
│   │   │               │   │   └── <AssetMovementHistoryTable />
│   │   │               │   ├── <InventoryRequestPage>
│   │   │               │   │   └── <IssueTransferRequestForm />   // approval required
│   │   │               │   └── <SupplierListPage>
│   │   │               │
│   │   │               ├── Documents/
│   │   │               │   ├── <DocumentLibraryPage>
│   │   │               │   │   ├── <DocumentFilterSidebar />
│   │   │               │   │   ├── <DocumentGrid /> | <DocumentList />
│   │   │               │   │   │   └── <DocumentCard />
│   │   │               │   │   └── <UploadDocumentButton />
│   │   │               │   └── <DocumentDetailPage>
│   │   │               │       ├── <DocumentPreview />
│   │   │               │       └── <VersionHistoryList />
│   │   │               │
│   │   │               ├── Photos/
│   │   │               │   └── <PhotoGalleryPage>
│   │   │               │       ├── <PhotoFilterBar />
│   │   │               │       ├── <PhotoGrid>
│   │   │               │       │   └── <PhotoCard />        // Thumbnail + caption
│   │   │               │       └── <PhotoLightbox />         // Full-screen viewer
│   │   │               │
│   │   │               ├── Approvals/
│   │   │               │   ├── <ApprovalInboxPage>
│   │   │               │   │   └── <ApprovalCard /> (per item)
│   │   │               │   │       ├── <ApprovalMeta />     // Type, date, requestor
│   │   │               │   │       └── <ApprovalActions />  // Approve/Reject buttons
│   │   │               │   └── <ApprovalDetailModal>
│   │   │               │       ├── <RequestContentPreview />
│   │   │               │       ├── <ApprovalComments />
│   │   │               │       └── <ApproveRejectForm />
│   │   │               │
│   │   │               └── Admin/
│   │   │                   ├── <UserManagementPage>
│   │   │                   │   ├── <UserTable />
│   │   │                   │   └── <UserFormModal />
│   │   │                   └── <AuditLogPage>
│   │   │                       └── <AuditLogTable />
│   │   │                           └── <JsonDiffViewer />   // old vs new values
│   │   │
│   │   └── ...
```

## State Management Strategy

```
┌─────────────────────────────────────────────────┐
│                   APP STATE                       │
│                                                   │
│  ┌──────────────┐  ┌──────────────────────┐      │
│  │ AuthContext   │  │ TanStack Query Cache │      │
│  │              │  │                      │      │
│  │ - user       │  │ - reports (list)     │      │
│  │ - role       │  │ - reports/{id}       │      │
│  │ - token      │  │ - projects           │      │
│  │ - login()    │  │ - materials          │      │
│  │ - logout()   │  │ - notifications      │      │
│  │ - isAuth     │  │ - dashboard (refetch │      │
│  └──────────────┘  │   every 5 min)       │      │
│                     └──────────────────────┘      │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │ Form State (React Hook Form + Zod)       │    │
│  │ - Local to each form component           │    │
│  │ - Zod schemas mirror Pydantic schemas    │    │
│  └──────────────────────────────────────────┘    │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │ UI State (useState / useReducer local)   │    │
│  │ - Sidebar collapsed                       │    │
│  │ - Modal open/close                        │    │
│  │ - Active tab                              │    │
│  │ - Theme (future)                          │    │
│  └──────────────────────────────────────────┘    │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │ Offline State (IndexedDB via idb)         │    │
│  │ - Draft reports                           │    │
│  │ - Pending sync queue                      │    │
│  │ - Cached reference data (projects, etc.)  │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

## Reusable UI Components Library

### Primitive (Atomic)
- `Button` — variants: primary, secondary, outline, ghost, danger; sizes: sm, md, lg
- `Input` — with label, error, icon slots
- `Select` — with label, error, searchable variant
- `TextArea` — with character count
- `Checkbox`, `RadioGroup`, `Toggle`
- `Badge` — variants: success, warning, danger, info, neutral
- `Card`, `CardHeader`, `CardBody`, `CardFooter`
- `Modal` — with title, body, footer slots, keyboard trap
- `Tabs`
- `Spinner`, `Skeleton` (loading states)
- `Avatar`
- `Tooltip`
- `DropdownMenu`

### Composite (Molecular)
- `DataTable` — sorting, filtering, pagination, row selection, column visibility
- `FileUpload` — drag-drop zone, file list, preview, progress bars, camera capture
- `PhotoGrid` — masonry layout with lightbox
- `StatusBadge` — color-coded by status enum
- `ProgressBar` — with percentage label
- `DateRangePicker`
- `EmptyState` — icon + message + CTA
- `ErrorBoundary` — fallback UI for crashes
- `ConfirmDialog` — for destructive actions

### Routing Structure

```
/login                          → LoginPage
/dashboard                      → DashboardPage
/projects                       → ProjectListPage
/projects/:id                   → ProjectTimelinePage
/reports                        → DailyReportListPage
/reports/new                    → DailyReportFormPage
/reports/:id                    → DailyReportDetailPage
/reports/:id/edit               → DailyReportFormPage
/materials                      → MaterialListPage
/materials/:id                  → MaterialDetailPage
/materials/request              → MaterialRequestPage
/suppliers                      → SupplierListPage
/documents                      → DocumentLibraryPage
/documents/:id                  → DocumentDetailPage
/photos                         → PhotoGalleryPage
/approvals                      → ApprovalInboxPage
/admin/users                    → UserManagementPage
/admin/audit-log                → AuditLogPage
/notifications                  → NotificationListPage
```
