async function callSectionAnalysis(section, payload) {
  // Payload is the full flightplan JSON; we send only relevant subset to the API
  const body = { section: section, data: payload };
  try {
    const res = await fetch('/api/analyze_section/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

function findSubsetForSection(section, flightplan) {
  // Conservative subsets tailored to the new minimal schema
  switch (section) {
    case 'weather':
      return { weather: flightplan.weather || {} };
    case 'notams':
      return { notams: flightplan.notams || {} };
    default:
      return {};
  }
}

function riskToClass(risk) {
  if (!risk) return 'risk-unknown';
  const r = String(risk).toLowerCase();
  if (r === 'low') return 'risk-low';
  if (r === 'moderate' || r === 'medium' || r === 'amber') return 'risk-moderate';
  if (r === 'high' || r === 'red') return 'risk-high';
  return 'risk-unknown';
}

function riskToBadgeClass(risk) {
  if (!risk) return 'unknown';
  const r = String(risk).toLowerCase();
  if (r === 'low') return 'low';
  if (r === 'moderate' || r === 'medium' || r === 'amber') return 'moderate';
  if (r === 'high' || r === 'red') return 'high';
  return 'unknown';
}

window.addEventListener('DOMContentLoaded', async () => {
  const backBtn = document.getElementById('backBtn');
  backBtn.addEventListener('click', () => { window.history.back(); });

  const payloadRaw = sessionStorage.getItem('fplguru_payload');
  if (!payloadRaw) {
    const weightsEl = document.getElementById('weightsResult');
    if (weightsEl) weightsEl.textContent = 'No payload found. Please go back and provide a payload.';
    return;
  }
  const payload = JSON.parse(payloadRaw);
  const flightplan = payload.flightplan || payload;

  // Hide sections that are no longer analyzed (weights, fuel, area_notams)
  ['headingWeights','headingFuel','headingAreaNotams','collapseWeights','collapseFuel','collapseAreaNotams'].forEach(id => {
    const el = document.getElementById(id);
    if (el && el.closest('.accordion-item')) {
      el.closest('.accordion-item').style.display = 'none';
    }
  });

  // Only analyze weather and notams as per minimal schema
  const sections = ['weather','notams'];
  const sectionToElement = {
    weather: 'weatherResult',
    notams: 'notamsResult'
  };
  const sectionToBadge = {
    weather: 'badge-weather',
    notams: 'badge-notams'
  };

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderLeafAnalysis(a) {
    const risk = a && a.risk_level ? a.risk_level : 'unknown';
    const details = a && a.details ? a.details : null;
    const flags = a && Array.isArray(a.flags) ? a.flags : [];
    let html = '';
    html += '<div><strong>Risk:</strong> ' + escapeHtml(risk) + '</div>';
    if (details) html += '<div class="mt-2"><strong>Details:</strong><div>' + escapeHtml(details) + '</div></div>';
    if (flags && flags.length) html += '<div class="mt-2"><strong>Flags:</strong><ul>' + flags.map(f => '<li>' + escapeHtml(f) + '</li>').join('') + '</ul></div>';
    return { html, risk };
  }

  function severityValue(risk) {
    if (!risk) return 0;
    const r = String(risk).toLowerCase();
    if (r === 'low') return 1;
    if (r === 'moderate' || r === 'medium' || r === 'amber') return 2;
    if (r === 'high' || r === 'red') return 3;
    return 0;
  }

  const promises = sections.map(async (s) => {
    const subset = findSubsetForSection(s, flightplan);
    const result = await callSectionAnalysis(s, subset);
    const el = document.getElementById(sectionToElement[s]);

    if (result && result.error) {
      if (el) el.innerText = 'Error: ' + result.error;
      return result;
    }

    // If the LLM/analyzer returned by_part (multi-part), render each part
    if (result && result.by_part && typeof result.by_part === 'object') {
      let html = '';
      let overallSeverity = 0;
      for (const [partKey, partVal] of Object.entries(result.by_part)) {
        html += '<div class="mb-3"><h5>' + escapeHtml(partKey) + '</h5>';
        // If partVal is a mapping of ICAO -> analysis
        if (partVal && typeof partVal === 'object' && !partVal.risk_level && Object.keys(partVal).length && Object.keys(partVal).every(k => /^[A-Z]{4}$/.test(k) || k === 'GENERIC')) {
          // iterate ICAOs
          for (const [icao, a] of Object.entries(partVal)) {
            const rendered = renderLeafAnalysis(a || {});
            overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
            html += '<div class="ms-3"><h6>' + escapeHtml(icao) + '</h6>' + rendered.html + '</div>';
          }
        } else {
          // single leaf for this part
          const rendered = renderLeafAnalysis(partVal || {});
          overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
          html += rendered.html;
        }
        html += '</div>';
      }
      // Add raw assistant output if provided
      if (result.raw_llm_response_text) {
        html += '<div class="mt-2"><details><summary>Raw assistant output</summary><pre style="white-space:pre-wrap;">' + escapeHtml(result.raw_llm_response_text) + '</pre></details></div>';
      }
      if (el) el.innerHTML = html || 'No observations.';

      // apply overall color classes and badge
      const overallRisk = overallSeverity === 3 ? 'high' : (overallSeverity === 2 ? 'moderate' : (overallSeverity === 1 ? 'low' : null));
      const badgeEl = document.getElementById(sectionToBadge[s]);
      const panelBody = el ? el.closest('.panel-risk-border') : null;
      const cls = riskToClass(overallRisk);
      if (panelBody) {
        panelBody.classList.remove('risk-low','risk-moderate','risk-high','risk-unknown');
        panelBody.classList.add(cls);
      }
      if (badgeEl) badgeEl.className = 'risk-badge ' + riskToBadgeClass(overallRisk);

      return result;
    }

    // Legacy single-section response handling
    const risk = (result && result.risk_level) ? result.risk_level : null;
    const details = (result && result.details) ? result.details : null;
    const flags = (result && Array.isArray(result.flags)) ? result.flags : [];
    const raw = (result && result.raw_llm_response_text) ? result.raw_llm_response_text : null;

    let html = '';
    html += '<div><strong>Risk:</strong> ' + escapeHtml(risk || 'unknown') + '</div>';
    if (details) html += '<div class="mt-2"><strong>Details:</strong><div>' + escapeHtml(details) + '</div></div>';
    if (flags && flags.length) html += '<div class="mt-2"><strong>Flags:</strong><ul>' + flags.map(f => '<li>' + escapeHtml(f) + '</li>').join('') + '</ul></div>';
    if (raw) html += '<div class="mt-2"><details><summary>Raw assistant output</summary><pre style="white-space:pre-wrap;">' + escapeHtml(raw) + '</pre></details></div>';
    if (!details && (!flags || flags.length === 0) && !raw) html += '<div>No observations.</div>';

    if (el) el.innerHTML = html;

    const badgeEl = document.getElementById(sectionToBadge[s]);
    const panelBody = el ? el.closest('.panel-risk-border') : null;
    const cls = riskToClass(risk);
    if (panelBody) {
      panelBody.classList.remove('risk-low','risk-moderate','risk-high','risk-unknown');
      panelBody.classList.add(cls);
    }
    if (badgeEl) badgeEl.className = 'risk-badge ' + riskToBadgeClass(risk);

    return result;
  });

  await Promise.all(promises);
});
