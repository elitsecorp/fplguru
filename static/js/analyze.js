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
  formData.append('file', file);
  document.getElementById('result').textContent = 'Parsing PDF...';
  try {
    const res = await fetch('/api/parse_pdf/', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    // Populate payload textarea with parsed flightplan so operator can review before analyze
    if (data && data.flightplan) {
      document.getElementById('payload').value = JSON.stringify({flightplan: data.flightplan, observations: []}, null, 2);
    }
    // Populate raw extracted text area (prefer full raw_text, fallback to snippet)
    if (data) {
      const raw = data.raw_text || data.raw_text_snippet || data.extracted_text || data.raw_llm_response_text || null;
      document.getElementById('rawText').value = raw || '';
      // Also store parsed payload so operator can click Analyze immediately
      try { sessionStorage.setItem('fplguru_payload', JSON.stringify({flightplan: data.flightplan, observations: []})); } catch (e) {}
    }
    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    document.getElementById('result').textContent = 'Error parsing PDF: ' + err.message;
  }
});
