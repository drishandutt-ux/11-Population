import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider, RequireAuth } from "@/lib/auth";
import SimpleViewPill from "@/components/lite/SimpleViewPill";

export const metadata: Metadata = {
  title: "11 Minds Population",
  description: "Multi-agent simulation — test products, strategies, predictions, and human behaviour",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background">
        <AuthProvider>
          <RequireAuth>
            {children}
            <SimpleViewPill />
          </RequireAuth>
        </AuthProvider>
      </body>
    </html>
  );
}
