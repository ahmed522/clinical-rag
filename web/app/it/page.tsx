"use client";

import { useState } from "react";

import { RequireRole } from "@/components/RequireRole";
import { Shell } from "@/components/Shell";
import { MetricsTab } from "@/components/it/MetricsTab";
import { OverviewTab } from "@/components/it/OverviewTab";
import { PipelineTestTab } from "@/components/it/PipelineTestTab";
import { ReportsTab } from "@/components/it/ReportsTab";
import { useLang } from "@/lib/i18n";

type TabKey = "overview" | "chatbot" | "test" | "reports";

/**
 * IT is internal operations, not clinic staff. Its reach is cross-clinic
 * (enforced by RLS's is_it() policies) but strictly technical: pipeline
 * metrics, document debugging, and the doctor bug-report queue. No patient
 * data, chat, or medical records are reachable from this role at all.
 */
export default function ItDashboard() {
  const { t } = useLang();
  const [tab, setTab] = useState<TabKey>("overview");

  const tabs = [
    { key: "overview", label: t("overview"), icon: "chart" as const },
    { key: "chatbot", label: t("chatbot"), icon: "activity" as const },
    { key: "test", label: t("testPipeline"), icon: "settings" as const },
    { key: "reports", label: t("bugReports"), icon: "bell" as const },
  ];

  return (
    <RequireRole role="it">
      <Shell tabs={tabs} activeTab={tab} onTabChange={(key) => setTab(key as TabKey)}>
        {tab === "overview" && <OverviewTab />}
        {tab === "chatbot" && <MetricsTab />}
        {tab === "test" && <PipelineTestTab />}
        {tab === "reports" && <ReportsTab />}
      </Shell>
    </RequireRole>
  );
}
