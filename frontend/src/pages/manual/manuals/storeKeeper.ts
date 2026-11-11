import type { Manual } from './common';

export const storeKeeperManual: Manual = {
  roleKey: 'store_keeper',
  roleLabel: 'Store Keeper',
  tagline: 'Own the stores — manage materials, track stock, and handle suppliers.',
  overview:
    'As a Store Keeper, you are responsible for the physical and digital management of materials and inventory. You manage stock levels in the portal, record material receipts and issues, and work with supplier records. Your role is critical for ensuring accurate cost tracking and that engineers have the materials they need.',
  permissions: [
    'Scoped dashboard',
    'View inventory',
    'Manage inventory (add, update, issue materials)',
    'Manage suppliers'
  ],
  limitations: [
    'Cannot view or submit reports',
    'Cannot access financial data directly',
    'Cannot access user management',
    'Cannot access documents',
    'Cannot access analytics or company-wide dashboard',
    'Cannot access audit logs',
    'Cannot approve any reports'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard gives you a quick overview of current stock levels, recent material movements, and any low-stock alerts.',
      tips: ['Set a bookmark to the Materials page for quick daily access.']
    },
    {
      id: 'manage-inventory',
      title: 'Managing Inventory',
      icon: '📦',
      content:
        'The Materials page is your main workspace. You can add new materials, update existing stock levels, and record material issues to projects.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'View current stock',
          detail: 'See all materials with their current quantities, units, and project assignments.'
        },
        {
          step: 3,
          action: 'Add a new material',
          detail:
            'Click "Add Material". Enter the material name, unit of measure (e.g., kg, m³, bags), and initial quantity.'
        },
        {
          step: 4,
          action: 'Record a delivery',
          detail:
            'When materials arrive, find the relevant item and click "Update" or "Receive". Enter the quantity received and the delivery note reference.'
        },
        {
          step: 5,
          action: 'Issue materials to a project',
          detail:
            'When issuing materials from store, click "Issue". Select the project, enter the quantity, and confirm.'
        },
        {
          step: 6,
          action: 'Review stock movements',
          detail:
            'Use the movement history on each material to see a full log of deliveries and issues.'
        }
      ],
      tips: [
        'Always record deliveries immediately when goods arrive — delays lead to discrepancies.',
        'Compare physical counts with the portal records at least once a week.',
        'If an engineer asks you to adjust a quantity without a delivery note, document your reason clearly.'
      ],
      diagram: `
Material Flow in the Portal:
[Supplier delivers goods]
          │
          ▼
[You record RECEIPT in Materials page]
          │
          ▼
[Stock level increases]
          │
          ▼
[Engineer uses materials on site]
          │
          ▼
[You record ISSUE to project in Materials page]
          │
          ▼
[Stock level decreases + project cost updated]
`
    },
    {
      id: 'suppliers',
      title: 'Managing Suppliers',
      icon: '🚚',
      content:
        'Maintain the supplier directory used across the portal for material orders, finance, and document workflows.',
      steps: [
        {
          step: 1,
          action: 'Go to Suppliers',
          detail:
            'Navigate to Suppliers from the portal (may appear in the sidebar or via the Materials area).'
        },
        {
          step: 2,
          action: 'View supplier list',
          detail:
            'See all registered suppliers with their names, contact details, and associated materials.'
        },
        {
          step: 3,
          action: 'Add a new supplier',
          detail:
            'Click "Add Supplier". Fill in the supplier name, contact person, phone, email, and any notes.'
        },
        {
          step: 4,
          action: 'Update supplier details',
          detail:
            'Click on an existing supplier to edit their information if contact details change.'
        },
        {
          step: 5,
          action: 'Upload TDS documents',
          detail:
            'For each supplier, you can upload their Technical Data Sheets (TDS) for the materials they supply.'
        }
      ],
      tips: [
        'Keep supplier contact details up to date — they are used by the finance team when processing invoices.',
        'Link suppliers to the correct materials so the system can provide accurate sourcing reports.'
      ]
    },
    {
      id: 'reconciliation',
      title: 'Stock Reconciliation Tips',
      icon: '🔄',
      content: 'Regularly reconcile physical stock with the portal to keep records accurate.',
      steps: [
        {
          step: 1,
          action: 'Export the inventory list',
          detail: 'Print or export the current stock from the Materials page.'
        },
        {
          step: 2,
          action: 'Conduct a physical count',
          detail: 'Count all items in the stores and compare with the portal figures.'
        },
        {
          step: 3,
          action: 'Investigate discrepancies',
          detail:
            'Look at the movement history for any item with a discrepancy to find missing receipts or issues.'
        },
        {
          step: 4,
          action: 'Correct the record',
          detail:
            'Make any necessary adjustments with a note explaining the reason for the correction.'
        }
      ],
      tips: [
        'Reconcile monthly at minimum — weekly is ideal for high-turnover materials.',
        'Document every adjustment with a reason — this is required for audit purposes.'
      ]
    }
  ]
};
