import type { Metadata } from "next";
import { Rajdhani, Share_Tech_Mono } from "next/font/google";
import "./globals.css";

const rajdhani = Rajdhani({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-rajdhani",
  display: "swap"
});

const shareTechMono = Share_Tech_Mono({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-share-tech",
  display: "swap"
});

export const metadata: Metadata = {
  title: "AstraGuard AI - Mission Control",
  description: "Satellite security and mission control dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${rajdhani.variable} ${shareTechMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
