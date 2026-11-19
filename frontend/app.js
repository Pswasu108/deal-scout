// Deal Scanner Frontend App Logic
(function () {
  'use strict';

  // State
  let allDeals = [];
  let ignoredDeals = [];
  let isIgnoredView = false;
  let currentConfig = null;
  let isRunning = false;
  let pollInterval = null;
  let countdownTimer = null;
  let nextRunSeconds = null;
  let feedbackMap = {};

  // DOM Elements
  const tabDeals = document.getElementById('tab-deals');
  const tabTrackers = document.getElementById('tab-trackers');
  const tabConfig = document.getElementById('tab-config');
  const tabScheduler = document.getElementById('tab-scheduler');
  const tabConsole = document.getElementById('tab-console');

  const tabAgent = document.getElementById('tab-agent');
  const panelAgent = document.getElementById('panel-agent');

  const panelDeals = document.getElementById('panel-deals');
  const panelTrackers = document.getElementById('panel-trackers');
  const panelConfig = document.getElementById('panel-config');
  const panelScheduler = document.getElementById('panel-scheduler');
  const panelConsole = document.getElementById('panel-console');
  const verdictFilter = document.getElementById('verdictFilter');
  const tabTrackersBadge = document.getElementById('tabTrackersBadge');

  const dealsContainer = document.getElementById('dealsContainer');
  const dealsEmptyState = document.getElementById('dealsEmptyState');
  const dealSearchInput = document.getElementById('dealSearchInput');
  const clearSearchBtn = document.getElementById('clearSearchBtn');
  const sourceFilter = document.getElementById('sourceFilter');
  const genderFilter = document.getElementById('genderFilter');
  const sortFilter = document.getElementById('sortFilter');
  const btnClearDeals = document.getElementById('btnClearDeals');

  const btnToggleIgnored = document.getElementById('btnToggleIgnored');
  const btnToggleIgnoredIcon = document.getElementById('btnToggleIgnoredIcon');
  const btnToggleIgnoredText = document.getElementById('btnToggleIgnoredText');
  const ignoredBadge = document.getElementById('ignoredBadge');
  const statIgnoredCount = document.getElementById('statIgnoredCount');
  const ignoredModeBanner = document.getElementById('ignoredModeBanner');
  const btnExitIgnored = document.getElementById('btnExitIgnored');
  const btnClearIgnored = document.getElementById('btnClearIgnored');

  const statDealsCount = document.getElementById('statDealsCount');
  const statBestDiscount = document.getElementById('statBestDiscount');
  const tabDealsBadge = document.getElementById('tabDealsBadge');

  const btnHeaderRun = document.getElementById('btnHeaderRun');
  const btnHeaderAbort = document.getElementById('btnHeaderAbort');
  const abortSpinner = document.getElementById('abortSpinner');
  const abortIcon = document.getElementById('abortIcon');
  const abortButtonText = document.getElementById('abortButtonText');
  const btnTriggerTerminalAbort = document.getElementById('btnTriggerTerminalAbort');
  const headerDryRun = document.getElementById('headerDryRun');
  const runButtonText = document.getElementById('runButtonText');
  const consoleLivePulse = document.getElementById('consoleLivePulse');
  const schedTabIndicator = document.getElementById('schedTabIndicator');

  // Config DOM
  const btnModeForm = document.getElementById('btnModeForm');
  const btnModeJson = document.getElementById('btnModeJson');
  const configFormView = document.getElementById('configFormView');
  const configJsonView = document.getElementById('configJsonView');
  const btnSaveConfig = document.getElementById('btnSaveConfig');
  const btnReloadConfig = document.getElementById('btnReloadConfig');
  const btnFormatJson = document.getElementById('btnFormatJson');
  const rawJsonEditor = document.getElementById('rawJsonEditor');
  const jsonValidationStatus = document.getElementById('jsonValidationStatus');
  const queriesListContainer = document.getElementById('queriesListContainer');
  const btnAddQuery = document.getElementById('btnAddQuery');

  // Scheduler DOM
  const schedEnableToggle = document.getElementById('schedEnableToggle');
  const schedToggleLabel = document.getElementById('schedToggleLabel');
  const schedIntervalInput = document.getElementById('schedIntervalInput');
  const btnSaveSchedule = document.getElementById('btnSaveSchedule');
  const schedStateVal = document.getElementById('schedStateVal');
  const schedCountdownVal = document.getElementById('schedCountdownVal');
  const schedLastRunVal = document.getElementById('schedLastRunVal');
  const schedDot = document.getElementById('schedDot');
  const schedStatusText = document.getElementById('schedStatusText');
  const schedCountdownText = document.getElementById('schedCountdownText');

  // Console DOM
  const terminalWindow = document.getElementById('terminalWindow');
  const chkAutoScroll = document.getElementById('chkAutoScroll');
  const btnClearTerminal = document.getElementById('btnClearTerminal');
  const btnTriggerTerminalRun = document.getElementById('btnTriggerTerminalRun');

  // ── Tab Management ─────────────────────────────────────────────────────────
  const tabs = [
    { btn: tabDeals, panel: panelDeals },
    { btn: tabTrackers, panel: panelTrackers },
    { btn: tabAgent, panel: panelAgent },
    { btn: tabConfig, panel: panelConfig },
    { btn: tabScheduler, panel: panelScheduler },
    { btn: tabConsole, panel: panelConsole },
  ];

  tabs.forEach(t => {
    if (t.btn) {
      t.btn.addEventListener('click', () => switchTab(t.btn.dataset.tab));
    }
  });

  function switchTab(tabName) {
    tabs.forEach(t => {
      if (!t.btn || !t.panel) return;
      const isMatch = t.btn.dataset.tab === tabName;
      t.btn.classList.toggle('active', isMatch);
      t.panel.classList.toggle('active', isMatch);
    });
    if (tabName === 'deals') loadDeals();
    if (tabName === 'trackers') loadTrackers();
    if (tabName === 'config') loadConfig();
  }

  // ── Toast Notifications ───────────────────────────────────────────────────
  function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✓' : (type === 'error' ? '✖' : 'ℹ');
    toast.innerHTML = `<span>${icon}</span><span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, m => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[m]));
  }

  // ── Deals API & Rendering ─────────────────────────────────────────────────
  async function loadFeedback() {
    try {
      const res = await fetch('/api/deals/feedback');
      const data = await res.json();
      feedbackMap = data.feedback || {};
    } catch (err) {
      console.warn('Feedback load error', err);
    }
  }

  async function loadDeals() {
    try {
      await loadFeedback();
      if (isIgnoredView) {
        const res = await fetch('/api/deals/ignored');
        const data = await res.json();
        ignoredDeals = data.deals || [];
        statIgnoredCount.textContent = ignoredDeals.length;
        if (ignoredBadge) ignoredBadge.textContent = ignoredDeals.length;
        renderIgnoredDeals();
      } else {
        const res = await fetch('/api/deals');
        const data = await res.json();
        allDeals = data.deals || [];
        const ignCount = data.ignored_count || 0;
        statIgnoredCount.textContent = ignCount;
        if (ignoredBadge) ignoredBadge.textContent = ignCount;
        renderDeals();
        updateDealStats();
      }
    } catch (err) {
      dealsContainer.innerHTML = `<div class="empty-state"><p class="text-danger">Failed to load deals: ${err.message}</p></div>`;
    }
  }

  function updateDealStats() {
    statDealsCount.textContent = allDeals.length;
    tabDealsBadge.textContent = allDeals.length;

    if (allDeals.length > 0) {
      const maxDisc = Math.max(...allDeals.map(d => d.wow_discount_pct || d.discount_pct || 0));
      statBestDiscount.textContent = `${Math.round(maxDisc)}%`;
    } else {
      statBestDiscount.textContent = '0%';
    }
  }

  function getStoreBadgeHtml(source) {
    const src = (source || 'other').toLowerCase();
    if (src === 'flipkart') {
      return `
        <span class="store-badge flipkart" title="Flipkart Deal">
          <svg class="store-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="24" height="24" rx="5" fill="#2874F0"/>
            <path d="M5.5 7.5C5.5 6.7 6.1 6 6.9 6H17.1C17.9 6 18.5 6.7 18.5 7.5L19.4 19.5C19.4 20.3 18.8 21 18 21H6C5.2 21 4.6 20.3 4.6 19.5L5.5 7.5Z" fill="#FFE11B"/>
            <path d="M9 6V4.8C9 3.5 10.3 2.5 12 2.5C13.7 2.5 15 3.5 15 4.8V6" stroke="#2874F0" stroke-width="1.8" stroke-linecap="round"/>
            <path d="M14 9.5C13.2 9.5 12.6 10 12.4 10.6V12H14.2L13.8 13.6H12.4V18H10.5V13.6H9.4V12H10.5V10.8C10.5 9.1 11.5 8.2 13 8.2C13.5 8.2 14 8.3 14.3 8.5L14 9.5Z" fill="#2874F0"/>
            <path d="M7 10.2H8.8M6.6 12H8.4M7 13.8H8.8" stroke="#2874F0" stroke-width="1.1" stroke-linecap="round"/>
          </svg>
          Flipkart
        </span>
      `;
    }
    if (src === 'myntra') {
      return `
        <span class="store-badge myntra" title="Myntra Deal">
          <svg class="store-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="24" height="24" rx="5" fill="#FFFFFF"/>
            <g transform="translate(1.5, 2.2) scale(0.88)">
              <path d="M3.2 18.5C3.2 18.5 4.8 8.8 7.5 5.5C9.2 3.5 11.2 4.2 11.2 7C11.2 10.8 8.2 15.5 8.2 18.5H3.2Z" fill="#FF3F6C"/>
              <path d="M6.8 18.5C6.8 15.8 9.5 11.2 11.5 7.2C12.8 4.8 14.5 5.8 14.5 8.2C14.5 12 11.2 16.2 10.2 18.5H6.8Z" fill="#C20056"/>
              <path d="M9.5 18.5C10.5 15.2 13.8 10.8 15.5 7C16.8 4.2 18.8 5.2 18.8 8C18.8 11.5 15.2 16 13.8 18.5H9.5Z" fill="#FF5722"/>
              <path d="M13.2 18.5C14.2 15.8 17.2 10.8 18.8 7C20.2 4.2 21.8 5.2 21.8 8C21.8 11.5 18.2 16.2 16.5 18.5H13.2Z" fill="#FFA100"/>
            </g>
          </svg>
          Myntra
        </span>
      `;
    }
    if (src === 'tatacliq') {
      return `
        <span class="store-badge tatacliq" title="Tata CLiQ Deal">
          <svg class="store-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="24" height="24" rx="5" fill="#121214"/>
            <circle cx="11.5" cy="11.5" r="6.2" stroke="#FFFFFF" stroke-width="2.2"/>
            <circle cx="11.8" cy="11.2" r="3.4" fill="#DA1C5C"/>
            <path d="M15.8 15.8L18.8 18.8" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round"/>
          </svg>
          Tata CLiQ
        </span>
      `;
    }
    return `<span class="store-badge">${escapeHtml(source || 'Deal')}</span>`;
  }

  function buildDealCardHtml(d, targetSizes = []) {
    const hasWowDisc = Boolean(d.wow_discount_pct && d.wow_discount_pct > 0);
    const displayDisc = Math.round(hasWowDisc ? d.wow_discount_pct : (d.discount_pct || 0));
    const badgeClass = hasWowDisc ? 'deal-discount-badge wow-badge' : 'deal-discount-badge';
    let badgeText = `${displayDisc}% OFF`;
    const wowPrice = d.wow_price ? Math.round(d.wow_price) : null;
    const salePrice = Math.round(d.sale_price || 0);
    const mrp = Math.round(d.original_price || 0);
    const dealId = d.deal_id || d.product_url;
    const userFeedback = feedbackMap[dealId] || '';

    // AI Verdict
    const verdict = (d.verdict || d.agent_verdict || '').toUpperCase();
    const reason = d.reason || d.agent_reason || '';
    const scoreVal = d.score != null ? Number(d.score).toFixed(1) : null;
    const verdictClass = verdict === 'STEAL' ? 'verdict-steal' : (verdict === 'WORTH_IT' ? 'verdict-worth_it' : (verdict === 'SKIP' ? 'verdict-skip' : ''));
    const verdictIcon = verdict === 'STEAL' ? '🔥' : (verdict === 'WORTH_IT' ? '✓' : '✗');
    const verdictLabel = verdict === 'STEAL' ? 'STEAL' : (verdict === 'WORTH_IT' ? 'WORTH IT' : 'SKIP');

    // Sizes markup
    let sizesHtml = '';
    if (d.available_sizes && d.available_sizes.length > 0) {
      const normTargets = (targetSizes || []).map(s => String(s).toUpperCase().replace(/^(UK|US|EU|IND|[\/\s\-])+/i, '').replace(/[\/\s\-]+/g, '').trim());
      const isTargetSize = (sz) => {
        const norm = String(sz).toUpperCase().replace(/^(UK|US|EU|IND|[\/\s\-])+/i, '').replace(/[\/\s\-]+/g, '').trim();
        if (normTargets.includes(norm)) return true;
        const num = parseFloat(norm);
        if (!isNaN(num)) {
          return normTargets.some(t => parseFloat(t) === num);
        }
        return false;
      };

      const sortedSizes = [...d.available_sizes].sort((a, b) => {
        const aTarget = isTargetSize(a);
        const bTarget = isTargetSize(b);
        if (aTarget && !bTarget) return -1;
        if (!aTarget && bTarget) return 1;
        const numA = parseFloat(a), numB = parseFloat(b);
        if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
        return String(a).localeCompare(String(b));
      });

      sizesHtml = sortedSizes.map(sz => {
        const isTarget = isTargetSize(sz);
        return `<span class="size-pill ${isTarget ? 'matched' : ''}">${escapeHtml(sz)}</span>`;
      }).join('');
    } else {
      sizesHtml = '<span class="size-pill">All Sizes / General</span>';
    }

    // Time formatted
    let timeStr = '';
    if (d.scraped_at) {
      try {
        const dt = new Date(d.scraped_at);
        timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + dt.toLocaleDateString([], { month: 'short', day: 'numeric' });
      } catch {
        timeStr = '';
      }
    }

    return `
      <div class="deal-card" id="card-${escapeHtml(encodeURIComponent(d.deal_id || d.product_url))}">
        ${verdict ? `
          <div class="deal-verdict-banner ${verdictClass}">
            <span class="deal-verdict-badge">${verdictIcon} AI Verdict: ${verdictLabel}</span>
            ${scoreVal ? `<span class="deal-verdict-score" style="font-size:0.75rem; font-weight:700; opacity:0.9;">⭐ ${scoreVal}</span>` : ''}
          </div>
        ` : ''}

        <div class="card-top-banner">
          <div style="display:flex; align-items:center; gap:6px;">
            ${getStoreBadgeHtml(d.source)}
            ${verdict ? `<span class="deal-verdict-chip ${verdictClass}">${verdictIcon} ${verdictLabel}</span>` : ''}
          </div>
          ${displayDisc > 0 ? `<span class="${badgeClass}" title="${hasWowDisc ? 'Effective WOW Discount' : 'Standard Discount'}">${badgeText}</span>` : ''}
        </div>

        <div class="deal-header-flex">
          ${d.image_url ? `
            <div class="deal-thumb-wrap">
              <img src="${escapeHtml(d.image_url)}" alt="${escapeHtml(d.title)}" class="deal-thumb-img" loading="lazy" onerror="this.onerror=null; this.parentElement.innerHTML='<span style=\\'font-size:1.6rem;\\'>📦</span>';">
            </div>
          ` : `
            <div class="deal-thumb-wrap deal-thumb-fallback">
              <span>📦</span>
            </div>
          `}
          <div class="deal-brand-wrap">
            <div class="deal-brand">${escapeHtml(d.brand || 'Brand')}</div>
            <h3 class="deal-title" title="${escapeHtml(d.title)}">${escapeHtml(d.title)}</h3>
          </div>
        </div>

        <div class="deal-content">
          ${reason ? `
            <div class="agent-reason-card-box ${verdictClass}">
              <strong>🤖 AI Evaluator:</strong> ${escapeHtml(reason)}
            </div>
          ` : ''}

          <div class="price-row">
            <span class="sale-price">₹${salePrice.toLocaleString('en-IN')}</span>
            ${mrp > salePrice ? `<span class="mrp-price">₹${mrp.toLocaleString('en-IN')}</span>` : ''}
          </div>

          ${wowPrice ? `
            <div class="wow-deal-box">
              <span class="wow-label">${d.source === 'myntra' ? '🏷️ Best Price with Coupon' : (d.source === 'tatacliq' ? (salePrice >= 2000 ? '🏷️ CLIQDEAL + 10% NeuCoins' : '🪙 10% NeuCoins (Tata Neu)') : '⚡ WOW / Effective Price')}</span>
              <span class="wow-price-tag">₹${wowPrice.toLocaleString('en-IN')}</span>
            </div>
          ` : ''}

          <div class="sizes-section">
            <span class="sizes-label">Available Sizes:</span>
            <div class="sizes-wrap">${sizesHtml}</div>
          </div>

          <div class="card-footer">
            <span class="scraped-time">${timeStr ? `🕒 ${timeStr}` : ''}</span>
            <div class="deal-actions-wrap">
              <div class="deal-feedback-actions">
                <button class="deal-feedback-btn ${userFeedback === 'LIKED' ? 'liked' : ''}" data-deal-id="${escapeHtml(dealId)}" data-action="LIKED" title="I like this deal">👍</button>
                <button class="deal-feedback-btn ${userFeedback === 'DISLIKED' ? 'disliked' : ''}" data-deal-id="${escapeHtml(dealId)}" data-action="DISLIKED" title="Not relevant / bad deal">👎</button>
              </div>
              <button class="deal-history-btn" data-deal-id="${escapeHtml(dealId)}" data-title="${escapeHtml(d.title || '')}" data-mrp="${mrp}" data-price="${salePrice}" title="View price history over time">
                📈
              </button>
              <button class="deal-ignore-btn" data-deal-id="${escapeHtml(dealId)}" data-brand="${escapeHtml(d.brand || '')}" data-title="${escapeHtml(d.title || '')}" data-url="${escapeHtml(d.product_url || '')}" data-price="${d.sale_price || 0}" data-source="${escapeHtml(d.source || '')}" title="Skip/ignore this product from subsequent scans">
                🚫 Skip
              </button>
              <a href="${escapeHtml(d.product_url)}" target="_blank" rel="noopener noreferrer" class="deal-link-btn">
                View Deal ↗
              </a>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderDeals() {
    const searchVal = dealSearchInput.value.trim().toLowerCase();
    const sourceVal = sourceFilter.value;
    const sortVal = sortFilter.value;

    let filtered = allDeals.filter(d => {
      if (sourceVal !== 'all' && (d.source || '').toLowerCase() !== sourceVal) {
        return false;
      }
      const genderVal = genderFilter.value;
      if (genderVal !== 'all') {
        const dg = (d.gender || '').toLowerCase();
        if (genderVal === 'unisex') {
          if (dg !== 'unisex' && dg !== 'kids') return false;
        } else {
          if (dg !== genderVal) return false;
        }
      }
      if (verdictFilter && verdictFilter.value !== 'all') {
        const v = (d.verdict || d.agent_verdict || '').toUpperCase();
        if (verdictFilter.value === 'QUALIFIED') {
          if (v !== 'STEAL' && v !== 'WORTH_IT') return false;
        } else if (v !== verdictFilter.value) {
          return false;
        }
      }
      if (searchVal) {
        const text = `${d.title || ''} ${d.brand || ''} ${(d.available_sizes || []).join(' ')}`.toLowerCase();
        if (!text.includes(searchVal)) return false;
      }
      return true;
    });

    // Sorting
    filtered.sort((a, b) => {
      if (sortVal === 'discount_desc') {
        const discA = a.wow_discount_pct || a.discount_pct || 0;
        const discB = b.wow_discount_pct || b.discount_pct || 0;
        return discB - discA;
      }
      if (sortVal === 'discount_asc') {
        const discA = a.wow_discount_pct || a.discount_pct || 0;
        const discB = b.wow_discount_pct || b.discount_pct || 0;
        return discA - discB;
      }
      if (sortVal === 'price_asc') {
        const pA = a.wow_price || a.sale_price || 0;
        const pB = b.wow_price || b.sale_price || 0;
        return pA - pB;
      }
      if (sortVal === 'price_desc') {
        const pA = a.wow_price || a.sale_price || 0;
        const pB = b.wow_price || b.sale_price || 0;
        return pB - pA;
      }
      if (sortVal === 'name_asc') {
        return (a.title || '').localeCompare(b.title || '');
      }
      if (sortVal === 'name_desc') {
        return (b.title || '').localeCompare(a.title || '');
      }
      if (sortVal === 'recent') {
        return (b.scraped_at || '').localeCompare(a.scraped_at || '');
      }
      return 0;
    });

    if (filtered.length === 0) {
      dealsContainer.style.display = 'none';
      dealsEmptyState.style.display = 'block';
      dealsEmptyState.querySelector('h3').textContent = 'No matching deals found';
      dealsEmptyState.querySelector('p').textContent = 'Run the scanner to discover deals matching your watchlist or clear search filters.';
      return;
    }

    dealsContainer.style.display = 'grid';
    dealsEmptyState.style.display = 'none';

    const targetSizes = (currentConfig?.watchlist?.target_sizes || []).map(s => String(s).toUpperCase());
    dealsContainer.innerHTML = filtered.map(d => buildDealCardHtml(d, targetSizes)).join('');
  }


  function renderIgnoredDeals() {
    const searchVal = dealSearchInput.value.trim().toLowerCase();
    let filtered = ignoredDeals.filter(d => {
      if (searchVal) {
        const text = `${d.title || ''} ${d.brand || ''} ${d.deal_id || ''} ${d.product_url || ''}`.toLowerCase();
        if (!text.includes(searchVal)) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      dealsContainer.style.display = 'none';
      dealsEmptyState.style.display = 'block';
      dealsEmptyState.querySelector('h3').textContent = 'No ignored listings';
      dealsEmptyState.querySelector('p').textContent = 'When you skip or ignore a listing, it will be kept here and omitted from all scans.';
      return;
    }

    dealsContainer.style.display = 'grid';
    dealsEmptyState.style.display = 'none';

    dealsContainer.innerHTML = filtered.map(d => {
      const sourceClass = (d.source || 'other').toLowerCase();
      const salePrice = d.sale_price ? Math.round(d.sale_price) : null;
      let timeStr = '';
      if (d.ignored_at) {
        try {
          const dt = new Date(d.ignored_at);
          timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + dt.toLocaleDateString([], { month: 'short', day: 'numeric' });
        } catch {
          timeStr = '';
        }
      }

      return `
        <div class="deal-card" style="opacity: 0.85; border-color: rgba(239, 68, 68, 0.25);">
          <div class="card-top-banner">
            ${getStoreBadgeHtml(d.source)}
            <span class="deal-discount-badge" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">🚫 SKIPPED</span>
          </div>

          <div class="deal-header-flex">
            <div class="deal-thumb-wrap deal-thumb-fallback">
              <span>🚫</span>
            </div>
            <div class="deal-brand-wrap">
              <div class="deal-brand">${escapeHtml(d.brand || 'Skipped Item')}</div>
              <h3 class="deal-title" title="${escapeHtml(d.title || d.deal_id || d.product_url)}">${escapeHtml(d.title || d.deal_id || d.product_url)}</h3>
            </div>
          </div>

          <div class="deal-content">
            ${salePrice ? `
              <div class="price-row">
                <span class="sale-price">₹${salePrice.toLocaleString('en-IN')}</span>
              </div>
            ` : ''}

            <div class="card-footer">
              <span class="scraped-time">${timeStr ? `🕒 Skipped ${timeStr}` : ''}</span>
              <div class="deal-actions-wrap">
                <button class="deal-unignore-btn" data-deal-id="${escapeHtml(d.deal_id || d.product_url)}" title="Restore listing so it can appear in scans">
                  ↩ Restore
                </button>
                ${d.product_url ? `
                  <a href="${escapeHtml(d.product_url)}" target="_blank" rel="noopener noreferrer" class="deal-link-btn">
                    View ↗
                  </a>
                ` : ''}
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  async function handleIgnoreDeal(dealId, meta) {
    try {
      const res = await fetch('/api/deals/ignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deal_id: dealId,
          ...meta,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        allDeals = allDeals.filter(d => d.deal_id !== dealId && d.product_url !== dealId);
        showToast('Listing skipped & added to ignore list', 'info');
        renderDeals();
        updateDealStats();
        const cur = parseInt(statIgnoredCount.textContent || '0', 10);
        statIgnoredCount.textContent = cur + 1;
        if (ignoredBadge) ignoredBadge.textContent = cur + 1;
      } else {
        showToast(data.error || 'Failed to ignore deal', 'error');
      }
    } catch (err) {
      showToast('Error: ' + err.message, 'error');
    }
  }

  async function handleUnignoreDeal(dealId) {
    try {
      const res = await fetch('/api/deals/unignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deal_id: dealId }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast('Listing restored to active scans', 'success');
        await loadDeals();
      } else {
        showToast(data.error || 'Failed to restore deal', 'error');
      }
    } catch (err) {
      showToast('Error: ' + err.message, 'error');
    }
  }

  async function handleFeedbackClick(dealId, action, btnEl) {
    try {
      const res = await fetch('/api/deals/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deal_id: dealId, action }),
      });
      if (res.ok) {
        feedbackMap[dealId] = action;
        const parent = btnEl.closest('.deal-feedback-actions');
        if (parent) {
          parent.querySelectorAll('.deal-feedback-btn').forEach(b => {
            b.classList.remove('liked', 'disliked');
          });
          if (action === 'LIKED') btnEl.classList.add('liked');
          if (action === 'DISLIKED') btnEl.classList.add('disliked');
        }
        showToast(action === 'LIKED' ? 'Marked deal as liked 👍' : 'Marked deal as disliked 👎', 'info');
      }
    } catch (err) {
      showToast('Error saving feedback: ' + err.message, 'error');
    }
  }

  // Click delegation for ignore, unignore, feedback & price history
  dealsContainer.addEventListener('click', e => {
    const feedbackBtn = e.target.closest('.deal-feedback-btn');
    if (feedbackBtn) {
      const dealId = feedbackBtn.dataset.dealId;
      const action = feedbackBtn.dataset.action;
      handleFeedbackClick(dealId, action, feedbackBtn);
      return;
    }

    const histBtn = e.target.closest('.deal-history-btn');
    if (histBtn) {
      const dealId = histBtn.dataset.dealId;
      const title = histBtn.dataset.title;
      const mrp = parseFloat(histBtn.dataset.mrp) || 0;
      const price = parseFloat(histBtn.dataset.price) || 0;
      showPriceHistory(dealId, title, mrp, price);
      return;
    }

    const ignoreBtn = e.target.closest('.deal-ignore-btn');
    if (ignoreBtn) {
      const dealId = ignoreBtn.dataset.dealId;
      const brand = ignoreBtn.dataset.brand;
      const title = ignoreBtn.dataset.title;
      const product_url = ignoreBtn.dataset.url;
      const sale_price = parseFloat(ignoreBtn.dataset.price) || 0;
      const source = ignoreBtn.dataset.source;
      handleIgnoreDeal(dealId, { brand, title, product_url, sale_price, source });
      return;
    }

    const unignoreBtn = e.target.closest('.deal-unignore-btn');
    if (unignoreBtn) {
      const dealId = unignoreBtn.dataset.dealId;
      handleUnignoreDeal(dealId);
      return;
    }
  });

  // Toggle Ignored view
  if (btnToggleIgnored) {
    btnToggleIgnored.addEventListener('click', () => {
      isIgnoredView = !isIgnoredView;
      updateIgnoredViewUI();
      loadDeals();
    });
  }

  if (btnExitIgnored) {
    btnExitIgnored.addEventListener('click', () => {
      isIgnoredView = false;
      updateIgnoredViewUI();
      loadDeals();
    });
  }

  function updateIgnoredViewUI() {
    if (isIgnoredView) {
      btnToggleIgnored.classList.add('active');
      if (btnToggleIgnoredText) btnToggleIgnoredText.textContent = 'Active Deals';
      if (btnToggleIgnoredIcon) btnToggleIgnoredIcon.textContent = '🏷️';
      if (ignoredModeBanner) ignoredModeBanner.style.display = 'flex';
      sourceFilter.style.display = 'none';
      genderFilter.style.display = 'none';
      sortFilter.style.display = 'none';
      btnClearDeals.style.display = 'none';
    } else {
      btnToggleIgnored.classList.remove('active');
      if (btnToggleIgnoredText) btnToggleIgnoredText.textContent = 'Ignored List';
      if (btnToggleIgnoredIcon) btnToggleIgnoredIcon.textContent = '🚫';
      if (ignoredModeBanner) ignoredModeBanner.style.display = 'none';
      sourceFilter.style.display = '';
      genderFilter.style.display = '';
      sortFilter.style.display = '';
      btnClearDeals.style.display = '';
    }
  }

  // Filter event listeners
  dealSearchInput.addEventListener('input', () => {
    clearSearchBtn.style.display = dealSearchInput.value ? 'block' : 'none';
    if (isIgnoredView) {
      renderIgnoredDeals();
    } else {
      renderDeals();
    }
  });
  clearSearchBtn.addEventListener('click', () => {
    dealSearchInput.value = '';
    clearSearchBtn.style.display = 'none';
    if (isIgnoredView) {
      renderIgnoredDeals();
    } else {
      renderDeals();
    }
  });
  sourceFilter.addEventListener('change', renderDeals);
  genderFilter.addEventListener('change', renderDeals);
  sortFilter.addEventListener('change', renderDeals);
  if (verdictFilter) verdictFilter.addEventListener('change', renderDeals);

  const btnRefreshDeals = document.getElementById('btnRefreshDeals');
  if (btnRefreshDeals) {
    btnRefreshDeals.addEventListener('click', async () => {
      btnRefreshDeals.disabled = true;
      btnRefreshDeals.textContent = '⏳ Refreshing...';
      await loadDeals();
      setTimeout(() => {
        btnRefreshDeals.disabled = false;
        btnRefreshDeals.textContent = '🔄 Refresh';
      }, 350);
      showToast('Deals refreshed from store', 'success');
    });
  }

  btnClearDeals.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to clear stored deals history? Ignored listings will NOT be cleared.')) return;
    try {
      const res = await fetch('/api/deals', { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message || 'Seen deals history cleared', 'success');
        allDeals = [];
        renderDeals();
        updateDealStats();
        await loadDeals();
      } else {
        showToast(data.detail || data.error || 'Failed to clear deals', 'error');
      }
    } catch (err) {
      showToast('Failed to clear deals: ' + err.message, 'error');
    }
  });

  if (btnClearIgnored) {
    btnClearIgnored.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to clear the entire ignore list? These items will appear in scans again.')) return;
      try {
        const res = await fetch('/api/deals/ignored', { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
          showToast(data.message || 'Ignored listings cleared', 'success');
          ignoredDeals = [];
          renderIgnoredDeals();
          await loadDeals();
        } else {
          showToast(data.detail || data.error || 'Failed to clear ignored list', 'error');
        }
      } catch (err) {
        showToast('Error: ' + err.message, 'error');
      }
    });
  }


  // ── Config Management ─────────────────────────────────────────────────────
  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      currentConfig = await res.json();
      populateConfigForm(currentConfig);
      rawJsonEditor.value = JSON.stringify(currentConfig, null, 2);
      validateRawJson();
    } catch (err) {
      showToast('Failed to load config: ' + err.message, 'error');
    }
  }

  function populateConfigForm(cfg) {
    if (!cfg) return;

    // Watchlist
    const wl = cfg.watchlist || {};
    document.getElementById('cfgBrandsInput').value = (wl.brands || []).join(', ');
    document.getElementById('cfgSizesInput').value = (wl.target_sizes || []).join(', ');

    // Price bands
    document.getElementById('cfgMinDiscount').value = cfg.min_discount_pct ?? 30;
    document.getElementById('cfgMinPrice').value = cfg.min_price ?? 1000;
    document.getElementById('cfgMaxPrice').value = cfg.max_price ?? 15000;
    if (document.getElementById('cfgPincode')) {
      document.getElementById('cfgPincode').value = cfg.pincode ?? '110009';
    }

    // Scraper
    const sc = cfg.scraper || {};
    document.getElementById('cfgDelay').value = sc.request_delay_sec ?? 2;
    document.getElementById('cfgTimeout').value = sc.timeout_sec ?? 15;
    document.getElementById('cfgRetries').value = sc.max_retries ?? 3;
    document.getElementById('cfgMaxProducts').value = cfg.max_products ?? sc.max_products ?? 40;
    document.getElementById('cfgFetchWow').checked = Boolean(sc.fetch_wow_price ?? true);
    document.getElementById('cfgUsePlaywright').checked = Boolean(sc.use_playwright ?? false);

    // Notifications
    const notif = cfg.notifications || {};
    document.getElementById('cfgMacosNotify').checked = Boolean(notif.macos_notify?.enabled ?? true);
    const tg = notif.telegram || {};
    document.getElementById('cfgTelegramNotify').checked = Boolean(tg.enabled ?? false);
    document.getElementById('cfgTelegramToken').value = tg.bot_token || '';
    document.getElementById('cfgTelegramChatId').value = tg.chat_id || '';

    // Search queries
    renderQueriesList(cfg.search_queries || []);
  }

  function renderQueriesList(queries) {
    queriesListContainer.innerHTML = '';
    queries.forEach((q, idx) => {
      const row = document.createElement('div');
      row.className = 'query-row';

      const qText = typeof q === 'string' ? q : (q.query || '');
      const minDisc = typeof q === 'object' && q.min_discount_pct !== undefined ? q.min_discount_pct : '';
      const minP = typeof q === 'object' && q.min_price !== undefined ? q.min_price : '';
      const maxP = typeof q === 'object' && q.max_price !== undefined ? q.max_price : '';
      const maxProds = typeof q === 'object' && q.max_products !== undefined ? q.max_products : '';
      const currentGender = typeof q === 'object' && q.gender ? String(q.gender).toLowerCase() : 'na';

      let currentScraper = 'all';
      if (typeof q === 'object') {
        const scs = q.scrapers || (q.scraper ? [q.scraper] : []);
        if (scs.length === 1) {
          currentScraper = String(scs[0]).toLowerCase();
        }
      }

      row.innerHTML = `
        <input type="text" class="text-input query-text-input" placeholder="Search Query (e.g. nike shoes)" value="${escapeHtml(qText)}">
        <select class="select-input query-retailer-select" title="Retailer to scrape for this query">
          <option value="all" ${currentScraper === 'all' ? 'selected' : ''}>All Retailers</option>
          <option value="flipkart" ${currentScraper === 'flipkart' ? 'selected' : ''}>Flipkart Only</option>
          <option value="myntra" ${currentScraper === 'myntra' ? 'selected' : ''}>Myntra Only</option>
          <option value="tatacliq" ${currentScraper === 'tatacliq' ? 'selected' : ''}>TataCLiQ Only</option>
        </select>
        <select class="select-input query-gender-select" title="Target gender for this query">
          <option value="na" ${currentGender === 'na' ? 'selected' : ''}>Gender: N/A</option>
          <option value="men" ${currentGender === 'men' ? 'selected' : ''}>Men</option>
          <option value="women" ${currentGender === 'women' ? 'selected' : ''}>Women</option>
          <option value="kids" ${currentGender === 'kids' ? 'selected' : ''}>Kids</option>
          <option value="unisex" ${currentGender === 'unisex' ? 'selected' : ''}>Unisex</option>
        </select>
        <input type="number" class="text-input query-num-input query-disc" placeholder="Min %" value="${minDisc}" title="Min Discount %">
        <input type="number" class="text-input query-num-input query-minp" placeholder="Min ₹" value="${minP}" title="Min Price (₹)">
        <input type="number" class="text-input query-num-input query-maxp" placeholder="Max ₹" value="${maxP}" title="Max Price (₹)">
        <input type="number" class="text-input query-num-input query-prods" placeholder="Limit (80)" value="${maxProds}" min="40" step="40" title="Raw products limit (e.g. 40, 80, 120)">
        <button type="button" class="btn-remove-query" title="Remove query">✕</button>
      `;

      row.querySelector('.btn-remove-query').addEventListener('click', () => {
        row.remove();
      });

      queriesListContainer.appendChild(row);
    });
  }

  btnAddQuery.addEventListener('click', () => {
    const row = document.createElement('div');
    row.className = 'query-row';
    row.innerHTML = `
      <input type="text" class="text-input query-text-input" placeholder="Search Query (e.g. adidas originals shoes)">
      <select class="select-input query-retailer-select" title="Retailer to scrape for this query">
        <option value="all" selected>All Retailers</option>
        <option value="flipkart">Flipkart Only</option>
        <option value="myntra">Myntra Only</option>
        <option value="tatacliq">TataCLiQ Only</option>
      </select>
      <select class="select-input query-gender-select" title="Target gender for this query">
        <option value="na" selected>Gender: N/A</option>
        <option value="men">Men</option>
        <option value="women">Women</option>
        <option value="kids">Kids</option>
        <option value="unisex">Unisex</option>
      </select>
      <input type="number" class="text-input query-num-input query-disc" placeholder="Min %" value="" title="Min Discount %">
      <input type="number" class="text-input query-num-input query-minp" placeholder="Min ₹" value="" title="Min Price (₹)">
      <input type="number" class="text-input query-num-input query-maxp" placeholder="Max ₹" value="" title="Max Price (₹)">
      <input type="number" class="text-input query-num-input query-prods" placeholder="Limit (80)" value="80" min="40" step="40" title="Raw products limit (e.g. 40, 80, 120)">
      <button type="button" class="btn-remove-query" title="Remove query">✕</button>
    `;
    row.querySelector('.btn-remove-query').addEventListener('click', () => row.remove());
    queriesListContainer.appendChild(row);
  });

  // Extract Form values into config object
  function serializeFormToConfig() {
    const cfg = JSON.parse(JSON.stringify(currentConfig || {}));

    const brandsStr = document.getElementById('cfgBrandsInput').value;
    const sizesStr = document.getElementById('cfgSizesInput').value;

    cfg.watchlist = cfg.watchlist || {};
    cfg.watchlist.brands = brandsStr.split(',').map(s => s.trim()).filter(Boolean);
    cfg.watchlist.target_sizes = sizesStr.split(',').map(s => s.trim()).filter(Boolean);

    cfg.min_discount_pct = Number(document.getElementById('cfgMinDiscount').value) || 0;
    cfg.min_price = Number(document.getElementById('cfgMinPrice').value) || 0;
    cfg.max_price = Number(document.getElementById('cfgMaxPrice').value) || 999999;
    const pincodeInput = document.getElementById('cfgPincode');
    if (pincodeInput) {
      cfg.pincode = (pincodeInput.value || '110009').trim();
    }
    const maxProd = Number(document.getElementById('cfgMaxProducts').value) || 40;
    cfg.max_products = maxProd;

    cfg.scraper = cfg.scraper || {};
    cfg.scraper.request_delay_sec = Number(document.getElementById('cfgDelay').value) || 2;
    cfg.scraper.timeout_sec = Number(document.getElementById('cfgTimeout').value) || 15;
    cfg.scraper.max_retries = Number(document.getElementById('cfgRetries').value) || 3;
    cfg.scraper.max_products = maxProd;
    cfg.scraper.fetch_wow_price = document.getElementById('cfgFetchWow').checked;
    cfg.scraper.use_playwright = document.getElementById('cfgUsePlaywright').checked;

    cfg.notifications = cfg.notifications || {};
    cfg.notifications.macos_notify = {
      enabled: document.getElementById('cfgMacosNotify').checked
    };
    cfg.notifications.telegram = {
      enabled: document.getElementById('cfgTelegramNotify').checked,
      bot_token: document.getElementById('cfgTelegramToken').value.trim(),
      chat_id: document.getElementById('cfgTelegramChatId').value.trim()
    };

    // Queries
    const queryRows = queriesListContainer.querySelectorAll('.query-row');
    const queries = [];
    queryRows.forEach(row => {
      const text = row.querySelector('.query-text-input').value.trim();
      if (!text) return;

      const retailerVal = row.querySelector('.query-retailer-select').value;
      const genderVal = row.querySelector('.query-gender-select')?.value || 'na';
      const disc = row.querySelector('.query-disc').value;
      const minp = row.querySelector('.query-minp').value;
      const maxp = row.querySelector('.query-maxp').value;
      const maxprods = row.querySelector('.query-prods').value;

      if (disc !== '' || minp !== '' || maxp !== '' || maxprods !== '' || retailerVal !== 'all' || genderVal !== 'na') {
        const item = { query: text };
        if (retailerVal !== 'all') item.scrapers = [retailerVal];
        if (genderVal !== 'na') item.gender = genderVal;
        if (disc !== '') item.min_discount_pct = Number(disc);
        if (minp !== '') item.min_price = Number(minp);
        if (maxp !== '') item.max_price = Number(maxp);
        if (maxprods !== '') item.max_products = Number(maxprods);
        queries.push(item);
      } else {
        queries.push(text);
      }
    });

    cfg.search_queries = queries;
    return cfg;
  }

  // Switch between Form View and JSON View
  btnModeForm.addEventListener('click', () => {
    btnModeForm.classList.add('active');
    btnModeJson.classList.remove('active');
    configFormView.style.display = 'block';
    configJsonView.style.display = 'none';

    // Parse JSON back into Form
    try {
      const parsed = JSON.parse(rawJsonEditor.value);
      currentConfig = parsed;
      populateConfigForm(parsed);
    } catch {
      showToast('Cannot switch to form: raw JSON contains syntax errors', 'error');
    }
  });

  btnModeJson.addEventListener('click', () => {
    btnModeJson.classList.add('active');
    btnModeForm.classList.remove('active');
    configJsonView.style.display = 'block';
    configFormView.style.display = 'none';

    // Sync Form into JSON editor
    const cfg = serializeFormToConfig();
    currentConfig = cfg;
    rawJsonEditor.value = JSON.stringify(cfg, null, 2);
    validateRawJson();
  });

  function validateRawJson() {
    try {
      JSON.parse(rawJsonEditor.value);
      jsonValidationStatus.textContent = '✓ JSON is valid';
      jsonValidationStatus.className = 'editor-status';
      return true;
    } catch (e) {
      jsonValidationStatus.textContent = `✖ Syntax Error: ${e.message}`;
      jsonValidationStatus.className = 'editor-status error';
      return false;
    }
  }

  rawJsonEditor.addEventListener('input', validateRawJson);

  btnFormatJson.addEventListener('click', () => {
    try {
      const parsed = JSON.parse(rawJsonEditor.value);
      rawJsonEditor.value = JSON.stringify(parsed, null, 2);
      validateRawJson();
      showToast('Formatted JSON', 'info');
    } catch (e) {
      showToast('Invalid JSON: ' + e.message, 'error');
    }
  });

  btnReloadConfig.addEventListener('click', () => {
    loadConfig();
    showToast('Configuration reloaded from disk', 'info');
  });

  btnSaveConfig.addEventListener('click', async () => {
    let payload = null;

    if (btnModeJson.classList.contains('active')) {
      if (!validateRawJson()) {
        showToast('Fix JSON errors before saving', 'error');
        return;
      }
      payload = JSON.parse(rawJsonEditor.value);
    } else {
      payload = serializeFormToConfig();
    }

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        currentConfig = payload;
        rawJsonEditor.value = JSON.stringify(payload, null, 2);
        showToast('Config saved successfully!', 'success');
      } else {
        showToast(data.error || 'Failed to save config', 'error');
      }
    } catch (err) {
      showToast('Network error saving config: ' + err.message, 'error');
    }
  });


  // ── Scheduler Management ──────────────────────────────────────────────────
  async function saveSchedule(enabled, intervalMinutes) {
    try {
      const res = await fetch('/api/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: Boolean(enabled),
          interval_minutes: Number(intervalMinutes),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(enabled ? `Scheduler active: every ${intervalMinutes}m` : 'Scheduler disabled', 'success');
        updateSchedulerUI(data.scheduler);
      } else {
        showToast(data.error || 'Failed to update schedule', 'error');
      }
    } catch (err) {
      showToast('Schedule error: ' + err.message, 'error');
    }
  }

  btnSaveSchedule.addEventListener('click', () => {
    saveSchedule(schedEnableToggle.checked, schedIntervalInput.value);
  });

  schedEnableToggle.addEventListener('change', () => {
    saveSchedule(schedEnableToggle.checked, schedIntervalInput.value);
  });

  // Presets
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      schedIntervalInput.value = btn.dataset.minutes;
      saveSchedule(schedEnableToggle.checked, btn.dataset.minutes);
    });
  });

  function updateSchedulerUI(sched) {
    if (!sched) return;

    schedEnableToggle.checked = sched.enabled;
    schedIntervalInput.value = sched.interval_minutes;

    if (sched.enabled) {
      schedToggleLabel.textContent = 'Active';
      schedToggleLabel.classList.add('active');
      schedStateVal.textContent = `Running every ${sched.interval_minutes}m`;
      schedDot.classList.add('active');
      schedStatusText.textContent = `Active (${sched.interval_minutes}m)`;
      schedTabIndicator.classList.add('active');
    } else {
      schedToggleLabel.textContent = 'Inactive';
      schedToggleLabel.classList.remove('active');
      schedStateVal.textContent = 'Disabled';
      schedDot.classList.remove('active');
      schedStatusText.textContent = 'Disabled';
      schedCountdownText.textContent = 'Scheduler';
      schedTabIndicator.classList.remove('active');
    }

    if (sched.next_run_in_seconds != null) {
      nextRunSeconds = sched.next_run_in_seconds;
    } else {
      nextRunSeconds = null;
    }
  }


  // ── Pipeline Runner & Live Console ────────────────────────────────────────
  window.triggerRun = async function (dryRun = true) {
    if (isRunning) return;

    const selectedScrapers = [];
    if (document.getElementById('headerScraperFlipkart')?.checked) selectedScrapers.push('flipkart');
    if (document.getElementById('headerScraperMyntra')?.checked) selectedScrapers.push('myntra');
    if (document.getElementById('headerScraperTataCliq')?.checked) selectedScrapers.push('tatacliq');

    if (selectedScrapers.length === 0) {
      showToast('Select at least one retailer scraper', 'error');
      return;
    }

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dry_run: dryRun,
          scrapers: selectedScrapers.length === 3 ? null : selectedScrapers
        }),
      });
      const data = await res.json();
      if (res.ok) {
        const scraperDesc = selectedScrapers.length === 3 ? 'all scrapers' : selectedScrapers.join(', ');
        showToast(`Scanner started (${dryRun ? 'Dry Run' : 'Live'} | ${scraperDesc})`, 'info');
        setRunningState(true);
      } else {
        showToast(data.error || 'Could not start runner', 'error');
      }
    } catch (err) {
      showToast('Error: ' + err.message, 'error');
    }
  };

  btnHeaderRun.addEventListener('click', () => {
    const dryRun = headerDryRun.checked;
    triggerRun(dryRun);
  });

  btnTriggerTerminalRun.addEventListener('click', () => {
    const dryRun = headerDryRun.checked;
    triggerRun(dryRun);
  });

  const abortRun = async () => {
    if (!isRunning) return;
    try {
      if (btnHeaderAbort) {
        btnHeaderAbort.disabled = true;
        if (abortSpinner) abortSpinner.style.display = 'inline-block';
        if (abortIcon) abortIcon.style.display = 'none';
        if (abortButtonText) abortButtonText.textContent = 'Aborting...';
      }
      if (btnTriggerTerminalAbort) {
        btnTriggerTerminalAbort.disabled = true;
        btnTriggerTerminalAbort.textContent = 'Aborting...';
      }

      showToast('Aborting scanner... Dumping collected deals', 'warning');

      const res = await fetch('/api/stop', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || 'Could not abort scanner', 'error');
      } else {
        showToast('Scan stopped. Dumping results to seen_deals...', 'info');
        setTimeout(async () => {
          await pollStatus();
          await loadDeals();
        }, 1000);
      }
    } catch (err) {
      showToast('Error aborting scanner: ' + err.message, 'error');
    }
  };

  if (btnHeaderAbort) {
    btnHeaderAbort.addEventListener('click', abortRun);
  }

  if (btnTriggerTerminalAbort) {
    btnTriggerTerminalAbort.addEventListener('click', abortRun);
  }

  function setRunningState(running) {
    isRunning = running;
    if (running) {
      btnHeaderRun.disabled = true;
      btnHeaderRun.classList.add('loading');
      runButtonText.textContent = 'Scanning...';
      consoleLivePulse.classList.add('active');

      if (btnHeaderAbort) {
        btnHeaderAbort.style.display = 'inline-flex';
        btnHeaderAbort.disabled = false;
        if (abortSpinner) abortSpinner.style.display = 'none';
        if (abortIcon) abortIcon.style.display = 'inline-block';
        if (abortButtonText) abortButtonText.textContent = 'Abort & Dump';
      }
      if (btnTriggerTerminalAbort) {
        btnTriggerTerminalAbort.style.display = 'inline-block';
        btnTriggerTerminalAbort.disabled = false;
        btnTriggerTerminalAbort.textContent = '🛑 Abort & Dump';
      }
      if (btnTriggerTerminalRun) {
        btnTriggerTerminalRun.disabled = true;
      }
    } else {
      btnHeaderRun.disabled = false;
      btnHeaderRun.classList.remove('loading');
      runButtonText.textContent = 'Run Now';
      consoleLivePulse.classList.remove('active');

      if (btnHeaderAbort) {
        btnHeaderAbort.style.display = 'none';
        btnHeaderAbort.disabled = false;
        if (abortSpinner) abortSpinner.style.display = 'none';
        if (abortIcon) abortIcon.style.display = 'inline-block';
        if (abortButtonText) abortButtonText.textContent = 'Abort & Dump';
      }
      if (btnTriggerTerminalAbort) {
        btnTriggerTerminalAbort.style.display = 'none';
        btnTriggerTerminalAbort.disabled = false;
        btnTriggerTerminalAbort.textContent = '🛑 Abort & Dump';
      }
      if (btnTriggerTerminalRun) {
        btnTriggerTerminalRun.disabled = false;
      }
    }
  }

  btnClearTerminal.addEventListener('click', async () => {
    terminalWindow.innerHTML = '';
    await fetch('/api/logs/clear', { method: 'POST' });
  });

  // ── Polling & Countdown Loop ──────────────────────────────────────────────
  async function pollStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();

      // Runner state transition
      if (data.is_running !== isRunning) {
        setRunningState(data.is_running);
        if (!data.is_running) {
          // If just finished, reload deals & trackers!
          loadDeals();
          loadTrackers();
        }
      }

      // Database stats update
      if (data.database) {
        if (data.database.total_deals != null && statDealsCount) {
          statDealsCount.textContent = data.database.total_deals;
          if (tabDealsBadge) tabDealsBadge.textContent = data.database.total_deals;
        }
        if (data.database.ignored_count != null && statIgnoredCount) {
          statIgnoredCount.textContent = data.database.ignored_count;
          if (ignoredBadge) ignoredBadge.textContent = data.database.ignored_count;
        }
      }

      // Trackers telemetry update
      if (data.trackers && tabTrackersBadge) {
        tabTrackersBadge.textContent = data.trackers.active ?? 0;
      }

      // Terminal logs rendering
      if (data.logs && data.logs.length > 0) {
        renderTerminalLogs(data.logs);
      }

      // Scheduler status
      if (data.scheduler) {
        updateSchedulerUI(data.scheduler);
      }

      if (data.last_run_time) {
        const dt = new Date(data.last_run_time);
        schedLastRunVal.textContent = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
    } catch (err) {
      console.warn('Status poll error', err);
    }
  }

  function renderTerminalLogs(lines) {
    const text = lines.map(line => {
      // Strip ANSI escape codes
      const clean = line.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
      return `<div class="terminal-line">${escapeHtml(clean)}</div>`;
    }).join('');

    terminalWindow.innerHTML = text;

    if (chkAutoScroll.checked) {
      terminalWindow.scrollTop = terminalWindow.scrollHeight;
    }
  }

  // Local ticker for smooth second-by-second countdown
  setInterval(() => {
    if (nextRunSeconds != null && nextRunSeconds > 0) {
      nextRunSeconds--;
      const mins = Math.floor(nextRunSeconds / 60);
      const secs = nextRunSeconds % 60;
      const formatted = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
      schedCountdownVal.textContent = formatted;
      schedCountdownText.textContent = `Next in ${formatted}`;
    } else if (nextRunSeconds === 0) {
      schedCountdownVal.textContent = '00:00';
      schedCountdownText.textContent = 'Triggering...';
    } else {
      schedCountdownVal.textContent = '--:--';
    }
  }, 1000);

  // ── Color Theme Management ───────────────────────────────────────────────
  const themeSelector = document.getElementById('themeSelector');
  if (themeSelector) {
    const savedTheme = localStorage.getItem('shopexpert_theme') || 'midnight';
    themeSelector.value = savedTheme;
    if (savedTheme !== 'midnight') {
      document.body.setAttribute('data-theme', savedTheme);
    }

    themeSelector.addEventListener('change', () => {
      const selected = themeSelector.value;
      if (selected === 'midnight') {
        document.body.removeAttribute('data-theme');
      } else {
        document.body.setAttribute('data-theme', selected);
      }
      localStorage.setItem('shopexpert_theme', selected);
      showToast(`Color theme set to ${themeSelector.options[themeSelector.selectedIndex].text}`, 'info');
    });
  }

  // ── Agent Scout Functionality ─────────────────────────────────────────────
  let agentDeals = [];
  let currentAgentParams = null;
  let agentVerdictFilter = 'qualified';

  const agentSearchForm = document.getElementById('agentSearchForm');
  const agentInput = document.getElementById('agentInput');
  const btnAgentSubmit = document.getElementById('btnAgentSubmit');
  const btnAgentAbort = document.getElementById('btnAgentAbort');
  const btnAbortScoutStatus = document.getElementById('btnAbortScoutStatus');
  const agentSpinner = document.getElementById('agentSpinner');
  const agentBtnIcon = document.getElementById('agentBtnIcon');
  const agentBtnText = document.getElementById('agentBtnText');
  const agentStatusCard = document.getElementById('agentStatusCard');
  const agentStatusTitle = document.getElementById('agentStatusTitle');
  const agentStep1 = document.getElementById('agentStep1');
  const agentStep2 = document.getElementById('agentStep2');
  const agentStep3 = document.getElementById('agentStep3');
  const agentResultsSection = document.getElementById('agentResultsSection');
  const agentParamsPills = document.getElementById('agentParamsPills');
  const agentDealsContainer = document.getElementById('agentDealsContainer');
  const agentEmptyState = document.getElementById('agentEmptyState');

  const afQualified = document.getElementById('af-qualified');
  const afAll = document.getElementById('af-all');
  const afSteal = document.getElementById('af-steal');
  const afWorth = document.getElementById('af-worth');
  const afSkip = document.getElementById('af-skip');
  const afCountQualified = document.getElementById('afCountQualified');
  const afCountAll = document.getElementById('afCountAll');
  const afCountSteal = document.getElementById('afCountSteal');
  const afCountWorth = document.getElementById('afCountWorth');
  const afCountSkip = document.getElementById('afCountSkip');

  function setAgentStep(stepNum, allDone = false) {
    [agentStep1, agentStep2, agentStep3].forEach((el, idx) => {
      if (!el) return;
      const num = idx + 1;
      el.classList.remove('active', 'done');
      if (allDone || num < stepNum) {
        el.classList.add('done');
      } else if (num === stepNum) {
        el.classList.add('active');
      }
    });
    if (!agentStatusTitle) return;
    if (stepNum === 1) agentStatusTitle.textContent = 'Stage 1: Parsing search parameters & constraints...';
    if (stepNum === 2) agentStatusTitle.textContent = 'Stage 2: Crawling Flipkart, Myntra, TataCLiQ...';
    if (stepNum === 3 && !allDone) agentStatusTitle.textContent = 'Stage 3: LLM evaluating deal quality & sizes...';
    if (allDone) agentStatusTitle.textContent = 'Evaluation complete!';
  }

  function renderAgentParams(params) {
    if (!agentParamsPills) return;
    let chips = [];
    if (params.queries && params.queries.length) {
      chips.push(`<span class="agent-param-chip">🔍 Query: <strong>${escapeHtml(params.queries.join(', '))}</strong></span>`);
    }
    if (params.brands && params.brands.length) {
      chips.push(`<span class="agent-param-chip">🏷️ Brand: <strong>${escapeHtml(params.brands.join(', '))}</strong></span>`);
    }
    if (params.target_sizes && params.target_sizes.length) {
      chips.push(`<span class="agent-param-chip">📏 Sizes: <strong>${escapeHtml(params.target_sizes.join(', '))}</strong></span>`);
    }
    if (params.max_price) {
      chips.push(`<span class="agent-param-chip">💰 Max: <strong>₹${Number(params.max_price).toLocaleString('en-IN')}</strong></span>`);
    }
    if (params.min_discount_pct) {
      chips.push(`<span class="agent-param-chip">🔥 Min Disc: <strong>${params.min_discount_pct}%</strong></span>`);
    }
    agentParamsPills.innerHTML = chips.join('');
  }

  function renderAgentDeals() {
    if (!agentDeals || agentDeals.length === 0) {
      if (agentResultsSection) agentResultsSection.style.display = 'none';
      if (agentEmptyState) {
        agentEmptyState.style.display = 'block';
        agentEmptyState.querySelector('h3').textContent = 'No matching deals found';
        agentEmptyState.querySelector('p').textContent = 'Try asking with broader criteria or lower discount requirements.';
      }
      return;
    }

    if (agentEmptyState) agentEmptyState.style.display = 'none';
    if (agentResultsSection) agentResultsSection.style.display = 'block';

    const steals = agentDeals.filter(d => (d.verdict || d.agent_verdict || '').toUpperCase() === 'STEAL').length;
    const worths = agentDeals.filter(d => (d.verdict || d.agent_verdict || '').toUpperCase() === 'WORTH_IT').length;
    const skips = agentDeals.filter(d => (d.verdict || d.agent_verdict || '').toUpperCase() === 'SKIP').length;
    const qualified = steals + worths;

    if (afCountQualified) afCountQualified.textContent = qualified;
    if (afCountAll) afCountAll.textContent = agentDeals.length;
    if (afCountSteal) afCountSteal.textContent = steals;
    if (afCountWorth) afCountWorth.textContent = worths;
    if (afCountSkip) afCountSkip.textContent = skips;

    let filtered = agentDeals.filter(d => {
      const v = (d.verdict || d.agent_verdict || '').toUpperCase();
      if (agentVerdictFilter === 'qualified') {
        return v === 'STEAL' || v === 'WORTH_IT';
      }
      if (agentVerdictFilter === 'all') return true;
      return v === agentVerdictFilter;
    });

    const activeTargets = (currentAgentParams?.target_sizes && currentAgentParams.target_sizes.length > 0)
      ? currentAgentParams.target_sizes
      : (currentConfig?.watchlist?.target_sizes || []);
    const targetSizes = activeTargets.map(s => String(s).toUpperCase());

    if (agentDealsContainer) {
      if (filtered.length === 0) {
        agentDealsContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 32px;">No deals match this verdict filter.</div>';
      } else {
        agentDealsContainer.innerHTML = filtered.map(d => buildDealCardHtml(d, targetSizes)).join('');
      }
    }
  }

  let currentAgentAbortController = null;

  async function abortAgentSearch() {
    if (currentAgentAbortController) {
      currentAgentAbortController.abort();
      currentAgentAbortController = null;
    }
    try {
      await fetch('/api/agent/abort', { method: 'POST' });
    } catch (_) {}
    showToast('Scouting aborted', 'warning');
    if (agentStatusCard) agentStatusCard.style.display = 'none';
    if (btnAgentSubmit) {
      btnAgentSubmit.style.display = 'inline-flex';
      btnAgentSubmit.disabled = false;
    }
    if (btnAgentAbort) btnAgentAbort.style.display = 'none';
    if (agentSpinner) agentSpinner.style.display = 'none';
    if (agentBtnIcon) agentBtnIcon.style.display = 'inline-block';
    if (agentBtnText) agentBtnText.textContent = 'Ask Agent';
  }

  if (btnAgentAbort) {
    btnAgentAbort.addEventListener('click', abortAgentSearch);
  }
  if (btnAbortScoutStatus) {
    btnAbortScoutStatus.addEventListener('click', abortAgentSearch);
  }

  async function runAgentSearch(query) {
    if (!query || !query.trim()) return;
    query = query.trim();

    if (agentStatusCard) agentStatusCard.style.display = 'block';
    if (agentResultsSection) agentResultsSection.style.display = 'none';
    if (agentEmptyState) agentEmptyState.style.display = 'none';
    if (btnAgentSubmit) btnAgentSubmit.style.display = 'none';
    if (btnAgentAbort) btnAgentAbort.style.display = 'inline-flex';

    setAgentStep(1);
    const step2Timer = setTimeout(() => setAgentStep(2), 2500);
    const step3Timer = setTimeout(() => setAgentStep(3), 8500);

    currentAgentAbortController = new AbortController();

    try {
      const resp = await fetch('/api/agent/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
        signal: currentAgentAbortController.signal,
      });
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || data.detail || 'Agent search failed');
      }

      setAgentStep(3, true);
      agentDeals = data.deals || [];
      currentAgentParams = data.params || {};
      renderAgentParams(data.params || {});
      renderAgentDeals();
      loadDeals(); // Refresh main deals list in background
      showToast(`Scout found ${agentDeals.length} deals!`, 'success');
    } catch (err) {
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);
      if (err.name === 'AbortError') {
        showToast('Scouting cancelled', 'warning');
        return;
      }
      showToast('Agent Error: ' + err.message, 'error');
      if (agentEmptyState) {
        agentEmptyState.style.display = 'block';
        agentEmptyState.querySelector('h3').textContent = 'Search Failed';
        agentEmptyState.querySelector('p').textContent = err.message;
      }
    } finally {
      currentAgentAbortController = null;
      if (agentStatusCard) agentStatusCard.style.display = 'none';
      if (btnAgentSubmit) {
        btnAgentSubmit.style.display = 'inline-flex';
        btnAgentSubmit.disabled = false;
      }
      if (btnAgentAbort) btnAgentAbort.style.display = 'none';
      if (agentSpinner) agentSpinner.style.display = 'none';
      if (agentBtnIcon) agentBtnIcon.style.display = 'inline-block';
      if (agentBtnText) agentBtnText.textContent = 'Ask Agent';
    }
  }

  if (agentSearchForm) {
    agentSearchForm.addEventListener('submit', e => {
      e.preventDefault();
      runAgentSearch(agentInput?.value || '');
    });
  }

  document.querySelectorAll('.agent-chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (agentInput) agentInput.value = btn.dataset.query;
      runAgentSearch(btn.dataset.query);
    });
  });

  [afQualified, afAll, afSteal, afWorth, afSkip].forEach(btn => {
    if (!btn) return;
    btn.addEventListener('click', () => {
      [afQualified, afAll, afSteal, afWorth, afSkip].forEach(b => b?.classList.remove('active'));
      btn.classList.add('active');
      agentVerdictFilter = btn.dataset.verdict;
      renderAgentDeals();
    });
  });

  if (agentDealsContainer) {
    agentDealsContainer.addEventListener('click', e => {
      const feedbackBtn = e.target.closest('.deal-feedback-btn');
      if (feedbackBtn) {
        const dealId = feedbackBtn.dataset.dealId;
        const action = feedbackBtn.dataset.action;
        handleFeedbackClick(dealId, action, feedbackBtn);
        return;
      }

      const histBtn = e.target.closest('.deal-history-btn');
      if (histBtn) {
        const dealId = histBtn.dataset.dealId;
        const title = histBtn.dataset.title;
        const mrp = parseFloat(histBtn.dataset.mrp) || 0;
        const price = parseFloat(histBtn.dataset.price) || 0;
        showPriceHistory(dealId, title, mrp, price);
        return;
      }

      const ignoreBtn = e.target.closest('.deal-ignore-btn');
      if (ignoreBtn) {
        const dealId = ignoreBtn.dataset.dealId;
        const brand = ignoreBtn.dataset.brand;
        const title = ignoreBtn.dataset.title;
        const product_url = ignoreBtn.dataset.url;
        const sale_price = parseFloat(ignoreBtn.dataset.price) || 0;
        const source = ignoreBtn.dataset.source;
        handleIgnoreDeal(dealId, { brand, title, product_url, sale_price, source });
        agentDeals = agentDeals.filter(d => (d.deal_id || d.product_url) !== dealId);
        renderAgentDeals();
      }
    });
  }

  // ── Price History Modal & Canvas Chart ──────────────────────────────────────
  const priceHistoryModal = document.getElementById('priceHistoryModal');
  const btnCloseHistoryModal = document.getElementById('btnCloseHistoryModal');
  const historyModalTitle = document.getElementById('historyModalTitle');
  const historyModalSubtitle = document.getElementById('historyModalSubtitle');
  const histMinPrice = document.getElementById('histMinPrice');
  const histCurrentPrice = document.getElementById('histCurrentPrice');
  const histMrp = document.getElementById('histMrp');
  const priceHistoryChart = document.getElementById('priceHistoryChart');
  const historyTableBody = document.getElementById('historyTableBody');

  if (btnCloseHistoryModal) {
    btnCloseHistoryModal.addEventListener('click', () => {
      if (priceHistoryModal) priceHistoryModal.style.display = 'none';
    });
  }

  if (priceHistoryModal) {
    priceHistoryModal.addEventListener('click', e => {
      if (e.target === priceHistoryModal) priceHistoryModal.style.display = 'none';
    });
  }

  async function showPriceHistory(dealId, title, mrp, currentPrice) {
    if (!priceHistoryModal) return;
    if (historyModalTitle) historyModalTitle.textContent = title || 'Price History';
    if (historyModalSubtitle) historyModalSubtitle.textContent = `Product ID: ${dealId}`;
    if (histCurrentPrice) histCurrentPrice.textContent = `₹${Number(currentPrice || 0).toLocaleString('en-IN')}`;
    if (histMrp) histMrp.textContent = mrp ? `₹${Number(mrp).toLocaleString('en-IN')}` : 'N/A';
    if (historyTableBody) {
      historyTableBody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:16px;">Loading price data...</td></tr>';
    }
    priceHistoryModal.style.display = 'flex';

    try {
      const res = await fetch(`/api/deals/history?deal_id=${encodeURIComponent(dealId)}`);
      const data = await res.json();
      let history = data.history || [];

      if (history.length === 0) {
        history = [{
          recorded_at: new Date().toISOString(),
          sale_price: currentPrice || 0,
          discount_pct: mrp && currentPrice ? Math.round(((mrp - currentPrice) / mrp) * 100) : 0,
        }];
      }

      const minP = Math.min(...history.map(h => Number(h.sale_price)));
      if (histMinPrice) histMinPrice.textContent = `₹${minP.toLocaleString('en-IN')}`;

      if (historyTableBody) {
        historyTableBody.innerHTML = history.slice().reverse().map(h => {
          let t = h.recorded_at;
          try {
            const dt = new Date(h.recorded_at);
            t = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + dt.toLocaleDateString([], { month: 'short', day: 'numeric' });
          } catch {}
          return `
            <tr>
              <td>${escapeHtml(t)}</td>
              <td><strong>₹${Number(h.sale_price).toLocaleString('en-IN')}</strong></td>
              <td>${h.discount_pct ? `${Math.round(h.discount_pct)}% OFF` : '-'}</td>
            </tr>
          `;
        }).join('');
      }

      drawPriceChart(priceHistoryChart, history);
    } catch (err) {
      if (historyTableBody) {
        historyTableBody.innerHTML = `<tr><td colspan="3" class="text-danger" style="text-align:center;">Failed to load history: ${err.message}</td></tr>`;
      }
    }
  }

  function drawPriceChart(canvas, history) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || 600;
    const height = 220;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    if (!history || history.length === 0) return;

    const padding = { top: 20, right: 30, bottom: 35, left: 60 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    const prices = history.map(h => Number(h.sale_price));
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = (maxPrice - minPrice) || (maxPrice * 0.1) || 100;
    const yMin = Math.max(0, minPrice - priceRange * 0.15);
    const yMax = maxPrice + priceRange * 0.15;

    // Grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 1;
    const gridSteps = 4;
    for (let i = 0; i <= gridSteps; i++) {
      const y = padding.top + (chartH / gridSteps) * i;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();

      const priceVal = Math.round(yMax - ((yMax - yMin) / gridSteps) * i);
      ctx.fillStyle = '#64748b';
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`₹${priceVal.toLocaleString('en-IN')}`, padding.left - 8, y + 4);
    }

    const pts = history.map((h, i) => {
      const x = history.length === 1
        ? padding.left + chartW / 2
        : padding.left + (chartW / (history.length - 1)) * i;
      const y = padding.top + chartH - ((h.sale_price - yMin) / (yMax - yMin)) * chartH;
      return { x, y, price: h.sale_price, date: h.recorded_at };
    });

    if (pts.length > 1) {
      const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
      gradient.addColorStop(0, 'rgba(56, 189, 248, 0.35)');
      gradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');

      ctx.beginPath();
      ctx.moveTo(pts[0].x, padding.top + chartH);
      pts.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.lineTo(pts[pts.length - 1].x, padding.top + chartH);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      pts.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }

    pts.forEach((p, idx) => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#38bdf8';
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 2;
      ctx.stroke();

      if (idx === 0 || idx === pts.length - 1 || history.length <= 4) {
        try {
          const dt = new Date(p.date);
          const lbl = `${dt.getDate()}/${dt.getMonth() + 1}`;
          ctx.fillStyle = '#94a3b8';
          ctx.font = '10px Inter, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(lbl, p.x, height - 10);
        } catch {}
      }
    });
  }

  // ── Price Trackers Management (V2) ──────────────────────────────────────────
  let allTrackers = [];
  let currentTrackerFilter = 'all';
  let candidateProducts = [];

  const trackersContainer = document.getElementById('trackersContainer');
  const trackersEmptyState = document.getElementById('trackersEmptyState');
  const btnCheckTrackersNow = document.getElementById('btnCheckTrackersNow');
  const trackerCheckSpinner = document.getElementById('trackerCheckSpinner');
  const trackerCheckBtnIcon = document.getElementById('trackerCheckBtnIcon');
  const trackerCheckBtnText = document.getElementById('trackerCheckBtnText');
  const btnRefreshTrackers = document.getElementById('btnRefreshTrackers');

  const trackerInputQuery = document.getElementById('trackerInputQuery');
  const trackerInputTargetPrice = document.getElementById('trackerInputTargetPrice');
  const trackerInputSize = document.getElementById('trackerInputSize');
  const trackerInputInterval = document.getElementById('trackerInputInterval');
  const trackerInputLimit = document.getElementById('trackerInputLimit');
  const btnPreviewCandidates = document.getElementById('btnPreviewCandidates');
  const btnDirectTrack = document.getElementById('btnDirectTrack');
  const previewSpinner = document.getElementById('previewSpinner');
  const previewBtnIcon = document.getElementById('previewBtnIcon');
  const previewBtnText = document.getElementById('previewBtnText');

  const trackerCandidatesBox = document.getElementById('trackerCandidatesBox');
  const candidatesCount = document.getElementById('candidatesCount');
  const candidatesGrid = document.getElementById('candidatesGrid');
  const btnSelectAllCandidates = document.getElementById('btnSelectAllCandidates');
  const btnTrackSelected = document.getElementById('btnTrackSelected');
  const btnCloseCandidates = document.getElementById('btnCloseCandidates');

  const tfAll = document.getElementById('tf-all');
  const tfActive = document.getElementById('tf-active');
  const tfPaused = document.getElementById('tf-paused');
  const tfHit = document.getElementById('tf-hit');
  const tfCountAll = document.getElementById('tfCountAll');
  const tfCountActive = document.getElementById('tfCountActive');
  const tfCountPaused = document.getElementById('tfCountPaused');
  const tfCountHit = document.getElementById('tfCountHit');

  async function loadTrackers() {
    try {
      const res = await fetch('/api/trackers');
      const data = await res.json();
      allTrackers = data.trackers || [];

      const activeCount = allTrackers.filter(t => t.status === 'ACTIVE').length;
      const pausedCount = allTrackers.filter(t => t.status === 'PAUSED').length;
      const hitCount = allTrackers.filter(t => t.status === 'TRIGGERED' || t.status === 'HIT').length;

      if (tfCountAll) tfCountAll.textContent = allTrackers.length;
      if (tfCountActive) tfCountActive.textContent = activeCount;
      if (tfCountPaused) tfCountPaused.textContent = pausedCount;
      if (tfCountHit) tfCountHit.textContent = hitCount;
      if (tabTrackersBadge) tabTrackersBadge.textContent = activeCount;

      renderTrackers();
    } catch (err) {
      if (trackersContainer) {
        trackersContainer.innerHTML = `<div class="empty-state"><p class="text-danger">Failed to load trackers: ${err.message}</p></div>`;
      }
    }
  }

  function renderTrackers() {
    if (!trackersContainer) return;

    let filtered = allTrackers.filter(t => {
      if (currentTrackerFilter === 'all') return true;
      if (currentTrackerFilter === 'HIT' || currentTrackerFilter === 'TRIGGERED') {
        return t.status === 'TRIGGERED' || t.status === 'HIT';
      }
      return t.status === currentTrackerFilter;
    });

    if (filtered.length === 0) {
      trackersContainer.style.display = 'none';
      if (trackersEmptyState) {
        trackersEmptyState.style.display = 'block';
        trackersEmptyState.querySelector('h3').textContent = currentTrackerFilter === 'all'
          ? 'No price trackers configured'
          : `No ${currentTrackerFilter.toLowerCase()} trackers`;
      }
      return;
    }

    if (trackersEmptyState) trackersEmptyState.style.display = 'none';
    trackersContainer.style.display = 'grid';

    trackersContainer.innerHTML = filtered.map(t => {
      const isHit = t.status === 'TRIGGERED' || t.status === 'HIT';
      const isPaused = t.status === 'PAUSED';
      const statusClass = isHit ? 'hit' : (isPaused ? 'paused' : 'active');
      const statusIcon = isHit ? '✨' : (isPaused ? '⏸️' : '●');
      const statusLabel = isHit ? 'TARGET HIT' : escapeHtml(t.status);
      const targetP = Math.round(t.target_price || 0);
      const currentP = t.current_price ? Math.round(t.current_price) : null;

      let lastCheckedStr = 'Never';
      const lastCheckedVal = t.last_checked || t.last_checked_at;
      if (lastCheckedVal) {
        try {
          const dt = new Date(lastCheckedVal);
          lastCheckedStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + dt.toLocaleDateString([], { month: 'short', day: 'numeric' });
        } catch {}
      }

      return `
        <div class="tracker-card status-${statusClass}" id="tracker-${t.id}">
          <div class="tracker-top-row">
            ${getStoreBadgeHtml(t.source)}
            <span class="tracker-status-badge ${statusClass}">${statusIcon} ${statusLabel}</span>
          </div>

          <div class="tracker-product-body">
            ${t.image_url ? `
              <img src="${escapeHtml(t.image_url)}" alt="${escapeHtml(t.title || '')}" class="tracker-thumb" loading="lazy" onerror="this.onerror=null; this.style.display='none';">
            ` : ''}
            <div class="tracker-product-info">
              <h4 class="tracker-title" title="${escapeHtml(t.title || t.target_input)}">${escapeHtml(t.title || t.target_input)}</h4>
              <div style="font-size:0.75rem; color:var(--text-dim); margin-top:2px;">
                ${t.target_size ? `Size: <strong>${escapeHtml(t.target_size)}</strong> · ` : ''}Interval: ${t.check_interval || t.check_interval_mins || 30}m
              </div>
            </div>
          </div>

          <div class="tracker-pricing-bar">
            <div>
              <span style="font-size:0.75rem; color:var(--text-muted); display:block;">Target Price</span>
              <span class="target-val">₹${targetP.toLocaleString('en-IN')}</span>
            </div>
            <div style="text-align: right;">
              <span style="font-size:0.75rem; color:var(--text-muted); display:block;">Current Price</span>
              <span class="current-val">${currentP ? `₹${currentP.toLocaleString('en-IN')}` : 'Pending'}</span>
            </div>
          </div>

          <div class="tracker-meta-row">
            <span>Checked: ${escapeHtml(lastCheckedStr)}</span>
            <span>Triggered: ${t.alert_count || t.triggered_count || 0} times</span>
          </div>

          <div class="tracker-footer-actions">
            ${t.product_url ? `
              <a href="${escapeHtml(t.product_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-outline">View ↗</a>
            ` : ''}
            ${isPaused ? `
              <button class="btn btn-sm btn-outline tracker-resume-btn" data-id="${t.id}" title="Resume monitoring">▶ Resume</button>
            ` : `
              <button class="btn btn-sm btn-outline tracker-pause-btn" data-id="${t.id}" title="Pause monitoring">⏸ Pause</button>
            `}
            <button class="btn btn-sm btn-outline tracker-delete-btn" data-id="${t.id}" style="color:#f87171;" title="Delete tracker">🗑 Delete</button>
          </div>
        </div>
      `;
    }).join('');
  }

  // Filter tab buttons
  [tfAll, tfActive, tfPaused, tfHit].forEach(btn => {
    if (!btn) return;
    btn.addEventListener('click', () => {
      [tfAll, tfActive, tfPaused, tfHit].forEach(b => b?.classList.remove('active'));
      btn.classList.add('active');
      currentTrackerFilter = btn.dataset.status;
      renderTrackers();
    });
  });

  if (btnRefreshTrackers) {
    btnRefreshTrackers.addEventListener('click', () => {
      loadTrackers();
      showToast('Trackers list refreshed', 'info');
    });
  }

  // Tracker Card Action Delegation
  if (trackersContainer) {
    trackersContainer.addEventListener('click', async e => {
      const pauseBtn = e.target.closest('.tracker-pause-btn');
      if (pauseBtn) {
        const id = pauseBtn.dataset.id;
        try {
          const res = await fetch(`/api/trackers/${id}/pause`, { method: 'POST' });
          if (res.ok) {
            showToast('Tracker paused', 'info');
            loadTrackers();
          }
        } catch (err) {
          showToast('Failed to pause: ' + err.message, 'error');
        }
        return;
      }

      const resumeBtn = e.target.closest('.tracker-resume-btn');
      if (resumeBtn) {
        const id = resumeBtn.dataset.id;
        try {
          const res = await fetch(`/api/trackers/${id}/resume`, { method: 'POST' });
          if (res.ok) {
            showToast('Tracker resumed', 'success');
            loadTrackers();
          }
        } catch (err) {
          showToast('Failed to resume: ' + err.message, 'error');
        }
        return;
      }

      const deleteBtn = e.target.closest('.tracker-delete-btn');
      if (deleteBtn) {
        const id = deleteBtn.dataset.id;
        if (!confirm('Are you sure you want to delete this price tracker?')) return;
        try {
          const res = await fetch(`/api/trackers/${id}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Tracker deleted', 'info');
            loadTrackers();
          }
        } catch (err) {
          showToast('Failed to delete: ' + err.message, 'error');
        }
        return;
      }
    });
  }

  // Check All Trackers Now
  if (btnCheckTrackersNow) {
    btnCheckTrackersNow.addEventListener('click', async () => {
      btnCheckTrackersNow.disabled = true;
      if (trackerCheckSpinner) trackerCheckSpinner.style.display = 'inline-block';
      if (trackerCheckBtnIcon) trackerCheckBtnIcon.style.display = 'none';
      if (trackerCheckBtnText) trackerCheckBtnText.textContent = 'Checking...';

      try {
        const res = await fetch('/api/trackers/check', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          showToast(`Checked ${data.checked || 0} trackers. ${data.alerts || 0} alerts sent!`, 'success');
          loadTrackers();
        } else {
          showToast(data.detail || 'Tracker check failed', 'error');
        }
      } catch (err) {
        showToast('Error checking trackers: ' + err.message, 'error');
      } finally {
        btnCheckTrackersNow.disabled = false;
        if (trackerCheckSpinner) trackerCheckSpinner.style.display = 'none';
        if (trackerCheckBtnIcon) trackerCheckBtnIcon.style.display = 'inline-block';
        if (trackerCheckBtnText) trackerCheckBtnText.textContent = 'Check All Trackers';
      }
    });
  }

  // Update search button text when limit dropdown changes
  if (trackerInputLimit) {
    trackerInputLimit.addEventListener('change', () => {
      const lim = trackerInputLimit.value || '20';
      if (previewBtnText) previewBtnText.textContent = `Search Preview (${lim})`;
    });
  }

  // Candidate Preview Search
  if (btnPreviewCandidates) {
    btnPreviewCandidates.addEventListener('click', async () => {
      const q = (trackerInputQuery?.value || '').trim();
      if (!q) {
        showToast('Enter a keyword or product URL to search', 'warning');
        return;
      }

      const limit = parseInt(trackerInputLimit?.value || '20', 10);
      btnPreviewCandidates.disabled = true;
      if (previewSpinner) previewSpinner.style.display = 'inline-block';
      if (previewBtnIcon) previewBtnIcon.style.display = 'none';
      if (previewBtnText) previewBtnText.textContent = 'Searching...';

      try {
        const res = await fetch(`/api/trackers/search?keyword=${encodeURIComponent(q)}&limit=${limit}&force_scrape=true`);
        const data = await res.json();
        candidateProducts = data.candidates || [];

        if (candidatesCount) candidatesCount.textContent = candidateProducts.length;

        if (candidateProducts.length === 0) {
          showToast('No candidates found matching that query', 'info');
          if (trackerCandidatesBox) trackerCandidatesBox.style.display = 'none';
        } else {
          renderCandidatesGrid();
          if (trackerCandidatesBox) trackerCandidatesBox.style.display = 'block';
          showToast(`Found ${candidateProducts.length} candidate products`, 'success');
        }
      } catch (err) {
        showToast('Error searching candidates: ' + err.message, 'error');
      } finally {
        btnPreviewCandidates.disabled = false;
        if (previewSpinner) previewSpinner.style.display = 'none';
        if (previewBtnIcon) previewBtnIcon.style.display = 'inline-block';
        if (previewBtnText) previewBtnText.textContent = `Search Preview (${limit})`;
      }
    });
  }

  function renderCandidatesGrid() {
    if (!candidatesGrid) return;
    const defaultTarget = parseFloat(trackerInputTargetPrice?.value) || null;

    candidatesGrid.innerHTML = candidateProducts.map((c, idx) => {
      const saleP = Math.round(c.sale_price || 0);
      const mrp = Math.round(c.original_price || 0);
      const suggestedTarget = defaultTarget || Math.round(saleP * 0.9);

      return `
        <div class="candidate-card selected" id="candidate-${idx}">
          <div class="candidate-top">
            <input type="checkbox" class="candidate-checkbox" data-idx="${idx}" checked>
            ${c.image_url ? `
              <img src="${escapeHtml(c.image_url)}" alt="${escapeHtml(c.title)}" class="candidate-thumb" loading="lazy" onerror="this.onerror=null; this.style.display='none';">
            ` : ''}
            <div class="candidate-info">
              <div class="candidate-brand">${escapeHtml(c.brand || c.source)}</div>
              <h4 class="candidate-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</h4>
              <div class="candidate-price-row">
                <span class="candidate-sale-price">₹${saleP.toLocaleString('en-IN')}</span>
                ${mrp > saleP ? `<span class="candidate-mrp">₹${mrp.toLocaleString('en-IN')}</span>` : ''}
              </div>
            </div>
          </div>
          <div class="candidate-bottom-row">
            <span style="font-size:0.75rem; color:var(--text-muted);">Target:</span>
            <input type="number" class="text-input candidate-target-input" id="cand-target-${idx}" value="${suggestedTarget}" min="1">
            <a href="${escapeHtml(c.product_url)}" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem; color:var(--accent-cyan);">View ↗</a>
          </div>
        </div>
      `;
    }).join('');
  }

  if (candidatesGrid) {
    candidatesGrid.addEventListener('change', e => {
      const chk = e.target.closest('.candidate-checkbox');
      if (chk) {
        const card = chk.closest('.candidate-card');
        if (card) {
          card.classList.toggle('selected', chk.checked);
        }
      }
    });
  }

  if (btnSelectAllCandidates) {
    btnSelectAllCandidates.addEventListener('click', () => {
      const chks = candidatesGrid?.querySelectorAll('.candidate-checkbox') || [];
      const anyUnchecked = Array.from(chks).some(c => !c.checked);
      chks.forEach(c => {
        c.checked = anyUnchecked;
        c.closest('.candidate-card')?.classList.toggle('selected', anyUnchecked);
      });
      btnSelectAllCandidates.textContent = anyUnchecked ? 'Deselect All' : 'Select All';
    });
  }

  if (btnCloseCandidates) {
    btnCloseCandidates.addEventListener('click', () => {
      if (trackerCandidatesBox) trackerCandidatesBox.style.display = 'none';
    });
  }

  // Track Selected Items
  if (btnTrackSelected) {
    btnTrackSelected.addEventListener('click', async () => {
      const chks = candidatesGrid?.querySelectorAll('.candidate-checkbox:checked') || [];
      if (chks.length === 0) {
        showToast('Select at least one product to track', 'warning');
        return;
      }

      btnTrackSelected.disabled = true;
      btnTrackSelected.textContent = 'Creating Trackers...';

      let createdCount = 0;
      const intervalMins = parseInt(trackerInputInterval?.value || '30', 10);
      const targetSize = (trackerInputSize?.value || '').trim() || null;

      for (const chk of chks) {
        const idx = parseInt(chk.dataset.idx, 10);
        const c = candidateProducts[idx];
        if (!c) continue;

        const targetInputEl = document.getElementById(`cand-target-${idx}`);
        const targetPrice = parseFloat(targetInputEl?.value) || Math.round(c.sale_price * 0.9);

        try {
          const res = await fetch('/api/trackers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_input: c.product_url,
              target_price: targetPrice,
              target_size: targetSize,
              target_type: 'ANY',
              check_interval: intervalMins,
            }),
          });
          if (res.ok) createdCount++;
        } catch (err) {
          console.warn('Tracker create error', err);
        }
      }

      btnTrackSelected.disabled = false;
      btnTrackSelected.textContent = 'Track Selected Items';
      if (trackerCandidatesBox) trackerCandidatesBox.style.display = 'none';

      showToast(`Created ${createdCount} price trackers successfully!`, 'success');
      loadTrackers();
    });
  }

  // Quick Direct Track
  if (btnDirectTrack) {
    btnDirectTrack.addEventListener('click', async () => {
      const q = (trackerInputQuery?.value || '').trim();
      const price = parseFloat(trackerInputTargetPrice?.value);
      if (!q) {
        showToast('Enter a URL or search keyword', 'warning');
        return;
      }
      if (!price || price <= 0) {
        showToast('Enter a valid target price (₹)', 'warning');
        return;
      }

      btnDirectTrack.disabled = true;
      btnDirectTrack.textContent = 'Adding...';

      try {
        const res = await fetch('/api/trackers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            target_input: q,
            target_price: price,
            target_size: (trackerInputSize?.value || '').trim() || null,
            target_type: 'ANY',
            check_interval: parseInt(trackerInputInterval?.value || '30', 10),
          }),
        });
        const data = await res.json();
        if (res.ok) {
          showToast('Tracker created successfully!', 'success');
          if (trackerInputQuery) trackerInputQuery.value = '';
          if (trackerInputTargetPrice) trackerInputTargetPrice.value = '';
          loadTrackers();
        } else {
          showToast(data.detail || 'Failed to create tracker', 'error');
        }
      } catch (err) {
        showToast('Error: ' + err.message, 'error');
      } finally {
        btnDirectTrack.disabled = false;
        btnDirectTrack.textContent = '+ Quick Add';
      }
    });
  }

  // Initialize
  loadDeals();
  loadTrackers();
  loadConfig();
  pollStatus();
  setInterval(pollStatus, 2000);

})();
