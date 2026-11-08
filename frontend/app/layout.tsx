import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RADAR — Unified Web Intelligence & Discovery",
  description: "Autonomous discovery, verification, and enrichment engine for businesses, jobs, and events.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased text-foreground">
        {children}
      </body>
    </html>
  );
}
