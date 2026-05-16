import { apiClient } from './client';

export type InvoiceRecord = {
  id: string;
  invoice_number: string;
  project_id: string;
  supplier_id: string | null;
  invoice_date: string;
  due_date: string;
  amount: string;
  tax_amount: string;
  total_amount: string;
  status: string;
  payment_status: string;
  attachment_key: string | null;
  notes: string | null;
  payments: Array<{
    id: string;
    payment_date: string;
    amount: string;
    method: string;
    reference_number: string | null;
  }>;
};

export async function listInvoices() {
  const { data } = await apiClient.get<{ items: InvoiceRecord[]; total: number }>(
    '/finance/invoices'
  );
  return data;
}

export async function createInvoice(payload: {
  invoice_number: string;
  project_id: string;
  supplier_id?: string;
  invoice_date: string;
  due_date: string;
  amount: string;
  tax_amount: string;
  notes?: string;
}) {
  const { data } = await apiClient.post<InvoiceRecord>('/finance/invoices', payload);
  return data;
}

export async function createPayment(
  invoiceId: string,
  payload: {
    payment_date: string;
    amount: string;
    method: string;
    reference_number?: string;
  }
) {
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
  const { data } = await apiClient.get<{ url: string; expires_in_seconds: number }>(
    `/finance/invoices/${invoiceId}/attachment`
  );
  return data;
}
