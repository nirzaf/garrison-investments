import { Component, type ErrorInfo, type ReactNode } from 'react';

type ErrorBoundaryState = {
  hasError: boolean;
};

export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Route render failed', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="alert-error rounded-lg border border-[var(--status-error-border)] px-4 py-6 text-sm">
          This screen could not be loaded. Refresh the page or try again later.
        </div>
      );
    }

    return this.props.children;
  }
}
