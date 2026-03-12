import * as pdfjsLib from "pdfjs-dist";

// Set up the worker - use CDN for simplicity
if (typeof window !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;
}

export async function getPageCount(file: File): Promise<number> {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  const count = pdf.numPages;
  pdf.destroy();
  return count;
}

export async function* iterPages(
  file: File,
  dpi: number = 200,
  jpegQuality: number = 0.85
): AsyncGenerator<{ pageNum: number; imageData: string }> {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  const totalPages = pdf.numPages;

  const scale = dpi / 72; // PDF default is 72 DPI

  for (let i = 1; i <= totalPages; i++) {
    const page = await pdf.getPage(i);
    const viewport = page.getViewport({ scale });

    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;

    const ctx = canvas.getContext("2d")!;
    await page.render({ canvasContext: ctx, viewport }).promise;

    // Convert to JPEG base64
    const dataUrl = canvas.toDataURL("image/jpeg", jpegQuality);
    // Strip the data:image/jpeg;base64, prefix
    const base64Data = dataUrl.split(",")[1];

    page.cleanup();
    yield { pageNum: i - 1, imageData: base64Data };
  }

  pdf.destroy();
}
