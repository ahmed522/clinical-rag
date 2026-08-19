"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface Record {
  id: string;
  diagnosis: string | null;
  notes: string | null;
  created_at: string;
}

export function RecordsTab() {
  const { t, lang } = useLang();
  const [records, setRecords] = useState<Record[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      // RLS's records_select policy already restricts this to the caller's
      // own patient_id — no read anywhere in this app can see another
      // patient's history, regardless of what this query does or doesn't
      // filter by.
      const { data } = await supabase
        .from("medical_records")
        .select("*")
        .order("created_at", { ascending: false });
      if (data) setRecords(data as Record[]);
      setLoading(false);
    })();
  }, []);

  return (
    <div>
      <PageHeader eyebrow={t("rolePatient")} title={t("myRecords")} description={t("fromClinicRecord")} />
      {loading ? <div className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : records.length === 0 ? <EmptyState icon="file" title={t("noRecordsYet")} description={t("fromClinicRecord")} /> : <div className="grid gap-3 lg:grid-cols-2">
      {records.map((record) => (
        <Card key={record.id}>
          <p className="font-bold text-sm">{record.diagnosis || "—"}</p>
          {record.notes && <p className="text-sm text-[var(--ink-soft)] mt-1">{record.notes}</p>}
          <p className="text-[11px] text-[var(--ink-faint)] mt-2">
            {t("fromClinicRecord")} · {new Date(record.created_at).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US")}
          </p>
        </Card>
      ))}
      </div>}
    </div>
  );
}
