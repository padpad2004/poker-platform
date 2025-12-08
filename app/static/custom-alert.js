(function () {
  const style = document.createElement('style');
  style.textContent = `
    .custom-alert-overlay {
      position: fixed;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(7, 11, 23, 0.65);
      backdrop-filter: blur(4px);
      z-index: 9999;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
    }

    .custom-alert-overlay.visible {
      opacity: 1;
      pointer-events: auto;
    }

    .custom-alert {
      width: min(440px, calc(100% - 32px));
      background: #0b1224;
      border: 1px solid #25304b;
      border-radius: 16px;
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
      color: #e5e7eb;
      padding: 20px 22px 18px;
      transform: translateY(10px);
      opacity: 0;
      transition: transform 0.2s ease, opacity 0.2s ease;
      position: relative;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .custom-alert-overlay.visible .custom-alert {
      transform: translateY(0);
      opacity: 1;
    }

    .custom-alert-title {
      margin: 0 0 8px;
      font-size: 16px;
      font-weight: 700;
      color: #f8fafc;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .custom-alert-title::before {
      content: "!";
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 999px;
      background: linear-gradient(135deg, #ef4444, #f97316);
      color: white;
      font-weight: 800;
      font-size: 14px;
      box-shadow: 0 8px 20px rgba(239, 68, 68, 0.35);
    }

    .custom-alert-message {
      margin: 0 0 14px;
      font-size: 14px;
      line-height: 1.6;
      color: #cbd5e1;
      white-space: pre-wrap;
    }

    .custom-alert-actions {
      display: flex;
      justify-content: flex-end;
    }

    .custom-alert-button {
      appearance: none;
      border: none;
      border-radius: 999px;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: white;
      box-shadow: 0 10px 30px rgba(37, 99, 235, 0.35);
      transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.2s ease;
    }

    .custom-alert-button:hover {
      filter: brightness(1.05);
      box-shadow: 0 12px 32px rgba(37, 99, 235, 0.45);
    }

    .custom-alert-button:active {
      transform: translateY(1px);
      box-shadow: 0 8px 24px rgba(37, 99, 235, 0.35);
    }

    .custom-confirm-overlay {
      position: fixed;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(7, 11, 23, 0.7);
      backdrop-filter: blur(6px);
      z-index: 9999;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
    }

    .custom-confirm-overlay.visible {
      opacity: 1;
      pointer-events: auto;
    }

    .custom-confirm {
      width: min(460px, calc(100% - 32px));
      background: #0b1224;
      border: 1px solid #25304b;
      border-radius: 16px;
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
      color: #e5e7eb;
      padding: 20px 22px 18px;
      transform: translateY(10px);
      opacity: 0;
      transition: transform 0.2s ease, opacity 0.2s ease;
      position: relative;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .custom-confirm-overlay.visible .custom-confirm {
      transform: translateY(0);
      opacity: 1;
    }

    .custom-confirm-title {
      margin: 0 0 8px;
      font-size: 17px;
      font-weight: 800;
      color: #f8fafc;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .custom-confirm-title::before {
      content: "!";
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      border-radius: 999px;
      background: linear-gradient(135deg, #ef4444, #f97316);
      color: white;
      font-weight: 800;
      font-size: 15px;
      box-shadow: 0 8px 20px rgba(239, 68, 68, 0.35);
    }

    .custom-confirm-message {
      margin: 0 0 16px;
      font-size: 14px;
      line-height: 1.6;
      color: #cbd5e1;
      white-space: pre-wrap;
    }

    .custom-confirm-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }

    .custom-confirm-button {
      appearance: none;
      border: none;
      border-radius: 10px;
      padding: 10px 16px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      color: white;
      transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.2s ease;
    }

    .custom-confirm-button.cancel {
      background: #1f2937;
      color: #e5e7eb;
      border: 1px solid #25304b;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }

    .custom-confirm-button.confirm {
      background: linear-gradient(135deg, #dc2626, #b91c1c);
      box-shadow: 0 12px 32px rgba(220, 38, 38, 0.45);
    }

    .custom-confirm-button:hover {
      filter: brightness(1.05);
      transform: translateY(-1px);
    }

    .custom-confirm-button:active {
      transform: translateY(1px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }
  `;

  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.className = 'custom-alert-overlay';
  overlay.setAttribute('role', 'presentation');
  overlay.innerHTML = `
    <div class="custom-alert" role="dialog" aria-modal="true" aria-live="assertive">
      <h3 class="custom-alert-title">Heads up</h3>
      <p class="custom-alert-message"></p>
      <div class="custom-alert-actions">
        <button class="custom-alert-button" type="button">OK</button>
      </div>
    </div>
  `;

  const messageEl = overlay.querySelector('.custom-alert-message');
  const confirmBtn = overlay.querySelector('.custom-alert-button');

  function closeAlert() {
    overlay.classList.remove('visible');
    overlay.setAttribute('aria-hidden', 'true');
  }

  function openAlert(message) {
    messageEl.textContent = message;
    overlay.classList.add('visible');
    overlay.setAttribute('aria-hidden', 'false');
    confirmBtn.focus();
  }

  confirmBtn.addEventListener('click', closeAlert);
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) {
      closeAlert();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && overlay.classList.contains('visible')) {
      closeAlert();
    }
  });

  document.body.appendChild(overlay);

  const customAlert = (message) => {
    openAlert(String(message ?? ''));
  };

  window.showCustomAlert = customAlert;
  window.alert = customAlert;

  // Confirm dialog
  const confirmOverlay = document.createElement('div');
  confirmOverlay.className = 'custom-confirm-overlay';
  confirmOverlay.setAttribute('role', 'presentation');
  confirmOverlay.innerHTML = `
    <div class="custom-confirm" role="dialog" aria-modal="true" aria-live="assertive">
      <h3 class="custom-confirm-title">Are you sure?</h3>
      <p class="custom-confirm-message"></p>
      <div class="custom-confirm-actions">
        <button class="custom-confirm-button cancel" type="button">Cancel</button>
        <button class="custom-confirm-button confirm" type="button">Confirm</button>
      </div>
    </div>
  `;

  const confirmTitleEl = confirmOverlay.querySelector('.custom-confirm-title');
  const confirmMessageEl = confirmOverlay.querySelector('.custom-confirm-message');
  const confirmCancelBtn = confirmOverlay.querySelector('.custom-confirm-button.cancel');
  const confirmConfirmBtn = confirmOverlay.querySelector('.custom-confirm-button.confirm');
  let confirmResolver = null;

  function closeConfirm(result) {
    confirmOverlay.classList.remove('visible');
    confirmOverlay.setAttribute('aria-hidden', 'true');
    if (confirmResolver) {
      confirmResolver(result);
      confirmResolver = null;
    }
  }

  function showCustomConfirm({
    title = 'Are you sure?',
    message = '',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
  } = {}) {
    confirmTitleEl.textContent = title;
    confirmMessageEl.textContent = message;
    confirmConfirmBtn.textContent = confirmText;
    confirmCancelBtn.textContent = cancelText;

    confirmOverlay.classList.add('visible');
    confirmOverlay.setAttribute('aria-hidden', 'false');
    confirmCancelBtn.focus();

    return new Promise((resolve) => {
      confirmResolver = resolve;
    });
  }

  confirmCancelBtn.addEventListener('click', () => closeConfirm(false));
  confirmConfirmBtn.addEventListener('click', () => closeConfirm(true));
  confirmOverlay.addEventListener('click', (event) => {
    if (event.target === confirmOverlay) {
      closeConfirm(false);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && confirmOverlay.classList.contains('visible')) {
      closeConfirm(false);
    }
  });

  document.body.appendChild(confirmOverlay);
  window.showCustomConfirm = showCustomConfirm;
})();
