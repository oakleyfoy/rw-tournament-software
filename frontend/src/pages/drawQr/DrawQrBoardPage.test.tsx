import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DrawQrBoardResponse } from '../../api/client'

const apiState = {
  data: {
    tournament_id: 9,
    tournament_name: 'Racquet War Destin',
    filename_slug: 'racquet-war-destin',
    items: [
      {
        event_id: 1,
        event_name: "Women's A",
        label: "Women's A",
        draw_type: 'waterfall',
        draw_type_label: 'Waterfall',
        division_code: null,
        public_path: '/t/9/draws/1/waterfall',
        public_url: 'https://players.example.com/t/9/draws/1/waterfall',
      },
      {
        event_id: 2,
        event_name: "Women's B",
        label: "Women's B",
        draw_type: 'round_robin',
        draw_type_label: 'Round Robin',
        division_code: null,
        public_path: '/t/9/draws/2/roundrobin',
        public_url: 'https://players.example.com/t/9/draws/2/roundrobin',
      },
      {
        event_id: 3,
        event_name: 'Mixed A',
        label: 'Mixed A',
        draw_type: 'bracket',
        draw_type_label: 'Bracket',
        division_code: 'BWW',
        public_path: '/t/9/draws/3/bracket/BWW',
        public_url: 'https://players.example.com/t/9/draws/3/bracket/BWW',
      },
    ],
  } as DrawQrBoardResponse,
}

const generatePdf = vi.fn()

vi.mock('../../api/client', () => ({
  getDrawQrBoard: () => Promise.resolve(apiState.data),
}))

vi.mock('./drawQrBoardPdf', () => ({
  buildDrawQrBoardPdf: (...args: unknown[]) => generatePdf(...args),
}))

import DrawQrBoardPage from './DrawQrBoardPage'
import { DrawQrBoardButton } from './DrawQrBoardButton'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/tournaments/9/draw-qr-board']}>
      <Routes>
        <Route path="/tournaments/:id/draw-qr-board" element={<DrawQrBoardPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('DrawQrBoardPage', () => {
  beforeEach(() => {
    apiState.data = {
      ...apiState.data,
      items: [...apiState.data.items],
    }
    generatePdf.mockReset()
    generatePdf.mockResolvedValue({
      blob: new Blob(['pdf'], { type: 'application/pdf' }),
      width: 2304,
      height: 1728,
      filename: 'draw-qr-board-racquet-war-destin.pdf',
    })
  })

  it('renders returned labels and the generate action', async () => {
    renderPage()
    expect(await screen.findByTestId('draw-qr-count')).toHaveTextContent('3 draws will be included')
    expect(screen.getByText("Women's A — Waterfall")).toBeInTheDocument()
    expect(screen.getByText("Women's B — Round Robin")).toBeInTheDocument()
    expect(screen.getByText('Mixed A — Bracket')).toBeInTheDocument()
    expect(screen.getByTestId('draw-qr-item-list').querySelectorAll('li')).toHaveLength(3)
    expect(screen.getByTestId('draw-qr-generate')).toHaveTextContent('Generate 32 × 24 PDF')
  })

  it('passes every returned item into PDF generation', async () => {
    renderPage()
    const button = await screen.findByTestId('draw-qr-generate')
    button.click()
    await waitFor(() => expect(generatePdf).toHaveBeenCalled())
    expect(generatePdf).toHaveBeenCalledWith(
      apiState.data.items,
      expect.objectContaining({
        tournamentName: 'Racquet War Destin',
        filenameSlug: 'racquet-war-destin',
      })
    )
  })

  it('shows the empty published-draw state', async () => {
    apiState.data = { ...apiState.data, items: [] }
    renderPage()
    expect(await screen.findByTestId('draw-qr-empty')).toHaveTextContent(
      'No published draws are currently available for this tournament.'
    )
    expect(screen.queryByTestId('draw-qr-generate')).not.toBeInTheDocument()
  })
})

describe('DrawQrBoardButton', () => {
  it('appears with the staff label', () => {
    render(
      <MemoryRouter>
        <DrawQrBoardButton tournamentId={9} />
      </MemoryRouter>
    )
    expect(screen.getByTestId('print-draw-qr-board')).toHaveTextContent('Print Draw QR Board')
  })
})
