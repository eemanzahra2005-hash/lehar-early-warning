import type { Metadata, Viewport } from "next";
import { Footer, Header } from "@/components/Chrome";
import { LevelsProvider } from "@/components/LevelsProvider";
import { WakeBanner } from "@/components/Status";
import { LanguageProvider } from "@/i18n/LanguageProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "LEHAR Early-Warning Console",
  description:
    "Research advisory early-warning console for Pakistan's districts. NDMA/PMD/PDMA official warnings are authoritative.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // lang/dir are switched client-side by LanguageProvider for Urdu (RTL).
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col bg-white text-slate-900 antialiased">
        <LanguageProvider>
          <LevelsProvider>
            <a href="#main" className="skip-link">
              Skip to content
            </a>
            <Header />
            <WakeBanner />
            <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
              {children}
            </main>
            <Footer />
          </LevelsProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
