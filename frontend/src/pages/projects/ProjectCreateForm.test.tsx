import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProjectCreateForm } from './ProjectCreateForm';

describe('project creation financial boundary', () => {
  it('shows financial fields and locks initial status for MEP', () => {
    const html = renderToStaticMarkup(
      <ProjectCreateForm planningOnly onCreated={() => {}} onCancel={() => {}} />
    );
    expect(html).toContain('Budget');
    expect(html).toContain('Unit rate');
    expect(html).toContain('disabled');
  });
  it('preserves financial fields for directors', () => {
    const html = renderToStaticMarkup(
      <ProjectCreateForm onCreated={() => {}} onCancel={() => {}} />
    );
    expect(html).toContain('Budget');
    expect(html).toContain('Unit rate');
  });
});
