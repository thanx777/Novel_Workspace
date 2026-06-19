export const API_FORMATS = {
  openai: {
    label: 'OpenAI Compatible',
    baseUrlExample: 'https://api.openai.com/v1',
    modelExamples: ['gpt-4', 'gpt-3.5-turbo', 'glm-4-flash', 'claude-3-haiku']
  },
  claude: {
    label: 'Anthropic Claude',
    baseUrlExample: 'https://api.anthropic.com',
    modelExamples: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229']
  }
}
export const API_BASE = '/api'
