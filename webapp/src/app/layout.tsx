import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OCR + LangExtract - Analisi Documenti",
  description: "OCR e estrazione strutturata da documenti legali italiani",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="it">
      <body className="bg-zinc-950 text-zinc-100 antialiased">
        {children}
      </body>
    </html>
  );
}
