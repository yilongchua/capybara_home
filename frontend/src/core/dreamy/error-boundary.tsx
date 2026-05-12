"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class DreamyErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  handleReset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
          <p className="text-sm font-medium text-destructive">Something went wrong in the Dreamy panel.</p>
          <p className="text-xs opacity-70">{this.state.error.message}</p>
          <button
            type="button"
            onClick={this.handleReset}
            className="rounded-md border px-3 py-1.5 text-xs hover:bg-muted"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
