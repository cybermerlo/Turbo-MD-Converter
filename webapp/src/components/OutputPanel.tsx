"use client";

import { Download, Copy, Check } from "lucide-react";
import { useState, useCallback } from "react";

interface OutputPanelProps {
  markdown: string;
  suggestedFilename: string;
}

export default function OutputPanel({ markdown, suggestedFilename }: OutputPanelProps) {
  const [copied, setCopied] = useState(false);

  const handleDownload = useCallback(() => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = suggestedFilename;
    a.click();
    URL.revokeObjectURL(url);
  }, [markdown, suggestedFilename]);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [markdown]);

  if (!markdown) {
    return (
      <div className="bg-zinc-800/50 rounded-xl p-8 flex-1 flex items-center justify-center">
        <p className="text-zinc-500 text-sm">
          L&apos;output apparira&apos; qui dopo l&apos;elaborazione
        </p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 rounded-xl flex-1 flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-700">
        <span className="text-sm text-zinc-400 truncate">
          {suggestedFilename}
        </span>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium
              text-zinc-300 bg-zinc-700 hover:bg-zinc-600 transition-colors"
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? "Copiato!" : "Copia"}
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium
              text-white bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Scarica
          </button>
        </div>
      </div>

      {/* Content */}
      <pre className="flex-1 overflow-auto p-4 text-sm text-zinc-300 whitespace-pre-wrap font-mono">
        {markdown}
      </pre>
    </div>
  );
}
