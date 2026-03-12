"use client";

import { useCallback, useRef, useState } from "react";
import { Upload, X, FileText } from "lucide-react";

interface FileUploadProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled: boolean;
}

export default function FileUpload({
  files,
  onFilesChange,
  disabled,
}: FileUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (newFiles: FileList | File[]) => {
      const validFiles = Array.from(newFiles).filter(
        (f) =>
          f.name.toLowerCase().endsWith(".pdf") ||
          f.name.toLowerCase().endsWith(".txt") ||
          f.name.toLowerCase().endsWith(".eml")
      );
      if (validFiles.length === 0) return;

      const existing = new Set(files.map((f) => f.name + f.size));
      const unique = validFiles.filter(
        (f) => !existing.has(f.name + f.size)
      );
      onFilesChange([...files, ...unique]);
    },
    [files, onFilesChange]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (disabled) return;
      addFiles(e.dataTransfer.files);
    },
    [addFiles, disabled]
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (!disabled) setIsDragOver(true);
    },
    [disabled]
  );

  const removeFile = useCallback(
    (index: number) => {
      onFilesChange(files.filter((_, i) => i !== index));
    },
    [files, onFilesChange]
  );

  return (
    <div className="flex flex-col gap-3">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={() => setIsDragOver(false)}
        onClick={() => !disabled && inputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-xl p-8
          flex flex-col items-center justify-center gap-3
          cursor-pointer transition-all min-h-[160px]
          ${disabled ? "opacity-50 cursor-not-allowed border-zinc-700" : ""}
          ${isDragOver ? "border-blue-400 bg-blue-500/10" : "border-zinc-600 hover:border-zinc-400 hover:bg-zinc-800/50"}
        `}
      >
        <Upload className="w-8 h-8 text-zinc-400" />
        <div className="text-center">
          <p className="text-zinc-300 font-medium">
            Trascina qui i file o clicca per selezionare
          </p>
          <p className="text-zinc-500 text-sm mt-1">
            PDF, TXT, EML
          </p>
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.eml"
        className="hidden"
        onChange={(e) => {
          if (e.target.files) addFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {files.length > 0 && (
        <div className="flex flex-col gap-1 max-h-[200px] overflow-y-auto">
          {files.map((file, i) => (
            <div
              key={file.name + file.size}
              className="flex items-center gap-2 px-3 py-2 bg-zinc-800 rounded-lg text-sm"
            >
              <FileText className="w-4 h-4 text-blue-400 flex-shrink-0" />
              <span className="text-zinc-300 truncate flex-1">{file.name}</span>
              <span className="text-zinc-500 text-xs flex-shrink-0">
                {(file.size / 1024).toFixed(0)} KB
              </span>
              {!disabled && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  className="text-zinc-500 hover:text-red-400 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
