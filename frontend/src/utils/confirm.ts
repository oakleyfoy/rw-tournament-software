export function confirmDialog(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    // Create overlay
    const overlay = document.createElement('div')
    overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background-color: rgba(0, 0, 0, 0.5);
      display: flex;
      justify-content: center;
      align-items: center;
      z-index: 10000;
    `

    // Create dialog
    const dialog = document.createElement('div')
    dialog.style.cssText = `
      background: white;
      padding: 24px;
      border-radius: 8px;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      max-width: 400px;
      width: 90%;
      z-index: 10001;
    `

    // Create message
    const messageEl = document.createElement('div')
    messageEl.textContent = message
    messageEl.style.cssText = `
      margin-bottom: 20px;
      font-size: 16px;
      color: #333;
    `

    // Create buttons container
    const buttonsContainer = document.createElement('div')
    buttonsContainer.style.cssText = `
      display: flex;
      gap: 12px;
      justify-content: flex-end;
    `

    // Create Cancel button
    const cancelButton = document.createElement('button')
    cancelButton.textContent = 'Cancel'
    cancelButton.style.cssText = `
      padding: 8px 16px;
      border: 1px solid #ccc;
      background: white;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    `
    cancelButton.onclick = () => {
      document.body.removeChild(overlay)
      resolve(false)
    }

    // Create OK button
    const okButton = document.createElement('button')
    okButton.textContent = 'OK'
    okButton.style.cssText = `
      padding: 8px 16px;
      border: none;
      background: #007bff;
      color: white;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    `
    okButton.onclick = () => {
      document.body.removeChild(overlay)
      resolve(true)
    }

    // Assemble dialog
    buttonsContainer.appendChild(cancelButton)
    buttonsContainer.appendChild(okButton)
    dialog.appendChild(messageEl)
    dialog.appendChild(buttonsContainer)
    overlay.appendChild(dialog)
    document.body.appendChild(overlay)

    // Close on overlay click
    overlay.onclick = (e) => {
      if (e.target === overlay) {
        document.body.removeChild(overlay)
        resolve(false)
      }
    }
  })
}

