// analyze.js - centralized handlers (legacy top-level analyze handler removed)

// PDF parse flow
const pdfForm = document.getElementById('pdfForm');
pdfForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById('pdfFile');
  if (!fileInput.files || fileInput.files.length === 0) {
    const resEl = document.getElementById('result');
    if (resEl) resEl.textContent = 'No PDF selected';
    return;
  }
  const file = fileInput.files[0];
  const formData = new FormData();
  // Use the canonical 'file' field name expected by /api/parse_pdf/
  const fileFieldName = 'file';
  formData.append(fileFieldName, file);
  const resElMain = document.getElementById('result');
  if (resElMain) resElMain.textContent = 'Parsing PDF...';
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
      if (resElMain) resElMain.textContent = 'Server returned non-JSON response: ' + text;
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
      const payloadEl = document.getElementById('payload');
      if (payloadEl) payloadEl.value = JSON.stringify({flightplan: flightplanObj, observations: []}, null, 2);
    }
    // Populate raw extracted text area (prefer full raw_text, fallback to snippet)
    if (data) {
      const raw = data.raw_text || data.raw_text_snippet || data.extracted_text || data.raw_llm_response_text || null;
      const rawEl = document.getElementById('rawText');
      if (rawEl) rawEl.value = raw || '';
      // Also store parsed payload so operator can click Analyze immediately
      try {
        // Prepare payload wrapper
        const wrapper = { flightplan: flightplanObj || data || {}, observations: [] };
        // DEBUG: show stored payload preview in browser console
        try { console.log('STORED_FPL_PREVIEW', wrapper); } catch (e) {}
        // Directly set sessionStorage and navigate to analysis page (reliable and avoids form submission issues)
        try {
          sessionStorage.setItem('fplguru_payload', JSON.stringify(wrapper));
          // Ensure Analyze button is enabled (useful when redirect is blocked)
          try {
            const analyzeBtnEl = document.getElementById('analyzeBtn');
            if (analyzeBtnEl) analyzeBtnEl.disabled = false;
          } catch (e) { /* ignore */ }
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
    if (resElMain) resElMain.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    if (resElMain) resElMain.textContent = 'Error parsing PDF: ' + err.message;
  }
});

// Fetch Telegram login status and update UI
async function refreshTelegramStatus(){
  try{
    const res = await fetch('/api/telegram_status/', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('not ok');
    const data = await res.json();
    const statusEl = document.getElementById('tgStatus');
    const remainingEl = document.getElementById('tgRemaining');
    if (data.logged_in){
      if (statusEl) statusEl.textContent = `Signed in as ${data.telegram_username || 'Telegram user'}. Remaining quota: ${data.remaining_quota}`;
      if (remainingEl) remainingEl.textContent = String(data.remaining_quota);
      // do not disable file input; only mark logged-in state
      document.body.dataset.tgLoggedIn = '1';
    } else {
      if (statusEl) statusEl.textContent = 'Sign in with Telegram to parse flight plans. Remaining quota: -';
      if (remainingEl) remainingEl.textContent = '-';
      document.body.dataset.tgLoggedIn = '0';
    }
    // update analyze enabled state
    try{ updateAnalyzeEnabled(); } catch(e){}
  } catch (e){
    console.warn('tg status fetch failed', e);
  }
}

// call refresh on load
refreshTelegramStatus();

// modify updateAnalyzeEnabled to require telegram login
function updateAnalyzeEnabled(){
  const analyzeBtn = document.getElementById('analyzeBtn');
  if (!analyzeBtn) return;
  try {
    const isLoggedIn = document.body.dataset.tgLoggedIn === '1';
    const hasStored = !!sessionStorage.getItem('fplguru_payload');
    const fileInput = document.getElementById('pdfFile');
    const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
    analyzeBtn.disabled = !(isLoggedIn && (hasStored || hasFile));
  } catch (e) {
    analyzeBtn.disabled = true;
  }
}

// Enhance analyze button behavior: disable unless an uploaded/parsed FPL is available
(function(){
  // initialize state on load
  updateAnalyzeEnabled();

  // toggle when file selected and auto-submit the parse form so PDF is parsed immediately
  const fileInput = document.getElementById('pdfFile');
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      // always update analyze enabled state (login may have changed previously)
      updateAnalyzeEnabled();
      try {
        const isLoggedIn = document.body.dataset.tgLoggedIn === '1';
        const form = document.getElementById('pdfForm');
        if (fileInput.files && fileInput.files.length > 0) {
          if (!isLoggedIn) {
            const resEl = document.getElementById('result');
            if (resEl) resEl.textContent = 'Please sign in with Telegram (use the widget below) before parsing. Click the Telegram login button to sign in.';
            // ensure analyze remains disabled
            try { const analyzeBtn = document.getElementById('analyzeBtn'); if (analyzeBtn) analyzeBtn.disabled = true; } catch(e){}
            return;
          }
          if (form) {
            // use requestSubmit when available (preserves form semantics), otherwise dispatch submit event
            if (typeof form.requestSubmit === 'function') {
              form.requestSubmit();
            } else {
              form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
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

// signup modal wiring
(function(){
  const signInBtn = document.getElementById('signInBtn');
  const modal = document.getElementById('signupModal');
  const closeBtn = document.getElementById('signupClose');
  const deep = document.getElementById('tgDeepLink');
  if (signInBtn && modal){
    signInBtn.addEventListener('click', () => { modal.style.display = 'flex'; });
    if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (deep) deep.addEventListener('click', () => { /* opens external link */ });
  }

  // If the Telegram widget fails with a username invalid error, provide clearer instructions in the modal
  window.addEventListener('message', (ev) => {
    try {
      if (!ev.data) return;
      if (typeof ev.data !== 'string') return;
      if (ev.data.indexOf('username invalid') !== -1) {
        if (modal) modal.style.display = 'flex';
      }
    } catch (e) {}
  });
})();
