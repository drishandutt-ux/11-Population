import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "11 Population",
  description: "Multi-agent simulation — test products, strategies, predictions, and human behaviour",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background">{children}</body>
    </html>
  );
}
