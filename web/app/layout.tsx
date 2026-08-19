import type { Metadata } from "next";

import { AuthProvider } from "@/lib/auth-context";
import { LangProvider } from "@/lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: "Tabibak — Clinical evidence you can trace",
  description: "Verified clinic guidance with claim-level evidence, citations, and safety checks.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // lang/dir default to Arabic on first paint (LangProvider corrects them
  // client-side from localStorage once mounted); no next/font here since
  // --font-ui is a system stack chosen specifically so Arabic and Latin
  // both render from one family, which the Geist fonts do not support.
  return (
    <html lang="ar" dir="rtl" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <AuthProvider>
          <LangProvider>{children}</LangProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
