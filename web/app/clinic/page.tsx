"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { AnalyticsTab } from "@/components/clinic/AnalyticsTab";
import { DoctorsTab } from "@/components/clinic/DoctorsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "doctors" | "analytics";

/**
 * Admin scope is deliberately narrow: register the clinic (elsewhere),
 * add/manage doctors, view analytics. Documents and patients moved to the
 * doctor dashboard (/doctor) — administrative, not medical.
 */
export default function ClinicDashboard() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("doctors");

  const tabs = [
    { key: "doctors", label: t("doctors"), icon: "user-plus" as const },
    { key: "analytics", label: t("analytics"), icon: "chart" as const },
  ];

  return (
    <RequireRole role="clinic_admin">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "doctors" && <DoctorsTab />}
        {tab === "analytics" && <AnalyticsTab />}
      </Shell>
    </RequireRole>
  );
}
