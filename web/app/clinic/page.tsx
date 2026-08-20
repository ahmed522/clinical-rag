"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { AnalyticsTab } from "@/components/clinic/AnalyticsTab";
import { DoctorsTab } from "@/components/clinic/DoctorsTab";
import { PatientsTab } from "@/components/clinic/PatientsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "doctors" | "patients" | "analytics";

/**
 * Receptionist scope is deliberately narrow, and enforced by RLS not just
 * this UI: register doctors, register patients (assigning each to a doctor),
 * and view clinic-wide counts. Documents, medical records, and chat are not
 * reachable from this role at all.
 */
export default function ClinicDashboard() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("doctors");

  const tabs = [
    { key: "doctors", label: t("doctors"), icon: "user-plus" as const },
    { key: "patients", label: t("patients"), icon: "users" as const },
    { key: "analytics", label: t("analytics"), icon: "chart" as const },
  ];

  return (
    <RequireRole role="clinic_admin">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "doctors" && <DoctorsTab />}
        {tab === "patients" && <PatientsTab />}
        {tab === "analytics" && <AnalyticsTab />}
      </Shell>
    </RequireRole>
  );
}
