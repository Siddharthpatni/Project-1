import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Navbar from "@/components/Navbar";
import { Providers } from "@/components/Providers";

// Inter for UI text, JetBrains Mono for code/figures — a clean, professional
// pairing exposed as CSS variables and mapped to Tailwind's font-sans/mono.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Vergabepilot.AI",
    template: "%s — Vergabepilot.AI",
  },
  description: "Autonomous AI for public procurement document extraction and cascade pipeline.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)",  color: "#0a0a0f" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" translate="no" suppressHydrationWarning className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <meta name="google" content="notranslate" />
        {/* Prevent dark mode flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){var t=localStorage.getItem('theme'),d=window.matchMedia('(prefers-color-scheme:dark)').matches;if(t==='dark'||(t!=='light'&&d))document.documentElement.classList.add('dark')})()`,
          }}
        />
      </head>
      <body className="min-h-screen font-sans antialiased" style={{ background: "var(--bg)", color: "var(--fg)" }}>
        <Providers>
          <div className="flex flex-col min-h-screen">
            <Navbar />
            <main className="flex-1 w-full max-w-7xl 2xl:max-w-[88rem] mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
              {children}
            </main>
            <footer className="py-4 text-center text-xs" style={{ color: "var(--fg-subtle)", borderTop: "1px solid var(--border)" }}>
              Vergabepilot.AI · Autonomous Procurement Scraper · SoSe 2026
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
