"use client";

import { useState } from "react";
import { X, Eye, EyeOff } from "lucide-react";
import type { AppConfig } from "@/lib/types";
import {
  AVAILABLE_OCR_MODELS,
  AVAILABLE_EXTRACTION_MODELS,
  DEFAULT_OCR_PROMPT,
  SCHEMA_PRESET_NAMES,
} from "@/lib/defaults";
import { getSchemaPreset } from "@/lib/schemas";

interface SettingsDialogProps {
  config: AppConfig;
  onSave: (config: AppConfig) => void;
  onClose: () => void;
}

export default function SettingsDialog({
  config,
  onSave,
  onClose,
}: SettingsDialogProps) {
  const [draft, setDraft] = useState<AppConfig>({ ...config });
  const [showKey, setShowKey] = useState(false);
  const [activeTab, setActiveTab] = useState<"api" | "ocr" | "extraction">("api");

  const update = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const getSchemaPrompt = (name: string): string => {
    if (name === "none") return "";
    if (draft.customSchemaPrompts[name]) return draft.customSchemaPrompts[name];
    try {
      const schema = getSchemaPreset(name);
      return schema?.promptDescription ?? "";
    } catch {
      return "";
    }
  };

  const handleSave = () => {
    onSave(draft);
    onClose();
  };

  const tabs = [
    { id: "api" as const, label: "API" },
    { id: "ocr" as const, label: "OCR" },
    { id: "extraction" as const, label: "Estrazione" },
  ];

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-700">
          <h2 className="text-lg font-bold text-zinc-100">Impostazioni</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6 pt-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "bg-blue-600 text-white"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {activeTab === "api" && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  Chiave API Gemini
                </label>
                <div className="relative">
                  <input
                    type={showKey ? "text" : "password"}
                    value={draft.geminiApiKey}
                    onChange={(e) => update("geminiApiKey", e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200 pr-10"
                    placeholder="AIza..."
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-zinc-500 mt-1">
                  La chiave viene usata per OCR (Gemini Vision) e per l&apos;estrazione strutturata.
                  Non viene mai inviata a nessun server, resta solo nel tuo browser.
                </p>
              </div>
            </div>
          )}

          {activeTab === "ocr" && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  Modello OCR
                </label>
                <select
                  value={draft.ocrModelId}
                  onChange={(e) => update("ocrModelId", e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200"
                >
                  {AVAILABLE_OCR_MODELS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-zinc-300">
                    Prompt OCR
                  </label>
                  <button
                    onClick={() => update("ocrPrompt", DEFAULT_OCR_PROMPT)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    Ripristina Default
                  </button>
                </div>
                <textarea
                  value={draft.ocrPrompt}
                  onChange={(e) => update("ocrPrompt", e.target.value)}
                  rows={8}
                  className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200 font-mono text-sm resize-y"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  DPI: {draft.pageDpi}
                </label>
                <input
                  type="range"
                  min={100}
                  max={400}
                  step={50}
                  value={draft.pageDpi}
                  onChange={(e) => update("pageDpi", Number(e.target.value))}
                  className="w-full accent-blue-500"
                />
                <div className="flex justify-between text-xs text-zinc-500">
                  <span>100</span>
                  <span>400</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === "extraction" && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  Schema di estrazione
                </label>
                <select
                  value={draft.activeSchema}
                  onChange={(e) => update("activeSchema", e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200"
                >
                  {SCHEMA_PRESET_NAMES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  Modello Estrazione
                </label>
                <select
                  value={draft.extractionModelId}
                  onChange={(e) => update("extractionModelId", e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200"
                >
                  {AVAILABLE_EXTRACTION_MODELS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              {draft.activeSchema !== "none" && (
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-1">
                    Prompt dello schema
                  </label>
                  <textarea
                    value={
                      draft.customSchemaPrompts[draft.activeSchema] ||
                      getSchemaPrompt(draft.activeSchema)
                    }
                    onChange={(e) =>
                      update("customSchemaPrompts", {
                        ...draft.customSchemaPrompts,
                        [draft.activeSchema]: e.target.value,
                      })
                    }
                    rows={8}
                    className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-zinc-200 font-mono text-sm resize-y"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1">
                  Passaggi di estrazione: {draft.extractionPasses}
                </label>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={draft.extractionPasses}
                  onChange={(e) => update("extractionPasses", Number(e.target.value))}
                  className="w-full accent-blue-500"
                />
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.includeOcrTextInOutput}
                  onChange={(e) => update("includeOcrTextInOutput", e.target.checked)}
                  className="accent-blue-500"
                />
                <span className="text-sm text-zinc-300">
                  Includi testo OCR nel Markdown
                </span>
              </label>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-zinc-700">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 bg-zinc-700 hover:bg-zinc-600 transition-colors"
          >
            Annulla
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            Salva
          </button>
        </div>
      </div>
    </div>
  );
}
