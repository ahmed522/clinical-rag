"use client";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-4 sm:p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function Pill({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "ok" | "pending" | "danger";
  children: React.ReactNode;
}) {
  const toneStyles: Record<string, string> = {
    neutral: "bg-[var(--surface-muted)] text-[var(--ink-soft)]",
    ok: "bg-[var(--ok-bg)] text-[var(--ok)]",
    pending: "bg-[var(--pending-bg)] text-[var(--pending)]",
    danger: "bg-[var(--danger-bg)] text-[var(--danger-ink)]",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${toneStyles[tone]}`}>
      {children}
    </span>
  );
}

export function PrimaryButton({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] bg-[var(--accent)] text-[var(--accent-ink)] px-4 py-2.5 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-semibold text-[var(--ink-soft)]">{label}</span>
      {children}
    </label>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] ${props.className ?? ""}`}
    />
  );
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p className="rounded-[var(--radius-sm)] bg-[var(--danger-bg)] text-[var(--danger-ink)] px-3.5 py-2.5 text-sm font-semibold">
      {children}
    </p>
  );
}
