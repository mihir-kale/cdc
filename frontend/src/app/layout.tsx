import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "FinePrint",
  description: "Understand a payday loan before you take it.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-white text-gray-900">
        {children}
      </body>
    </html>
  );
}
