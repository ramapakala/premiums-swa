import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import AuthStatus from "@/components/AuthStatus";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Premiums",
  description: "Options premium dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <header className="w-full border-b bg-white">
          <div className="mx-auto max-w-[1400px] px-6 py-3 flex items-center justify-between">
            <h1 className="text-lg font-semibold">Premiums</h1>
            <AuthStatus />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
