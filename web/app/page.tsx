"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { LoadingScreen } from "@/components/ui";

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
    } else if (role === "it") {
      router.replace("/it");
    } else {
      router.replace("/login");
    }
  }, [loading, session, role, router]);

  return <LoadingScreen label={t("loading")} />;
}
