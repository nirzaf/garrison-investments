import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function AuthScreen() {
  return (
    <div className="screenStack">
      <div className="dualGrid">
        <div data-tour-target="auth-login">
          <Panel title="Login experience" icon={<ShieldCheck size={18} />}>
            <div className="loginMock">
              <label>Email</label>
              <div>engineer@garrisons.example</div>
              <label>Password</label>
              <div>••••••••••••</div>
              <label>2FA code</label>
              <div>184 902</div>
              <button type="button">Sign in securely</button>
            </div>
          </Panel>
        </div>
        <Panel title="Session and security decisions" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "Email OTP for MVP two-factor authentication",
              "1-day session with short-lived access token and silent refresh",
              "3 failed attempts lock the account",
              "Admin creates accounts and can reset passwords",
              "First login requires password change",
            ]}
          />
        </Panel>
      </div>
      <DataTable
        columns={["Role", "Access scope", "Key permissions"]}
        rows={roleMatrix.map((role) => [
          role.role,
          role.access,
          role.permissions.join(", "),
        ])}
      />
    </div>
  );
}
