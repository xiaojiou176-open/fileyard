import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { createRouteIntentPrefetchHandlers } from '@/routes/lazy-routes'

export function NotFoundPage() {
  const homePrefetch = createRouteIntentPrefetchHandlers('dashboard')

  return (
    <div className="grid min-h-[60vh] place-items-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Page not found</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">This route is not assigned to an Fileman WebUI workflow yet.</p>
          <Button asChild>
            <Link {...homePrefetch} to="/">
              Back to home
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
