import { describe, expect, it } from 'vitest';

import {
  MAX_DOCUMENT_FILE_BYTES,
  MAX_REPORT_FILE_BYTES,
  classifyReportFile,
  validateDocumentFile
} from './fileValidation';

const pdf = '%PDF-1.4\n%%EOF';
const pngHeader = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const heicHeader = new Uint8Array([0, 0, 0, 24, ...'ftypheic'.split('').map((char) => char.charCodeAt(0))]);

describe('report and document file rules', () => {
  it('normalizes PDF by bytes and accepts original-only HEIC only as a photo', async () => {
    await expect(classifyReportFile(new File([pdf], 'extensionless'), 'photo')).resolves.toBe('attachment');
    const heic = new File([heicHeader], 'photo.heic');
    await expect(classifyReportFile(heic, 'photo')).resolves.toBe('photo');
    await expect(classifyReportFile(heic, 'attachment')).rejects.toThrow('Select PDF, JPEG, or PNG');
    await expect(validateDocumentFile(heic)).rejects.toThrow('Select a PDF, JPEG, or PNG');
  });

  it('rejects spoofed or blocked file types regardless of browser MIME labels', async () => {
    await expect(classifyReportFile(new File(['not a picture'], 'picture.png', { type: 'image/png' }), 'photo'))
      .rejects.toThrow('Unsupported file type');
    await expect(classifyReportFile(new File([pngHeader], 'photo.js'), 'photo'))
      .rejects.toThrow('File type is blocked');
  });

  it('applies distinct file-size limits to the report and document routes', async () => {
    const report = new File([pdf, new Uint8Array(MAX_REPORT_FILE_BYTES - pdf.length)], 'report.pdf');
    await expect(classifyReportFile(report, 'attachment')).resolves.toBe('attachment');
    await expect(classifyReportFile(new File([report, ' '], 'too-large.pdf'), 'attachment'))
      .rejects.toThrow('10 MiB');
    const document = new File([pdf, new Uint8Array(MAX_DOCUMENT_FILE_BYTES - pdf.length)], 'doc.pdf');
    await expect(validateDocumentFile(document)).resolves.toBeUndefined();
    await expect(validateDocumentFile(new File([document, ' '], 'too-large.pdf'))).rejects.toThrow('60 MiB');
  });
});
