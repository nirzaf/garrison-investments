export type EvidenceClassification = 'unclassified' | 'operational' | 'financial';

export function EvidenceClassificationField({
  value,
  onChange,
  disabled = false,
  id = 'evidence-classification'
}: {
  value: EvidenceClassification | '';
  onChange: (value: EvidenceClassification | '') => void;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <label className="block space-y-1 text-sm" htmlFor={id}>
      <span className="font-medium">Evidence classification</span>
      <select
        className="form-field w-full"
        disabled={disabled}
        id={id}
        onChange={(event) => onChange(event.target.value as EvidenceClassification | '')}
        value={value}
      >
        <option value="">Select before uploading</option>
        <option value="operational">Operational · no restricted financial details</option>
        <option value="financial">Financial · restricted to financial viewers</option>
        <option value="unclassified">Unclassified · restricted until reviewed</option>
      </select>
      <span className="block text-xs text-theme-text-muted">
        Invoices and cost-bearing originals should be financial. Upload a redacted operational copy
        for technical review.
      </span>
    </label>
  );
}
