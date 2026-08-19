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
  const roleLabel = role === "doctor" ? t("roleDoctor") : role === "clinic_admin" ? t("roleAdmin") : t("rolePatient");
  const activeLabel = tabs.find((tab) => tab.key === activeTab)?.label ?? "";

  async function handleSignOut() { await signOut(); router.replace("/login"); }
  function selectTab(key: string) { onTabChange(key); setDrawerOpen(false); }

  const nav = (
    <>
      <div className="px-5 pb-5"><Logo /><p className="mt-3 text-xs leading-5 text-[var(--ink-faint)]">{roleLabel} · {t("evidenceWorkspace")}</p></div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3" aria-label={activeLabel}>
        {tabs.map((tab) => {
          const active = tab.key === activeTab;
          return <button key={tab.key} onClick={() => selectTab(tab.key)} aria-current={active ? "page" : undefined} className={`group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start text-sm font-bold transition ${active ? "bg-[var(--accent)] text-white shadow-[0_10px_24px_-16px_var(--accent)]" : "text-[var(--ink-soft)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"}`}><Icon name={tab.icon} size={19} strokeWidth={active ? 2.4 : 2} /><span>{tab.label}</span></button>;
        })}
      </nav>
      <div className="m-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-subtle)] p-3">
        <div className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-xs font-extrabold text-[var(--accent)]">{initials}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-extrabold">{displayName || "—"}</p><p className="text-xs text-[var(--ink-faint)]">{roleLabel}</p></div><button onClick={handleSignOut} aria-label={t("logout")} className="rounded-lg p-2 text-[var(--ink-faint)] hover:bg-[var(--danger-bg)] hover:text-[var(--danger)]"><Icon name="logout" size={17} /></button></div>
      </div>
    </>
  );

  return <div data-role={role ?? undefined} className="min-h-screen bg-[var(--bg)] lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
    <aside className="sticky top-0 hidden h-screen flex-col border-e border-[var(--border)] bg-white py-5 lg:flex">{nav}</aside>
    {drawerOpen && <div className="fixed inset-0 z-50 lg:hidden"><button className="absolute inset-0 cursor-default bg-slate-950/35" aria-label={t("close")} onClick={() => setDrawerOpen(false)} /><aside className="absolute inset-y-0 start-0 flex w-[285px] flex-col bg-white py-5 shadow-2xl"><button onClick={() => setDrawerOpen(false)} aria-label={t("close")} className="absolute end-4 top-4 rounded-lg p-2 text-[var(--ink-soft)]"><Icon name="close" size={19} /></button>{nav}</aside></div>}
    <div className="min-w-0">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-[var(--border)] bg-white/90 px-4 backdrop-blur sm:px-7">
        <div className="flex min-w-0 items-center gap-3"><button onClick={() => setDrawerOpen(true)} aria-label={t("menu")} className="rounded-xl border border-[var(--border)] bg-white p-2 text-[var(--ink-soft)] lg:hidden"><Icon name="menu" size={20} /></button><div><p className="truncate text-base font-extrabold">{activeLabel}</p><p className="hidden text-xs text-[var(--ink-faint)] sm:block">{t("verifiedKnowledge")}</p></div></div>
        <div className="flex items-center gap-2"><span className="hidden items-center gap-1.5 rounded-full border border-[#c8e9da] bg-[var(--ok-bg)] px-3 py-1.5 text-xs font-bold text-[var(--ok)] sm:inline-flex"><Icon name="shield" size={14} />{t("clinicalSafe")}</span><button onClick={toggleLang} className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-[var(--border)] bg-white px-3 text-xs font-extrabold text-[var(--ink-soft)] hover:border-[var(--border-strong)]"><Icon name="globe" size={15} />{lang === "ar" ? "EN" : "AR"}</button></div>
      </header>
      <main className="mx-auto min-h-[calc(100vh-8rem)] w-full max-w-[1240px] px-4 py-6 sm:px-7 sm:py-8">{children}</main>
      <footer className="border-t border-[var(--border)] bg-white px-6 py-5 text-center text-xs leading-5 text-[var(--ink-faint)]">{t("supportDisclaimer")}</footer>
    </div>
  </div>;
}
