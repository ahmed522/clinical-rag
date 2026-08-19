"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

export default function Home() {
  const { session, role, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!session) {
      router.replace("/login");
    } else if (role === "clinic_admin") {
      router.replace("/clinic");
    } else if (role === "doctor") {
      router.replace("/doctor");
    } else if (role === "patient") {
      router.replace("/patient");
    } else {
      router.replace("/login");
    }
  }, [loading, session, role, router]);

  return (
    <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
      {t("loading")}
    </div>
  );
}
