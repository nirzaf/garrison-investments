import { Upload } from 'lucide-react';
import { type DragEvent, useState } from 'react';

type FileDropZoneProps = {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: FileList) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
};

export function FileDropZone({
  accept,
  disabled,
  hint,
  label,
  multiple,
  onFiles
}: FileDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!disabled) setIsDragOver(true);
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
    if (disabled || !event.dataTransfer.files.length) return;
    onFiles(event.dataTransfer.files);
  }

  return (
    <label
      className={`flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors ${
        isDragOver
          ? 'border-brand-500 bg-brand-50'
          : 'border-theme-border bg-theme-main hover:border-theme-text-muted'
      } ${disabled ? 'pointer-events-none opacity-50' : ''}`}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Upload className="h-6 w-6 text-theme-text-muted" />
      <span className="text-sm font-medium text-theme-text-secondary">{label}</span>
      {hint ? <span className="text-xs text-theme-text-muted">{hint}</span> : null}
      <input
        accept={accept}
        className="sr-only"
        disabled={disabled}
        multiple={multiple}
        onChange={(event) => {
          if (event.target.files?.length) onFiles(event.target.files);
          event.target.value = '';
        }}
        type="file"
      />
    </label>
  );
}
