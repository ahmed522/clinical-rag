"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { type Role, useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { LoadingScreen } from "@/components/ui";

function homeFor(role: Role): string {
  if (role === "clinic_admin") return "/clinic";
  if (role === "doctor") return "/doctor";
  if (role === "patient") return "/patient";
  if (role === "it") return "/it";
  return "/login";
}

/**
 * Gate for a page that needs a specific signed-in role, with the
 * password-change and onboarding steps forced ahead of it.
 *
 * This is a UX convenience, not the security boundary — it just keeps a
 * signed-out, wrong-role, or not-yet-onboarded visitor from staring at a
 * broken page while every request underneath silently fails or a patient
 * skips the safety welcome screen. RLS is what actually decides whether
 * any given read or write is allowed; this component enforces nothing a
 * forged client could bypass its way past.
 *
 * Order matters: must_change_password is checked before onboarding, so a
 * patient can't reach the welcome screen on a password they didn't choose.
 * /change-password and /patient/welcome do NOT use this gate themselves —
 * they use a lighter "just signed in" check — or this would loop.
 */
export function RequireRole({
  role,
  children,
}: {
  role: Exclude<Role, null>;
  children: React.ReactNode;
}) {
  const { session, role: currentRole, loading, profile, profileLoading } = useAuth();
  const { t } = useLang();
  const router = useRouter();

  const ready = !loading && !profileLoading;
  const roleMatches = currentRole === role;
  const mustChangePassword = !!profile?.must_change_password;
  const needsOnboarding =
    role === "patient" && !mustChangePassword && profile?.onboarding_completed === false;

  useEffect(() => {
    if (!ready) return;
    if (!session) {
      router.replace("/login");
      return;
    }
    if (!roleMatches) {
      router.replace(homeFor(currentRole));
      return;
    }
    if (mustChangePassword) {
      router.replace("/change-password");
      return;
    }
    if (needsOnboarding) {
      router.replace("/patient/welcome");
    }
  }, [ready, session, roleMatches, currentRole, mustChangePassword, needsOnboarding, router]);

  if (!ready || !session || !roleMatches || mustChangePassword || needsOnboarding) {
    return <LoadingScreen label={t("loading")} />;
  }

  return <>{children}</>;
}
