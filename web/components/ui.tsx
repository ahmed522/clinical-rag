"use client";

import { Icon, type IconName } from "@/components/Icon";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-sm)] ${className}`}>{children}</section>;
}

export function Pill({ tone = "neutral", children, className = "" }: { tone?: "neutral" | "ok" | "pending" | "danger" | "accent" | "blue"; children: React.ReactNode; className?: string }) {
  const tones = {
    neutral: "bg-[var(--surface-muted)] text-[var(--ink-soft)] border-[var(--border)]",
    ok: "bg-[var(--ok-bg)] text-[var(--ok)] border-[#c8e9da]",
    pending: "bg-[var(--pending-bg)] text-[var(--pending)] border-[#f1d9a5]",
    danger: "bg-[var(--danger-bg)] text-[var(--danger-ink)] border-[#f2cfcc]",
    accent: "bg-[var(--accent-soft)] text-[var(--accent)] border-[#bde4dc]",
    blue: "bg-[var(--blue-soft)] text-[var(--blue)] border-[#cad8ff]",
  };
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${tones[tone]} ${className}`}>{children}</span>;
}

const baseButton = "inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--radius-sm)] px-4 py-2.5 text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed active:translate-y-px";

export function PrimaryButton({ children, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`${baseButton} bg-[var(--accent)] text-white shadow-[0_8px_20px_-12px_var(--accent)] hover:bg-[var(--accent-2)] ${className}`} {...props}>{children}</button>;
}

export function SecondaryButton({ children, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`${baseButton} border border-[var(--border)] bg-white text-[var(--ink)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-subtle)] ${className}`} {...props}>{children}</button>;
}

export function IconButton({ icon, label, className = "", size = 18, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string; size?: number }) {
  return <button aria-label={label} title={label} className={`inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-white text-[var(--ink-soft)] transition hover:border-[var(--border-strong)] hover:text-[var(--accent)] ${className}`} {...props}><Icon name={icon} size={size} /></button>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5 text-sm"><span className="font-bold text-[var(--ink)]">{label}</span>{children}{hint && <span className="text-xs text-[var(--ink-faint)]">{hint}</span>}</label>;
}

const inputClass = "w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-white px-3.5 py-2.5 text-sm text-[var(--ink)] shadow-inner shadow-slate-100 outline-none transition placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)]";
export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) { return <input {...props} className={`${inputClass} ${props.className ?? ""}`} />; }
export function SelectInput(props: React.SelectHTMLAttributes<HTMLSelectElement>) { return <select {...props} className={`${inputClass} ${props.className ?? ""}`} />; }
export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) { return <textarea {...props} className={`${inputClass} min-h-24 resize-y ${props.className ?? ""}`} />; }

export function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return <p role="alert" className="rounded-[var(--radius-sm)] border border-[#f2cfcc] bg-[var(--danger-bg)] px-3.5 py-2.5 text-sm font-semibold text-[var(--danger-ink)]">{children}</p>;
}

export function Logo({ size = "md", inverted = false }: { size?: "sm" | "md" | "lg"; inverted?: boolean }) {
  const tile = size === "lg" ? "h-11 w-11" : "h-9 w-9";
  const text = size === "lg" ? "text-2xl" : "text-lg";
  return <span className="inline-flex items-center gap-2.5"><span className={`${tile} flex items-center justify-center rounded-xl bg-[var(--accent)] text-white shadow-[0_10px_26px_-14px_var(--accent)]`}><Icon name="activity" size={size === "lg" ? 22 : 18} strokeWidth={2.5} /></span><span className={`${text} font-extrabold tracking-tight ${inverted ? "text-white" : "text-[var(--ink)]"}`}>Tabibak</span></span>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="mb-1 text-xs font-extrabold uppercase tracking-[0.18em] text-[var(--accent)]">{eyebrow}</p><h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>{description && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">{description}</p>}</div>{action}</div>;
}

export function EmptyState({ icon = "file", title, description, action }: { icon?: IconName; title: string; description?: string; action?: React.ReactNode }) {
  return <Card className="flex min-h-52 flex-col items-center justify-center text-center"><span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--accent-soft)] text-[var(--accent)]"><Icon name={icon} size={23} /></span><p className="font-extrabold">{title}</p>{description && <p className="mt-1 max-w-md text-sm text-[var(--ink-soft)]">{description}</p>}{action && <div className="mt-4">{action}</div>}</Card>;
}

export function Skeleton({ className = "h-20" }: { className?: string }) { return <div className={`skeleton rounded-[var(--radius)] ${className}`} aria-hidden="true" />; }

export function MetricCard({ label, value, detail, tone = "accent" }: { label: string; value: React.ReactNode; detail?: string; tone?: "accent" | "ok" | "pending" | "blue" }) {
  const color = tone === "ok" ? "var(--ok)" : tone === "pending" ? "var(--pending)" : tone === "blue" ? "var(--blue)" : "var(--accent)";
  return <Card className="relative overflow-hidden"><span className="absolute inset-y-0 start-0 w-1" style={{ background: color }} /><p className="text-xs font-bold uppercase tracking-wider text-[var(--ink-faint)]">{label}</p><p className="mt-2 text-3xl font-extrabold tracking-tight" style={{ color }}>{value}</p>{detail && <p className="mt-1 text-xs text-[var(--ink-soft)]">{detail}</p>}</Card>;
}
