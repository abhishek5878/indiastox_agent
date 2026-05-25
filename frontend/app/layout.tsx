import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "IndiaStox · live read",
  description:
    "The percentage of new users on the badge path this week. " +
    "One number, one action, recomputed every load.",
  openGraph: {
    title: "IndiaStox · live read",
    description:
      "What's happening in IndiaStox this week. Single-screen view: " +
      "headline, this week's numbers, the one action to take.",
    url: "https://indiastox.vercel.app/today",
    siteName: "IndiaStox",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "IndiaStox · live read",
    description: "One number. One action. Recomputed every load.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex">
        <Sidebar />
        <main className="flex-1 overflow-auto">{children}</main>
      </body>
    </html>
  );
}
