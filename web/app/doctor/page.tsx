"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { AppointmentsTab } from "@/components/doctor/AppointmentsTab";
import { AssistantTab } from "@/components/doctor/AssistantTab";
import { AvailabilityTab } from "@/components/doctor/AvailabilityTab";
import { DocumentsTab } from "@/components/doctor/DocumentsTab";
import { PatientsTab } from "@/components/doctor/PatientsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "assistant" | "documents" | "patients" | "appointments" | "availability";

export default function DoctorDashboard() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("assistant");

  const tabs = [
    { key: "assistant", label: t("assistant"), icon: "chat" as const },
    { key: "documents", label: t("documents"), icon: "file" as const },
    { key: "patients", label: t("myPatients"), icon: "users" as const },
    { key: "appointments", label: t("appointmentsWithMe"), icon: "calendar" as const },
    { key: "availability", label: t("availability"), icon: "clock" as const },
  ];

  return (
    <RequireRole role="doctor">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "assistant" && <AssistantTab />}
        {tab === "documents" && <DocumentsTab />}
        {tab === "patients" && <PatientsTab />}
        {tab === "appointments" && <AppointmentsTab />}
        {tab === "availability" && <AvailabilityTab />}
      </Shell>
    </RequireRole>
  );
}
