export type ManualStep = {
  step: number;
  action: string;
  detail?: string;
};

export type ManualSection = {
  id: string;
  title: string;
  icon: string;
  content?: string;
  steps?: ManualStep[];
  tips?: string[];
  diagram?: string;
};

export type Manual = {
  roleKey: string;
  roleLabel: string;
  overview: string;
  tagline: string;
  permissions: string[];
  limitations: string[];
  sections: ManualSection[];
};

export const COMMON_SECTIONS: ManualSection[] = [
  {
    id: 'getting-started',
    title: 'Getting Started',
    icon: '🚀',
    content:
      'Welcome to the Garrisons Construction Internal Portal. This guide will help you navigate the system confidently based on your assigned role.',
    steps: [
      {
        step: 1,
        action: 'Sign In',
        detail: 'Go to the portal URL and enter your email and password on the login page.'
      },
      {
        step: 2,
        action: 'Enter OTP',
        detail: 'A one-time password (OTP) will be shown or sent. Enter it to complete login.'
      },
      {
        step: 3,
        action: 'Land on the Dashboard',
        detail: 'You will be taken to your dashboard, which shows a summary relevant to your role.'
      }
    ],
    tips: [
      'Bookmark the portal URL for quick access.',
      'Always sign out from shared computers using the user menu → "Sign out".',
      'If you forget your password, use the "Forgot password?" link on the login page.'
    ]
  },
  {
    id: 'profile-security',
    title: 'Your Profile & Security',
    icon: '👤',
    content: 'View your account details and manage your password.',
    steps: [
      {
        step: 1,
        action: 'Open the user menu',
        detail: 'Click your name in the top-right header to open the dropdown.'
      },
      {
        step: 2,
        action: 'Go to Profile',
        detail:
          'Open Profile to view your account details. Contact an authorized administrator for corrections.'
      },
      {
        step: 3,
        action: 'Change your password',
        detail:
          'Click "Security" in the user menu dropdown, then enter your current password followed by your new password.'
      }
    ],
    tips: [
      'Use a strong, unique password with a mix of letters, numbers, and symbols.',
      'Change your password if you suspect your account has been compromised.'
    ]
  },
  {
    id: 'notifications',
    title: 'Notifications',
    icon: '🔔',
    content: 'Stay up-to-date with activity relevant to your role via the Notifications panel.',
    steps: [
      {
        step: 1,
        action: 'Check the bell icon',
        detail:
          'The bell icon in the top-right header shows a red badge when you have unread notifications.'
      },
      {
        step: 2,
        action: 'Click Notifications',
        detail: 'Click the bell icon or navigate to /notifications to view your notification list.'
      },
      {
        step: 3,
        action: 'Review and act',
        detail:
          'Read each notification and take any required action (e.g., reviewing an approval request).'
      }
    ]
  },
  {
    id: 'navigation',
    title: 'Navigating the Portal',
    icon: '🧭',
    content:
      'The portal has a sidebar navigation on desktop and a bottom navigation bar on mobile.',
    diagram: `
Desktop Layout:
┌─────────────────────────────────────────────────┐
│  🏢 Garrisons  │         Page Header            │
│  Logo          │  [ Notifications ]  [ User ▾ ]  │
├────────────────┼─────────────────────────────────┤
│  ▪ Dashboard   │                                 │
│  ▪ Projects    │         Page Content            │
│  ▪ Reports     │                                 │
│  ▪ ...         │                                 │
│                │                                 │
└────────────────┴─────────────────────────────────┘

Mobile Layout (bottom tab bar):
┌─────────────────────────────┐
│        Page Content         │
├─────────┬───────┬───────────┤
│Dashboard│Reports│ Materials │
└─────────┴───────┴───────────┘
`,
    tips: [
      'On mobile, tap the ☰ menu icon in the header to open the full sidebar.',
      'The current page is highlighted in teal/green in the sidebar.',
      'The breadcrumb at the top of every page shows where you are: Portal / Page Name.'
    ]
  }
];
