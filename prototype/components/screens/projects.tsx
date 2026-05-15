import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function ProjectsScreen({
  selectedProject,
  setSelectedProject,
}: {
  selectedProject: (typeof projects)[number];
  setSelectedProject: (project: (typeof projects)[number]) => void;
}) {
  return (
    <div className="screenStack">
      <div className="projectSelector" data-tour-target="project-selector">
        {projects.map((project) => (
          <button
            className={project.code === selectedProject.code ? "selected" : ""}
            key={project.code}
            onClick={() => setSelectedProject(project)}
            type="button"
          >
            <strong>{project.code}</strong>
            <span>{project.name}</span>
          </button>
        ))}
      </div>
      <section className="dualGrid wideLeft">
        <Panel title={`${selectedProject.name} details`} icon={<HardHat size={18} />}>
          <div className="detailGrid">
            <Detail label="Location" value={selectedProject.location} />
            <Detail label="Manager" value={selectedProject.manager} />
            <Detail label="Deadline" value={selectedProject.deadline} />
            <Detail label="Budget" value={selectedProject.budget} />
            <Detail
              label="Reports"
              value={`${selectedProject.reports} (${selectedProject.delayed} delayed)`}
            />
            <Detail label="Phase" value={selectedProject.phase} />
          </div>
          <BarList
            rows={selectedProject.disciplines.map((item) => ({
              label: item.name,
              value: item.value,
              meta: "approved quantity / planned quantity",
            }))}
          />
        </Panel>
        <Panel title="BOQ and progress rules" icon={<ListChecks size={18} />}>
          <Checklist
            items={[
              "BOQ supports manual entry and spreadsheet import",
              "Fields: item code, description, unit, quantity, rate, amount, discipline, phase, milestone",
              "Project code is auto-generated",
              "Progress is weighted by discipline/BOQ progress",
            ]}
          />
        </Panel>
      </section>
      <Panel title="Project setup preview" icon={<BriefcaseBusiness size={18} />}>
        <MiniFactGrid rows={projectSetupPreview} target="project-setup-preview" />
      </Panel>
      <div data-tour-target="gantt-timeline">
        <Panel title="Gantt-style timeline" icon={<CircleDashed size={18} />}>
          <div className="gantt">
            {ganttTasks.map((task) => {
              const statusClass = `status-${task.status.toLowerCase().replace(/\s+/g, "-")}`;
              return (
                <div className="ganttRow" key={task.task}>
                  <span>{task.task}</span>
                  <div className="ganttTrack">
                    <div
                      className={statusClass}
                      style={{ marginLeft: `${task.start}%`, width: `${task.span}%` }}
                    >
                      {task.status}
                    </div>
                  </div>
                  <small>{task.owner}</small>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>
    </div>
  );
}
