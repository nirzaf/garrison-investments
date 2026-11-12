import { apiClient } from './client';
import { normalizeProtectedFileUrl } from './fileUrls';
import type { components } from './schema';

export type InvoiceRecord = components['schemas']['InvoiceResponse'];
export type InvoiceListResponse = components['schemas']['InvoiceListResponse'];
export type InvoiceCreatePayload = components['schemas']['InvoiceCreateRequest'];
export type InvoiceUpdatePayload = components['schemas']['InvoiceUpdateRequest'];
export type PaymentCreatePayload = components['schemas']['PaymentCreateRequest'];
export type InvoiceAttachmentUrl = components['schemas']['InvoiceAttachmentUrlResponse'];
export type InvoiceSupplierOptions = components['schemas']['InvoiceSupplierOptionsResponse'];
export type BudgetSummary = components['schemas']['BudgetSummaryResponse'];

export async function listInvoices(params?: {
  project_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const { data } = await apiClient.get<InvoiceListResponse>('/finance/invoices', { params });
  return data;
}

export async function getInvoice(invoiceId: string) {
  const { data } = await apiClient.get<InvoiceRecord>(`/finance/invoices/${invoiceId}`);
  return data;
}

export async function updateInvoice(invoiceId: string, payload: InvoiceUpdatePayload) {
  const { data } = await apiClient.patch<InvoiceRecord>(`/finance/invoices/${invoiceId}`, payload);
  return data;
}

export async function listInvoiceSupplierOptions(params: {
  search?: string;
  limit: number;
  offset: number;
}) {
  const { data } = await apiClient.get<InvoiceSupplierOptions>('/finance/supplier-options', {
    params
  });
  return data;
}

export async function getBudgetSummary(projectId: string) {
  const { data } = await apiClient.get<BudgetSummary>(
    `/finance/projects/${projectId}/budget-summary`
  );
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
