import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DisplayBoardResponse } from '../../api/client'
import { sampleBoard } from './displayBoardFixture'
import { useDisplayBoard } from './useDisplayBoard'

function HookProbe({
  fetcher,
  intervalMs,
}: {
  fetcher: (id: number) => Promise<DisplayBoardResponse>
  intervalMs?: number
}) {
  const state = useDisplayBoard(9, { fetcher, intervalMs })
  return (
    <div>
      <div data-testid="loading">{String(state.initialLoading)}</div>
      <div data-testid="refreshing">{String(state.refreshing)}</div>
      <div data-testid="name">{state.data?.tournament_name || ''}</div>
      <div data-testid="playing">{state.data?.currently_playing[0]?.team_a_names || ''}</div>
      <div data-testid="error">{state.error || ''}</div>
    </div>
  )
}

describe('useDisplayBoard', () => {
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('shows loading then renders fetched board data', async () => {
    const fetcher = vi.fn().mockResolvedValue(sampleBoard)
    render(<HookProbe fetcher={fetcher} intervalMs={60_000} />)
    expect(screen.getByTestId('loading')).toHaveTextContent('true')
    expect(await screen.findByTestId('name')).toHaveTextContent('Display Board Open')
    expect(screen.getByTestId('loading')).toHaveTextContent('false')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('refetches on the polling interval and keeps previous data visible', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const updated: DisplayBoardResponse = {
      ...sampleBoard,
      currently_playing: [
        {
          ...sampleBoard.currently_playing[0],
          team_a_names: 'Pat / Kim',
        },
      ],
    }
    const fetcher = vi.fn()
      .mockResolvedValueOnce(sampleBoard)
      .mockResolvedValueOnce(updated)
      .mockRejectedValueOnce(new Error('network down'))

    render(<HookProbe fetcher={fetcher} intervalMs={20} />)
    expect(await screen.findByTestId('playing')).toHaveTextContent('Helen / Simone')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20)
    })
    expect(await screen.findByTestId('playing')).toHaveTextContent('Pat / Kim')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20)
    })
    expect(screen.getByTestId('playing')).toHaveTextContent('Pat / Kim')
    expect(await screen.findByTestId('error')).toHaveTextContent('network down')
  })

  it('does not overlap in-flight requests', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let resolveFirst: ((value: DisplayBoardResponse) => void) | undefined
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise<DisplayBoardResponse>((resolve) => {
          resolveFirst = resolve
        })
    )
    render(<HookProbe fetcher={fetcher} intervalMs={20} />)
    expect(fetcher).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(40)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)
    await act(async () => {
      resolveFirst?.(sampleBoard)
    })
    expect(await screen.findByTestId('name')).toHaveTextContent('Display Board Open')
  })

  it('stops polling after unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const fetcher = vi.fn().mockResolvedValue(sampleBoard)
    const view = render(<HookProbe fetcher={fetcher} intervalMs={20} />)
    expect(await screen.findByTestId('name')).toHaveTextContent('Display Board Open')
    view.unmount()
    const calls = fetcher.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80)
    })
    expect(fetcher.mock.calls.length).toBe(calls)
  })
})
