async function callSectionAnalysis(section, payload, extra = {}) {
  // Ensure we always send the minimal flightplan schema under a consistent key so
  // server-side handlers and normalization logic receive the expected shape.
  // Allow extra metadata (part, focus) to be merged into the data object.
  const dataObj = Object.assign({ flightplan: payload }, extra);
  const body = { section: section, data: dataObj };
  try {
    // DEBUG: log payload being POSTed so the browser Network tab shows exact body
    try { console.log('POSTING_ANALYZE_SECTION', section, JSON.parse(JSON.stringify(body))); } catch (e) {}
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
  // Previously we sent only a small subset which could be empty.
  // Send the full flightplan object so the analyzer/LLM has all context
  // and can derive weather/notams even if nested or named differently.
  // The server-side analyzer accepts either the minimal flightplan dict
  // or a wrapper { flightplan: {...} } — we send the minimal object itself.
  if (!flightplan || typeof flightplan !== 'object') return {};
  return flightplan;
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

  // We'll drive multiple targeted analysis calls per the user's request.
  // Weather: analyze departure, destination, destination_alternate, and enroute alternates.
  // NOTAMs: analyze departure, destination, enroute alternates, company, and area.

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Render a leaf analysis object {risk_level, flags, details} into HTML and return overall risk
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

  // Orchestrate weather calls
  const weatherParts = [
    { part: 'departure', title: 'Departure Weather', focus: 'Analyze winds, visibility, QNH, cloud tops and convective risk for the departure airport and identify operational risks.' },
    { part: 'destination', title: 'Destination Weather', focus: 'Analyze winds, visibility, QNH, cloud tops and convective risk for the destination airport and identify operational risks.' },
    { part: 'destination_alternate', title: 'Destination Alternate Weather', focus: 'Analyze the destination alternate weather and any risks that would affect diversion.' },
    { part: 'enroute_alternates', title: 'Enroute Alternates / Enroute Weather', focus: 'Assess enroute weather risks including icing, turbulence, convective activity, low clouds, and wind shear for enroute alternates and enroute waypoints.' }
  ];

  // Populate each weather sub-panel individually (template contains dedicated panel elements)
  for (const wp of weatherParts) {
    const res = await callSectionAnalysis('weather', flightplan, { analyze_part: wp.part, focus: wp.focus });
    const panelId = 'panel-weather-' + wp.part;
    const badgeId = 'badge-weather-' + wp.part;
    const panelEl = document.getElementById(panelId);
    const badgeEl = document.getElementById(badgeId);
    let partHtml = '';
    let overallSeverity = 0;
    if (res && res.error) {
      partHtml = '<div>Error: ' + escapeHtml(res.error) + '</div>';
    } else if (res && res.by_part) {
      const partVal = res.by_part[wp.part] || res.by_part[wp.part.replace('_alternates','')];
      if (partVal && typeof partVal === 'object' && Object.keys(partVal).length && !partVal.risk_level) {
        for (const [icao, a] of Object.entries(partVal)) {
          const rendered = renderLeafAnalysis(a || {});
          overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
          partHtml += '<div class="ms-3"><h6>' + escapeHtml(icao) + '</h6>' + rendered.html + '</div>';
        }
      } else {
        const rendered = renderLeafAnalysis(partVal || {});
        overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
        partHtml += rendered.html;
      }
      if (res.raw_llm_response_text) partHtml += '<div class="mt-2"><details><summary>Raw assistant output</summary><pre style="white-space:pre-wrap;">' + escapeHtml(res.raw_llm_response_text) + '</pre></details></div>';
    } else {
      partHtml = '<div>No observations.</div>';
    }
    if (panelEl) panelEl.innerHTML = '<h5>' + escapeHtml(wp.title) + '</h5>' + partHtml;
    // Apply badge and panel color based on severity
    const overallRisk = overallSeverity === 3 ? 'high' : (overallSeverity === 2 ? 'moderate' : (overallSeverity === 1 ? 'low' : null));
    if (badgeEl) badgeEl.className = 'risk-badge ' + (overallRisk ? (overallRisk === 'low' ? 'low' : (overallRisk === 'moderate' ? 'moderate' : 'high')) : 'unknown');
    if (panelEl) {
      const panelBody = panelEl.closest('.panel-risk-border');
      if (panelBody) {
        panelBody.classList.remove('risk-low','risk-moderate','risk-high','risk-unknown');
        panelBody.classList.add(overallRisk ? (overallRisk === 'low' ? 'risk-low' : (overallRisk === 'moderate' ? 'risk-moderate' : 'risk-high')) : 'risk-unknown');
      }
    }
  }

  // Orchestrate NOTAM calls
  const notamParts = [
    { part: 'departure', title: 'Departure NOTAMs', focus: 'Emphasize runway closures, navaid degradation, runway shortening and any NOTAM that impacts takeoff.' },
    { part: 'destination', title: 'Destination NOTAMs', focus: 'Emphasize runway closures, navaid degradation, runway shortening and any NOTAM that impacts landing.' },
    { part: 'enroute_alternates', title: 'Enroute NOTAMs', focus: 'Emphasize navaid degradation, runway closures at alternates and enroute aerodromes, and any hazards affecting diversion.' },
    { part: 'company', title: 'Company NOTAMs', focus: 'Highlight company-level operational NOTAMs or company procedures that affect this flight.' },
    { part: 'area', title: 'Area NOTAMs', focus: 'Emphasize airspace closures, GPS/jamming, and other area-level risks.' }
  ];

  // Populate each NOTAM sub-panel individually
  for (const np of notamParts) {
    const res = await callSectionAnalysis('notams', flightplan, { analyze_part: np.part, focus: np.focus });
    const panelId = 'panel-notams-' + np.part;
    const badgeId = 'badge-notams-' + np.part;
    const panelEl = document.getElementById(panelId);
    const badgeEl = document.getElementById(badgeId);
    let partHtml = '';
    let overallSeverity = 0;
    if (res && res.error) {
      partHtml = '<div>Error: ' + escapeHtml(res.error) + '</div>';
    } else if (res && res.by_part) {
      const partVal = res.by_part[np.part] || {};
      if (partVal && typeof partVal === 'object' && !partVal.risk_level && Object.keys(partVal).length) {
        for (const [k, a] of Object.entries(partVal)) {
          const rendered = renderLeafAnalysis(a || {});
          overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
          partHtml += '<div class="ms-3"><h6>' + escapeHtml(k) + '</h6>' + rendered.html + '</div>';
        }
      } else {
        const rendered = renderLeafAnalysis(partVal || {});
        overallSeverity = Math.max(overallSeverity, severityValue(rendered.risk));
        partHtml += rendered.html;
      }
      if (res.raw_llm_response_text) partHtml += '<div class="mt-2"><details><summary>Raw assistant output</summary><pre style="white-space:pre-wrap;">' + escapeHtml(res.raw_llm_response_text) + '</pre></details></div>';
    } else {
      partHtml = '<div>No observations.</div>';
    }
    if (panelEl) panelEl.innerHTML = '<h5>' + escapeHtml(np.title) + '</h5>' + partHtml;
    const overallRisk = overallSeverity === 3 ? 'high' : (overallSeverity === 2 ? 'moderate' : (overallSeverity === 1 ? 'low' : null));
    if (badgeEl) badgeEl.className = 'risk-badge ' + (overallRisk ? (overallRisk === 'low' ? 'low' : (overallRisk === 'moderate' ? 'moderate' : 'high')) : 'unknown');
    if (panelEl) {
      const panelBody = panelEl.closest('.panel-risk-border');
      if (panelBody) {
        panelBody.classList.remove('risk-low','risk-moderate','risk-high','risk-unknown');
        panelBody.classList.add(overallRisk ? (overallRisk === 'low' ? 'risk-low' : (overallRisk === 'moderate' ? 'risk-moderate' : 'risk-high')) : 'risk-unknown');
      }
    }
  }

 });
