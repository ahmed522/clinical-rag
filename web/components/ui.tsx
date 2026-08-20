"use client";

import { Icon, type IconName } from "@/components/Icon";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`surface-card motion-reveal rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-sm)] ${className}`}>{children}</section>;
}

export function Pill({ tone = "neutral", children, className = "" }: { tone?: "neutral" | "ok" | "pending" | "danger" | "accent" | "blue" | "cura"; children: React.ReactNode; className?: string }) {
  const tones = {
    neutral: "bg-[var(--surface-muted)] text-[var(--ink-soft)] border-[var(--border)]",
    ok: "bg-[var(--ok-bg)] text-[var(--ok)] border-[#bee4d6]",
    pending: "bg-[var(--pending-bg)] text-[var(--pending)] border-[#f1d9a5]",
    danger: "bg-[var(--danger-bg)] text-[var(--danger-ink)] border-[#f2cfcc]",
    accent: "bg-[var(--accent-soft)] text-[var(--accent-2)] border-[#b8dfda]",
    blue: "bg-[var(--blue-soft)] text-[var(--blue)] border-[#cad8ff]",
    cura: "bg-[var(--cura-soft)] text-[var(--cura-strong)] border-[#d8cfee]",
  };
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${tones[tone]} ${className}`}>{children}</span>;
}

const baseButton = "inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--radius-sm)] px-4 py-2.5 text-sm font-bold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 active:translate-y-px";

export function PrimaryButton({ children, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`${baseButton} brand-button bg-[var(--accent)] text-[var(--accent-ink)] hover:-translate-y-0.5 hover:bg-[var(--accent-2)] hover:text-white ${className}`} {...props}><span className="inline-flex items-center justify-center gap-2">{children}</span></button>;
}

export function SecondaryButton({ children, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`${baseButton} border border-[var(--border)] bg-white text-[var(--ink)] shadow-[var(--shadow-sm)] hover:-translate-y-0.5 hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] ${className}`} {...props}>{children}</button>;
}

export function IconButton({ icon, label, className = "", size = 18, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string; size?: number }) {
  return <button aria-label={label} title={label} className={`inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-white text-[var(--ink-soft)] shadow-[var(--shadow-sm)] transition-all hover:-translate-y-0.5 hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent-2)] ${className}`} {...props}><Icon name={icon} size={size} /></button>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5 text-sm"><span className="font-bold text-[var(--ink)]">{label}</span>{children}{hint && <span className="text-xs text-[var(--ink-faint)]">{hint}</span>}</label>;
}

const inputClass = "w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-white px-3.5 py-2.5 text-sm text-[var(--ink)] shadow-[inset_0_1px_2px_rgba(15,37,55,.04)] outline-none transition-all placeholder:text-[var(--ink-faint)] hover:border-[var(--border-strong)] focus:border-[var(--accent)] focus:ring-4 focus:ring-[color-mix(in_srgb,var(--accent)_12%,transparent)]";
export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) { return <input {...props} className={`${inputClass} ${props.className ?? ""}`} />; }
export function SelectInput(props: React.SelectHTMLAttributes<HTMLSelectElement>) { return <select {...props} className={`${inputClass} ${props.className ?? ""}`} />; }
export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) { return <textarea {...props} className={`${inputClass} min-h-24 resize-y ${props.className ?? ""}`} />; }

export function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return <p role="alert" className="motion-reveal rounded-[var(--radius-sm)] border border-[#f2cfcc] bg-[var(--danger-bg)] px-3.5 py-2.5 text-sm font-semibold text-[var(--danger-ink)]">{children}</p>;
}

function BrandMark({ dimension }: { dimension: number }) {
  return <span className="brand-mark flex shrink-0 items-center justify-center rounded-[28%] bg-[#0F2537]" style={{ width: dimension, height: dimension }} aria-hidden="true"><svg width={dimension * 0.62} height={dimension * 0.62} viewBox="0 0 80 80"><rect x="34" y="10" width="12" height="46" rx="3" fill="#F8FAFC" /><rect x="8" y="10" width="64" height="12" rx="3" fill="#F8FAFC" /><path d="M34 56 Q34 72 46 72 L46 62 Q40 62 40 56 Z" fill="#00A896" /></svg></span>;
}

export function Logo({ size = "md", inverted = false }: { size?: "sm" | "md" | "lg"; inverted?: boolean }) {
  const dimensions = { sm: 32, md: 40, lg: 54 };
  const nameSize = size === "lg" ? "text-[1.65rem]" : size === "sm" ? "text-base" : "text-xl";
  return <span className="inline-flex items-center gap-3" aria-label="Tabeebak طبيبك"><BrandMark dimension={dimensions[size]} /><span className="flex flex-col leading-none"><span className={`${nameSize} font-extrabold tracking-[-0.035em] ${inverted ? "text-[#F8FAFC]" : "text-[var(--ink)]"}`}>Tabeebak</span><span lang="ar" className={`mt-1 font-[var(--font-arabic)] text-[.72em] font-bold tracking-normal ${inverted ? "text-white/65" : "text-[var(--ink-soft)]"}`}>طبيبك</span></span></span>;
}

export function LoadingScreen({ label }: { label: string }) {
  return <div className="clinical-grid flex min-h-screen items-center justify-center bg-[var(--bg)] px-5"><div className="motion-reveal flex flex-col items-center rounded-[var(--radius)] border border-[var(--border)] bg-white px-10 py-8 shadow-[var(--shadow)]"><Logo size="lg" /><div className="mt-6 flex gap-1.5" aria-hidden="true">{[0, 1, 2].map((index) => <span key={index} className="h-2 w-2 animate-bounce rounded-full bg-[var(--accent)]" style={{ animationDelay: `${index * 120}ms` }} />)}</div><p className="mt-3 text-sm font-bold text-[var(--ink-soft)]">{label}</p></div></div>;
}

export function CuraAvatar({ size = 44, className = "" }: { size?: number; className?: string }) {
  return <span className={`cura-float inline-flex shrink-0 items-center justify-center rounded-[28%_28%_28%_10%] bg-[var(--cura)] shadow-[0_14px_30px_-16px_rgba(142,124,195,.9)] ${className}`} style={{ width: size, height: size }} aria-label="Cura AI"><svg width={size * 0.56} height={size * 0.56} viewBox="0 0 70 70" fill="none" aria-hidden="true"><polyline points="6,36 20,36 27,20 38,50 47,30 54,36 64,36" stroke="#F8FAFC" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" /></svg></span>;
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="motion-reveal mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div className="max-w-3xl">{eyebrow && <p className="mb-2 flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.2em] text-[var(--accent-2)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] shadow-[0_0_0_4px_var(--accent-soft)]" />{eyebrow}</p>}<h1 className="text-2xl font-extrabold tracking-[-0.035em] text-[var(--ink)] sm:text-3xl">{title}</h1>{description && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">{description}</p>}</div>{action}</div>;
}

export function EmptyState({ icon = "file", title, description, action }: { icon?: IconName; title: string; description?: string; action?: React.ReactNode }) {
  return <Card className="flex min-h-52 flex-col items-center justify-center text-center"><span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--accent-soft)] text-[var(--accent-2)]"><Icon name={icon} size={23} /></span><p className="font-extrabold">{title}</p>{description && <p className="mt-1 max-w-md text-sm text-[var(--ink-soft)]">{description}</p>}{action && <div className="mt-4">{action}</div>}</Card>;
}

export function Skeleton({ className = "h-20" }: { className?: string }) { return <div className={`skeleton rounded-[var(--radius)] ${className}`} aria-hidden="true" />; }

export function MetricCard({ label, value, detail, tone = "accent" }: { label: string; value: React.ReactNode; detail?: string; tone?: "accent" | "ok" | "pending" | "blue" }) {
  const color = tone === "ok" ? "var(--ok)" : tone === "pending" ? "var(--pending)" : tone === "blue" ? "var(--blue)" : "var(--accent-2)";
  return <Card className="overflow-hidden"><span className="absolute inset-x-0 top-0 h-1" style={{ background: `linear-gradient(90deg, ${color}, transparent)` }} /><p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--ink-faint)]">{label}</p><p className="mt-2 text-3xl font-extrabold tracking-[-0.04em]" style={{ color }}>{value}</p>{detail && <p className="mt-1 text-xs text-[var(--ink-soft)]">{detail}</p>}</Card>;
}
