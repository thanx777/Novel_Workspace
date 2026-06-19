import { Component } from 'react'

const ERROR_TEXT = {
  zh: { title: '组件渲染出错', retry: '重试', refresh: '刷新页面', unknown: '未知错误' },
  en: { title: 'Render Error', retry: 'Retry', refresh: 'Refresh Page', unknown: 'Unknown error' },
}

function getErrorText() {
  const lang = localStorage.getItem('language') || 'zh'
  return ERROR_TEXT[lang] || ERROR_TEXT.zh
}

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  handleRefresh = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      const text = getErrorText()
      return (
        <div className="error-boundary-container">
          <h3 className="error-boundary-title">{text.title}</h3>
          <p className="error-boundary-message">{this.state.error?.message || text.unknown}</p>
          <div className="error-boundary-actions">
            <button className="error-boundary-btn" onClick={() => this.setState({ hasError: false, error: null })}>
              {text.retry}
            </button>
            <button className="error-boundary-btn-primary" onClick={this.handleRefresh}>
              {text.refresh}
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
