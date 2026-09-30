import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PRIMEVPN",
  description: "Commercial PasarGuard control plane"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
