"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

export function Shell({
  tabs,
  activeTab,
  onTabChange,
  children,
}: {
  tabs: { key: string; label: string }[];
  activeTab: string;
  onTabChange: (key: string) => void;
  children: React.ReactNode;
}) {
  const { t, lang, toggleLang } = useLang();
  const { signOut } = useAuth();
  const router = useRouter();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-[var(--border)] bg-[var(--bg-raised)] sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-4">
          <span className="text-lg font-bold text-[var(--accent)]">{t("appName")}</span>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLang}
              className="text-sm font-semibold rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
            >
              {lang === "ar" ? "EN" : "AR"}
            </button>
            <button
              onClick={async () => {
                await signOut();
                router.replace("/login");
              }}
              className="text-sm font-semibold rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 hover:border-[var(--danger)] hover:text-[var(--danger)] transition-colors"
            >
              {t("logout")}
            </button>
          </div>
        </div>
        <nav className="max-w-5xl mx-auto px-4 sm:px-6 flex gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => onTabChange(tab.key)}
              className={`whitespace-nowrap px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "border-[var(--accent)] text-[var(--accent)]"
                  : "border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-6">{children}</main>
      <footer className="text-center text-xs text-[var(--ink-faint)] px-6 py-6 max-w-xl mx-auto">
        {t("supportDisclaimer")}
      </footer>
    </div>
  );
}
