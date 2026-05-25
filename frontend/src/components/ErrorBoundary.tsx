import { Component, type ReactNode, type ErrorInfo } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
  info: ErrorInfo | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Logged so the actual stack is visible in the browser console even
    // when the user isn't watching DevTools.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] React render crash', error, info)
    this.setState({ info })
  }

  render() {
    if (!this.state.error) return this.props.children
    const { error, info } = this.state
    return (
      <div className="min-h-screen flex items-start justify-center bg-bg text-fg p-8">
        <div className="card max-w-3xl w-full p-6 space-y-4 border-danger/40">
          <div className="flex items-center gap-3 text-danger">
            <AlertTriangle size={20} />
            <h1 className="text-lg font-semibold">Something broke in the UI</h1>
          </div>
          <p className="text-sm text-fg-muted">
            The page hit an unhandled error during render. The data below helps
            diagnose it — copy/paste this into a bug report.
          </p>
          <pre className="text-xs bg-bg-subtle border border-border rounded-md p-3 overflow-auto max-h-64">
            {error.name}: {error.message}
            {'\n\n'}
            {error.stack}
          </pre>
          {info?.componentStack && (
            <details className="text-xs text-fg-muted">
              <summary className="cursor-pointer">Component stack</summary>
              <pre className="bg-bg-subtle border border-border rounded-md p-3 overflow-auto max-h-64 mt-2">
                {info.componentStack}
              </pre>
            </details>
          )}
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="btn-primary"
          >
            <RefreshCw size={14} /> Reload page
          </button>
        </div>
      </div>
    )
  }
}
