document.getElementById('analyzeBtn').addEventListener('click', async () => {
  const payloadText = document.getElementById('payload').value;
  let json;
  try {
    json = JSON.parse(payloadText);
  } catch (e) {
    document.getElementById('result').textContent = 'Invalid JSON: ' + e.message;
    return;
  }
  // Store payload for the analysis results page and navigate there
  try {
    sessionStorage.setItem('fplguru_payload', JSON.stringify(json));
    // go to analysis results page
    window.location.href = '/analyze/result/';
  } catch (err) {
    document.getElementById('result').textContent = 'Failed to navigate to analysis page: ' + err.message;
  }
});

// PDF parse flow
const pdfForm = document.getElementById('pdfForm');
pdfForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById('pdfFile');
  if (!fileInput.files || fileInput.files.length === 0) {
    document.getElementById('result').textContent = 'No PDF selected';
    return;
  }
  const file = fileInput.files[0];
  const formData = new FormData();
  // Use the canonical 'file' field name expected by /api/parse_pdf/
  const fileFieldName = 'file';
  formData.append(fileFieldName, file);
  document.getElementById('result').textContent = 'Parsing PDF...';
  try {
    // Force the JSON-producing parser endpoint for production/debugging
    const endpoint = '/api/parse_pdf/';
    const res = await fetch(endpoint, {
      method: 'POST',
      body: formData,
      // Let browser include cookies and CSRF cookie if present
      credentials: 'same-origin'
    });
    // Be robust: some endpoints (diagnostic /api/upload/) return HTML/text; avoid calling res.json() on non-JSON
    const contentType = (res.headers.get('content-type') || '').toLowerCase();
    let data;
    if (contentType.indexOf('application/json') !== -1) {
      data = await res.json();
    } else {
      const text = await res.text();
      // Surface the server response for debugging and abort further JSON-processing
      document.getElementById('result').textContent = 'Server returned non-JSON response: ' + text;
      return;
    }
    // Normalize parse response: support both legacy shape { flightplan: {...} } and
    // the newer minimal schema returned directly by the API.
    let flightplanObj = null;
    if (data) {
      if (data.flightplan && typeof data.flightplan === 'object') {
        flightplanObj = data.flightplan;
      } else if (typeof data === 'object') {
        // API returned minimal flightplan directly
        flightplanObj = data;
      }
    }
    if (flightplanObj) {
      document.getElementById('payload').value = JSON.stringify({flightplan: flightplanObj, observations: []}, null, 2);
    }
    // Populate raw extracted text area (prefer full raw_text, fallback to snippet)
    if (data) {
      const raw = data.raw_text || data.raw_text_snippet || data.extracted_text || data.raw_llm_response_text || null;
      document.getElementById('rawText').value = raw || '';
      // Also store parsed payload so operator can click Analyze immediately
      try {
        // Prepare payload wrapper
        const wrapper = { flightplan: flightplanObj || data || {}, observations: [] };
        // DEBUG: show stored payload preview in browser console
        try { console.log('STORED_FPL_PREVIEW', wrapper); } catch (e) {}
        // Directly set sessionStorage and navigate to analysis page (reliable and avoids form submission issues)
        try {
          sessionStorage.setItem('fplguru_payload', JSON.stringify(wrapper));
          // Visible confirmation on page for operators (not relying on console)
          try {
            const resultEl = document.getElementById('result');
            if (resultEl) resultEl.textContent = 'STORED_FPL_PREVIEW: ' + JSON.stringify(wrapper, null, 2);
          } catch (e) {}
          console.log('SESSION STORAGE SET, scheduling redirect to analysis page');
          // ensure storage is committed and then navigate; use replace to avoid back history noise
          setTimeout(() => {
            try {
              console.log('Performing redirect now');
              window.location.replace('/analyze/result/');
            } catch (e) {
              console.error('redirect failed', e);
              try {
                window.location.href = '/analyze/result/';
              } catch (e2) {
                console.error('href redirect failed', e2);
                const resultEl2 = document.getElementById('result');
                if (resultEl2) resultEl2.textContent = 'Redirect failed: ' + String(e2);
                // Create a visible fallback button for manual navigation
                try {
                  const btn = document.createElement('button');
                  btn.id = 'goToAnalysisBtn';
                  btn.textContent = 'Go to Analysis (click if not redirected)';
                  btn.className = 'btn btn-primary mt-2';
                  btn.addEventListener('click', () => { try { window.location.href = '/analyze/result/'; } catch (err) { console.error(err); } });
                  if (resultEl2) resultEl2.appendChild(document.createElement('br'));
                  if (resultEl2) resultEl2.appendChild(btn);
                  // hint about extensions
                  const hint = document.createElement('div');
                  hint.style.marginTop = '8px';
                  hint.style.fontSize = '0.9em';
                  hint.textContent = 'If redirect fails repeatedly, try disabling browser extensions or open the page in Incognito mode.';
                  if (resultEl2) resultEl2.appendChild(hint);
                } catch (e3) {
                  console.error('failed to create fallback button', e3);
                }
              }
            }
          }, 120);
        } catch (e) {
          console.error('sessionStorage set or redirect failed', e);
          const resultEl = document.getElementById('result');
          if (resultEl) resultEl.textContent = 'Failed to store payload: ' + String(e);
          // Fallback: attempt form submit as last resort
          try {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/api/submit_analysis/';
            form.target = '_self';
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'payload';
            input.value = JSON.stringify(wrapper);
            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
          } catch (e2) {
            console.error('fallback form submit also failed', e2);
          }
        }
      } catch (e) {}
    }
    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    document.getElementById('result').textContent = 'Error parsing PDF: ' + err.message;
  }
});

// Enhance analyze button behavior: disable unless an uploaded/parsed FPL is available
(function(){
  function updateAnalyzeEnabled(){
    const analyzeBtn = document.getElementById('analyzeBtn');
    if (!analyzeBtn) return;
    try {
      const hasStored = !!sessionStorage.getItem('fplguru_payload');
      const fileInput = document.getElementById('pdfFile');
      const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
      analyzeBtn.disabled = !(hasStored || hasFile);
    } catch (e) {
      // be conservative on error
      analyzeBtn.disabled = true;
    }
  }

  // initialize state on load
  updateAnalyzeEnabled();

  // toggle when file selected and auto-submit the parse form so PDF is parsed immediately
  const fileInput = document.getElementById('pdfFile');
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      updateAnalyzeEnabled();
      try {
        const form = document.getElementById('pdfForm');
        if (fileInput.files && fileInput.files.length > 0 && form) {
          // use requestSubmit when available (preserves form semantics), otherwise dispatch submit event
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.dispatchEvent(new Event('submit', { cancelable: true }));
          }
        }
      } catch (ex) {
        console.error('auto-submit failed', ex);
      }
    });
  }

  // prefer stored payload when Analyze clicked; fall back to payload textarea
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
        // store canonical location and navigate
        sessionStorage.setItem('fplguru_payload', JSON.stringify(json));
        window.location.href = '/analyze/result/';
      } catch (err) {
        if (resultEl) resultEl.textContent = 'Failed to navigate to analysis page: ' + (err && err.message ? err.message : String(err));
      }
    });
  }
})();
