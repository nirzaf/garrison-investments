export const MAX_REPORT_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_DOCUMENT_FILE_BYTES = 60 * 1024 * 1024;
export const MAX_REPORT_PHOTOS = 5;
export const REPORT_PHOTO_ACCEPT = 'image/jpeg,image/png,image/heic,.heic,.heif';
export const PDF_IMAGE_ACCEPT = 'application/pdf,image/jpeg,image/png';

export type ReportFileKind = 'photo' | 'attachment';

const blockedExtension = /\.(exe|sh|bat|cmd|js|ps1|php|py)$/i;

async function detectFileFormat(file: File, limit: number, limitMiB: number) {
  if (file.size > limit) throw new Error(`File exceeds the ${limitMiB} MiB limit.`);
  if (blockedExtension.test(file.name)) throw new Error('File type is blocked.');
  const header = new Uint8Array(await file.slice(0, 32).arrayBuffer());
  const starts = (signature: number[]) => signature.every((byte, index) => header[index] === byte);
  if (starts([0xff, 0xd8, 0xff])) return 'jpeg';
  if (starts([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'png';
  if (starts([0x25, 0x50, 0x44, 0x46, 0x2d])) return 'pdf';
  if (/^ftyp(heic|heix|hevc|mif1)/.test(String.fromCharCode(...header.subarray(4, 12)))) {
    return 'heic';
  }
  throw new Error('Unsupported file type.');
}

export async function classifyReportFile(file: File, kind: ReportFileKind): Promise<ReportFileKind> {
  const format = await detectFileFormat(file, MAX_REPORT_FILE_BYTES, 10);
  if (format === 'pdf' || kind === 'attachment') {
    if (format === 'heic') throw new Error('Select PDF, JPEG, or PNG for attachments.');
    return 'attachment';
  }
  return 'photo';
}

export async function validateDocumentFile(file: File) {
  if (await detectFileFormat(file, MAX_DOCUMENT_FILE_BYTES, 60) === 'heic') {
    throw new Error('Select a PDF, JPEG, or PNG document.');
  }
}
