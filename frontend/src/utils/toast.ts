export type ToastType = 'success' | 'error' | 'warning'

let toastContainer: HTMLDivElement | null = null

function getToastContainer(): HTMLDivElement {
  if (!toastContainer) {
    toastContainer = document.createElement('div')
    document.body.appendChild(toastContainer)
  }
  return toastContainer
}

export function showToast(message: string, type: ToastType = 'success') {
  const container = getToastContainer()
  const toast = document.createElement('div')
  toast.className = `toast ${type}`
  toast.textContent = message

  container.appendChild(toast)

  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease-out'
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast)
      }
    }, 300)
  }, 3000)
}

// Add slideOut animation to CSS
const style = document.createElement('style')
style.textContent = `
  @keyframes slideOut {
    from {
      transform: translateX(0);
      opacity: 1;
    }
    to {
      transform: translateX(100%);
      opacity: 0;
    }
  }
`
document.head.appendChild(style)

