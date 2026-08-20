"use client";

import { Icon } from "@/components/Icon";
import { Logo } from "@/components/ui";
import { useLang } from "@/lib/i18n";

export function AuthShell({ title, subtitle, children, clinicName }: { title: string; subtitle: string; children: React.ReactNode; clinicName?: string }) {
  const { lang, setLang, t } = useLang();
  return <main className="clinical-grid min-h-screen bg-[var(--bg)] p-3 sm:p-5">
    <div className="page-enter mx-auto grid min-h-[calc(100vh-1.5rem)] max-w-6xl overflow-hidden rounded-[30px] border border-[var(--border)] bg-white shadow-[0_30px_90px_-46px_rgba(15,37,55,.48)] sm:min-h-[calc(100vh-2.5rem)] lg:grid-cols-[1.06fr_.94fr]">
      <section className="auth-story relative hidden overflow-hidden bg-[#0F2537] p-11 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -end-32 -top-32 h-96 w-96 rounded-full bg-[var(--accent)]/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -start-20 h-72 w-72 rounded-full bg-[var(--accent)]/10 blur-3xl" />
        <span className="auth-outline-mark pointer-events-none absolute end-[-.16em] top-[15%] select-none" aria-hidden="true">T</span>
        <svg className="pointer-events-none absolute end-8 top-[42%] w-64 text-[var(--accent)] opacity-[.08]" viewBox="0 0 300 100" fill="none" aria-hidden="true"><polyline points="0,52 58,52 82,18 116,84 154,34 184,52 300,52" stroke="currentColor" strokeWidth="12" strokeLinecap="round" strokeLinejoin="round" /></svg>
        <div className="relative motion-reveal auth-logo-frame"><Logo size="lg" inverted /></div>
        <div className="relative max-w-lg motion-reveal">
          <h2 className="max-w-md text-[2.65rem] font-extrabold leading-[1.08] tracking-[-0.05em]">{t("evidenceFirstTitle")}</h2>
          <p className="mt-5 max-w-md text-[15px] leading-7 text-white/60">{t("evidenceFirstHint")}</p>
          <div className="mt-9 grid gap-3"><Feature icon="file" title={t("supportingEvidence")} text={t("exactExcerpt")} /><Feature icon="shield" title={t("safetyAndLimits")} text={t("verificationPassed")} /><Feature icon="chart" title={t("ragQuality")} text={t("evaluationSubtitle")} /></div>
        </div>
        <p className="relative max-w-lg text-xs leading-5 text-white/40">{t("supportDisclaimer")}</p>
      </section>
      <section className="auth-form-panel flex flex-col p-5 sm:p-8 lg:p-12">
        <div className="flex items-center justify-between lg:justify-end"><div className="lg:hidden"><Logo /></div><div role="group" aria-label="Language" className="inline-flex items-center rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] p-1 text-xs font-extrabold shadow-[var(--shadow-sm)]"><Icon name="globe" size={15} className="mx-2 text-[var(--ink-soft)]" /><button type="button" lang="en" aria-pressed={lang === "en"} onClick={() => setLang("en")} className={`rounded-lg px-3 py-1.5 transition-all ${lang === "en" ? "bg-white text-[var(--accent-2)] shadow-sm" : "text-[var(--ink-soft)] hover:text-[var(--ink)]"}`}>English</button><button type="button" lang="ar" aria-pressed={lang === "ar"} onClick={() => setLang("ar")} className={`rounded-lg px-3 py-1.5 transition-all ${lang === "ar" ? "bg-white text-[var(--accent-2)] shadow-sm" : "text-[var(--ink-soft)] hover:text-[var(--ink)]"}`}>العربية</button></div></div>
        <div className="motion-reveal my-auto mx-auto w-full max-w-md py-8 sm:py-10"><div className="mb-9">{clinicName && <p className="mb-2 text-[11px] font-extrabold uppercase tracking-[0.2em] text-[var(--accent-2)]">{clinicName}</p>}<h1 className="text-[2rem] font-extrabold tracking-[-0.045em] text-[var(--ink)]">{title}</h1><p className="mt-2.5 text-[15px] leading-6 text-[var(--ink-soft)]">{subtitle}</p></div>{children}</div>
      </section>
    </div>
  </main>;
}

function Feature({ icon, title, text }: { icon: "file" | "shield" | "chart"; title: string; text: string }) { return <div className="group flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.055] p-3.5 backdrop-blur transition-all hover:-translate-y-0.5 hover:border-[var(--accent)]/35 hover:bg-white/[0.08]"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent)]/15 text-[#76d8cd] transition group-hover:bg-[var(--accent)] group-hover:text-[#0F2537]"><Icon name={icon} size={18} /></span><div><p className="text-sm font-extrabold">{title}</p><p className="mt-0.5 text-xs text-white/45">{text}</p></div></div>; }
