"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { AppointmentsTab } from "@/components/patient/AppointmentsTab";
import { ChatTab } from "@/components/patient/ChatTab";
import { RecordsTab } from "@/components/patient/RecordsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "chat" | "appointments" | "records";

export default function PatientApp() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("chat");

  const tabs = [
    { key: "chat", label: t("chat"), icon: "chat" as const },
    { key: "appointments", label: t("appointments"), icon: "calendar" as const },
    { key: "records", label: t("myRecords"), icon: "file" as const },
  ];

  return (
    <RequireRole role="patient">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "chat" && <ChatTab />}
        {tab === "appointments" && <AppointmentsTab />}
        {tab === "records" && <RecordsTab />}
      </Shell>
    </RequireRole>
  );
}
