"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { DoctorsTab } from "@/components/clinic/DoctorsTab";
import { DocumentsTab } from "@/components/clinic/DocumentsTab";
import { PatientsTab } from "@/components/clinic/PatientsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "documents" | "doctors" | "patients";

export default function ClinicDashboard() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("documents");

  const tabs = [
    { key: "documents", label: t("documents") },
    { key: "doctors", label: t("doctors") },
    { key: "patients", label: t("patients") },
  ];

  return (
    <RequireRole role="clinic_admin">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "documents" && <DocumentsTab />}
        {tab === "doctors" && <DoctorsTab />}
        {tab === "patients" && <PatientsTab />}
      </Shell>
    </RequireRole>
  );
}
