import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  children: ReactNode
  /** "wide" (default): ~1800px cap for list/grid pages.
   *  "form": ~880px cap for narrow single-column forms. */
  width?: 'wide' | 'form'
  className?: string
}

/** Single source of truth for page-content width. Tightening or loosening
 *  the cap globally only needs to touch this file. */
export function PageContainer({ children, width = 'wide', className }: Props) {
  return (
    <div
      className={cn(
        'px-6 py-8 mx-auto w-full space-y-5',
        // ~90% of common monitor widths (1920/2560 land at 1728/2304 visible).
        // Form pages stay narrower so single-column inputs aren't a marathon.
        width === 'form' ? 'max-w-[55rem]' : 'max-w-[112.5rem]',
        className,
      )}
    >
      {children}
    </div>
  )
}
