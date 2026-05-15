import type { ReactNode } from "react";
import { ArrowRight, CheckCircle2, FileText, HardHat, Upload } from "lucide-react";

import { sampleAttachments, walkthroughSteps } from "@/lib/portal-data";

export function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase().replace(/\s+/g, "-");
  const label = status;
  return <span className={`statusPill ${normalized}`}>{label}</span>;
}

export function MiniFactGrid({
  rows,
  target,
}: {
  rows: { label: string; value?: string; detail?: string; status?: string }[];
  target?: string;
}) {
  return (
    <div className="miniFactGrid" data-tour-target={target}>
      {rows.map((row) => (
        <article key={`${row.label}-${row.value}`}>
          <span>{row.label}</span>
          {row.value ? <strong>{row.value}</strong> : null}
          {row.status ? <em>{row.status}</em> : null}
          {row.detail ? <p>{row.detail}</p> : null}
        </article>
      ))}
    </div>
  );
}

export function ProcessStrip({
  rows,
  target,
}: {
  rows: { step?: string; state?: string; owner?: string; detail: string }[];
  target?: string;
}) {
  return (
    <div className="processStrip" data-tour-target={target}>
      {rows.map((row, index) => (
        <article key={`${row.step ?? row.state}-${index}`}>
          <span>{index + 1}</span>
          <div>
            <strong>{row.step ?? row.state}</strong>
            {row.owner ? <small>{row.owner}</small> : null}
            <p>{row.detail}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

export function Panel({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panelHeader">
        <div>{icon}</div>
        <h2>{title}</h2>
      </header>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: string;
}) {
  return (
    <article className={`metricCard tone-${tone ?? "blue"}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}

export function DataTable({ columns, rows }: { columns: string[]; rows: ReactNode[][] }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, index) => (
                <td key={index}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="checkList">
      {items.map((item) => (
        <li key={item}>
          <CheckCircle2 size={14} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function BarList({ rows }: { rows: { label: string; value: number; meta: string }[] }) {
  return (
    <div className="barList">
      {rows.map((row) => (
        <div key={row.label}>
          <div>
            <strong>{row.label}</strong>
            <span>{row.value}%</span>
          </div>
          <div className="barTrack">
            <span style={{ width: `${row.value}%` }} />
          </div>
          <small>{row.meta}</small>
        </div>
      ))}
    </div>
  );
}

export function CardList({ rows }: { rows: { title: string; meta: string; badge: string }[] }) {
  return (
    <div className="cardList">
      {rows.map((row) => (
        <article key={row.title}>
          <div>
            <strong>{row.title}</strong>
            <span>{row.meta}</span>
          </div>
          <StatusPill status={row.badge} />
        </article>
      ))}
    </div>
  );
}

export function WalkthroughTimeline() {
  return (
    <div className="walkthrough">
      {walkthroughSteps.map((item) => (
        <article key={item.step}>
          <span>{item.step}</span>
          <div>
            <strong>{item.title}</strong>
            <small>{item.screen}</small>
            <p>{item.detail}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

export function AttachmentList({
  filter,
  compact = false,
}: {
  filter?: string[];
  compact?: boolean;
}) {
  const rows = filter
    ? sampleAttachments.filter((item) => filter.includes(item.type))
    : sampleAttachments;

  return (
    <div className={compact ? "attachmentList compact" : "attachmentList"}>
      {rows.map((item) => (
        <article key={item.name}>
          <FileText size={17} />
          <div>
            <strong>{item.name}</strong>
            <span>
              {item.type} • {item.owner} • {item.size}
            </span>
            <small>{item.linkedTo}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

export function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detailItem">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function PackageIcon() {
  return <Upload size={18} />;
}

export function RouteIcon() {
  return <ArrowRight size={18} />;
}

export function SmartphoneIcon() {
  return <HardHat size={18} />;
}
