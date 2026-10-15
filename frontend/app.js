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

  // DOM Elements
  const tabDeals = document.getElementById('tab-deals');
  const tabConfig = document.getElementById('tab-config');
  const tabScheduler = document.getElementById('tab-scheduler');
  const tabConsole = document.getElementById('tab-console');

  const tabAgent = document.getElementById('tab-agent');
  const panelAgent = document.getElementById('panel-agent');

  const panelDeals = document.getElementById('panel-deals');
  const panelConfig = document.getElementById('panel-config');
  const panelScheduler = document.getElementById('panel-scheduler');
  const panelConsole = document.getElementById('panel-console');
  const verdictFilter = document.getElementById('verdictFilter');

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
    { btn: tabAgent, panel: panelAgent },
    { btn: tabConfig, panel: panelConfig },
    { btn: tabScheduler, panel: panelScheduler },
    { btn: tabConsole, panel: panelConsole },
  ];

  tabs.forEach(t => {
    t.btn.addEventListener('click', () => switchTab(t.btn.dataset.tab));
  });

  function switchTab(tabName) {
    tabs.forEach(t => {
      const isMatch = t.btn.dataset.tab === tabName;
      t.btn.classList.toggle('active', isMatch);
      t.panel.classList.toggle('active', isMatch);
    });
    if (tabName === 'deals') loadDeals();
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
  async function loadDeals() {
    try {
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

    // AI Verdict
    const verdict = (d.agent_verdict || '').toUpperCase();
    const verdictClass = verdict === 'STEAL' ? 'verdict-steal' : (verdict === 'WORTH_IT' ? 'verdict-worth_it' : (verdict === 'SKIP' ? 'verdict-skip' : ''));
    const verdictIcon = verdict === 'STEAL' ? '🔥' : (verdict === 'WORTH_IT' ? '✓' : '✗');
    const verdictLabel = verdict === 'STEAL' ? 'STEAL' : (verdict === 'WORTH_IT' ? 'WORTH IT' : 'SKIP');

    // Sizes markup
    let sizesHtml = '';
    if (d.available_sizes && d.available_sizes.length > 0) {
      sizesHtml = d.available_sizes.slice(0, 10).map(sz => {
        const isTarget = targetSizes.includes(String(sz).toUpperCase());
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
          </div>
        ` : ''}

        <div class="card-top-banner">
          ${getStoreBadgeHtml(d.source)}
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
          ${d.agent_reason ? `
            <div class="agent-reason-card-box ${verdictClass}">
              <strong>🤖 AI Evaluator:</strong> ${escapeHtml(d.agent_reason)}
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
              <button class="deal-ignore-btn" data-deal-id="${escapeHtml(d.deal_id || d.product_url)}" data-brand="${escapeHtml(d.brand || '')}" data-title="${escapeHtml(d.title || '')}" data-url="${escapeHtml(d.product_url || '')}" data-price="${d.sale_price || 0}" data-source="${escapeHtml(d.source || '')}" title="Skip/ignore this product from subsequent scans">
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
        const v = (d.agent_verdict || '').toUpperCase();
        if (v !== verdictFilter.value) return false;
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

  // Click delegation for ignore & unignore
  dealsContainer.addEventListener('click', e => {
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
      if (res.ok) {
        showToast('Seen deals history cleared', 'success');
        loadDeals();
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
        if (res.ok) {
          showToast('Ignored listings cleared', 'success');
          await loadDeals();
        } else {
          showToast('Failed to clear ignored list', 'error');
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
      const disc = row.querySelector('.query-disc').value;
      const minp = row.querySelector('.query-minp').value;
      const maxp = row.querySelector('.query-maxp').value;
      const maxprods = row.querySelector('.query-prods').value;

      if (disc !== '' || minp !== '' || maxp !== '' || maxprods !== '' || retailerVal !== 'all') {
        const item = { query: text };
        if (retailerVal !== 'all') item.scrapers = [retailerVal];
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
          // If just finished, reload deals!
          loadDeals();
        }
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
  let agentVerdictFilter = 'all';

  const agentSearchForm = document.getElementById('agentSearchForm');
  const agentInput = document.getElementById('agentInput');
  const btnAgentSubmit = document.getElementById('btnAgentSubmit');
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

  const afAll = document.getElementById('af-all');
  const afSteal = document.getElementById('af-steal');
  const afWorth = document.getElementById('af-worth');
  const afSkip = document.getElementById('af-skip');
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

    const steals = agentDeals.filter(d => (d.agent_verdict || '').toUpperCase() === 'STEAL').length;
    const worths = agentDeals.filter(d => (d.agent_verdict || '').toUpperCase() === 'WORTH_IT').length;
    const skips = agentDeals.filter(d => (d.agent_verdict || '').toUpperCase() === 'SKIP').length;

    if (afCountAll) afCountAll.textContent = agentDeals.length;
    if (afCountSteal) afCountSteal.textContent = steals;
    if (afCountWorth) afCountWorth.textContent = worths;
    if (afCountSkip) afCountSkip.textContent = skips;

    let filtered = agentDeals.filter(d => {
      if (agentVerdictFilter === 'all') return true;
      return (d.agent_verdict || '').toUpperCase() === agentVerdictFilter;
    });

    const targetSizes = (currentConfig?.watchlist?.target_sizes || []).map(s => String(s).toUpperCase());
    if (agentDealsContainer) {
      if (filtered.length === 0) {
        agentDealsContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 32px;">No deals match this verdict filter.</div>';
      } else {
        agentDealsContainer.innerHTML = filtered.map(d => buildDealCardHtml(d, targetSizes)).join('');
      }
    }
  }

  async function runAgentSearch(query) {
    if (!query || !query.trim()) return;
    query = query.trim();

    if (agentStatusCard) agentStatusCard.style.display = 'block';
    if (agentResultsSection) agentResultsSection.style.display = 'none';
    if (agentEmptyState) agentEmptyState.style.display = 'none';
    if (btnAgentSubmit) btnAgentSubmit.disabled = true;
    if (agentSpinner) agentSpinner.style.display = 'inline-block';
    if (agentBtnIcon) agentBtnIcon.style.display = 'none';
    if (agentBtnText) agentBtnText.textContent = 'Scouting...';

    setAgentStep(1);
    const step2Timer = setTimeout(() => setAgentStep(2), 2500);
    const step3Timer = setTimeout(() => setAgentStep(3), 8500);

    try {
      const resp = await fetch('/api/agent/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || 'Agent search failed');
      }

      setAgentStep(3, true);
      agentDeals = data.deals || [];
      renderAgentParams(data.params || {});
      renderAgentDeals();
      loadDeals(); // Refresh main deals list in background
      showToast(`Scout found ${agentDeals.length} deals!`, 'success');
    } catch (err) {
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);
      showToast('Agent Error: ' + err.message, 'error');
      if (agentEmptyState) {
        agentEmptyState.style.display = 'block';
        agentEmptyState.querySelector('h3').textContent = 'Search Failed';
        agentEmptyState.querySelector('p').textContent = err.message;
      }
    } finally {
      if (agentStatusCard) agentStatusCard.style.display = 'none';
      if (btnAgentSubmit) btnAgentSubmit.disabled = false;
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

  [afAll, afSteal, afWorth, afSkip].forEach(btn => {
    if (!btn) return;
    btn.addEventListener('click', () => {
      [afAll, afSteal, afWorth, afSkip].forEach(b => b?.classList.remove('active'));
      btn.classList.add('active');
      agentVerdictFilter = btn.dataset.verdict;
      renderAgentDeals();
    });
  });

  if (agentDealsContainer) {
    agentDealsContainer.addEventListener('click', e => {
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

  // Initialize
  loadDeals();
  loadConfig();
  pollStatus();
  setInterval(pollStatus, 2000);

})();
