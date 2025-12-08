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
})();
