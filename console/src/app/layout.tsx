import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Noto_Nastaliq_Urdu, Sora } from "next/font/google";
import { BottomNav, Footer, Header } from "@/components/Chrome";
import { LevelsProvider } from "@/components/LevelsProvider";
import { MotionProvider, PageTransition } from "@/components/Motion";
import { WakeBanner } from "@/components/Status";
import { LanguageProvider } from "@/i18n/LanguageProvider";
import "./globals.css";

// next/font downloads these at BUILD time and serves them from this app, so
// the browser never calls Google (and the built console works offline).
const sora = Sora({ subsets: ["latin"], variable: "--font-sora", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
// Numbers and timestamps only, never above the fold on first paint: no preload.
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap", preload: false });
// Nastaliq is large (~240 KB): no preload, and on English pages the few Urdu
// lines use a system font (globals.css), so only Urdu readers download it.
const nastaliq = Noto_Nastaliq_Urdu({
  subsets: ["arabic"],
  weight: ["400", "700"],
  variable: "--font-nastaliq",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "LEHAR Early-Warning Console",
  description:
    "Research advisory early-warning console for Pakistan's districts. NDMA/PMD/PDMA official warnings are authoritative.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#070b14",
  colorScheme: "dark",
  viewportFit: "cover",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // lang/dir are switched client-side by LanguageProvider for Urdu (RTL).
    <html
      lang="en"
      dir="ltr"
      suppressHydrationWarning
      className={`${sora.variable} ${inter.variable} ${jetbrains.variable} ${nastaliq.variable}`}
    >
      <body className="flex min-h-dvh flex-col antialiased">
        <LanguageProvider>
          <LevelsProvider>
            <MotionProvider>
              <a href="#main" className="skip-link">
                Skip to content
              </a>
              <Header />
              <WakeBanner />
              <main id="main" className="w-full flex-1">
                <PageTransition>{children}</PageTransition>
              </main>
              <Footer />
              <BottomNav />
            </MotionProvider>
          </LevelsProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
