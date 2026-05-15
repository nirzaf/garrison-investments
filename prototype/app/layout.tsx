import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Garrisons Internal Portal Prototype",
  description: "Animated requirements prototype for the Garrisons construction internal portal.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
