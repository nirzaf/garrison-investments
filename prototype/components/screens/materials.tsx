import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function MaterialsScreen() {
  return (
    <div className="screenStack">
      <Panel title="Warehouse and site stores" icon={<PackageIcon />}>
        <section className="locationCardGrid" data-tour-target="storage-locations">
          {storageLocations.map((location) => (
            <article key={location.code}>
              <div>
                <span>{location.code}</span>
                <StatusPill status={location.status} />
              </div>
              <h3>{location.name}</h3>
              <p>{location.project}</p>
              <div className="locationMeta">
                <strong>{location.type}</strong>
                <span>{location.items}</span>
                <em>{location.lowStock} low-stock</em>
              </div>
            </article>
          ))}
        </section>
      </Panel>

      <section className="dualGrid wideLeft">
        <div data-tour-target="materials-inventory">
          <Panel title="Inventory stock matrix" icon={<PackageIcon />}>
            <DataTable
              columns={["Code", "Item", "Type", "Total", "Reserved", "Available", "Current location", "Status"]}
              rows={inventoryItems.map((item) => [
                item.code,
                item.name,
                item.type,
                `${item.totalStock} ${item.unit}`,
                `${item.reserved} ${item.unit}`,
                `${item.available} ${item.unit}`,
                item.currentLocation,
                <StatusPill key={item.status} status={item.status} />,
              ])}
            />
          </Panel>
        </div>
        <Panel title="Request lifecycle" icon={<RouteIcon />}>
          <Checklist items={materialLifecycle} />
        </Panel>
      </section>

      <section className="dualGrid">
        <Panel title="Stock by warehouse/site" icon={<ListChecks size={18} />}>
          <DataTable
            columns={["Item", "Location", "On hand", "Reserved", "Available", "Status"]}
            rows={inventoryItems.flatMap((item) =>
              item.locations.map((location) => [
                item.name,
                location.location,
                `${location.onHand} ${item.unit}`,
                `${location.reserved} ${item.unit}`,
                `${location.available} ${item.unit}`,
                <StatusPill key={`${item.code}-${location.location}`} status={location.status} />,
              ]),
            )}
          />
        </Panel>
        <Panel title="Low stock by location" icon={<AlertCircle size={18} />}>
          <DataTable
            columns={["Location", "Item", "Available", "Minimum", "Status"]}
            rows={lowStockByLocation.map((item) => [
              item.location,
              item.item,
              item.available,
              item.minimum,
              <StatusPill key={`${item.location}-${item.item}`} status={item.status} />,
            ])}
          />
        </Panel>
      </section>

      <Panel title="Current tool/item location tracker" icon={<Map size={18} />}>
        <section className="assetTrackerGrid" data-tour-target="tool-location-tracker">
          {toolAssets.map((asset) => (
            <article key={asset.tag}>
              <div>
                <strong>{asset.tag}</strong>
                <StatusPill status={asset.status} />
              </div>
              <h3>{asset.item}</h3>
              <p>{asset.currentLocation}</p>
              <dl>
                <div>
                  <dt>Project</dt>
                  <dd>{asset.project}</dd>
                </div>
                <div>
                  <dt>Condition</dt>
                  <dd>{asset.condition}</dd>
                </div>
              </dl>
              <small>{asset.lastMovement}</small>
            </article>
          ))}
        </section>
      </Panel>

      <section className="dualGrid">
        <Panel title="Supplier management" icon={<Upload size={18} />}>
          <DataTable
            columns={["Supplier", "Category", "Terms", "TDS"]}
            rows={suppliers.map((supplier) => [
              supplier.name,
              supplier.category,
              supplier.terms,
              supplier.tds,
            ])}
          />
        </Panel>
        <Panel title="Material rules" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "No negative stock",
              "Issue and transfer require approval before stock moves",
              "Warehouse/site location is mandatory for every movement",
              "Asset-tagged tools keep current warehouse/site location",
              "Unit conversion configured per material",
              "Pricing restricted to allowed finance/management roles",
            ]}
          />
        </Panel>
      </section>
      <section className="dualGrid wideLeft">
        <Panel title="Approved issue and transfer workflow" icon={<RouteIcon />}>
          <ProcessStrip rows={inventoryMovementFlow} target="material-flow" />
        </Panel>
        <Panel title="Recent inventory movements" icon={<FileText size={18} />}>
          <DataTable
            columns={["Type", "Item", "Qty", "From", "To", "Approval"]}
            rows={materialTransactions.map((item) => [
              item.type,
              item.item,
              item.qty,
              item.from,
              item.to,
              item.approval,
            ])}
          />
        </Panel>
      </section>
      <Panel title="Sample inventory and supplier attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["Supplier Compliance", "BOQ Import"]} />
      </Panel>
    </div>
  );
}
