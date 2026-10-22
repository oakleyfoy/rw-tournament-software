const MAX_UPLOAD_BYTES = 12 * 1024 * 1024

export function fitPhotoDimensions(width: number, height: number, maxEdge = 4096): { width: number; height: number } {
  const longest = Math.max(width, height, 1)
  const scale = Math.min(1, maxEdge / longest)
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

function isPhotograph(file: File): boolean {
  return file.type.startsWith('image/') || /hei[cf]/i.test(file.type) || /\.(jpe?g|png|webp|hei[cf])$/i.test(file.name)
}

export async function prepareTeamPhoto(file: File): Promise<{ blob: Blob; clientUploadId: string }> {
  const clientUploadId = crypto.randomUUID()
  if (!isPhotograph(file)) {
    throw new Error('Choose a photograph from the camera or photo library')
  }
  // The server stores a normal camera JPEG unchanged. Recompressing it here
  // is what made the print preview look grainy next to the original.
  if (file.size <= MAX_UPLOAD_BYTES) {
    return { blob: file, clientUploadId }
  }
  if (typeof createImageBitmap !== 'function') {
    throw new Error('This photograph is too large to upload')
  }
  const bitmap = await createImageBitmap(file)
  try {
    const fitted = fitPhotoDimensions(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = fitted.width
    canvas.height = fitted.height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Could not prepare the photograph')
    context.imageSmoothingEnabled = true
    context.imageSmoothingQuality = 'high'
    context.drawImage(bitmap, 0, 0, fitted.width, fitted.height)
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((value) => {
        if (value) resolve(value)
        else reject(new Error('Could not prepare the photograph'))
      }, 'image/jpeg', 0.95)
    })
    return { blob, clientUploadId }
  } finally {
    bitmap.close()
  }
}
