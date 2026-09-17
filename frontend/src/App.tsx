import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

function App() {
  const [result, setResult] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const checkBackendHealth = async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await fetch('http://localhost:8000/api/health')
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`)
      }
      const data = await response.json()
      setResult(JSON.stringify(data, null, 2))
    } catch {
      setError('Backend unreachable')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Network Analyser — Frontend Skeleton</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button onClick={checkBackendHealth} disabled={loading}>
            {loading ? 'Checking...' : 'Check Backend Health'}
          </Button>
          {error && (
            <p className="text-sm font-medium text-red-600">{error}</p>
          )}
          {result && (
            <pre className="overflow-x-auto rounded-md bg-muted p-4 text-sm text-foreground">
              {result}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default App
