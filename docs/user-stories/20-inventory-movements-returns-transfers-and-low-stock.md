# Inventory Movements, Returns, Transfers, and Low Stock

## Title
Inventory Movements, Returns, Transfers, and Low Stock

## User Story
As a Store Keeper,
I want to record inventory receives, transfers, returns, consumption, wastage, damage, and adjustments,
so that stock history and low-stock alerts remain accurate.

## Description
Implement the full inventory movement ledger, current location updates, low-stock alerts, returns, transfers, consumption, wastage, damage, and adjustment controls.

## Acceptance Criteria
1. Given stock is received,
   When I record a receive movement,
   Then location stock increases and movement history records the handler.

2. Given stock is transferred,
   When I record a transfer,
   Then source and destination balances update without allowing negative stock.

3. Given material is consumed, returned, wasted, damaged, or adjusted,
   When I record the movement,
   Then the correct quantity and reason are stored.

4. Given stock falls below reorder level,
   When low-stock checks run,
   Then Store Keeper, Project Manager, and Operation Manager are notified.

## Business Rules
- Movement types include receive, reserve, issue, transfer, return, consume, adjustment, wastage, and damaged.
- Transfers support movement between warehouses, stores, and project/site locations.
- Material consumption in daily reports should automatically reduce stock.
- Minimum stock and reorder points are set by Store Manager based on requirement.
- Low-stock alerts go to Store Keeper, Project Manager, and Operation Manager.
- All movements capture the handling person.

## UI/UX Notes
- Movement forms should be optimized for Store Keeper daily use.
- Movement history should be filterable by item, asset, project, or location.
- Low-stock panels should identify location and reorder threshold.
- Current-location banners should be visible for asset-tagged tools.

## Technical Notes
- Use `inventory_movements` and `inventory_location_stock` schema references.
- Use transactional updates for every movement.
- Add low-stock detection and notification triggers.
- Ensure asset movements update current asset location.
- Link consumption to daily report material lines where applicable.
- Follow `ARCHITECTURE.md` task layer: `check_low_stock` should run as an hourly Celery Beat maintenance task.
- MovementService must own business rules, while repositories only persist movement and stock rows.
- Low-stock notifications should use the notification service and Celery email flow.

## Priority
Medium

## Dependencies
- Inventory catalog and stock.
- Material request reservation and issue flow.
- Notifications.
- Final unit conversion rules per material.

## Definition of Done
- All movement types update stock correctly.
- Movement history is filterable.
- Low-stock alerts work.
- Asset current location updates.
- Tests cover negative-stock prevention and each movement type.
