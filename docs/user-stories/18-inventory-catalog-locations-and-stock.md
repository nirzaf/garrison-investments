# Inventory Catalog, Locations, and Stock

## Title
Inventory Catalog, Locations, and Stock

## User Story
As a Store Keeper,
I want to manage inventory items, storage locations, and stock balances,
so that materials and tools are visible across warehouses and project stores.

## Description
Implement Phase 2 inventory catalog, storage locations, consumable materials, asset-tagged tools/items, stock by location, and current tool location visibility.

## Acceptance Criteria
1. Given I am a Store Keeper,
   When I create a storage location,
   Then it can represent a central warehouse, site store, or project location.

2. Given I create an inventory item,
   When I classify it,
   Then it supports consumable material or asset-tagged tool/item behavior.

3. Given stock exists in multiple locations,
   When I view an item,
   Then I see on-hand, reserved, and available quantities per location.

4. Given an asset-tagged tool exists,
   When I open asset detail,
   Then I see its current location, condition, and movement history.

## Business Rules
- Inventory uses a multi-location model with central warehouse plus project/site stores.
- One material can exist in multiple locations.
- Stock cannot go negative.
- Material codes are mandatory for tools but not all materials.
- Supplier records are required before creating materials.
- Unit options include Nos, KG, TON, and SQM.
- Material pricing visibility is restricted.

## UI/UX Notes
- Inventory screens should emphasize stock matrix, location cards, low-stock panels, and current tool location.
- Pricing fields must be hidden from unauthorized roles.
- Store Keeper workflows should be fast and form-driven.

## Technical Notes
- Use `inventory_items`, `inventory_assets`, `storage_locations`, and `inventory_location_stock` schema references.
- Add APIs for locations, items, item detail, stock, and assets.
- Model unit conversion per material, not globally.
- Prepare stock reservation fields for material request workflow.
- Follow `ARCHITECTURE.md` guidance that inventory stock quantities should not be cached aggressively.
- InventoryService owns stock business rules; repositories perform async SQLAlchemy reads/writes with soft-delete filtering.
- Use ACID PostgreSQL transactions for stock-affecting operations.

## Priority
Medium

## Dependencies
- Phase 1 core modules.
- Supplier management.
- Initial warehouse/site/store list.
- Confirmation whether Project Managers can view material pricing.

## Definition of Done
- Inventory locations and items can be managed.
- Stock by location is visible.
- Asset current location is visible.
- Pricing restrictions are enforced.
- Tests cover catalog, locations, stock, assets, and permission rules.
