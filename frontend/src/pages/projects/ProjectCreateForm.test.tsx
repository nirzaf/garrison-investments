import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProjectCreateForm } from './ProjectCreateForm';

describe('project creation financial boundary', () => {
  it('starts without a BOQ row, retains the add action, and locks initial status for MEP', () => {
    const html = renderToStaticMarkup(
      <ProjectCreateForm planningOnly onCreated={() => {}} onCancel={() => {}} />
    );
    expect(html).toContain('Budget');
    expect(html).toContain('BOQ items can be added after project creation.');
    expect(html).toContain('Add BOQ item');
    expect(html).not.toContain('BOQ description');
    expect(html).toContain('disabled');
  });
  it('starts directors with an optional BOQ and mandatory project fields', () => {
    const html = renderToStaticMarkup(
      <ProjectCreateForm onCreated={() => {}} onCancel={() => {}} />
    );
    expect(html).toContain('Budget');
    expect(html).toContain('Project name');
    expect(html).toContain('Scope of work');
    expect(html).toContain('Target end date');
    expect(html).toContain('BOQ items can be added after project creation.');
    expect(html).toContain('Add BOQ item');
    expect(html).not.toContain('BOQ description');
  });
});
