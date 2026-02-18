// analyze.js - handlers for PDF upload, parse, and navigation to analysis (Telegram removed)

// PDF parse flow
const pdfForm = document.getElementById('pdfForm');
if (pdfForm) {
  pdfForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('pdfFile');
    const resElMain = document.getElementById('result');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      if (resElMain) resElMain.textContent = 'No PDF selected';
      return;
    }
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);
    if (resElMain) resElMain.textContent = 'Parsing PDF...';

    try {
      const res = await fetch('/api/parse_pdf/', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin'
      });

      const contentType = (res.headers.get('content-type') || '').toLowerCase();
      let data = null;
      if (contentType.indexOf('application/json') !== -1) {
        data = await res.json();
      } else {
        const text = await res.text();
        if (resElMain) resElMain.textContent = 'Server returned non-JSON response: ' + text;
        return;
      }

      // Normalize parse response
      let flightplanObj = null;
      if (data) {
        if (data.flightplan && typeof data.flightplan === 'object') flightplanObj = data.flightplan;
        else if (typeof data === 'object') flightplanObj = data;
      }

      try {
        const payloadEl = document.getElementById('payload');
        if (payloadEl) payloadEl.value = JSON.stringify({flightplan: flightplanObj || {}, observations: []}, null, 2);
      } catch (e) { console.error('payload set error', e); }

      try {
        const raw = (data && (data.raw_text || data.raw_text_snippet || data.extracted_text || data.raw_llm_response_text)) || '';
        const rawEl = document.getElementById('rawText');
        if (rawEl) rawEl.value = raw || '';
      } catch (e) { console.error('raw text set error', e); }

      try {
        const wrapper = { flightplan: flightplanObj || data || {}, observations: [] };
        try { sessionStorage.setItem('fplguru_payload', JSON.stringify(wrapper)); } catch (e) { console.error('sessionStorage error', e); }
        try { const analyzeBtnEl = document.getElementById('analyzeBtn'); if (analyzeBtnEl) analyzeBtnEl.disabled = false; } catch (e) {}
        if (resElMain) {
          try { resElMain.textContent = 'STORED_FPL_PREVIEW: ' + JSON.stringify(wrapper, null, 2); } catch (e) { resElMain.textContent = 'Parsed OK'; }
        }

        setTimeout(() => {
          try { window.location.replace('/analyze/result/'); }
          catch (e) {
            try { window.location.href = '/analyze/result/'; }
            catch (e2) {
              if (resElMain) resElMain.textContent = 'Redirect failed: ' + String(e2);
              try {
                const btn = document.createElement('button');
                btn.id = 'goToAnalysisBtn';
                btn.textContent = 'Go to Analysis (click if not redirected)';
                btn.className = 'btn primary';
                btn.addEventListener('click', () => { try { window.location.href = '/analyze/result/'; } catch (err) { console.error(err); } });
                if (resElMain) {
                  resElMain.appendChild(document.createElement('br'));
                  resElMain.appendChild(btn);
                  const hint = document.createElement('div');
                  hint.style.marginTop = '8px';
                  hint.style.fontSize = '0.9em';
                  hint.textContent = 'If redirect fails repeatedly, try disabling browser extensions or open the page in Incognito mode.';
                  resElMain.appendChild(hint);
                }
              } catch (e3) { console.error('failed to create fallback UI', e3); }
            }
          }
        }, 120);
      } catch (e) { console.error('store/redirect error', e); }

      if (resElMain) resElMain.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      if (resElMain) resElMain.textContent = 'Error parsing PDF: ' + (err && err.message ? err.message : String(err));
    }
  });
}

// update analyze enabled state (no Telegram requirement)
function updateAnalyzeEnabled(){
  const analyzeBtn = document.getElementById('analyzeBtn');
  if (!analyzeBtn) return;
  try {
    const hasStored = !!sessionStorage.getItem('fplguru_payload');
    const fileInput = document.getElementById('pdfFile');
    const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
    analyzeBtn.disabled = !(hasStored || hasFile);
  } catch (e) {
    analyzeBtn.disabled = true;
  }
}

// Initialization and handlers
(function(){
  updateAnalyzeEnabled();

  const fileInput = document.getElementById('pdfFile');
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      updateAnalyzeEnabled();
      try {
        const form = document.getElementById('pdfForm');
        if (fileInput.files && fileInput.files.length > 0) {
          if (form) {
            if (typeof form.requestSubmit === 'function') form.requestSubmit();
            else form.dispatchEvent(new Event('submit', { cancelable: true }));
          }
        }
      } catch (ex) { console.error('auto-submit failed', ex); }
    });
  }

  const existingAnalyze = document.getElementById('analyzeBtn');
  if (existingAnalyze) {
    existingAnalyze.addEventListener('click', async (ev) => {
      ev.preventDefault();
      const resultEl = document.getElementById('result');
      try {
        const stored = sessionStorage.getItem('fplguru_payload');
        let json = null;
        if (stored) {
          try { json = JSON.parse(stored); } catch (e) { if (resultEl) resultEl.textContent = 'Stored payload corrupted: ' + e.message; return; }
        } else {
          const payloadText = document.getElementById('payload').value;
          try { json = JSON.parse(payloadText); } catch (e) { if (resultEl) resultEl.textContent = 'Invalid JSON: ' + e.message; return; }
        }
        try { sessionStorage.setItem('fplguru_payload', JSON.stringify(json)); } catch (e) {}
        window.location.href = '/analyze/result/';
      } catch (err) {
        if (resultEl) resultEl.textContent = 'Failed to navigate to analysis page: ' + (err && err.message ? err.message : String(err));
      }
    });
  }
})();
