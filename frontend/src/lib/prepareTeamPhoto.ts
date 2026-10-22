export function fitPhotoDimensions(width: number, height: number, maxEdge = 3000): { width: number; height: number } {
  const longest = Math.max(width, height, 1)
  const scale = Math.min(1, maxEdge / longest)
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

export async function prepareTeamPhoto(file: File): Promise<{ blob: Blob; clientUploadId: string }> {
  const clientUploadId = crypto.randomUUID()
  if (typeof createImageBitmap !== 'function') {
    return { blob: file, clientUploadId }
  }
  try {
    const bitmap = await createImageBitmap(file)
    const fitted = fitPhotoDimensions(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = fitted.width
    canvas.height = fitted.height
    const context = canvas.getContext('2d')
    if (!context) {
      bitmap.close()
      return { blob: file, clientUploadId }
    }
    context.drawImage(bitmap, 0, 0, fitted.width, fitted.height)
    bitmap.close()
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((value) => {
        if (value) resolve(value)
        else reject(new Error('Could not compress photograph'))
      }, 'image/jpeg', 0.92)
    })
    return { blob, clientUploadId }
  } catch {
    const heic = /hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name)
    if (!file.type.startsWith('image/') && !heic) {
      throw new Error('Choose a photograph from the camera or photo library')
    }
    return { blob: file, clientUploadId }
  }
}
