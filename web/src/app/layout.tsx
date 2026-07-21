import type { Metadata } from "next";
import { Syne, Outfit } from "next/font/google";
import { Providers } from "@/components/Providers";
import "./globals.css";

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

export const metadata: Metadata = {
  title: "VADER — Rhino Python Scripts",
  description:
    "Collect, sync, and run ready-to-use Rhino Python scripts through Vader — without exposing source.",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${syne.variable} ${outfit.variable} galaxy antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
