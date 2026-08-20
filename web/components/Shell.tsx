"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Icon, type IconName } from "@/components/Icon";
import { Logo } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

export interface ShellTab { key: string; label: string; icon: IconName; }

export function Shell({ tabs, activeTab, onTabChange, children }: { tabs: ShellTab[]; activeTab: string; onTabChange: (key: string) => void; children: React.ReactNode }) {
  const { t, lang, toggleLang } = useLang();
  const { signOut, role, profile, session } = useAuth();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const displayName = ((profile?.name as string) || session?.user?.email || "").trim();
  const initials = displayName.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "T";
  const roleLabel = role === "doctor" ? t("roleDoctor") : role === "clinic_admin" ? t("roleAdmin") : role === "it" ? t("roleIt") : t("rolePatient");
  const activeLabel = tabs.find((tab) => tab.key === activeTab)?.label ?? "";

  async function handleSignOut() { await signOut(); router.replace("/login"); }
  function selectTab(key: string) { onTabChange(key); setDrawerOpen(false); }

  const nav = (
    <>
      <div className="px-5 pb-7">
        <Logo inverted />
        <p className="mt-4 text-[11px] font-bold uppercase tracking-[0.13em] text-white/40">{roleLabel}</p>
        <p className="mt-1 text-xs leading-5 text-white/55">{t("evidenceWorkspace")}</p>
      </div>
      <nav className="flex-1 space-y-1.5 overflow-y-auto px-3" aria-label={activeLabel}>
        {tabs.map((tab) => {
          const active = tab.key === activeTab;
          return <button key={tab.key} onClick={() => selectTab(tab.key)} aria-current={active ? "page" : undefined} className={`group relative flex w-full items-center gap-3 overflow-hidden rounded-xl px-3.5 py-3 text-start text-sm font-bold transition-all duration-200 ${active ? "bg-[var(--accent)] text-[#0F2537] shadow-[0_14px_30px_-18px_rgba(0,168,150,.9)]" : "text-white/65 hover:bg-white/[0.07] hover:text-white"}`}><span className={`flex h-8 w-8 items-center justify-center rounded-lg transition ${active ? "bg-[#0F2537]/10" : "bg-white/[0.06] group-hover:bg-white/10"}`}><Icon name={tab.icon} size={18} strokeWidth={active ? 2.4 : 2} /></span><span>{tab.label}</span>{active && <span className="absolute inset-y-2 end-0 w-1 rounded-s-full bg-[#0F2537]/55" />}</button>;
        })}
      </nav>
      <div className="m-3 rounded-2xl border border-white/10 bg-white/[0.055] p-3.5 backdrop-blur">
        <div className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent)] text-xs font-extrabold text-[#0F2537] shadow-[0_10px_24px_-16px_rgba(0,168,150,.9)]">{initials}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-extrabold text-white">{displayName || "—"}</p><p className="text-xs text-white/45">{roleLabel}</p></div><button onClick={handleSignOut} aria-label={t("logout")} className="rounded-lg p-2 text-white/45 transition hover:bg-[var(--danger)]/15 hover:text-[#ffaaa5]"><Icon name="logout" size={17} /></button></div>
      </div>
    </>
  );

  return <div data-role={role ?? undefined} className="min-h-screen bg-[var(--bg)] lg:grid lg:grid-cols-[276px_minmax(0,1fr)]">
    <aside className="sticky top-0 hidden h-screen flex-col overflow-hidden bg-[#0F2537] py-6 lg:flex"><span className="pointer-events-none absolute -start-28 -top-32 h-72 w-72 rounded-full bg-[var(--accent)]/15 blur-3xl" />{nav}</aside>
    {drawerOpen && <div className="fixed inset-0 z-50 lg:hidden"><button className="absolute inset-0 cursor-default bg-[#0F2537]/55 backdrop-blur-sm" aria-label={t("close")} onClick={() => setDrawerOpen(false)} /><aside className="drawer-in absolute inset-y-0 start-0 flex w-[292px] flex-col overflow-hidden bg-[#0F2537] py-6 shadow-2xl"><button onClick={() => setDrawerOpen(false)} aria-label={t("close")} className="absolute end-4 top-4 z-10 rounded-lg p-2 text-white/60 transition hover:bg-white/10 hover:text-white"><Icon name="close" size={19} /></button>{nav}</aside></div>}
    <div className="min-w-0">
      <header className="sticky top-0 z-30 flex h-[68px] items-center justify-between border-b border-[var(--border)] bg-[rgba(248,250,252,.88)] px-4 shadow-[0_8px_28px_-28px_rgba(15,37,55,.5)] backdrop-blur-xl sm:px-7">
        <div className="flex min-w-0 items-center gap-3"><button onClick={() => setDrawerOpen(true)} aria-label={t("menu")} className="rounded-xl border border-[var(--border)] bg-white p-2 text-[var(--ink-soft)] shadow-[var(--shadow-sm)] transition hover:border-[var(--accent)] hover:text-[var(--accent-2)] lg:hidden"><Icon name="menu" size={20} /></button><div><p className="truncate text-base font-extrabold tracking-[-0.02em] text-[var(--ink)]">{activeLabel}</p><p className="hidden text-xs text-[var(--ink-faint)] sm:block">{t("verifiedKnowledge")}</p></div></div>
        <div className="flex items-center gap-2"><span className="hidden items-center gap-1.5 rounded-full border border-[#bee4d6] bg-[var(--ok-bg)] px-3 py-1.5 text-xs font-bold text-[var(--ok)] sm:inline-flex"><Icon name="shield" size={14} />{t("clinicalSafe")}</span><button onClick={toggleLang} className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-[var(--border)] bg-white px-3 text-xs font-extrabold text-[var(--ink-soft)] shadow-[var(--shadow-sm)] transition hover:border-[var(--accent)] hover:text-[var(--accent-2)]"><Icon name="globe" size={15} />{lang === "ar" ? "EN" : "AR"}</button></div>
      </header>
      <main key={activeTab} className="page-enter mx-auto min-h-[calc(100vh-8rem)] w-full max-w-[1280px] px-4 py-6 sm:px-7 sm:py-9">{children}</main>
      <footer className="border-t border-[var(--border)] bg-white/75 px-6 py-5 text-center text-xs leading-5 text-[var(--ink-faint)] backdrop-blur">{t("supportDisclaimer")}</footer>
    </div>
  </div>;
}
