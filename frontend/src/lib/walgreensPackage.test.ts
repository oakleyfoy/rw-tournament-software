import { describe, expect, it } from 'vitest'
import { defaultWatermarkSettings } from './photoPrintSettings'
import { printNeedsUpscale, walgreensFileName, walgreensZipName, zipStored } from './walgreensPackage'

describe('Walgreens package', () => {
  it('names the files as pictures, without player names', () => {
    expect(walgreensFileName({ photo_kind: 'team', team_id: 42, settings: defaultWatermarkSettings('Palm Springs') })).toBe('team-42.jpg')
    expect(walgreensFileName({ photo_kind: 'group', group_photo_id: 7, settings: defaultWatermarkSettings('Palm Springs') })).toBe('group-7.jpg')
    expect(walgreensZipName('Palm Springs 2026 (Copy)')).toBe('Palm-Springs-2026-Copy-prints.zip')
    const names = ['team-42.jpg', 'group-7.jpg', walgreensZipName('Palm Springs')]
    expect(names.join(' ')).not.toContain('Haley')
  })

  it('stores the photographs in a zip the laptop can save', () => {
    const bytes = zipStored([
      { name: 'team-42.jpg', data: new Uint8Array([1, 2, 3, 4]) },
      { name: 'group-7.jpg', data: new Uint8Array([9, 8]) },
    ])
    const names = zipNames(bytes)
    expect(names).toEqual(['team-42.jpg', 'group-7.jpg'])
    expect(zipFile(bytes, 'team-42.jpg')).toEqual([1, 2, 3, 4])
    expect(zipFile(bytes, 'group-7.jpg')).toEqual([9, 8])
    expect(new TextDecoder().decode(bytes)).not.toContain('Haley')
  })

  it('flags a photograph that would be enlarged to 4×6', () => {
    expect(printNeedsUpscale(1600, 1000)).toBe(true)
    expect(printNeedsUpscale(4032, 3024)).toBe(false)
  })
})

function zipNames(bytes: Uint8Array): string[] {
  const names: string[] = []
  let offset = 0
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  while (offset + 30 < bytes.length && view.getUint32(offset, true) === 0x04034b50) {
    const nameLength = view.getUint16(offset + 26, true)
    const size = view.getUint32(offset + 22, true)
    names.push(new TextDecoder().decode(bytes.slice(offset + 30, offset + 30 + nameLength)))
    offset += 30 + nameLength + size
  }
  return names
}

function zipFile(bytes: Uint8Array, name: string): number[] {
  let offset = 0
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  while (offset + 30 < bytes.length && view.getUint32(offset, true) === 0x04034b50) {
    const nameLength = view.getUint16(offset + 26, true)
    const size = view.getUint32(offset + 22, true)
    const found = new TextDecoder().decode(bytes.slice(offset + 30, offset + 30 + nameLength))
    const start = offset + 30 + nameLength
    if (found === name) return Array.from(bytes.slice(start, start + size))
    offset = start + size
  }
  throw new Error(name)
}
