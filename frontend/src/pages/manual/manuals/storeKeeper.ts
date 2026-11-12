import type { Manual } from './common';

export const storeKeeperManual: Manual = {
  roleKey: 'store_keeper',
  roleLabel: 'Store Keeper',
  tagline: 'Own the stores — manage materials, track stock, and handle suppliers.',
  overview:
    'As a Store Keeper, you are responsible for the physical and digital management of materials and inventory. You manage stock levels in the portal, record material receipts and issues, and work with supplier records. Use requests and movement history to keep stock records aligned with physical balances.',
  permissions: [
    'Scoped dashboard',
    'View inventory',
    'Add locations and items, receive stock, and reserve or issue approved requests',
    'Manage suppliers',
    'Create requests for active projects and track your submissions'
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
        'Use the Dashboard for unread workflow alerts and Materials for current stock and movements.',
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
          detail:
            'Choose an inventory item to view its location-level On hand, Reserved, and Available balances.'
        },
        {
          step: 3,
          action: 'Add a new material',
          detail:
            'Fill the Inventory item form with the required name, item code, category, type, and unit, then choose Add item. Record opening stock as a receipt.'
        },
        {
          step: 4,
          action: 'Record a delivery',
          detail:
            'Select the item and use Quick receive. Choose the Receipt destination, enter the quantity and notes, then select Receive stock.'
        },
        {
          step: 5,
          action: 'Issue materials to a project',
          detail:
            'Create a material request with an active project, source location, and item quantities. After approval, open Request lines and use Reserve selected and Issue selected for the quantities you are fulfilling.'
        },
        {
          step: 6,
          action: 'Review stock movements',
          detail:
            'Use Recent movements to review receipts and issues, and Request lifecycle to check fulfillment status.'
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
[Material request approved]
          │
          ▼
[Reserve selected quantities → Issue selected quantities]
          │
          ▼
[Stock and request balances update]
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
          detail: 'Open Suppliers from the sidebar.'
        },
        {
          step: 2,
          action: 'View supplier list',
          detail:
            'Use search and the active status filter to find registered suppliers and review contact and compliance details.'
        },
        {
          step: 3,
          action: 'Add a new supplier',
          detail: 'Choose New supplier and enter the required contact, tax, and compliance details.'
        },
        {
          step: 4,
          action: 'Update supplier details',
          detail:
            'Choose Edit supplier to update details. Deactivate supplier makes the supplier unavailable for new selection while retaining historical references.'
        },
        {
          step: 5,
          action: 'Upload TDS documents',
          detail:
            'Select a file and choose Upload TDS document on the supplier card. Update the expiry date in Edit supplier when applicable.'
        }
      ],
      tips: [
        'Keep supplier contact details up to date — they are used by the finance team when processing invoices.',
        'Keep TDS expiry dates current for compliance review.'
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
          action: 'Open the stock matrix',
          detail:
            'Select the inventory item and use Filter by location to find the balance you are reconciling.'
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
            'Review Recent movements for receipts, issues, and adjustments that explain the discrepancy.'
        },
        {
          step: 4,
          action: 'Correct the record',
          detail:
            'Use Record movement with the adjustment type, applicable location, quantity, and reason in Notes.'
        }
      ],
      tips: [
        'Reconcile monthly at minimum — weekly is ideal for high-turnover materials.',
        'Document every adjustment with a reason — this is required for audit purposes.'
      ]
    }
  ]
};
