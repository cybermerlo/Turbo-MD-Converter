"use client";

import { useEffect, useRef } from "react";
import type { LogEntry } from "@/lib/types";

interface LogPanelProps {
  logs: LogEntry[];
}

const levelColors: Record<string, string> = {
  INFO: "text-zinc-400",
  WARNING: "text-amber-400",
  ERROR: "text-red-400",
};

export default function LogPanel({ logs }: LogPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="bg-zinc-800/50 rounded-xl overflow-hidden">
      <div className="px-4 py-2 border-b border-zinc-700">
        <span className="text-sm font-medium text-zinc-400">Log</span>
      </div>
      <div
        ref={scrollRef}
        className="h-[150px] overflow-y-auto px-4 py-2 font-mono text-xs space-y-0.5"
      >
        {logs.length === 0 ? (
          <p className="text-zinc-600">In attesa di elaborazione...</p>
        ) : (
          logs.map((log, i) => (
            <div key={i} className={levelColors[log.level] || "text-zinc-400"}>
              <span className="text-zinc-600">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>{" "}
              {log.level !== "INFO" && (
                <span className="font-bold">[{log.level}] </span>
              )}
              {log.message}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
