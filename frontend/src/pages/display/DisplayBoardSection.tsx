import { ReactNode } from 'react'

export function DisplayBoardSection({
  testId,
  title,
  emptyLabel,
  isEmpty,
  gridClass,
  gridTestId,
  children,
}: {
  testId: string
  title: string
  emptyLabel: string
  isEmpty: boolean
  gridClass?: string
  gridTestId?: string
  children?: ReactNode
}) {
  if (isEmpty) {
    return (
      <section
        className="display-section display-section-compact"
        data-testid={testId}
        data-empty="true"
      >
        <h2 className="display-section-title">{title}</h2>
        <p className="display-empty">{emptyLabel}</p>
      </section>
    )
  }

  return (
    <section className="display-section" data-testid={testId} data-empty="false">
      <h2 className="display-section-title">{title}</h2>
      <div className={gridClass} data-testid={gridTestId}>
        {children}
      </div>
    </section>
  )
}
