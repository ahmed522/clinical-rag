"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { type Role, useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

/**
 * Gate for a page that needs a specific signed-in role.
 *
 * This is a UX convenience, not the security boundary — it just keeps a
 * signed-out or wrong-role visitor from staring at a broken page while
 * every request underneath silently fails. RLS is what actually decides
 * whether any given read or write is allowed; this component enforces
 * nothing a forged client could bypass its way past.
 */
export function RequireRole({
  role,
  children,
}: {
  role: Exclude<Role, null>;
  children: React.ReactNode;
}) {
  const { session, role: currentRole, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!session) {
      router.replace("/login");
      return;
    }
    if (currentRole !== role) {
      router.replace(currentRole === "clinic_admin" ? "/clinic" : "/patient");
    }
  }, [loading, session, currentRole, role, router]);

  if (loading || !session || currentRole !== role) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
        {t("loading")}
      </div>
    );
  }

  return <>{children}</>;
}
