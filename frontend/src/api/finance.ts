import { apiClient } from './client';
import { normalizeProtectedFileUrl } from './fileUrls';
import type { components } from './schema';

export type InvoiceRecord = components['schemas']['InvoiceResponse'];
export type InvoiceListResponse = components['schemas']['InvoiceListResponse'];
export type InvoiceCreatePayload = components['schemas']['InvoiceCreateRequest'];
export type PaymentCreatePayload = components['schemas']['PaymentCreateRequest'];
export type InvoiceAttachmentUrl = components['schemas']['InvoiceAttachmentUrlResponse'];

export async function listInvoices() {
  const { data } = await apiClient.get<InvoiceListResponse>('/finance/invoices');
  return data;
}

export async function createInvoice(payload: InvoiceCreatePayload) {
  const { data } = await apiClient.post<InvoiceRecord>('/finance/invoices', payload);
  return data;
}

export async function createPayment(invoiceId: string, payload: PaymentCreatePayload) {
  const { data } = await apiClient.post<InvoiceRecord>(
    `/finance/invoices/${invoiceId}/payments`,
    payload
  );
  return data;
}

export async function uploadInvoiceAttachment(invoiceId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<InvoiceRecord>(
    `/finance/invoices/${invoiceId}/attachment`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return data;
}

export async function getInvoiceAttachmentUrl(invoiceId: string) {
  const { data } = await apiClient.get<InvoiceAttachmentUrl>(
    `/finance/invoices/${invoiceId}/attachment`
  );
  return { ...data, url: normalizeProtectedFileUrl(data.url) };
}
