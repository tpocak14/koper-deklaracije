console.log('=== JAVASCRIPT DATOTEKA NALOŽENA ===');
console.log('main.js v2.2 naložen - ' + Date.now());
console.log('Document ready state:', document.readyState);

// Preprost test, da preverimo, ali se main.js naloži
try {
    console.log('main.js se naloži uspešno');
} catch (error) {
    console.error('Napaka v main.js:', error);
}

// --- GLOBALNE SPREMENLJIVKE ---
let searchParfumSelect; // TomSelect instanca za iskanje parfumov
let isManufacturerChanging = false; // Globalna spremenljivka za sledenje spremembi proizvajalca
let currentPage = 1;
let currentFilter = 'all';
let currentSearchTerm = '';
let totalPages = 1;
let totalCount = 0;
let isOnline = navigator.onLine;
let syncInProgress = false;
let lastSyncTime = null;
let conflicts = [];
let currentUser = null;
let offlineSince = navigator.onLine ? null : Date.now();
let initialNarocilaRequested = false;
let lastOrdersRenderAt = 0;
let lastOrdersRenderKey = '';
let lastOrdersUserChangeAt = 0;

// Funkcija za preverjanje povezave - globalna funkcija
async function checkConnection() {
    console.log('checkConnection() klicana...');
    try {
        console.log('Pošiljam HEAD zahtevek na /api/health...');
        const response = await fetch('/api/health', { 
            method: 'HEAD',
            cache: 'no-cache',
            signal: AbortSignal.timeout(3000)
        });
        console.log('checkConnection() rezultat:', response.ok, 'status:', response.status);
        return response.ok;
    } catch (error) {
        console.log('Povezava preverjena - offline:', error.message, 'type:', error.name);
        if (error.name === 'AbortError') {
            console.log('Timeout pri preverjanju povezave');
        }
        return false;
    }
}

// Naredi checkConnection globalno dostopno
window.checkConnection = checkConnection;

// --- GLOBALNE FUNKCIJE ---
// Funkcija za inicializacijo zavihkov
function initializeTabs() {
    const tabButtons = document.querySelectorAll('[data-tab]');
    const tabPanels = document.querySelectorAll('.tab-pane');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetTab = this.getAttribute('data-tab');
            
            // Odstrani aktivni razred iz vseh zavihkov
            tabButtons.forEach(btn => {
                btn.classList.remove('active', 'border-primary-500', 'text-primary-600');
                btn.classList.add('border-transparent', 'text-gray-500');
            });
            
            // Skrij vse tab panele
            tabPanels.forEach(panel => {
                panel.classList.remove('show', 'active');
                panel.style.display = 'none';
            });
            
            // Aktiviraj izbrani zavihek
            this.classList.add('active', 'border-primary-500', 'text-primary-600');
            this.classList.remove('border-transparent', 'text-gray-500');
            
            // Prikaži izbrani panel
            const targetPanel = document.getElementById(`${targetTab}-panel`);
            if (targetPanel) {
                targetPanel.classList.add('show', 'active');
                targetPanel.style.display = 'block';
                
                // Naloži podatke glede na zavihek
                if (targetTab === 'katalog') {
                    if (window.proizvajalecSelect && !window.proizvajalecSelect.value) {
                        window.loadProizvajalci();
                    }
                } else if (targetTab === 'rocno') {
                    window.initializeManualAndPrintTab();
                } else if (targetTab === 'opozorila') {
                    window.fetchExpiringPerfumes();
                } else if (targetTab === 'returned-damaged') {
                    if (typeof window.initializeReturnedDamagedTab === 'function') {
                        window.initializeReturnedDamagedTab();
                    }
                    if (typeof window.initializeRDFilters === 'function') {
                        window.initializeRDFilters();
                    }
                    if (typeof window.loadReturnedDamaged === 'function') {
                        window.loadReturnedDamaged();
                    }
                } else if (targetTab === 'users') {
                    try {
                        const spinner = document.getElementById('users-spinner');
                        const list = document.getElementById('users-list');
                        if (spinner) spinner.style.display = '';
                        if (list) list.style.display = '';
                    } catch(_){}
                    window.loadUsers();
                } else if (targetTab === 'search-synonyms') {
                    if (typeof window.loadSearchSynonyms === 'function') {
                        window.loadSearchSynonyms();
                    }
                } else if (targetTab === 'procurement') {
                    if (typeof window.initializeProcurementTab === 'function') {
                        window.initializeProcurementTab();
                    }
                } else if (targetTab === 'navodila') {
                    window.loadInstructionCategories();
                    window.loadInstructions();
                    // Poveži gumbe za admin orodja (če so vidni)
                    const addCat = document.getElementById('add-category-btn');
                    const addIns = document.getElementById('add-instruction-btn');
                    if (addCat && !addCat.dataset.bound) {
                        addCat.dataset.bound = '1';
                        addCat.addEventListener('click', async () => {
                            const name = prompt('Ime nove kategorije navodil:');
                            if (!name) return;
                            try {
                                const res = await fetch('/api/instruction-categories', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ name })
                                });
                                if (!res.ok) {
                                    const err = await res.json().catch(()=>({error:'Napaka'}));
                                    throw new Error(err.error || 'Napaka pri shranjevanju kategorije');
                                }
                                await window.loadInstructionCategories();
                                showToast('Kategorija dodana', 'success');
                            } catch (e) {
                                showToast(e.message, 'danger');
                            }
                        });
                    }
                    if (addIns && !addIns.dataset.bound) {
                        addIns.dataset.bound = '1';
                        addIns.addEventListener('click', async () => {
                            // Odpri modal
                            const modal = document.getElementById('instructionModal');
                            const titleEl = document.getElementById('instructionModalTitle');
                            const catEl = document.getElementById('instructionModalCategory');
                            const titleInput = document.getElementById('instructionModalTitleInput');
                            const contentEl = document.getElementById('instructionModalContent');
                            const saveBtn = document.getElementById('instructionModalSave');
                            const cancelBtn = document.getElementById('instructionModalCancel');
                            const closeBtn = document.getElementById('instructionModalClose');
                            const imgTools = document.getElementById('instructionModalImageTools');
                            const imgInput = document.getElementById('instructionModalImageInput');
                            
                            // Napolni kategorije v modal
                            await window.loadInstructionCategories();
                            const srcSelect = document.getElementById('instruction-category');
                            catEl.innerHTML = srcSelect ? srcSelect.innerHTML : '<option value="">Vse kategorije</option>';
                            // Izberi trenutno izbrano kategorijo, če obstaja
                            if (srcSelect) catEl.value = srcSelect.value;
                            
                            titleEl.textContent = 'Novo navodilo';
                            titleInput.value = '';
                            contentEl.value = '';
                            // Ob ustvarjanju novega navodila prikaži orodja za dodajanje slike
                            imgTools.style.display = 'flex';
                            modal.dataset.mode = 'create';
                            modal.dataset.id = '';
                            
                            // Handlers
                            const hideModal = () => { modal.classList.add('hidden'); };
                            const showModal = () => { modal.classList.remove('hidden'); };
                            const onClose = () => hideModal();
                            closeBtn.onclick = onClose;
                            cancelBtn.onclick = onClose;

                            // Toolbar za oblikovanje vsebine
                            const toolbar = document.getElementById('instructionModalToolbar');
                            if (toolbar && !toolbar.dataset.bound) {
                                toolbar.dataset.bound = '1';
                                toolbar.addEventListener('click', (e) => {
                                    const btn = e.target.closest('button[data-format]');
                                    if (!btn) return;
                                    const format = btn.getAttribute('data-format');
                                    const textarea = contentEl;
                                    const start = textarea.selectionStart || 0;
                                    const end = textarea.selectionEnd || 0;
                                    const selected = textarea.value.substring(start, end);
                                    let before = textarea.value.substring(0, start);
                                    let after = textarea.value.substring(end);
                                    let insert = selected;
                                    switch (format) {
                                        case 'bold':
                                            insert = selected ? `<strong>${selected}</strong>` : `<strong></strong>`;
                                            break;
                                        case 'italic':
                                            insert = selected ? `<em>${selected}</em>` : `<em></em>`;
                                            break;
                                        case 'h2':
                                            insert = selected ? `<h2 class="text-xl font-semibold">${selected}</h2>` : `<h2 class="text-xl font-semibold"></h2>`;
                                            break;
                                        case 'h3':
                                            insert = selected ? `<h3 class="text-lg font-semibold">${selected}</h3>` : `<h3 class="text-lg font-semibold"></h3>`;
                                            break;
                                        case 'ul':
                                            insert = selected ? `<ul class="list-disc pl-5"><li>${selected}</li></ul>` : `<ul class="list-disc pl-5"><li></li></ul>`;
                                            break;
                                        case 'ol':
                                            insert = selected ? `<ol class="list-decimal pl-5"><li>${selected}</li></ol>` : `<ol class="list-decimal pl-5"><li></li></ol>`;
                                            break;
                                        case 'link':
                                            const href = prompt('Vnesite URL povezave:', 'https://');
                                            if (!href) return;
                                            insert = `<a href="${href}" target="_blank" class="text-blue-600 underline">${selected || href}</a>`;
                                            break;
                                        default:
                                            return;
                                    }
                                    textarea.value = `${before}${insert}${after}`;
                                    const cursorPos = before.length + insert.length;
                                    textarea.focus();
                                    textarea.setSelectionRange(cursorPos, cursorPos);
                                });
                            }
                            
                            saveBtn.onclick = async () => {
                                try {
                                    const category_id = catEl.value ? Number(catEl.value) : null;
                                    const title = titleInput.value.trim();
                                    const content = contentEl.value.trim();
                                    if (!title || !content) {
                                        showToast('Vnesite naslov in vsebino', 'warning');
                                        return;
                                    }
                                    const res = await fetch('/api/instructions', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ category_id, title, content })
                                    });
                                    if (!res.ok) throw new Error('Napaka pri shranjevanju navodila');
                                    showToast('Navodilo dodano', 'success');
                                    hideModal();
                                    await window.loadInstructions(category_id || '');
                                } catch (e) {
                                    showToast(e.message, 'danger');
                                }
                            };
                            
                            // Upload slike v modalu (dodamo v vsebino)
                            imgInput.onchange = async () => {
                                if (!imgInput.files || imgInput.files.length === 0) return;
                                const file = imgInput.files[0];
                                // Za novo navodilo slike ne nalagamo ločeno; uporabnik lahko slike doda po shranitvi v načinu urejanja
                                showToast('Sliko dodajte po shranitvi z gumbom Dodaj sliko v načinu urejanja.', 'info');
                                imgInput.value = '';
                            };
                            
                            showModal();
                        });
                    }
                }
            }
        });
    });

    // Prikaži prvi zavihek (Naročila) kot privzeti
    const firstTab = document.querySelector('[data-tab="narocila"]');
    if (firstTab) {
        firstTab.click();
    }
}

// Funkcija za inicializacijo ročnega in tiskanja zavihka
function initializeManualAndPrintTab() {
    console.log('Inicializiram ročni in tiskanje zavihek...');
    
    // Naloži proizvajalce za ročno pošiljanje
    window.loadProizvajalciForManualAndPrint();
    
    // Nastavi event listenerje za gumbe
    const manualSendBtn = document.getElementById('manual-send-btn');
    const printBtn = document.getElementById('print-btn');
    
    if (manualSendBtn) {
        manualSendBtn.removeEventListener('click', window.handleManualSend);
        manualSendBtn.addEventListener('click', window.handleManualSend);
    }
    
    if (printBtn) {
        printBtn.removeEventListener('click', window.handlePrintAction);
        printBtn.addEventListener('click', window.handlePrintAction);
    }
    
    console.log('Ročni in tiskanje zavihek inicializiran');
}

// Naredi funkcije globalno dostopne
window.initializeTabs = initializeTabs;
window.initializeManualAndPrintTab = initializeManualAndPrintTab;

// Placeholder funkcije, ki bodo prepisane znotraj DOMContentLoaded
window.loadProizvajalci = function() { console.log('loadProizvajalci not yet initialized'); };
window.fetchExpiringPerfumes = function() { console.log('fetchExpiringPerfumes not yet initialized'); };
window.loadUsers = function() { console.log('loadUsers not yet initialized'); };
    window.loadInstructionCategories = function() { console.log('loadInstructionCategories not yet initialized'); };
    window.loadInstructions = function() { console.log('loadInstructions not yet initialized'); };
window.loadSearchSynonyms = function() { console.log('loadSearchSynonyms not yet initialized'); };
window.loadProizvajalciForManualAndPrint = function() { console.log('loadProizvajalciForManualAndPrint not yet initialized'); };
window.handleManualSend = function() { console.log('handleManualSend not yet initialized'); };
window.handlePrintAction = function() { console.log('handlePrintAction not yet initialized'); };

document.addEventListener('DOMContentLoaded', function() {
    console.log('=== DOMContentLoaded EVENT FIRED ===');
    const narocilaList = document.getElementById('narocila-list');
    console.log('narocilaList element:', narocilaList);
    console.log('narocilaList HTML:', narocilaList ? narocilaList.outerHTML.substring(0, 200) + '...' : 'null');
    const loadingSpinner = document.getElementById('loading-spinner');
    const refreshButton = document.getElementById('refresh-button');
    // Bootstrap modal je zamenjan z lastno implementacijo
    const confirmResendButton = document.getElementById('confirm-resend');
    const confirmSendInvoiceButton = document.getElementById('confirm-send-invoice');
    const toastContainer = document.querySelector('.toast-container');

    // --- Splošna funkcija za obvestila ---
    function showToast(message, type = 'success') {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;

        const toastId = 'toast-' + Date.now();
        
        const typeClasses = {
            'success': 'bg-green-500',
            'error': 'bg-red-500',
            'warning': 'bg-yellow-500',
            'info': 'bg-blue-500',
            'danger': 'bg-red-500'
        };
        
        const iconClasses = {
            'success': 'bi-check-circle',
            'error': 'bi-exclamation-triangle',
            'warning': 'bi-exclamation-triangle',
            'info': 'bi-info-circle',
            'danger': 'bi-exclamation-triangle'
        };

        const toastHTML = `
            <div class="flex items-center w-full max-w-xs p-4 text-gray-500 bg-white rounded-lg shadow-lg border border-gray-200" role="alert" id="${toastId}">
                <div class="inline-flex items-center justify-center flex-shrink-0 w-8 h-8 ${typeClasses[type] || typeClasses['success']} text-white rounded-lg">
                    <i class="bi ${iconClasses[type] || iconClasses['success']}"></i>
                </div>
                <div class="ml-3 text-sm font-normal">${message}</div>
                <button type="button" class="ml-auto -mx-1.5 -my-1.5 bg-white text-gray-400 hover:text-gray-900 rounded-lg focus:ring-2 focus:ring-gray-300 p-1.5 hover:bg-gray-100 inline-flex items-center justify-center h-8 w-8" onclick="this.parentElement.remove()">
                    <i class="bi bi-x"></i>
                </button>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        const toastElement = document.getElementById(toastId);

        // Avtomatsko odstrani toast po 5 sekundah
        setTimeout(() => {
            if (toastElement && toastElement.parentNode) {
                toastElement.remove();
            }
        }, 5000);
    }
    
    // Naredi showToast globalno dostopno za Local First funkcionalnosti
    window.showToast = showToast;

    // --- Funkcija za prikaz spinnerja na gumbu ---
    function setButtonLoading(button, isLoading, text = 'Nalagam...') {
        if (isLoading) {
            button.disabled = true;
            button.dataset.originalHtml = button.innerHTML;
            button.innerHTML = `<svg class="animate-spin -ml-1 mr-3 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg> ${text}`;
        } else {
            button.disabled = false;
            if (button.dataset.originalHtml) {
                button.innerHTML = button.dataset.originalHtml;
            }
        }
    }

    function formatDateTime(value) {
        if (!value) return '';
        try {
            return new Date(value).toLocaleString('sl-SI');
        } catch (_) {
            return value;
        }
    }

    function getSearchSynonymsElements() {
        return {
            shop: document.getElementById('search-synonyms-shop'),
            filter: document.getElementById('search-synonyms-filter'),
            refresh: document.getElementById('search-synonyms-refresh'),
            clear: document.getElementById('search-synonyms-clear'),
            phrase: document.getElementById('synonym-phrase'),
            target: document.getElementById('synonym-target-code'),
            handle: document.getElementById('synonym-product-handle'),
            productId: document.getElementById('synonym-product-id'),
            save: document.getElementById('synonym-save-btn'),
            tableBody: document.getElementById('search-synonyms-table-body'),
        };
    }

    async function loadShopifyStores() {
        const { shop } = getSearchSynonymsElements();
        if (!shop) return;
        const res = await fetch('/api/shopify-stores');
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            return;
        }
        const stores = data.data || [];
        const current = shop.value;
        shop.innerHTML = '<option value="">Izberi shop domain...</option>';
        stores.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.shop_domain;
            opt.textContent = s.shop_domain + (s.is_default ? ' (default)' : '');
            shop.appendChild(opt);
        });
        const saved = current || localStorage.getItem('searchSynonymsShop');
        if (saved) shop.value = saved;
    }

    async function loadSearchSynonyms() {
        const els = getSearchSynonymsElements();
        if (!els.tableBody) return;
        const shop = (els.shop?.value || '').trim();
        const filter = (els.filter?.value || '').trim();
        if (!shop) {
            showToast('Vpiši shop domain', 'warning');
            return;
        }
        try {
            localStorage.setItem('searchSynonymsShop', shop);
        } catch (_) {}
        const params = new URLSearchParams();
        params.set('shop_domain', shop);
        if (filter) params.set('q', filter);
        const res = await fetch(`/api/search-synonyms?${params.toString()}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            const msg = data?.error?.message || 'Napaka pri nalaganju sinonimov';
            showToast(msg, 'danger');
            return;
        }
        renderSearchSynonyms(data.data || []);
    }

    function renderSearchSynonyms(rows) {
        const { tableBody } = getSearchSynonymsElements();
        if (!tableBody) return;
        if (!rows.length) {
            tableBody.innerHTML = '<tr><td class="px-4 py-4 text-gray-500" colspan="8">Ni podatkov</td></tr>';
            return;
        }
        tableBody.innerHTML = rows.map(r => `
            <tr>
                <td class="px-4 py-3 text-gray-900">${r.phrase_raw || ''}</td>
                <td class="px-4 py-3 text-gray-600">${r.phrase_norm || ''}</td>
                <td class="px-4 py-3 text-gray-900 font-mono">${r.target_code || ''}</td>
                <td class="px-4 py-3 text-gray-600">${r.product_handle || ''}</td>
                <td class="px-4 py-3 text-gray-600">${r.product_id || ''}</td>
                <td class="px-4 py-3 text-gray-600">${r.shop_domain || ''}</td>
                <td class="px-4 py-3 text-gray-500">${formatDateTime(r.updated_at)}</td>
                <td class="px-4 py-3">
                    <button class="text-red-600 hover:text-red-800" data-synonym-delete="${r.id}">Izbriši</button>
                </td>
            </tr>
        `).join('');
    }

    async function saveSearchSynonym() {
        const els = getSearchSynonymsElements();
        const shop = (els.shop?.value || '').trim();
        const phrase = (els.phrase?.value || '').trim();
        const target = (els.target?.value || '').trim();
        const handle = (els.handle?.value || '').trim();
        const productId = (els.productId?.value || '').trim();

        if (!shop || !phrase || !target) {
            showToast('Manjka shop domain, vnos ali target koda', 'warning');
            return;
        }

        const payload = {
            shop_domain: shop,
            phrase,
            target_code: target,
            product_handle: handle || null,
            product_id: productId || null,
        };

        try {
            setButtonLoading(els.save, true, 'Shranjujem...');
            const res = await fetch('/api/search-synonyms', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                const msg = data?.error?.message || 'Napaka pri shranjevanju';
                showToast(msg, 'danger');
                return;
            }
            showToast('Sinonim shranjen', 'success');
            if (els.phrase) els.phrase.value = '';
            if (els.target) els.target.value = '';
            if (els.handle) els.handle.value = '';
            if (els.productId) els.productId.value = '';
            await loadSearchSynonyms();
        } finally {
            setButtonLoading(els.save, false);
        }
    }

    async function deleteSearchSynonym(id) {
        if (!id) return;
        if (!confirm('Izbrišem sinonim?')) return;
        const res = await fetch(`/api/search-synonyms/${id}`, { method: 'DELETE' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            const msg = data?.error?.message || 'Napaka pri brisanju';
            showToast(msg, 'danger');
            return;
        }
        showToast('Sinonim izbrisan', 'success');
        await loadSearchSynonyms();
    }

    const synonymEls = getSearchSynonymsElements();
    if (synonymEls.shop && !synonymEls.shop.value) {
        try {
            const last = localStorage.getItem('searchSynonymsShop');
            if (last) synonymEls.shop.value = last;
        } catch (_) {}
    }
    if (synonymEls.shop && !synonymEls.shop.dataset.bound) {
        synonymEls.shop.dataset.bound = '1';
        synonymEls.shop.addEventListener('change', () => {
            try {
                localStorage.setItem('searchSynonymsShop', synonymEls.shop.value || '');
            } catch (_) {}
            loadSearchSynonyms();
        });
    }
    if (synonymEls.refresh && !synonymEls.refresh.dataset.bound) {
        synonymEls.refresh.dataset.bound = '1';
        synonymEls.refresh.addEventListener('click', () => loadSearchSynonyms());
    }
    if (synonymEls.clear && !synonymEls.clear.dataset.bound) {
        synonymEls.clear.dataset.bound = '1';
        synonymEls.clear.addEventListener('click', () => {
            if (synonymEls.filter) synonymEls.filter.value = '';
            loadSearchSynonyms();
        });
    }
    if (synonymEls.save && !synonymEls.save.dataset.bound) {
        synonymEls.save.dataset.bound = '1';
        synonymEls.save.addEventListener('click', () => saveSearchSynonym());
    }
    if (synonymEls.filter && !synonymEls.filter.dataset.bound) {
        synonymEls.filter.dataset.bound = '1';
        synonymEls.filter.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                loadSearchSynonyms();
            }
        });
    }
    if (synonymEls.tableBody && !synonymEls.tableBody.dataset.bound) {
        synonymEls.tableBody.dataset.bound = '1';
        synonymEls.tableBody.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-synonym-delete]');
            if (!btn) return;
            const id = btn.getAttribute('data-synonym-delete');
            deleteSearchSynonym(id);
        });
    }

    window.loadSearchSynonyms = async () => {
        await loadShopifyStores();
        await loadSearchSynonyms();
    };

    // --- Pomožna funkcija za formatiranje datuma ---
    function formatDateForInput(dateString) {
        if (!dateString) return '';
        try {
            return new Date(dateString).toISOString().split('T')[0];
        } catch (e) {
            return '';
        }
    }

    // --- Logika za NAROČILA ---

    const perPage = 50;

    // Dodatne spremenljivke za naročila
    let autoRefreshInterval = null;
    let countdownInterval = null;
    let countdownSeconds = 60; // 1 minuta (webhooks so hitrejši)
let narocilaFetchSeq = 0;
let narocilaAbortController = null;
    
    // Nastavi globalno spremenljivko
    window.isOnline = isOnline;
    
    async function fetchNarocila(page = 1, forceFilter = null, source = 'unknown') {
        const filterToUse = forceFilter || currentFilter;
        if (narocilaAbortController) {
            narocilaAbortController.abort();
        }
        narocilaAbortController = new AbortController();
        const fetchId = ++narocilaFetchSeq;
        const browserOnline = navigator.onLine;
        const shouldUseLocal = !browserOnline && !isOnline && offlineSince && (Date.now() - offlineSince > 2000);
        const renderKey = `${page}|${filterToUse}|${currentSearchTerm || ''}`;
        if (
            lastOrdersRenderAt &&
            renderKey !== lastOrdersRenderKey &&
            Date.now() - lastOrdersRenderAt < 2000 &&
            Date.now() - lastOrdersUserChangeAt > 2000
        ) {
            console.log('fetchNarocila: preskočim hiter preklop prikaza', renderKey, lastOrdersRenderKey);
            return;
        }
        console.log(
            'fetchNarocila() klicana za stran:',
            page,
            'filter:',
            filterToUse,
            'search:',
            currentSearchTerm,
            'isOnline:',
            isOnline,
            'navigator.onLine:',
            browserOnline,
            'shouldUseLocal:',
            shouldUseLocal,
            'fetchId:',
            fetchId,
            'source:',
            source
        );
        loadingSpinner.style.display = 'block';
        
        try {
            // 1. Najprej poskusi naložiti iz lokalne baze (samo offline)
            let localOrders = [];
            if (shouldUseLocal && window.localDB) {
                try {
                    localOrders = await localDB.getOrders();
                    console.log(`Naloženih ${localOrders.length} naročil iz lokalne baze (offline)`);
                } catch (error) {
                    console.warn('Napaka pri nalaganju iz lokalne baze:', error);
                }
            }
            
            // 2. Če je online, sinhroniziraj z API in posodobi lokalno bazo
            let apiData = null;
            if (!shouldUseLocal) {
                try {
                    console.log('Pošiljam API klic na /api/narocila');
                    const searchParam = currentSearchTerm ? `&search=${encodeURIComponent(currentSearchTerm)}` : '';
                    const response = await fetch(`/api/narocila?page=${page}&per_page=${perPage}&filter=${filterToUse}${searchParam}`, {
                        cache: 'no-store',
                        signal: narocilaAbortController.signal
                    });
                    console.log('API odgovor prejet:', response.status);
                    
                    if (response.ok) {
                        apiData = await response.json();
                        console.log('Naročila prejeta iz API:', apiData.narocila.length);
                        
                        // Shrani v lokalno bazo
                        if (window.localDB && apiData.narocila) {
                            await localDB.saveOrders(apiData.narocila);
                            console.log('Naročila shranjena v lokalno bazo');
                        }
                        
                        // Debug: Prikaži podatke o fulfilled naročilih
                        const fulfilledOrders = apiData.narocila.filter(n => n.fulfilled_at);
                        console.log('Fulfilled naročila:', fulfilledOrders.length);
                        fulfilledOrders.forEach(order => {
                            console.log(`Naročilo ${order.order_number}: fulfilled_at=${order.fulfilled_at}, shopify_fulfilled_at=${order.shopify_fulfilled_at}`);
                        });
                    } else {
                        console.warn(`API napaka: ${response.status}`);
                    }
                } catch (error) {
                    if (error.name === 'AbortError') {
                        console.log('fetchNarocila aborted');
                        return;
                    }
                    console.warn('Napaka pri API klicu:', error);
                }
            }
            
            // 3. Določi, katere podatke prikazati
            let ordersToDisplay = [];
            let paginationData = null;
            
            const fromApi = !!(apiData && apiData.narocila);
            if (fromApi) {
                // Uporabi API podatke, če so na voljo
                ordersToDisplay = apiData.narocila;
                paginationData = apiData.pagination;
                console.log('Prikazujem podatke iz API');
            } else if (shouldUseLocal && localOrders.length > 0) {
                // Uporabi lokalne podatke kot fallback (samo offline)
                ordersToDisplay = localOrders;
                console.log('Prikazujem podatke iz lokalne baze (offline mode)');
            } else {
                // Ni podatkov
                console.log('Ni podatkov za prikaz');
            }
            
            // 4. Aplikiraj filter in iskanje na lokalne podatke, če je potrebno
            if (!fromApi && ordersToDisplay.length > 0) {
                ordersToDisplay = ordersToDisplay.filter(order => {
                                    // Aplikiraj status filter
                if (filterToUse && filterToUse !== 'all') {
                    if (filterToUse === 'fulfilled') {
                        if (order.fulfilled_at === null) return false;
                    } else if (filterToUse === 'unfulfilled') {
                        if (order.fulfilled_at !== null) return false;
                    } else if (filterToUse === 'manjkajo_podatki') {
                        // Prikaži samo naročila z manjkajočimi podatki
                        if (order.status !== 'manjkajo_podatki') return false;
                    } else if (filterToUse === 'invoice_sent') {
                        if (!order.invoice_sent) return false;
                    } else if (filterToUse === 'invoice_not_sent') {
                        if (order.invoice_sent) return false;
                    }
                }
                    
                    // Aplikiraj iskalni filter
                    if (currentSearchTerm) {
                        const orderNumber = order.order_number || '';
                        const searchTerm = currentSearchTerm.toLowerCase();
                        const orderNumberLower = orderNumber.toLowerCase();
                        
                        // Preveri, ali številka naročila vsebuje iskalni izraz
                        if (!orderNumberLower.includes(searchTerm)) {
                            return false;
                        }
                    }
                    
                    return true;
                });
            }
            
            // 5. Posodobi globalne spremenljivke
            if (!forceFilter && paginationData) {
                currentPage = paginationData.current_page;
                totalPages = paginationData.total_pages;
                totalCount = paginationData.total_count;
            } else if (!forceFilter) {
                // Uporabi lokalne podatke za paginacijo
                currentPage = page;
                totalPages = Math.ceil(ordersToDisplay.length / perPage);
                totalCount = ordersToDisplay.length;
            }
            
            // 6. Prikaži podatke (samo če je to zadnji fetch)
            if (fetchId !== narocilaFetchSeq) {
                console.log('fetchNarocila: preskočen zastarel rezultat', fetchId, narocilaFetchSeq);
                return;
            }
            if (ordersToDisplay.length === 0) {
                narocilaList.innerHTML = '<div class="text-center text-muted">Ni novih naročil.</div>';
            } else {
                // Zagotovi stabilno razvrstitev tudi, če pridejo podatki iz lokalne baze
                const getSortTime = (o) => {
                    const raw = o?.created_at || o?.email_sent_at || o?.fulfilled_at || null;
                    const ts = raw ? Date.parse(raw) : NaN;
                    return Number.isFinite(ts) ? ts : 0;
                };
                ordersToDisplay.sort((a, b) => getSortTime(b) - getSortTime(a));
                narocilaList.innerHTML = ordersToDisplay.map(narocilo => createNarociloHTML(narocilo)).join('');
                initializeTooltips();
            }
            lastOrdersRenderAt = Date.now();
            lastOrdersRenderKey = renderKey;
            console.log('fetchNarocila render', {
                source,
                fromApi,
                shouldUseLocal,
                filter: filterToUse,
                search: currentSearchTerm || '',
                count: ordersToDisplay.length,
                fetchId
            });
            
            // Posodobi badge za manjkajoče podatke
            try {
                const badge = document.getElementById('missing-count-badge');
                if (badge && Array.isArray(ordersToDisplay)) {
                    const countMissing = ordersToDisplay.filter(o => o.status === 'manjkajo_podatki').length;
                    if (countMissing > 0) {
                        badge.textContent = String(countMissing);
                        badge.style.display = '';
                    } else {
                        badge.style.display = 'none';
                    }
                }
            } catch(_) {}
            
            // 7. Posodobi paginacijo
            if (!forceFilter) {
                if (paginationData) {
                    updatePagination(paginationData);
                } else {
                    // Ustvari paginacijo iz lokalnih podatkov
                    updatePagination({
                        current_page: currentPage,
                        total_pages: totalPages,
                        total_count: totalCount,
                        per_page: perPage,
                        has_prev: currentPage > 1,
                        has_next: currentPage < totalPages
                    });
                }
            }
            
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('fetchNarocila aborted');
                return;
            }
            console.error('Napaka pri nalaganju naročil:', error);
            narocilaList.innerHTML = `<div class="alert alert-danger">Napaka pri nalaganju naročil: ${error.message}</div>`;
        } finally {
            if (fetchId === narocilaFetchSeq) {
                loadingSpinner.style.display = 'none';
            }
        }
    }

    function updatePagination(pagination) {
        const paginationControls = document.getElementById('pagination-controls');
        const showingStart = document.getElementById('showing-start');
        const showingEnd = document.getElementById('showing-end');
        const totalCountEl = document.getElementById('total-count');
        
        if (!paginationControls || !showingStart || !showingEnd || !totalCountEl) return;
        
        // Posodobi informacije o prikazanih naročilih
        const start = (pagination.current_page - 1) * pagination.per_page + 1;
        const end = Math.min(start + pagination.per_page - 1, pagination.total_count);
        
        showingStart.textContent = start;
        showingEnd.textContent = end;
        totalCountEl.textContent = pagination.total_count;
        
        // Generiraj paginacijske gumbe
        let paginationHTML = '';
        
        // Prejšnja stran
        if (pagination.has_prev) {
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200" onclick="fetchNarocila(${pagination.current_page - 1}, null, 'pagination')">
                <i class="bi bi-chevron-left mr-1"></i> Prejšnja
            </button>`;
        } else {
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-400 bg-gray-100 cursor-not-allowed" disabled>
                <i class="bi bi-chevron-left mr-1"></i> Prejšnja
            </button>`;
        }
        
        // Številke strani
        const startPage = Math.max(1, pagination.current_page - 2);
        const endPage = Math.min(pagination.total_pages, pagination.current_page + 2);
        
        if (startPage > 1) {
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200" onclick="fetchNarocila(1, null, 'pagination')">1</button>`;
            if (startPage > 2) {
                paginationHTML += `<span class="inline-flex items-center px-3 py-2 text-sm text-gray-500">...</span>`;
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            if (i === pagination.current_page) {
                paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-primary-500 rounded-lg text-sm font-medium text-primary-700 bg-primary-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500">
                    ${i}
                </button>`;
            } else {
                paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200" onclick="fetchNarocila(${i}, null, 'pagination')">
                    ${i}
                </button>`;
            }
        }
        
        if (endPage < pagination.total_pages) {
            if (endPage < pagination.total_pages - 1) {
                paginationHTML += `<span class="inline-flex items-center px-3 py-2 text-sm text-gray-500">...</span>`;
            }
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200" onclick="fetchNarocila(${pagination.total_pages}, null, 'pagination')">${pagination.total_pages}</button>`;
        }
        
        // Naslednja stran
        if (pagination.has_next) {
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200" onclick="fetchNarocila(${pagination.current_page + 1}, null, 'pagination')">
                Naslednja <i class="bi bi-chevron-right ml-1"></i>
            </button>`;
        } else {
            paginationHTML += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-400 bg-gray-100 cursor-not-allowed" disabled>
                Naslednja <i class="bi bi-chevron-right ml-1"></i>
            </button>`;
        }
        
        paginationControls.innerHTML = paginationHTML;
    }





    async function migrateFromLocalFile() {
        const button = document.getElementById('migrate-local-file-btn');
        if (!button) return;

        // Preverimo, ali je gumb že v procesu
        if (button.disabled) {
            showToast('Proces je že v teku, počakajte...', 'warning');
            return;
        }

        // Potrdimo akcijo
        if (!confirm('⚠️  POZOR! To bo dodalo nove serije iz lokalne Excel datoteke (DEKLARACIJE_PARFUMOV_KOPER.xlsm) v tabelo serije. Datoteka mora biti v root direktoriju aplikacije. Ali ste prepričani?')) {
            return;
        }

        setButtonLoading(button, true, 'Migriram...');
        showToast('Začenjam migracijo novih serij iz lokalne Excel datoteke... To lahko traja nekaj časa.', 'info');

        try {
            const response = await fetch('/api/migrate-local-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) {
                let errorMsg = 'Neznana napaka';
                try {
                    const result = await response.json();
                    errorMsg = result.error || result.message || 'Neznana napaka';
                } catch (e) {
                    errorMsg = `Strežnik je vrnil napako ${response.status}.`;
                }
                throw new Error(errorMsg);
            }

            const result = await response.json();

            if (result.success) {
                showToast(result.message, 'success');
                // Po uspešni migraciji lahko osvežimo seznam naročil
                await fetchNarocila(1);
            } else {
                showToast(result.message, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri migraciji iz lokalne Excel datoteke:', error);
            showToast(`Napaka pri migraciji: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    if (refreshButton) {
        console.log('Dodajam event listener za refresh button');
        refreshButton.addEventListener('click', () => {
            lastOrdersUserChangeAt = Date.now();
            syncAndFetchNarocila();
        });
    }



    // Event listener za "Migracija iz lokalne datoteke (CLI stil)" gumb
    const migrateLocalFileBtn = document.getElementById('migrate-local-file-btn');
    if (migrateLocalFileBtn) {
        migrateLocalFileBtn.addEventListener('click', migrateFromLocalFile);
    }

    // Event listener za "Sinhroniziraj INCI iz Shopify" gumb
    const syncAllInciBtn = document.getElementById('sync-all-inci-btn');
    if (syncAllInciBtn) {
        syncAllInciBtn.addEventListener('click', syncAllInciFromShopify);
    }



    // Event listener za dodajanje proizvajalca
    document.getElementById('add-proizvajalec-btn')?.addEventListener('click', showAddProizvajalecModal);

    // Event listener za brisanje proizvajalca
    document.getElementById('delete-proizvajalec-btn')?.addEventListener('click', showDeleteProizvajalecModal);

    // Event listener za migracijo parfumov
    document.getElementById('migrate-perfumes-btn')?.addEventListener('click', migratePerfumesFromExcel);

    // Event listener za avtomatsko vklopitev sinhronizacije
    document.getElementById('auto-enable-sync-btn')?.addEventListener('click', autoEnableShopifySync);
    document.getElementById('auto-disable-sync-btn')?.addEventListener('click', autoDisableShopifySync);

    // Event listener za migracijo iz lokalne datoteke
    document.getElementById('migrate-local-file-btn')?.addEventListener('click', migrateFromLocalFile);

    // POPRAVEK: Nova funkcija, ki najprej sinhronizira, nato prikaže naročila.
    async function syncAndFetchNarocila() {
        setButtonLoading(refreshButton, true, 'Sinhroniziram...');
        try {
            // 1. korak: Sproži sinhronizacijo novih naročil s strežnika
            const syncResponse = await fetch('/api/sync-new-orders', { method: 'POST' });
            const syncResult = await syncResponse.json();

            if (!syncResponse.ok) {
                throw new Error(syncResult.error || 'Napaka pri sinhronizaciji naročil.');
            }
            
            // Prikaži obvestilo o rezultatu sinhronizacije
            showToast(syncResult.message, syncResult.new_orders_count > 0 ? 'success' : 'info');

            // 2. korak: Sinhroniziraj fulfilled status
            const fulfilledResponse = await fetch('/api/sync-fulfilled-status', { method: 'POST' });
            const fulfilledResult = await fulfilledResponse.json();

            if (fulfilledResponse.ok) {
                if (fulfilledResult.updated_count > 0) {
                    showToast(`Posodobljen fulfilled status za ${fulfilledResult.updated_count} naročil`, 'success');
                } else {
                    console.log('Ni naročil za posodobitev fulfilled statusa:', fulfilledResult.message);
                }
            } else {
                console.error('Napaka pri posodabljanju fulfilled statusa:', fulfilledResult.error);
            }

            // 3. korak: Posodobi Shopify fulfilled čase
            const shopifyTimesResponse = await fetch('/api/sync-shopify-fulfilled-times', { method: 'POST' });
            const shopifyTimesResult = await shopifyTimesResponse.json();

            if (shopifyTimesResponse.ok) {
                if (shopifyTimesResult.updated_count > 0) {
                    showToast(`Posodobljen Shopify čas za ${shopifyTimesResult.updated_count} naročil`, 'success');
                } else {
                    console.log('Ni naročil za posodobitev Shopify časa:', shopifyTimesResult.message);
                }
            } else {
                console.error('Napaka pri posodabljanju Shopify časov:', shopifyTimesResult.error);
            }

            // 4. korak: Osveži prikaz naročil v vmesniku (prva stran)
            console.log('Osvežujem prikaz naročil...');
            console.log('Trenutni filter:', currentFilter);
            await fetchNarocila(1, null, 'sync');
            
            console.log('Osveževanje končano');
            
            // Dodatno: Preveri specifično fulfilled naročila
            await checkSpecificFulfilledOrders();

        } catch (error) {
            console.error('Napaka v postopku osveževanja:', error);
            showToast(error.message, 'danger');
        } finally {
            setButtonLoading(refreshButton, false);
        }
    }
    
    // Funkcija za preverjanje specifičnih fulfilled naročil
    async function checkSpecificFulfilledOrders() {
        try {
            console.log('Preverjam specifična fulfilled naročila...');
            
            // Pridobi vsa fulfilled naročila iz trenutne strani
            const response = await fetch(`/api/narocila?page=${currentPage}&per_page=${perPage}&filter=${currentFilter}`);
            if (!response.ok) return;
            
            const data = await response.json();
            const fulfilledOrders = data.narocila.filter(n => n.fulfilled_at);
            
            console.log(`Na trenutni strani je ${fulfilledOrders.length} fulfilled naročil`);
            
            // Preveri vsako fulfilled naročilo posebej
            for (const order of fulfilledOrders) {
                if (!order.shopify_fulfilled_at) {
                    console.log(`Preverjam Shopify čas za naročilo ${order.order_number}...`);
                    
                    // Pridobi podrobnosti o fulfillment-u iz Shopify-ja
                    const shopifyResponse = await fetch(`/api/check-shopify-fulfillment/${order.shopify_order_id}`);
                    if (shopifyResponse.ok) {
                        const shopifyData = await shopifyResponse.json();
                        if (shopifyData.fulfilled_at) {
                            console.log(`Posodobljen Shopify čas za naročilo ${order.order_number}: ${shopifyData.fulfilled_at}`);
                        }
                    }
                }
            }
            
        } catch (error) {
            console.error('Napaka pri preverjanju fulfilled naročil:', error);
        }
    }

    // Helper funkcija za preverjanje, ali naročilo vsebuje Parfumi tipe izdelkov
    function hasParfumiProducts(narocilo) {
        try {
            const lineItems = narocilo.line_items || [];
            // Če je line_items string, poskusi parsirati
            const items = typeof lineItems === 'string' ? JSON.parse(lineItems) : lineItems;
            
            console.log(`Checking Parfumi for order ${narocilo.order_number}:`, items);
            
            const hasParfumi = items.some(item => {
                const productType = item.product_type || '';
                const vendor = item.vendor || '';
                const title = item.title || '';
                const norm = (value) => String(value || '')
                    .toLowerCase()
                    .normalize('NFKD')
                    .replace(/[\u0300-\u036f]/g, '');
                const ptNorm = norm(productType);
                const titleNorm = norm(title);
                const isParfumi = /parfum|perfume/.test(ptNorm) || /parfum|perfume|eau de parfum|edp/.test(titleNorm);
                console.log(`Item: "${title}", vendor: "${vendor}", product_type: "${productType}", isParfumi: ${isParfumi}`);
                return isParfumi;
            });
            
            console.log(`Order ${narocilo.order_number} hasParfumiProducts: ${hasParfumi}`);
            return hasParfumi;
        } catch (error) {
            console.error('Napaka pri preverjanju Parfumi izdelkov:', error);
            return false;
        }
    }
    function createNarociloHTML(narocilo) {
        console.log('=== CREATE NAROCILO HTML ===');
        console.log('Narocilo object:', narocilo);
        console.log('order_number:', narocilo.order_number);
        
        const statusMap = {
            'pripravljeno_za_posiljanje': { text: 'Pripravljeno', class: 'bg-blue-100 text-blue-800' },
            'manjkajo_podatki': { text: 'Manjkajo podatki', class: 'bg-red-100 text-red-800' },
            'email_poslan': { text: 'Email poslan', class: 'bg-green-100 text-green-800' },
            'brez_parfumov': { text: 'Brez parfumov', class: 'bg-gray-100 text-gray-800' },
            'fulfilled': { text: 'Fulfilled', class: 'bg-green-100 text-green-800' },
            'unfulfilled': { text: 'Unfulfilled', class: 'bg-yellow-100 text-yellow-800' }
        };
        const statusInfo = statusMap[narocilo.status] || { text: narocilo.status, class: 'bg-gray-100 text-gray-800' };
        const createdAt = new Date(narocilo.created_at).toLocaleString('sl-SI');
        
        // Prikaži Shopify fulfilled čas, če obstaja, sicer naš čas
        let fulfilledAt = 'Unfulfilled';
        let fulfilledIcon = 'bi-x-circle';
        let fulfilledClass = 'text-gray-500';
        
        console.log(`Naročilo ${narocilo.order_number}: fulfilled_at=${narocilo.fulfilled_at}, shopify_fulfilled_at=${narocilo.shopify_fulfilled_at}`);
        
        if (narocilo.fulfilled_at) {
            if (narocilo.shopify_fulfilled_at) {
                // Uporabi Shopify čas
                fulfilledAt = new Date(narocilo.shopify_fulfilled_at).toLocaleString('sl-SI');
                console.log(`Uporabljam Shopify čas: ${fulfilledAt}`);
            } else {
                // Uporabi naš čas
                fulfilledAt = new Date(narocilo.fulfilled_at).toLocaleString('sl-SI');
                console.log(`Uporabljam naš čas: ${fulfilledAt}`);
            }
            fulfilledIcon = 'bi-check-circle-fill';
            fulfilledClass = 'text-green-600';
        } else {
            console.log(`Naročilo ni fulfilled`);
        }
        
        const emailSentAt = narocilo.email_sent_at ? new Date(narocilo.email_sent_at).toLocaleString('sl-SI') : 'še ni poslan';
        const mkUploadedAt = narocilo.mk_decl_uploaded_at ? new Date(narocilo.mk_decl_uploaded_at).toLocaleString('sl-SI') : 'še ni naložen';

        let actionButtons = '';
        if (narocilo.status === 'manjkajo_podatki') {
            const firstPid = (Array.isArray(narocilo.affected_perfumes) && narocilo.affected_perfumes[0] && narocilo.affected_perfumes[0].id) ? narocilo.affected_perfumes[0].id : '';
            actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-red-300 rounded-lg text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors duration-200 check-order-btn" data-order-number="${narocilo.order_number}" data-first-perfume-id="${firstPid}">
                <i class="bi bi-exclamation-triangle-fill mr-2"></i> Preveri podatke
            </button>`;
        }
        if (narocilo.status === 'unfulfilled' && hasUserPermission('send_auto_declarations')) {
            actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-green-300 rounded-lg text-sm font-medium text-green-700 bg-green-50 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 transition-colors duration-200 generate-send-btn" data-order-number="${narocilo.order_number}">
                <i class="bi bi-send mr-2"></i> Generiraj in pošlji
            </button>`;
        }
        // Prikaži "Poglej PDF" gumb, ko je PDF ustvarjen in ima deklaracijske vrstice (ali naložen na MK)
        const pdfReady = Boolean(
            narocilo.mk_decl_uploaded_at ||
            (narocilo.pdf_generated_at && narocilo.has_declarations)
        );
        if (pdfReady) {
             actionButtons += `<a href="/generiraj_pdf/${narocilo.order_number.replace('#','')}" target="_blank" class="inline-flex items-center px-3 py-2 border border-blue-300 rounded-lg text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors duration-200">
                <i class="bi bi-file-pdf mr-2"></i> Poglej PDF
            </a>`;
        }
        // Pošlji račun (MetaKocka) – vidno s pravico send_invoice
        if (hasUserPermission && hasUserPermission('send_invoice')) {
            actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-amber-300 rounded-lg text-sm font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors duration-200 send-invoice-btn" data-order-number="${narocilo.order_number}">
                <i class="bi bi-receipt mr-2"></i> Pošlji račun
            </button>`;
        }
        if (narocilo.status !== 'brez_parfumov' && hasUserPermission('send_auto_declarations')) {
            actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 transition-colors duration-200 resend-btn" data-order-number="${narocilo.order_number}">
                <i class="bi bi-envelope mr-2"></i> Ponovno pošlji
            </button>`;
        }
        if (narocilo.order_number) {
            if (narocilo.has_images) {
                actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-blue-300 rounded-lg text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors duration-200 order-images-btn" data-order-number="${narocilo.order_number}">
                    <i class="bi bi-images mr-2"></i> Poglej ali dodaj slike
                </button>`;
            } else {
                actionButtons += `<button class="inline-flex items-center px-3 py-2 border border-primary-300 rounded-lg text-sm font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200 order-images-btn" data-order-number="${narocilo.order_number}">
                    <i class="bi bi-camera mr-2"></i> Naloži slike
                </button>`;
            }
        }

        // Manjkajo podatki box (preprosto in brez inline IIFE, da ne pride do sintaksnih napak)
        let mdAffected = Array.isArray(narocilo.affected_perfumes) ? narocilo.affected_perfumes : [];
        const mdCount = mdAffected.length;
        const mdTargetId = mdCount ? (mdAffected[0]?.id || '') : '';
        const mdClickableClass = mdCount === 1 ? ' cursor-pointer hover:bg-red-100' : '';
        let mdChipsHtml = '';
        try {
            // Render chips always if there are affected perfumes; click will check permissions
            if (mdCount > 0) {
                const seen = new Set();
                const chips = mdAffected.filter(p => p && p.id && !seen.has(p.id) && seen.add(p.id)).map(p => {
                    const label = `(${p.product_no}) ${p.proizvajalec} - ${p.ime_parfuma}`.replace(/"/g, '&quot;');
                    return `<button type="button" class="missing-perfume-link inline-flex items-center px-2 py-1 mt-2 mr-2 border border-red-300 rounded text-xs text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none" data-perfume-id="${p.id}" data-label="${label}"><i class="bi bi-plus-circle mr-1"></i>${label}</button>`;
                });
                mdChipsHtml = `<div class="mt-2"><span class="text-xs text-red-700">Dodaj/uredi serijo za:</span><div class="mt-1">${chips.join('')}</div></div>`;
            }
        } catch(_) {}

        const missingDataHTML = narocilo.status === 'manjkajo_podatki' && narocilo.missing_data_details ? `
            <div class="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg transition-colors missing-data-box${mdClickableClass}" data-order-number="${narocilo.order_number}" data-affected-count="${mdCount}" data-target-perfume-id="${mdTargetId}">
                <div class="flex items-center">
                    <i class="bi bi-exclamation-triangle-fill text-red-500 mr-2"></i>
                    <span class="text-sm font-medium text-red-800">Manjkajo podatki:</span>
                </div>
                <p class="text-sm text-red-700 mt-1">${Array.isArray(narocilo.missing_data_details) ? narocilo.missing_data_details.join(', ') : narocilo.missing_data_details}</p>
                ${mdChipsHtml}
            </div>
        ` : '';

        return `
            <div class="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-md transition-shadow duration-200">
                <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between space-y-4 lg:space-y-0">
                    <div class="flex-1">
                        <div class="flex items-center space-x-3 mb-3">
                            <h4 class="text-lg font-semibold text-gray-900">
                                <a href="${narocilo.order_admin_url}" target="_blank" class="hover:text-primary-600 transition-colors duration-200">${narocilo.order_number}</a>
                            </h4>
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusInfo.class}">${statusInfo.text}</span>
                             ${(() => {
                                const chips = [];
                                // Dodatni statusi (brez ponavljanja Unfulfilled/Fulfilled)
                                if ((narocilo.prepared_by_display || narocilo.prepared_by) && narocilo.has_images) {
                                    chips.push('<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">Pripravljeno</span>');
                                }
                                if (narocilo.email_sent_at && narocilo.status !== 'email_poslan') {
                                    chips.push('<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">Email poslan</span>');
                                }
                                return chips.join(' ');
                             })()}
                </div>
                        <p class="text-gray-600 mb-3">${narocilo.customer_name || 'N/A'}</p>
                        <div class="flex flex-wrap gap-4 text-sm text-gray-500 mb-3">
                            
                            <div class="flex items-center">
                                <i class="bi bi-calendar mr-2"></i> ${createdAt}
                            </div>
                            <div class="flex items-center">
                                <i class="bi ${fulfilledIcon} mr-2 ${fulfilledClass}"></i> ${fulfilledAt}
                            </div>
                            <div class="flex items-center gap-2">
                                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${narocilo.invoice_sent ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                                    ${narocilo.invoice_sent ? 'Račun poslan' : 'Račun ni poslan'}
                                </span>
                                <span class="flex items-center"><i class="bi bi-envelope mr-2"></i> Email: ${emailSentAt}${narocilo.email_recipient ? ` (${narocilo.email_recipient})` : ''}</span>
                                <span class="flex items-center"><i class="bi bi-cloud-upload mr-2"></i> MK: ${mkUploadedAt}</span>
                            </div>
                            ${narocilo.prepared_by_display ? `
                            <div class="flex items-center">
                                <i class="bi bi-person-check mr-2"></i> Pripravil: ${narocilo.prepared_by_display}
                            </div>
                            ` : ''}
                            ${(() => {
                                // Preveri, ali naročilo vsebuje Parfumi izdelke
                                const hasParfumi = hasParfumiProducts(narocilo);
                                const isPrepared = narocilo.prepared_by_display;
                                const hasNalivalec = Boolean(narocilo.nalivalec_display);
                                
                                // Preveri tudi backend status - če je "brez_parfumov", ne prikaži Nalivalca
                                const isBrezParfumov = narocilo.status === 'brez_parfumov';
                                
                                console.log(`Order ${narocilo.order_number}: hasParfumi=${hasParfumi}, isPrepared=${isPrepared}, status=${narocilo.status}, isBrezParfumov=${isBrezParfumov}`);
                                
                                // Ne prikaži Nalivalca, če:
                                // 1. Naročilo ne vsebuje Parfumi izdelkov, ALI
                                // 2. Naročilo je označeno kot "brez_parfumov" na backend strani, ALI
                                // 3. Naročilo še ni pripravljeno in nima nastavljenega nalivalca
                                if (!hasParfumi || isBrezParfumov || (!isPrepared && !hasNalivalec)) {
                                    console.log(`Hiding Nalivalec for order ${narocilo.order_number}: hasParfumi=${hasParfumi}, isPrepared=${isPrepared}, hasNalivalec=${hasNalivalec}, isBrezParfumov=${isBrezParfumov}`);
                                    return '';
                                }
                                
                                // Prikaži Nalivalca z obveznim označevanjem (brez rdečega vprašaja)
                                const nalivalecText = narocilo.nalivalec_display || 
                                    '<span class="text-orange-600 font-medium">Potrebno označiti</span>';
                                
                                console.log(`Showing Nalivalec for order ${narocilo.order_number}: ${nalivalecText}`);
                                
                                return `
                                <div class="flex items-center">
                                    <i class="bi bi-person-fill mr-2"></i> Nalivalec: ${nalivalecText}
                                </div>`;
                            })()}
                        </div>
                        ${missingDataHTML}
                    </div>
                    <div class="flex flex-col space-y-2 lg:space-y-0 lg:space-x-2 lg:flex-row">
                    ${actionButtons}
                    </div>
                </div>
            </div>`;
    }

    function initializeTooltips() {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Basic hook for Stats tab if present
    window.switchToStatsTab = function() {
        const ordersTab = document.getElementById('narocila-tab');
        const statsTab = document.getElementById('stats-tab');
        if (ordersTab && statsTab) {
            ordersTab.classList.add('hidden');
            statsTab.classList.remove('hidden');
            // Lazy render placeholder; real React app would mount here
            const root = document.getElementById('stats-root');
            if (root && !root.dataset.rendered) {
                root.innerHTML = '<div class="p-4 text-gray-600">Statistika bo na voljo v React komponenti (ločen frontend build).</div>';
                root.dataset.rendered = '1';
            }
        }
    }

    async function handleApiAction(button, url, body, successMessage) {
        console.log('=== HANDLE API ACTION ===');
        console.log('URL:', url);
        console.log('Body:', body);
        console.log('Success message:', successMessage);
        
        setButtonLoading(button, true);
        try {
            console.log('Sending fetch request to:', url);
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            console.log('Response status:', response.status);
            console.log('Response ok:', response.ok);
            // Robust parse: handle HTML error pages and empty body
            const raw = await response.text();
            let result = {};
            try { result = raw ? JSON.parse(raw) : {}; } catch (_) { result = {}; }
            if (!response.ok) {
                const msg = (result && (result.error || result.sporocilo)) || `${response.status} ${response.statusText}`;
                throw new Error(msg);
            }
            showToast((result && result.sporocilo) || successMessage);
            await fetchNarocila(); // Po akciji samo osvežimo prikaz
        } catch (error) {
            console.error('Error in handleApiAction:', error);
            showToast(`Napaka: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    if (narocilaList) {
        console.log('narocilaList found, adding event listener');
        console.log('narocilaList element:', narocilaList);
        console.log('narocilaList HTML:', narocilaList ? narocilaList.outerHTML.substring(0, 200) + '...' : 'null');
        narocilaList.addEventListener('click', function(e) {
            console.log('=== NAROCILA LIST CLICK EVENT ===');
            console.log('Click event detected on narocilaList');
            // 1) Poseben handling za klik na Manjkajo podatki box ali na posamezen parfum
            const missingPerfBtn = e.target.closest('.missing-perfume-link');
            if (missingPerfBtn) {
                e.preventDefault();
                const pid = missingPerfBtn.getAttribute('data-perfume-id');
                if (pid && window.switchToKatalogTab && window.loadPerfumeForEditing) {
                    window.switchToKatalogTab();
                    Promise.resolve(window.loadPerfumeForEditing(pid)).then(()=>{
                        if (typeof openAddSerijaForm === 'function') openAddSerijaForm();
                        if (window.showToast) window.showToast('Odprl dodajanje serije za izbran parfum.', 'info');
                    }).catch(()=>{});
                } else {
                    if (window.showToast) window.showToast('Ni mogoče odpreti urejanja serije.', 'warning');
                }
                return;
            }
            const missingBox = e.target.closest('.missing-data-box');
            if (missingBox) {
                try {
                    const affectedCount = parseInt(missingBox.getAttribute('data-affected-count') || '0', 10);
                    if (affectedCount > 1) {
                        // več parfumov → uporabi čipke, cel blok naj ne odpira nič
                        return;
                    }
                    const firstPid = missingBox.getAttribute('data-target-perfume-id') || missingBox.getAttribute('data-first-perfume-id');
                    if (firstPid && window.switchToKatalogTab && window.loadPerfumeForEditing) {
                        window.switchToKatalogTab();
                        Promise.resolve(window.loadPerfumeForEditing(firstPid)).then(()=>{
                            if (typeof openAddSerijaForm === 'function') openAddSerijaForm();
                            window.showToast && window.showToast('Odprl dodajanje serije za manjkajoči parfum.', 'info');
                        }).catch(()=>{});
                    } else {
                        const orderNo = missingBox.getAttribute('data-order-number');
                        let btn = document.querySelector(`.check-order-btn[data-order-number="${orderNo}"]`);
                        if (!btn) {
                            const card = missingBox.closest('[data-order-card]') || document;
                            btn = card.querySelector(`.check-order-btn[data-order-number="${orderNo}"]`);
                        }
                        if (btn) btn.click();
                    }
                } catch (err) { console.warn('Napaka pri kliku na Manjkajo podatke:', err); }
                return;
            }
            
            const target = e.target.closest('button, a');
            if (!target) {
                console.log('No button or link found');
                return;
            }
            
            console.log('Target element:', target);
            console.log('Target classes:', target.className);
            console.log('Target dataset:', target.dataset);
            console.log('Target outerHTML:', target.outerHTML);
            
            // Preverimo, ali je to gumb, ki potrebuje orderNumber
            const needsOrderNumber = target.classList.contains('generate-send-btn') || 
                                   target.classList.contains('check-order-btn') || 
                                   target.classList.contains('resend-btn') || 
                                   target.classList.contains('order-images-btn') ||
                                   target.classList.contains('send-invoice-btn');
            
            // Če gumb ne potrebuje orderNumber, pustimo, da se obnaša normalno (npr. PDF link)
            if (!needsOrderNumber) {
                console.log('Gumb ne potrebuje orderNumber, pustimo normalno obnašanje');
                return;
            }
            
            let orderNumber = target.dataset.orderNumber;
            console.log('Extracted orderNumber:', orderNumber);
            
            // Počisti orderNumber - odstrani # znak, če obstaja
            if (orderNumber && orderNumber.startsWith('#')) {
                orderNumber = orderNumber.substring(1);
                console.log('Cleaned orderNumber:', orderNumber);
            }
            
            if (!orderNumber) {
                console.error('Manjka orderNumber na gumbu, ki ga potrebuje.');
                console.error('Target element:', target);
                console.error('Target classes:', target.className);
                console.error('Target dataset:', target.dataset);
                console.error('Target outerHTML:', target.outerHTML);
                console.error('Event type:', e.type);
                console.error('Event target:', e.target);
                return;
            }

            if (target.classList.contains('generate-send-btn')) {
                e.preventDefault();
                if (!hasUserPermission('send_auto_declarations')) {
                    showToast('Nimate dovoljenja za pošiljanje iz seznama naročil.', 'warning');
                    return;
                }
                
                // Dodaj potrditveno okno
                const confirmMessage = `Ali res želite generirati in poslati deklaracijo za naročilo ${orderNumber}?\n\nTo bo:\n• Ustvarilo PDF deklaracijo\n• Poslalo email stranki\n• Oznacilo naročilo kot obdelano`;
                
                if (confirm(confirmMessage)) {
                handleApiAction(target, '/api/generiraj_in_poslji', { order_number: orderNumber }, 'Postopek sprožen.');
                }
            } else if (target.classList.contains('check-order-btn')) {
                e.preventDefault();
                const firstPid = target.getAttribute('data-first-perfume-id');
                if (firstPid && window.switchToKatalogTab && window.loadPerfumeForEditing) {
                    window.switchToKatalogTab();
                    Promise.resolve(window.loadPerfumeForEditing(firstPid)).then(()=>{
                        if (typeof openAddSerijaForm === 'function') openAddSerijaForm();
                        window.showToast && window.showToast('Odprl dodajanje serije za manjkajoči parfum.', 'info');
                    }).catch(()=>{});
                } else {
                handleApiAction(target, '/api/generiraj_in_poslji', { order_number: orderNumber }, 'Preverjanje podatkov...');
                }
            } else if (target.classList.contains('resend-btn')) {
                e.preventDefault();
                if (!hasUserPermission('send_auto_declarations')) {
                    showToast('Nimate dovoljenja za ponovno pošiljanje iz seznama naročil.', 'warning');
                    return;
                }
                document.getElementById('resend-order-number').value = orderNumber;
                document.getElementById('resend-email').value = '';
                showModal('resendModal');
            } else if (target.classList.contains('send-invoice-btn')) {
                e.preventDefault();
                if (!hasUserPermission('send_invoice')) {
                    showToast('Nimate dovoljenja za pošiljanje računa.', 'warning');
                    return;
                }
                document.getElementById('send-invoice-order-number').value = orderNumber;
                document.getElementById('send-invoice-email').value = '';
                showModal('sendInvoiceModal');
            } else if (target.classList.contains('order-images-btn')) {
                e.preventDefault();
                console.log('=== ORDER IMAGES BUTTON CLICKED ===');
                console.log('orderNumber from dataset:', orderNumber);
                showOrderImages(orderNumber);
            // Event listener za brisanje slik je sedaj direktno na gumbu z onclick
            }
        });
    } else {
        console.error('narocilaList NOT FOUND!');
        console.error('Available elements with "narocila" in ID:');
        document.querySelectorAll('[id*="narocila"]').forEach(function(el) {
            console.error('Found element:', el.id, el);
        });
    }

    if (confirmResendButton) {
        confirmResendButton.addEventListener('click', async function() {
            const orderNumber = document.getElementById('resend-order-number').value;
            const novEmail = document.getElementById('resend-email').value;
            console.log('Ponovno pošiljanje - orderNumber:', orderNumber, 'novEmail:', novEmail);
            setButtonLoading(this, true);
            try {
                const requestBody = { order_number: orderNumber, nov_email: novEmail };
                console.log('Pošiljam request body:', requestBody);
                const response = await fetch('/api/ponovno_poslji_deklaracijo', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.sporocilo || 'Neznana napaka');
                showToast(result.sporocilo);
                closeModal('resendModal');
                await fetchNarocila();
            } catch (error) {
                showToast(`Napaka: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(this, false);
            }
        });
    }

    if (confirmSendInvoiceButton) {
        confirmSendInvoiceButton.addEventListener('click', async function() {
            const orderNumber = document.getElementById('send-invoice-order-number').value;
            const recipientEmail = document.getElementById('send-invoice-email').value;
            setButtonLoading(this, true);
            try {
                const requestBody = { order_number: orderNumber, recipient_email: recipientEmail };
                const response = await fetch('/api/mk/send-invoice', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || result.sporocilo || 'Neznana napaka');
                showToast(result.sporocilo || 'Račun poslan.');
                closeModal('sendInvoiceModal');
            } catch (error) {
                showToast(`Napaka: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(this, false);
            }
        });
    }

    if (refreshButton) {
        refreshButton.addEventListener('click', syncAndFetchNarocila);
    }

    // --- Stats tab minimal wiring ---
    (function setupStatsTab(){
        const btn = document.getElementById('stats-tab-btn');
        const panel = document.getElementById('stats-panel');
        if (!btn || !panel) return;
        const startI = document.getElementById('stats-start');
        const endI = document.getElementById('stats-end');
        const gbI = null;
        const sourceI = null;
        const loadingEl = document.getElementById('stats-loading');
        const exportLink = document.getElementById('stats-export-link');
        const tbody = document.getElementById('stats-summary-body');
        const kpiPoints = document.getElementById('kpi-points');
        const kpiPack = document.getElementById('kpi-pack');
        const kpiPour = document.getElementById('kpi-pour');
        const kpiPackParfumi = document.getElementById('kpi-pack-parfumi');
        const kpiPackNonParfumi = document.getElementById('kpi-pack-nonparfumi');
        const kpiOrdersCount = document.getElementById('kpi-orders-count');

        // defaults
        const today = new Date();
        const start = new Date(today.getTime() - 29*864e5);
        if (startI) startI.value = start.toISOString().slice(0,10);
        if (endI) endI.value = today.toISOString().slice(0,10);
        

        async function fetchStats(){
            try{
                if (loadingEl) loadingEl.style.display = '';
                const q = new URLSearchParams({
                    start: startI.value,
                    end: endI.value
                }).toString();
                if (exportLink) exportLink.href = `/api/stats/workers/export.csv?${q}`;
                const res = await fetch(`/api/stats/workers?${q}`);
                if (!res.ok) {
                    let errMsg = 'Napaka pri nalaganju statistike';
                    try {
                        const ej = await res.json();
                        errMsg = ej?.message || ej?.error || errMsg;
                    } catch {}
                    throw new Error(errMsg);
                }
                const js = await res.json();
                console.log('STATS META', js?.data?.meta);
                const summary = js?.data?.summary || [];
                const meta = js?.data?.meta || {};
                const series = js?.data?.timeseries || [];
                // KPIs
                const points = summary.reduce((a,b)=>a+(b.points||0),0);
                const packParfumi = summary.reduce((a,b)=>a+(b.parfumi_items||0),0);
                const packNonParfumi = summary.reduce((a,b)=>a+(b.non_parfumi_items||0),0);
                const packItems = packParfumi + packNonParfumi;
                const pourParfumi = summary.reduce((a,b)=>a+(b.pour_count||0),0);
                const ordersCount = summary.reduce((a,b)=>a+(b.orders_count||0),0);
                if (kpiPoints) kpiPoints.textContent = points.toFixed(1);
                if (kpiPack) kpiPack.textContent = String(packItems);
                if (kpiPour) kpiPour.textContent = String(pourParfumi);
                if (kpiPackParfumi) kpiPackParfumi.textContent = String(packParfumi);
                if (kpiPackNonParfumi) kpiPackNonParfumi.textContent = String(packNonParfumi);
                if (kpiOrdersCount) kpiOrdersCount.textContent = String(ordersCount);
                
                // Prikaži skupno število pripravljenih naročil
                if (meta.total_prepared_orders !== undefined) {
                    const totalPreparedEl = document.getElementById('kpi-total-prepared');
                    if (totalPreparedEl) {
                        totalPreparedEl.textContent = String(meta.total_prepared_orders);
                    }
                }

                // Render simple points timeseries chart using Chart.js (loaded once via CDN)
                try {
                    if (!window.Chart) {
                        await new Promise((resolve, reject) => {
                            const s = document.createElement('script');
                            s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js';
                            s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
                        });
                    }
                    const ctx = document.getElementById('statsPointsChart');
                    if (ctx) {
                        const allDatesSet = new Set(series.map(r => r.date));
                        const labels = Array.from(allDatesSet).sort();
                        const userLabel = (r) => (r.full_name || r.username || ('User ' + r.user_id));
                        const idToLabel = {};
                        summary.forEach(r => { if (r.user_id != null) idToLabel[r.user_id] = userLabel(r); });
                        const perUser = {};
                        series.forEach(r => {
                            const uid = r.user_id || 'unknown';
                            if (!perUser[uid]) perUser[uid] = {};
                            perUser[uid][r.date] = (perUser[uid][r.date] || 0) + (r.points || 0);
                        });
                        const palette = (i) => `hsl(${(i*57)%360} 80% 45%)`;
                        const datasets = Object.keys(perUser).map((uid, idx) => ({
                            label: idToLabel[uid] || `User ${uid}`,
                            data: labels.map(d => Number(((perUser[uid][d]||0)).toFixed(2))),
                            fill: false,
                            borderColor: palette(idx),
                            tension: 0.25
                        }));
                        if (window._statsChart) { window._statsChart.destroy(); }
                        window._statsChart = new Chart(ctx, {
                            type: 'line',
                            data: { labels, datasets },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true, position: 'bottom' } }, scales: { x: { ticks: { maxRotation: 0 } } } }
                        });
                    }
                } catch (err) { console.warn('Chart render failed', err); }
                // table
                if (tbody){
                    tbody.innerHTML = summary.map((r,i)=>`
                        <tr class="${i%2? 'bg-white':'bg-gray-50'} hover:bg-blue-50 cursor-pointer employee-row" data-user-id="${r.user_id}" role="button" tabindex="0">
                          <td class="px-4 py-2">${r.full_name || r.username || ('User '+r.user_id)}</td>
                          <td class="px-4 py-2 text-right font-semibold">${(r.points||0).toFixed(1)}</td>
                          <td class="px-4 py-2 text-right">${(r.non_parfumi_items||0)+(r.parfumi_items||0)}</td>
                          <td class="px-4 py-2 text-right">${r.parfumi_items||0}</td>
                          <td class="px-4 py-2 text-right">${r.non_parfumi_items||0}</td>
                          <td class="px-4 py-2 text-right">${r.pour_count||0}</td>
                          <td class="px-4 py-2 text-right">${r.orders_count||0}</td>
                        </tr>
                    `).join('');
                }
            } catch(e){
                showToast('Napaka pri nalaganju statistike', 'danger');
            } finally{
                if (loadingEl) loadingEl.style.display = 'none';
            }
        }

        btn.addEventListener('click', function(){
            document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('show'));
            panel.classList.add('show');
            fetchStats();
        });
        if (startI) startI.addEventListener('change', fetchStats);
        if (endI) endI.addEventListener('change', fetchStats);
        
        // Quick presets
        const btnToday = document.getElementById('stats-preset-today');
        const btnYest = document.getElementById('stats-preset-yesterday');
        const btnThisM = document.getElementById('stats-preset-this-month');
        const btnLastM = document.getElementById('stats-preset-last-month');
        const btnYtd = document.getElementById('stats-preset-ytd');
        function setRange(s, e){ if (startI) startI.value = s; if (endI) endI.value = e; fetchStats(); }
        function fmt(d){ return d.toISOString().slice(0,10); }
        if (btnToday) btnToday.addEventListener('click', ()=>{
            const now = new Date(); const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())); setRange(fmt(d), fmt(d));
        });
        if (btnYest) btnYest.addEventListener('click', ()=>{
            const now = new Date(); const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()-1)); setRange(fmt(d), fmt(d));
        });
        if (btnThisM) btnThisM.addEventListener('click', ()=>{
            const now = new Date(); const s = new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1)); const e = new Date(Date.UTC(now.getFullYear(), now.getMonth()+1, 0)); setRange(fmt(s), fmt(e));
        });
        if (btnLastM) btnLastM.addEventListener('click', ()=>{
            const now = new Date(); const s = new Date(Date.UTC(now.getFullYear(), now.getMonth()-1, 1)); const e = new Date(Date.UTC(now.getFullYear(), now.getMonth(), 0)); setRange(fmt(s), fmt(e));
        });
        if (btnYtd) btnYtd.addEventListener('click', ()=>{
            const now = new Date();
            const e = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
            let s = new Date(Date.UTC(now.getFullYear(), 0, 1));
            const msInDay = 86400000;
            const diffDays = Math.floor((e - s) / msInDay) + 1;
            if (diffDays > 180) {
                // cap to last 180 days due to backend limit
                s = new Date(e.getTime() - (179 * msInDay));
                showToast('Prikazan je zadnjih 180 dni tekočega leta', 'info');
            }
            setRange(fmt(s), fmt(e));
        });
        // Delegated click/keyboard handler for employee rows
        if (tbody) {
            tbody.addEventListener('click', (ev)=>{
                const tr = ev.target?.closest('tr[data-user-id]');
                if (tr && typeof window.showWorkerDetails === 'function') {
                    const uid = parseInt(tr.getAttribute('data-user-id'), 10);
                    if (!Number.isNaN(uid)) window.showWorkerDetails(uid);
                }
            });
            tbody.addEventListener('keydown', (ev)=>{
                if (ev.key === 'Enter' || ev.key === ' ') {
                    const tr = ev.target?.closest('tr[data-user-id]');
                    if (tr && typeof window.showWorkerDetails === 'function') {
                        ev.preventDefault();
                        const uid = parseInt(tr.getAttribute('data-user-id'), 10);
                        if (!Number.isNaN(uid)) window.showWorkerDetails(uid);
                    }
                }
            });
        }
        })();
    // Funkcije za modal podrobnosti zaposlenega
    window.showWorkerDetails = async function(userId) {
        try {
            const startDate = document.getElementById('stats-start')?.value;
            const endDate = document.getElementById('stats-end')?.value;
            const groupBy = 'day';
            
            if (!startDate || !endDate) {
                showToast('Izberite obdobje za statistiko', 'warning');
                return;
            }

            const params = new URLSearchParams({
                start: startDate,
                end: endDate,
                group_by: groupBy,
                source: 'created'
            });

            const response = await fetch(`/api/stats/workers/${userId}/details?${params}`);
            if (!response.ok) {
                throw new Error('Napaka pri pridobivanju podrobnosti');
            }

            const data = await response.json();
            if (data.success) {
                displayWorkerDetails(data.data);
                showWorkerDetailsModal();
            } else {
                showToast('Napaka pri pridobivanju podrobnosti', 'danger');
            }
        } catch (error) {
            console.error('Error fetching worker details:', error);
            showToast('Napaka pri pridobivanju podrobnosti', 'danger');
        }
    };

    window.displayWorkerDetails = async function(data) {
        const { user, period, summary, prepared_orders, nalivalec_orders, timeseries } = data;
        
        // Nastavi naslov
        document.getElementById('workerDetailsTitle').textContent = `Podrobnosti o delu: ${user.full_name}`;
        
        // Nastavi KPI-je
        document.getElementById('worker-prepared-count').textContent = summary.total_prepared_orders;
        document.getElementById('worker-prepared-parfumi').textContent = summary.prepared_parfumi_qty;
        document.getElementById('worker-prepared-nonparfumi').textContent = summary.prepared_non_parfumi_qty;
        document.getElementById('worker-total-products').textContent = summary.prepared_total_qty;
        document.getElementById('worker-nalivalec-count').textContent = summary.poured_parfumi_qty;
        document.getElementById('worker-period').textContent = `${period.start} - ${period.end}`;
        
        // Nariši graf točk za izbranega zaposlenega (timeseries iz backend-a, če je na voljo)
        try {
            if (!window.Chart) {
                // graf se je morda že naložil v Stats tabu; če ne, ga naloži
                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js';
                    s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
                });
            }
            const ctx = document.getElementById('workerPointsChart');
            const wrapper = document.getElementById('worker-chart-wrapper');
            if (wrapper) wrapper.style.display = Array.isArray(timeseries) && timeseries.length ? 'block' : 'none';
            if (ctx && Array.isArray(timeseries) && timeseries.length) {
                const byDate = {};
                timeseries.forEach(r => { const d = r.date; byDate[d] = (byDate[d]||0) + (r.points||0); });
                const labels = Object.keys(byDate).sort();
                const dataPts = labels.map(k => Number(byDate[k].toFixed(2)));
                if (window._workerChart) window._workerChart.destroy();
                window._workerChart = new Chart(ctx, {
                    type: 'line',
                    data: { labels, datasets: [{ label: 'Točke na dan', data: dataPts, fill: false, borderColor: '#8b5cf6', tension: 0.25 }] },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxRotation: 0 } } } }
                });
            }
        } catch (err) { console.warn('Worker chart render failed', err); }

        // Prikaži pripravljena naročila
        const preparedContainer = document.getElementById('worker-prepared-orders');
        if (prepared_orders.length > 0) {
            preparedContainer.innerHTML = prepared_orders.map(order => `
                <div class="bg-white rounded-lg p-3 border border-gray-200">
                    <div class="grid grid-cols-1 sm:flex sm:flex-row sm:items-start sm:justify-between gap-1.5 mb-1.5">
                        <div class="font-medium text-gray-900 flex items-center gap-2 flex-wrap">
                            ${order.order_admin_url ? `<a href="${order.order_admin_url}" target="_blank" class="text-blue-600 hover:underline">${order.order_number}</a>` : order.order_number}
                        </div>
                        <div class="text-xs text-gray-500 sm:text-sm sm:mt-0 mt-1">${new Date(order.created_at).toLocaleDateString('sl-SI')}</div>
                    </div>
                    <div class="grid grid-cols-1 gap-2 sm:flex sm:items-center sm:justify-between sm:flex-wrap">
                        <div class="text-sm text-gray-600">
                            ${(() => {
                                const parf = Number(order.parfumi_count||0);
                                const nonp = Math.max(0, Number(order.product_count||0) - parf);
                                let html = '';
                                if (parf > 0) html += `<div>Parfumi: ${parf}</div>`;
                                if (nonp > 0) html += `<div>Izdelki: ${nonp}</div>`;
                                return html || '<div>—</div>';
                            })()}
                        </div>
                        <div class="flex items-center gap-2 mt-1 sm:mt-0">
                            <button class="inline-flex items-center px-2 py-1 border border-gray-300 rounded text-xs text-gray-700 bg-gray-50 hover:bg-gray-100 order-images-btn" data-order-number="${order.order_number}">
                                <i class="bi bi-images mr-1"></i> Slike
                            </button>
                            <button class="inline-flex items-center px-2 py-1 border border-gray-300 rounded text-xs text-gray-700 bg-gray-50 hover:bg-gray-100 order-items-btn" data-context="prepared" data-order-json='${encodeURIComponent(JSON.stringify(order))}'>
                                <i class="bi bi-list-ul mr-1"></i> Izdelki
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            preparedContainer.innerHTML = '<div class="text-gray-500 text-center py-4">Ni pripravljenih naročil</div>';
        }
        
        // Prikaži nalivanja (samo Parfumi; odstrani prikaz "Izdelki")
        const nalivalecContainer = document.getElementById('worker-nalivalec-orders');
        if (nalivalec_orders.length > 0) {
            nalivalecContainer.innerHTML = nalivalec_orders.map(order => `
                <div class="bg-white rounded-lg p-3 border border-gray-200">
                    <div class="grid grid-cols-1 sm:flex sm:flex-row sm:items-start sm:justify-between gap-1.5 mb-1.5">
                        <div class="font-medium text-gray-900 flex items-center gap-2 flex-wrap">
                            ${order.order_admin_url ? `<a href="${order.order_admin_url}" target="_blank" class="text-blue-600 hover:underline">${order.order_number}</a>` : order.order_number}
                        </div>
                        <div class="text-xs text-gray-500 sm:text-sm sm:mt-0 mt-1">${new Date(order.created_at).toLocaleDateString('sl-SI')}</div>
                    </div>
                    <div class="grid grid-cols-1 gap-2 sm:flex sm:items-center sm:justify-between sm:flex-wrap">
                        <div class="text-sm text-gray-600">
                            <div>Parfumi: ${order.parfumi_count}</div>
                        </div>
                        <div class="flex items-center gap-2 mt-1 sm:mt-0">
                            <button class="inline-flex items-center px-2 py-1 border border-gray-300 rounded text-xs text-gray-700 bg-gray-50 hover:bg-gray-100 order-images-btn" data-order-number="${order.order_number}">
                                <i class="bi bi-images mr-1"></i> Slike
                            </button>
                            <button class="inline-flex items-center px-2 py-1 border border-gray-300 rounded text-xs text-gray-700 bg-gray-50 hover:bg-gray-100 order-items-btn" data-context="nalivalec" data-order-json='${encodeURIComponent(JSON.stringify(order))}'>
                                <i class="bi bi-list-ul mr-1"></i> Izdelki
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            nalivalecContainer.innerHTML = '<div class="text-gray-500 text-center py-4">Ni nalivanj</div>';
        }
    };

    // Order items modal helpers
    function openOrderItemsModal(order, context){
        try {
            const listEl = document.getElementById('orderItemsList');
            const titleEl = document.getElementById('orderItemsTitle');
            if (!listEl || !titleEl) return;
            const raw = order.line_items || [];
            const items = Array.isArray(raw) ? raw : (typeof raw === 'string' ? JSON.parse(raw||'[]') : []);
            // Build list with counts and perfume flag
            const rows = items.map(it=>{
                const qty = parseInt(it.quantity||1,10)||1;
                const title = it.title || '(brez naslova)';
                const sku = it.sku || '';
                const ptype = String(it.product_type||'').toLowerCase();
                const isPerfume = ptype === 'parfumi' || ptype === 'parfum';
                return `
                    <div class="flex items-center justify-between bg-white rounded border border-gray-200 px-3 py-2">
                        <div>
                            <div class="font-medium text-gray-900">${title}</div>
                            <div class="text-xs text-gray-500">SKU: ${sku || '-'}</div>
                        </div>
                        <div class="text-sm ${isPerfume ? 'text-purple-700' : 'text-gray-700'}">${qty}× ${isPerfume ? 'Parfum' : 'Izdelek'}</div>
                    </div>`;
            }).join('');
            listEl.innerHTML = rows || '<div class="text-gray-500">Ni artiklov</div>';
            titleEl.textContent = `Izdelki (${context === 'nalivalec' ? 'nalivanje' : 'priprava'})`;
            document.getElementById('orderItemsModal')?.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        } catch(_){ /* ignore */ }
    }
    window.closeOrderItemsModal = function(){
        document.getElementById('orderItemsModal')?.classList.add('hidden');
        document.body.style.overflow = 'auto';
    };

    // Delegate clicks for order-items-btn in worker modal
    document.addEventListener('click', (e)=>{
        const btn = e.target.closest('.order-items-btn');
        if (!btn) return;
        e.preventDefault();
        try{
            const ctx = btn.getAttribute('data-context') || 'prepared';
            const raw = btn.getAttribute('data-order-json') || '{}';
            const order = JSON.parse(decodeURIComponent(raw));
            openOrderItemsModal(order, ctx);
        }catch(_){ /* ignore */ }
    });

    // Delegate clicks for order-images-btn in worker modal (same behavior as in Naročila seznam)
    document.addEventListener('click', (e)=>{
        const btn = e.target.closest('.order-images-btn');
        if (!btn) return;
        e.preventDefault();
        let orderNumber = btn.getAttribute('data-order-number') || '';
        if (orderNumber.startsWith('#')) orderNumber = orderNumber.slice(1);
        if (typeof showOrderImages === 'function') {
            showOrderImages(orderNumber);
        }
    });

    window.showWorkerDetailsModal = function() {
        const modal = document.getElementById('workerDetailsModal');
        if (modal) {
            modal.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        }
    };

    window.closeWorkerDetailsModal = function() {
        const modal = document.getElementById('workerDetailsModal');
        if (modal) {
            modal.classList.add('hidden');
            document.body.style.overflow = 'auto';
        }
    };

    // Bulk nalivalec bar
    // Bulk nalivalec bar removed as not used anymore
    
    // --- Logika za KATALOG & ZALOGA ---
    const searchProizvajalecSelect = document.getElementById('search-proizvajalec');
    // searchParfumSelect je že definirana v globalnem scope-u
    const katalogForm = document.getElementById('katalog-form');
    const proizvajalecSelect = document.getElementById('proizvajalec-id');
    const clearFormButton = document.getElementById('clear-form-button');
    const savePerfumeButton = document.getElementById('save-perfume-button');
    const serijeSection = document.getElementById('serije-section');
    const serijeTableBody = document.getElementById('serije-table-body');
    const serijaForm = document.getElementById('serija-form');
    const clearSerijaFormButton = document.getElementById('clear-serija-form-button');
    const stockStatusSwitch = document.getElementById('na-zalogi-switch');
    const syncWithShopifySwitch = document.getElementById('sinhroniziraj-s-shopify');
    const syncSwitchWrapper = document.getElementById('sync-switch-wrapper');
    const syncStockBtn = document.getElementById('sync-stock-btn');
    const syncNamesBtn = document.getElementById('sync-names-btn');
    const syncDataStatusBtn = document.getElementById('sync-data-status-btn');

    // Inicializacija TomSelect za iskanje parfumov
    const searchParfumElement = document.getElementById('search-parfum');
    if (searchParfumElement) {
        searchParfumSelect = new TomSelect(searchParfumElement, {
            valueField: 'id',
            labelField: 'label',
            searchField: ['label', 'product_no', 'ime_parfuma'],
            placeholder: 'Izberi parfum za urejanje',
            maxItems: 1,
            maxOptions: 50,
            closeAfterSelect: true,
            dropdownParent: 'body', // Vedno uporabi body, ne portal
            sortField: [
                { field: 'product_no_num', direction: 'asc' },
                { field: 'ime_parfuma', direction: 'asc' }
            ],
            score: function(search) {
                const q = (search || '').toLowerCase();
                const qNum = parseInt(q, 10);
                const hasNum = !isNaN(qNum);
                return function(item) {
                    const pnStr = (item.product_no || '').toString();
                    const name = (item.ime_parfuma || '').toLowerCase();
                    const label = (item.label || '').toLowerCase();
                    let s = 0;
                    if (pnStr === q) s = 10000;
                    else if (pnStr.startsWith(q)) s = 9000;
                    else if (hasNum && item.product_no_num) s = 8000 - Math.abs((item.product_no_num || 0) - qNum);
                    if (name.startsWith(q)) s = Math.max(s, 500);
                    if (label.startsWith(q)) s = Math.max(s, 400);
                    if (name.includes(q) || label.includes(q) || pnStr.includes(q)) s = Math.max(s, 100);
                    return s;
                };
            },

            onDropdownOpen: function(dropdown) {
                console.log('Dropdown opened, window width:', window.innerWidth);
                if (window.innerWidth <= 768) {
                    // Mobilno obnašanje
                    dropdown.classList.add('mobile-optimized-dropdown');
                    document.body.classList.add('prevent-scroll');
                    console.log('Added mobile-optimized-dropdown class to dropdown');
                    console.log('Added prevent-scroll class to body');
                    console.log('Dropdown classes:', dropdown.className);
                } else {
                    // Desktop obnašanje
                    dropdown.classList.remove('mobile-optimized-dropdown');
                    document.body.classList.remove('prevent-scroll');
                    console.log('Desktop mode - removed mobile classes');
                }
            },
            onDropdownClose: function() {
                document.body.classList.remove('prevent-scroll');
                console.log('Removed prevent-scroll class from body');
            },
            render: {
                option: function(data, escape) {
                    const product_no = data.product_no || '';
                    const ime_parfuma = data.ime_parfuma || '';
                    return `<div class="py-2 px-3 hover:bg-gray-100 cursor-pointer">
                        <div class="font-medium">${escape(data.label)}</div>
                        <div class="text-xs text-gray-500">ID: ${escape(product_no)} | Ime: ${escape(ime_parfuma)}</div>
                    </div>`;
                },
                item: function(data, escape) {
                    return `<div class="py-1">${escape(data.label)}</div>`;
                }
            },
            onChange: function(value) {
                if (value) {
                    switchToKatalogTab();
                    loadPerfumeForEditing(value);
                    // Preveri zaklepanje serijske številke ob spremembi parfuma
                    setTimeout(() => {
                        preveriZaklepanjeSerijske();
                    }, 100);
                } else {
                    clearKatalogForm();
                }
            }
        });
        searchParfumSelect.disable(); // Začnemo z onemogočenim poljem
        
        // Če je offline, naloži vse parfume iz lokalne baze za offline dostop
        if (!isOnline && window.localDB) {
            loadAllPerfumesForOffline();
        }
    }

    // Hitri iskalec parfumov (šifra -> ime)
    const perfumeLookupInput = document.getElementById('perfume-lookup-input');
    const perfumeLookupResults = document.getElementById('perfume-lookup-results');
    const perfumeLookupEmpty = document.getElementById('perfume-lookup-empty');
    if (perfumeLookupInput && perfumeLookupResults && perfumeLookupEmpty) {
        let lookupTimer;

        const clearPerfumeLookup = () => {
            perfumeLookupResults.innerHTML = '';
            perfumeLookupEmpty.style.display = 'none';
        };

        const renderPerfumeLookup = (items) => {
            perfumeLookupResults.innerHTML = '';
            if (!items || items.length === 0) {
                perfumeLookupEmpty.style.display = 'block';
                return;
            }
            perfumeLookupEmpty.style.display = 'none';
            items.forEach(p => {
                const row = document.createElement('div');
                row.className = 'flex flex-col md:flex-row md:items-center md:justify-between px-3 py-2 border border-gray-200 rounded-lg bg-gray-50';

                const colNo = document.createElement('div');
                colNo.className = 'font-medium text-gray-900';
                colNo.textContent = p.product_no || '';

                const colName = document.createElement('div');
                colName.className = 'text-gray-700';
                colName.textContent = p.ime_parfuma || '';

                const colSupplier = document.createElement('div');
                colSupplier.className = 'text-xs text-gray-500';
                colSupplier.textContent = p.proizvajalec || '';

                const actionWrap = document.createElement('div');
                actionWrap.className = 'mt-2 md:mt-0';
                const openBtn = document.createElement('button');
                openBtn.type = 'button';
                openBtn.className = 'perfume-lookup-open inline-flex items-center px-3 py-1.5 border border-primary-300 rounded-lg text-xs font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200';
                openBtn.setAttribute('data-perfume-id', p.id);
                openBtn.textContent = 'Vnos serije';
                actionWrap.appendChild(openBtn);

                row.append(colNo, colName, colSupplier, actionWrap);
                perfumeLookupResults.appendChild(row);
            });
        };

        perfumeLookupResults.addEventListener('click', (e) => {
            const btn = e.target.closest('.perfume-lookup-open');
            if (!btn) return;
            const perfumeId = btn.getAttribute('data-perfume-id');
            if (perfumeId && window.switchToKatalogTab && window.loadPerfumeForEditing) {
                window.switchToKatalogTab();
                window.loadPerfumeForEditing(perfumeId);
            }
        });

        perfumeLookupInput.addEventListener('input', () => {
            clearTimeout(lookupTimer);
            const q = perfumeLookupInput.value.trim();
            if (q.length < 2 && !/^\d+$/.test(q)) {
                clearPerfumeLookup();
                return;
            }
            perfumeLookupResults.innerHTML = '<div class="text-xs text-gray-500">Iščem...</div>';
            perfumeLookupEmpty.style.display = 'none';
            lookupTimer = setTimeout(async () => {
                try {
                    const response = await fetch(`/api/parfum-search?q=${encodeURIComponent(q)}`);
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || 'Neznana napaka');
                    const items = Array.isArray(data)
                        ? data
                        : (Array.isArray(data.data) ? data.data : (Array.isArray(data.results) ? data.results : []));
                    renderPerfumeLookup(items);
                } catch (error) {
                    perfumeLookupResults.innerHTML = '';
                    perfumeLookupEmpty.style.display = 'block';
                    console.error('Napaka pri iskanju parfumov:', error);
                }
            }, 250);
        });
    }

    // Funkcija za nalaganje vseh parfumov iz lokalne baze za offline dostop
    async function loadAllPerfumesForOffline() {
        try {
            console.log('loadAllPerfumesForOffline() klicana...');
            
            if (!window.localDB) {
                console.log('localDB ni na voljo');
                return;
            }
            
            console.log('Preverjam, ali je localDB inicializiran...');
            if (!localDB.isInitialized) {
                console.log('localDB ni inicializiran, poskušam inicializirati...');
                await localDB.init();
                console.log('localDB uspešno inicializiran');
            }
            
            console.log('Nalagam parfume iz lokalne baze...');
            const allPerfumes = await localDB.getPerfumes();
            console.log(`Najdenih ${allPerfumes.length} parfumov v lokalni bazi`);
            
            if (allPerfumes.length > 0) {
                console.log(`Naloženih ${allPerfumes.length} parfumov iz lokalne baze za offline dostop`);
                
                const options = allPerfumes.map(p => {
                    const stockIndicator = p.na_zalogi ? '🟢' : '🔴';
                    return {
                        id: p.id,
                        label: `${stockIndicator} ${p.product_no} - ${p.ime_parfuma}`,
                        product_no: p.product_no,
                        ime_parfuma: p.ime_parfuma,
                        product_no_num: parseInt(p.product_no, 10) || 0
                    };
                }).sort((a,b)=> (a.product_no_num - b.product_no_num) || (a.ime_parfuma||'').localeCompare(b.ime_parfuma||''));
                
                // Počisti obstoječe opcije in dodaj nove
                if (searchParfumSelect) {
                    console.log(`Dodajam ${options.length} opcij v TomSelect za offline dostop`);
                    console.log('Prve 3 opcije za offline:', options.slice(0, 3));
                    
                    searchParfumSelect.clear();
                    searchParfumSelect.clearOptions();
                    searchParfumSelect.addOptions(options);
                    searchParfumSelect.enable();
                    
                    console.log(`TomSelect ima sedaj ${searchParfumSelect.options.length} opcij za offline dostop`);
                    console.log('TomSelect opcije posodobljene');
                } else {
                    console.error('searchParfumSelect ni na voljo');
                }
                
                if (window.showToast) {
                    window.showToast('Prikazujem vse parfume iz lokalne baze (offline)', 'warning');
                }
            } else {
                console.log('Ni parfumov v lokalni bazi za offline dostop');
                if (window.showToast) {
                    window.showToast('Ni parfumov v lokalni bazi. Naložite podatke ko ste online.', 'warning');
                }
            }
        } catch (error) {
            console.warn('Napaka pri nalaganju parfumov za offline dostop:', error);
            if (window.showToast) {
                window.showToast('Napaka pri nalaganju parfumov iz lokalne baze', 'error');
            }
        }
    }

    async function loadProizvajalci() {
        console.log('loadProizvajalci() klicana, isOnline:', isOnline);
        try {
            // 1. Najprej poskusi naložiti iz lokalne baze
            let localProizvajalci = [];
            if (window.localDB) {
                try {
                    localProizvajalci = await localDB.getProizvajalci();
                    console.log(`Naloženih ${localProizvajalci.length} proizvajalcev iz lokalne baze`);
                } catch (error) {
                    console.warn('Napaka pri nalaganju proizvajalcev iz lokalne baze:', error);
                }
            }
            
            // 2. Če je online, sinhroniziraj z API in posodobi lokalno bazo
            let apiProizvajalci = null;
            if (isOnline) {
                console.log('loadProizvajalci: Pošiljam API klic (online)');
        try {
            const response = await fetch('/api/proizvajalci');
                    if (response.ok) {
                        apiProizvajalci = await response.json();
                        console.log(`Naloženih ${apiProizvajalci.length} proizvajalcev iz API`);
                        
                        // Shrani v lokalno bazo
                        if (window.localDB && apiProizvajalci) {
                            await localDB.saveProizvajalci(apiProizvajalci);
                            console.log('Proizvajalci shranjeni v lokalno bazo');
                        }
                    } else {
                        console.warn(`API napaka pri nalaganju proizvajalcev: ${response.status}`);
                    }
                } catch (error) {
                    console.warn('Napaka pri API klicu za proizvajalce:', error);
                }
            }
            
            // 3. Določi, katere podatke uporabiti
            let proizvajalciToUse = [];
            if (apiProizvajalci && apiProizvajalci.length > 0) {
                proizvajalciToUse = apiProizvajalci;
                console.log('Uporabljam proizvajalce iz API');
            } else if (localProizvajalci.length > 0) {
                proizvajalciToUse = localProizvajalci;
                console.log('Uporabljam proizvajalce iz lokalne baze (offline mode)');
                
                // Prikaži offline indikator
                if (window.showToast) {
                    window.showToast('Prikazujem proizvajalce iz lokalne baze (offline)', 'warning');
                }
            } else {
                console.log('Ni podatkov o proizvajalcih');
                showToast('Ni podatkov o proizvajalcih.', 'warning');
                return;
            }
            
            // 4. Posodobi UI
            const optionsHtml = '<option value="">Izberi...</option>' + proizvajalciToUse.map(p => `<option value="${p.id}">${p.ime}</option>`).join('');
            if (proizvajalecSelect) proizvajalecSelect.innerHTML = optionsHtml;
            if (searchProizvajalecSelect) searchProizvajalecSelect.innerHTML = '<option value="">Izberi proizvajalca</option>' + proizvajalciToUse.map(p => `<option value="${p.id}">${p.ime}</option>`).join('');
            
            // Debug - prikaži proizvajalce
            console.log('Proizvajalci v UI:');
            proizvajalciToUse.forEach(p => {
                console.log(`  ${p.ime} (ID: ${p.id}, tip: ${typeof p.id})`);
            });
            
        } catch (error) {
            console.error('Napaka pri nalaganju proizvajalcev:', error);
            showToast('Napaka pri nalaganju proizvajalcev.', 'danger');
        }
    }
    if (searchProizvajalecSelect) {
        // Obstoječa portal logika je odstranjena - uporabljamo nov sistem iz HTML-ja

        // Event listener za gumb statistike lokalne baze
        const dbStatsBtn = document.getElementById('db-stats-btn');
        if (dbStatsBtn) {
            dbStatsBtn.addEventListener('click', async function() {
                try {
                    const proizvajalci = await localDB.getProizvajalci();
                    const parfumi = await localDB.getPerfumes();
                    const serije = await localDB.getAll('serije');
                    
                    // Preveri, koliko parfumov ima proizvajalec_id
                    const parfumiWithProizvajalecId = parfumi.filter(p => p.proizvajalec_id !== undefined && p.proizvajalec_id !== null);
                    
                    const stats = {
                        proizvajalci: proizvajalci.length,
                        parfumi: parfumi.length,
                        parfumiWithProizvajalecId: parfumiWithProizvajalecId.length,
                        serije: serije.length,
                        online: isOnline
                    };
                    
                    const message = `Lokalna baza:\n` +
                        `• Proizvajalci: ${stats.proizvajalci}\n` +
                        `• Parfumi: ${stats.parfumi}\n` +
                        `• Parfumi z proizvajalec_id: ${stats.parfumiWithProizvajalecId}\n` +
                        `• Serije: ${stats.serije}\n` +
                        `• Online: ${stats.online ? 'Da' : 'Ne'}\n\n` +
                        `Prvi parfumi v bazi:\n` +
                        `${parfumi.slice(0, 5).map(p => `ID: ${p.id}, ${p.product_no} - ${p.ime_parfuma} (proizvajalec_id: ${p.proizvajalec_id})`).join('\n')}`;
                    
                    alert(message);
                } catch (error) {
                    console.error('Napaka pri pridobivanju statistike:', error);
                    showToast('Napaka pri pridobivanju statistike', 'error');
                }
            });
        }

        // Event listener za gumb osveževanja parfumov
        const refreshPerfumesBtn = document.getElementById('refresh-perfumes-btn');
        if (refreshPerfumesBtn) {
            refreshPerfumesBtn.addEventListener('click', async function() {
                if (!isOnline) {
                    // Če je offline, poskusi osvežiti z obstoječimi podatki
                    showToast('Aplikacija je offline - poskušam osvežiti z obstoječimi podatki', 'warning');
                    setButtonLoading(this, true, 'Osvežujem...');
                    try {
                        // Poskusi osvežiti z obstoječimi podatki v IndexedDB
                        await loadAllPerfumesForOffline();
                        showToast('Podatki osveženi iz lokalne baze', 'success');
                    } catch (error) {
                        console.error('Napaka pri osveževanju iz lokalne baze:', error);
                        showToast('Napaka pri osveževanju iz lokalne baze', 'error');
                    } finally {
                        setButtonLoading(this, false, 'Osveži');
                    }
                    return;
                }
                
                setButtonLoading(this, true, 'Osvežujem...');
                try {
                    await refreshLocalPerfumes();
                } finally {
                    setButtonLoading(this, false, 'Osveži');
                }
            });
        }

        searchProizvajalecSelect.addEventListener('change', async function() {
            const proizvajalecId = this.value;
            
            // Nastavi flag, da se proizvajalec spreminja
            isManufacturerChanging = true;
            
            searchParfumSelect.disable();
            searchParfumSelect.clear();
            searchParfumSelect.clearOptions();
            
            // Takoj skrij FLORGARDEN polja ob spremembi proizvajalca (PRED clearKatalogForm)
            const florgardenFields = document.getElementById('florgarden-serial-fields');
            if (florgardenFields) {
                florgardenFields.classList.add('hidden');
                florgardenFields.style.display = 'none';
                florgardenFields.style.visibility = 'hidden';
                florgardenFields.style.opacity = '0';
                florgardenFields.style.position = 'absolute';
                florgardenFields.style.left = '-9999px';
                console.log('Manufacturer change: FLORGARDEN fields hidden immediately');
            }
            
            clearKatalogForm();
            
            // Preveri zaklepanje serijske številke ob spremembi proizvajalca
            setTimeout(() => {
                preveriZaklepanjeSerijske();
            }, 100);
            
            // Preveri Shopify obstoj ob spremembi proizvajalca
            // Če je trenutno izbran parfum, preveri ali še vedno obstaja v Shopify-ju
            const currentPerfumeId = document.getElementById('perfume-id')?.value;
            if (currentPerfumeId) {
                setTimeout(async () => {
                    await checkShopifyExists(currentPerfumeId);
                    // Osveži UI na podlagi trenutnih podatkov iz baze
                    await refreshPerfumeUI(currentPerfumeId);
                }, 200);
            }

            if (!proizvajalecId) {
                isManufacturerChanging = false;
                return;
            }

            const proizvajalecIdNum = parseInt(proizvajalecId);

            // Pomočnik za pretvorbo parfumov v TomSelect opcije (stabilno sortirano)
            const buildParfumOptions = (list) => (list || []).map(p => {
                const stockIndicator = p.na_zalogi ? '🟢' : '🔴';
                return {
                    id: p.id,
                    label: `${stockIndicator} ${p.product_no} - ${p.ime_parfuma}`,
                    product_no: p.product_no,
                    ime_parfuma: p.ime_parfuma,
                    product_no_num: parseInt(p.product_no, 10) || 0
                };
            }).sort((a,b)=> (a.product_no_num - b.product_no_num) || (a.ime_parfuma||'').localeCompare(b.ime_parfuma||''));

            const applyOptions = (options) => {
                searchParfumSelect.clearOptions();
                searchParfumSelect.addOptions(options);
                searchParfumSelect.enable();
            };

            // Označuje trenutno aktivno spremembo proizvajalca, da zastareli API odgovor
            // ne prepiše aktualnega seznama, če uporabnik medtem zamenja proizvajalca.
            const changeToken = ++window.__proizvajalecChangeToken || (window.__proizvajalecChangeToken = 1);

            // 1) HITRA POT: takoj napolni iz IndexedDB prek indeksa `proizvajalec_id`
            let hasLocal = false;
            if (window.localDB && typeof localDB.getAll === 'function') {
                try {
                    const localParfumi = await localDB.getAll('perfumes', 'proizvajalec_id', proizvajalecIdNum);
                    if (Array.isArray(localParfumi) && localParfumi.length > 0) {
                        applyOptions(buildParfumOptions(localParfumi));
                        hasLocal = true;
                        console.log(`Parfumi prikazani takoj iz IndexedDB (${localParfumi.length}) za proizvajalca ${proizvajalecIdNum}`);
                    }
                } catch (err) {
                    console.warn('Napaka pri branju parfumov iz IndexedDB indexa:', err);
                }
            }

            // 2) ČE JE ONLINE: v ozadju osveži iz strežnika (ne blokiraj UX)
            if (isOnline) {
                fetch(`/api/parfumi_by_proizvajalec/${proizvajalecId}`)
                    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
                    .then(apiParfumi => {
                        if (!Array.isArray(apiParfumi)) return;
                        // Ignoriraj odgovor, če je uporabnik medtem zamenjal proizvajalca
                        if (window.__proizvajalecChangeToken !== changeToken) return;

                        applyOptions(buildParfumOptions(apiParfumi));
                        console.log(`Parfumi osveženi iz API (${apiParfumi.length}) za proizvajalca ${proizvajalecIdNum}`);

                        // Pisanje v IndexedDB pustimo v ozadju (ne čakamo)
                        if (window.localDB) {
                            Promise.resolve().then(() => localDB.savePerfumes(apiParfumi)).catch(()=>{});
                        }
                    })
                    .catch(err => {
                        console.warn('API klic za parfume v ozadju ni uspel:', err);
                        if (!hasLocal && window.showToast) {
                            window.showToast(`Napaka pri nalaganju parfumov: ${err.message}`, 'danger');
                        }
                    })
                    .finally(() => {
                        setTimeout(() => { isManufacturerChanging = false; }, 200);
                    });
            } else {
                if (!hasLocal && window.showToast) {
                    window.showToast('Ni parfumov v lokalni bazi za tega proizvajalca (offline).', 'warning');
                }
                setTimeout(() => { isManufacturerChanging = false; }, 200);
            }
        });
    }

    async function loadPerfumeForEditing(perfumeId) {
        try {
            console.log(`Nalaganje parfuma za urejanje - ID: ${perfumeId} (tip: ${typeof perfumeId})`);
            
            // 1. Najprej poskusi naložiti iz lokalne baze
            let localPerfume = null;
            if (window.localDB) {
                try {
                    // Poskusi naložiti z različnimi tipi ID-ja
                    const perfumeIdNum = parseInt(perfumeId);
                    console.log(`Poskušam naložiti parfum z ID: ${perfumeId} -> ${perfumeIdNum}`);
                    
                    localPerfume = await localDB.get('perfumes', perfumeIdNum);
                    if (!localPerfume) {
                        // Poskusi z originalnim ID-jem
                        localPerfume = await localDB.get('perfumes', perfumeId);
                    }
                    
                    console.log('Parfum naložen iz lokalne baze:', localPerfume ? 'da' : 'ne');
                    if (localPerfume) {
                        console.log('Podatki parfuma iz lokalne baze:', {
                            id: localPerfume.id,
                            product_no: localPerfume.product_no,
                            ime_parfuma: localPerfume.ime_parfuma,
                            proizvajalec_id: localPerfume.proizvajalec_id
                        });
                    }
                } catch (error) {
                    console.warn('Napaka pri nalaganju parfuma iz lokalne baze:', error);
                }
            }
            
            // 2. Če je online, sinhroniziraj z API in posodobi lokalno bazo
            let apiPerfume = null;
            if (isOnline) {
                try {
                    console.log(`Pošiljam API klic za parfum ID: ${perfumeId}`);
            const response = await fetch(`/api/parfum/${perfumeId}`);
                    if (response.ok) {
                        apiPerfume = await response.json();
                        console.log('Parfum naložen iz API:', apiPerfume);
                        
                        // Shrani v lokalno bazo
                        if (window.localDB && apiPerfume) {
                            await localDB.put('perfumes', apiPerfume);
                            console.log('Parfum shranjen v lokalno bazo');
                        }
                    } else {
                        console.warn(`API napaka pri nalaganju parfuma: ${response.status}`);
                    }
                } catch (error) {
                    console.warn('Napaka pri API klicu za parfum:', error);
                }
            }
            
            // 3. Določi, katere podatke uporabiti
            let parfum = null;
            if (apiPerfume) {
                parfum = apiPerfume;
                console.log('Uporabljam parfum iz API');
            } else if (localPerfume) {
                parfum = localPerfume;
                console.log('Uporabljam parfum iz lokalne baze (offline mode)');
                
                // Prikaži offline indikator
                if (window.showToast) {
                    window.showToast('Prikazujem parfum iz lokalne baze (offline)', 'warning');
                }
            } else {
                // Poskusi najti parfum med vsemi parfumi v lokalni bazi
                console.log('Parfum ni najden - poskušam iskati med vsemi parfumi v lokalni bazi...');
                if (window.localDB) {
                    try {
                        const allPerfumes = await localDB.getPerfumes();
                        console.log(`Vseh parfumov v lokalni bazi: ${allPerfumes.length}`);
                        
                        const foundPerfume = allPerfumes.find(p => 
                            p.id == perfumeId || p.id == parseInt(perfumeId)
                        );
                        
                        if (foundPerfume) {
                            parfum = foundPerfume;
                            console.log('Parfum najden med vsemi parfumi:', foundPerfume);
                        } else {
                            console.log('Parfum ni najden med vsemi parfumi v lokalni bazi');
                            console.log('Prvi parfumi v bazi:', allPerfumes.slice(0, 3));
                        }
                    } catch (error) {
                        console.error('Napaka pri iskanju med vsemi parfumi:', error);
                    }
                }
                
                if (!parfum) {
                    throw new Error(`Parfum z ID ${perfumeId} ni najden v lokalni bazi ali API-ju.`);
                }
            }
            
            // 4. Posodobi UI
            document.getElementById('perfume-id').value = parfum.id;
            document.getElementById('product-no').value = parfum.product_no;
            document.getElementById('proizvajalec-id').value = parfum.proizvajalec_id;
            document.getElementById('ime-parfuma').value = parfum.ime_parfuma;
            document.getElementById('sestava-inci').value = parfum.sestava_inci || '';
            stockStatusSwitch.checked = parfum.na_zalogi;

            // Preveri obstoj v Shopify-ju in posodobi UI (samo če je online)
            if (isOnline) {
                await checkShopifyExists(parfum.id);
            }
            
            // Nastavi sinhronizacijo na podlagi podatkov iz baze
            if (syncWithShopifySwitch) {
                    syncWithShopifySwitch.checked = parfum.sinhroniziraj_s_shopify;
            }

            showToast('Podatki o parfumu naloženi.');
            
            const selName = document.getElementById('selected-perfume-name');
            if (selName) {
                selName.textContent = parfum.ime_parfuma;
                selName.title = parfum.ime_parfuma;
            }
            document.getElementById('serija-parfum-id').value = parfum.id;
            // prikaži serije in katalog form
            serijeSection.style.display = 'block';
            const katalogCard = document.getElementById('katalog-card');
            if (katalogCard) katalogCard.style.display = 'block';
            loadSerijeForPerfume(parfum.id);

        } catch (error) {
            showToast(error.message, 'danger');
            serijeSection.style.display = 'none';
        }
    }

    function clearKatalogForm() {
        if (katalogForm) {
            katalogForm.reset();
            // skrij form dokler ni izbran parfum
            const katalogCard = document.getElementById('katalog-card');
            if (katalogCard) katalogCard.style.display = 'none';
        }
        const perfumeIdEl = document.getElementById('perfume-id');
        if (perfumeIdEl) perfumeIdEl.value = '';
        if (serijeSection) serijeSection.style.display = 'none';
        if (stockStatusSwitch) {
            stockStatusSwitch.checked = false;
        }
        if (syncWithShopifySwitch) {
            syncWithShopifySwitch.checked = false;
            syncSwitchWrapper.title = '';
        }
        
        // Počisti serijska polja
        const serijaStevilkaInput = document.getElementById('serija-stevilka');
        const florgardenFields = document.getElementById('florgarden-serial-fields');
        const serijaLabel = document.querySelector('label[for="serija-stevilka"]');
        const requiredIndicator = document.getElementById('serija-stevilka-required');
        const helpText = document.getElementById('serija-stevilka-help');
        
        if (serijaStevilkaInput) {
            serijaStevilkaInput.style.display = 'block';
            serijaStevilkaInput.disabled = false;
            serijaStevilkaInput.readOnly = false;
            serijaStevilkaInput.value = '';
            serijaStevilkaInput.classList.remove('bg-gray-100', 'cursor-not-allowed', 'mistral-locked');
            serijaStevilkaInput.placeholder = 'Serijska številka';
        }
        
                   if (florgardenFields && !isManufacturerChanging) {
               florgardenFields.classList.add('hidden');
               florgardenFields.style.display = 'none';
               florgardenFields.style.visibility = 'hidden';
               florgardenFields.style.opacity = '0';
               florgardenFields.style.position = 'absolute';
               florgardenFields.style.left = '-9999px';
               console.log('clearKatalogForm: FLORGARDEN fields hidden immediately');
           } else if (florgardenFields && isManufacturerChanging) {
               console.log('clearKatalogForm: Skipping FLORGARDEN fields hide (manufacturer changing)');
           }
        
        if (serijaLabel) {
            serijaLabel.style.display = 'block';
        }
        
        if (requiredIndicator) {
            requiredIndicator.style.display = 'none';
        }
        
        if (helpText) {
            helpText.style.display = 'none';
        }
    }

    if (katalogForm) {
        katalogForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(katalogForm);
            const data = Object.fromEntries(formData.entries());
            
            data.id = data.id ? parseInt(data.id, 10) : null;
            if (data.proizvajalec_id) data.proizvajalec_id = parseInt(data.proizvajalec_id, 10);

            // Dodamo vrednosti tikala iz forme
            const stockEl = document.getElementById('na-zalogi-switch');
            if (stockEl) data.na_zalogi = stockEl.checked;
            const syncEl = document.getElementById('sinhroniziraj-s-shopify');
            if (syncEl) data.sinhroniziraj_s_shopify = syncEl.checked;

            setButtonLoading(savePerfumeButton, true);
            try {
                const response = await fetch('/api/parfumi', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || 'Neznana napaka');
                
                showToast(result.message, 'success');
                
                // Če je bil parfum posodobljen (ima ID), preveri obstoj v Shopify-ju
                if (data.id) {
                    await checkShopifyExists(data.id);
                }
                
                clearKatalogForm();
                loadProizvajalci();
                searchProizvajalecSelect.value = '';
                searchParfumSelect.clear();
                searchParfumSelect.clearOptions();
                searchParfumSelect.disable();
            } catch (error) {
                showToast(`Napaka pri shranjevanju: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(savePerfumeButton, false);
            }
        });
    }

    if (clearFormButton) {
        clearFormButton.addEventListener('click', () => {
            clearKatalogForm();
            searchProizvajalecSelect.value = '';
            searchParfumSelect.clear();
            searchParfumSelect.clearOptions();
            searchParfumSelect.disable();
            showToast('Obrazec počiščen. Pripravljen za nov vnos.', 'success');
        });
    }

    async function handleStockStatusToggle() {
        const perfumeId = document.getElementById('perfume-id').value;
        if (!perfumeId) {
            showToast('Najprej izberite parfum.', 'danger');
            stockStatusSwitch.checked = !stockStatusSwitch.checked;
            return;
        }

        const isInStock = stockStatusSwitch.checked;
        stockStatusSwitch.disabled = true;

        try {
            const response = await fetch(`/api/parfum/${perfumeId}/stock-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ na_zalogi: isInStock })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || result.message || 'Neznana napaka');
            showToast(result.message, 'success');
            
            clearKatalogForm();
            searchProizvajalecSelect.value = '';
            searchParfumSelect.clear();
            searchParfumSelect.clearOptions();
            searchParfumSelect.disable();

        } catch (error) {
            showToast(`Napaka pri posodabljanju zaloge: ${error.message}`, 'danger');
            stockStatusSwitch.checked = !isInStock;
        } finally {
            stockStatusSwitch.disabled = false;
        }
    }

    // Odstranimo trenutne event listener-je za tikala - sedaj se bodo shranila šele ob shranjevanju forme
    // if (stockStatusSwitch) {
    //     stockStatusSwitch.addEventListener('change', handleStockStatusToggle);
    // }

    // if (syncWithShopifySwitch) {
    //     syncWithShopifySwitch.addEventListener('change', handleSyncStatusToggle);
    // }

    // Tikala se sedaj upravljajo samo v formi, ne več takoj ob spremembi

    async function handleSyncStatusToggle() {
        const perfumeId = document.getElementById('perfume-id').value;
        if (!perfumeId) {
            showToast('Najprej izberite parfum, da lahko spremenite nastavitev sinhronizacije.', 'danger');
            syncWithShopifySwitch.checked = !syncWithShopifySwitch.checked;
            return;
        }

        const syncWithShopify = syncWithShopifySwitch.checked;
        syncWithShopifySwitch.disabled = true;

        try {
            // Če vklopujemo sinhronizacijo, najprej preveri, ali parfum obstaja v Shopify-ju
            if (syncWithShopify) {
                const exists = await checkShopifyExists(perfumeId);
                if (!exists) {
                    showToast('Parfum ne obstaja v Shopify-ju. Sinhronizacija ni mogoča.', 'danger');
                    syncWithShopifySwitch.checked = false;
                    return;
                }
            }

            const response = await fetch(`/api/parfum/${perfumeId}/sync-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sinhroniziraj_s_shopify: syncWithShopify })
            });

            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || 'Neznana napaka');
            }
            
            showToast(result.message, 'success');

        } catch (error) {
            showToast(`Napaka pri shranjevanju nastavitve: ${error.message}`, 'danger');
            syncWithShopifySwitch.checked = !syncWithShopify;
        } finally {
            syncWithShopifySwitch.disabled = false;
        }
    }

    // Odstranimo trenutne event listener-je za tikala - sedaj se bodo shranila šele ob shranjevanju forme
    // if (syncWithShopifySwitch) {
    //     syncWithShopifySwitch.addEventListener('change', handleSyncStatusToggle);
    // }

    // Tikala se sedaj upravljajo samo v formi, ne več takoj ob spremembi

    // Dodaj event listener za spremembo šifre parfuma
    const productNoInput = document.getElementById('product-no');
    if (productNoInput) {
        let debounceTimer;
        productNoInput.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(async () => {
                const perfumeId = document.getElementById('perfume-id').value;
                if (perfumeId) {
                    // Preveri obstoj v Shopify-ju po spremembi šifre
                    await checkShopifyExists(perfumeId);
                }
            }, 1000); // Počakaj 1 sekundo po zadnji spremembi
        });
    }

    // Dodaj event listener za spremembo proizvajalca
    const proizvajalecIdSelect = document.getElementById('proizvajalec-id');
    if (proizvajalecIdSelect) {
        proizvajalecIdSelect.addEventListener('change', async function() {
            const perfumeId = document.getElementById('perfume-id').value;
            if (perfumeId) {
                // Preveri obstoj v Shopify-ju po spremembi proizvajalca
                await checkShopifyExists(perfumeId);
            }
        });
    }

    if (syncStockBtn) {
        syncStockBtn.addEventListener('click', async () => {
            showToast('Začenjam sinhronizacijo zaloge iz Shopify... To lahko traja nekaj časa.', 'info');
            setButtonLoading(syncStockBtn, true, 'Sinhroniziram...');

            try {
                const response = await fetch('/api/sync-stock-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (!response.ok) {
                    let errorMsg = 'Neznana napaka';
                    try {
                        const result = await response.json();
                        errorMsg = result.error || 'Neznana napaka';
                    } catch (e) {
                        errorMsg = `Strežnik je vrnil napako ${response.status}.`;
                    }
                    throw new Error(errorMsg);
                }

                const result = await response.json();
                showToast(result.message, 'success');
                
                if (searchProizvajalecSelect.value) {
                    const event = new Event('change');
                    searchProizvajalecSelect.dispatchEvent(event);
                }

            } catch (error) {
                console.error('Napaka pri sinhronizaciji zaloge:', error);
                showToast(`Napaka pri sinhronizaciji: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(syncStockBtn, false);
            }
        });
    }
    if (syncNamesBtn) {
        syncNamesBtn.addEventListener('click', async () => {
            showToast('Začenjam sinhronizacijo imen iz Shopify... To lahko traja nekaj časa.', 'info');
            setButtonLoading(syncNamesBtn, true, 'Sinhroniziram...');

            try {
                const response = await fetch('/api/sync-names', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (!response.ok) {
                    let errorMsg = 'Neznana napaka';
                    try {
                        const result = await response.json();
                        errorMsg = result.error || 'Neznana napaka';
                    } catch (e) {
                        errorMsg = `Strežnik je vrnil napako ${response.status}.`;
                    }
                    throw new Error(errorMsg);
                }

                const result = await response.json();
                showToast(result.message, 'success');
                
                if (searchProizvajalecSelect.value) {
                    const event = new Event('change');
                    searchProizvajalecSelect.dispatchEvent(event);
                }

            } catch (error) {
                console.error('Napaka pri sinhronizaciji imen:', error);
                showToast(`Napaka pri sinhronizaciji: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(syncNamesBtn, false);
            }
        });
    }

    // Gumb za sinhronizacijo parfumov iz Shopify-ja (modal kot app-v2)
    const SYNC_PARFUMI_DEFAULT_STORE = 'amour-parfums-2.myshopify.com';
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
    const syncNewPerfumesBtn = document.getElementById('sync-new-perfumes-btn');
    const syncParfumiModal = document.getElementById('sync-parfumi-modal');
    const syncParfumiStoresEl = document.getElementById('sync-parfumi-stores');
    const syncParfumiDryRunEl = document.getElementById('sync-parfumi-dry-run');
    const syncParfumiResultEl = document.getElementById('sync-parfumi-result');
    const syncParfumiStartBtn = document.getElementById('sync-parfumi-start');
    const syncParfumiStartLabel = document.getElementById('sync-parfumi-start-label');
    const syncParfumiCancelBtn = document.getElementById('sync-parfumi-cancel');
    const syncParfumiCloseBtn = document.getElementById('sync-parfumi-modal-close');
    const syncParfumiProgressEl = document.getElementById('sync-parfumi-progress');
    const syncParfumiProgressTextEl = document.getElementById('sync-parfumi-progress-text');
    let syncParfumiSelectedStore = SYNC_PARFUMI_DEFAULT_STORE;
    let syncParfumiRunning = false;

    if (syncParfumiModal && syncParfumiModal.parentElement !== document.body) {
        document.body.appendChild(syncParfumiModal);
    }

    function setSyncParfumiModalOpen(open) {
        if (!syncParfumiModal) return;
        if (open) {
            if (syncParfumiModal.parentElement !== document.body) {
                document.body.appendChild(syncParfumiModal);
            }
            syncParfumiModal.classList.remove('hidden');
            syncParfumiModal.classList.add('flex');
            document.body.classList.add('overflow-hidden');
        } else {
            syncParfumiModal.classList.add('hidden');
            syncParfumiModal.classList.remove('flex');
            document.body.classList.remove('overflow-hidden');
        }
    }

    function setSyncParfumiProgress(visible, text) {
        if (!syncParfumiProgressEl) return;
        syncParfumiProgressEl.classList.toggle('hidden', !visible);
        if (visible && syncParfumiProgressTextEl && text) {
            syncParfumiProgressTextEl.textContent = text;
        }
    }

    function setSyncParfumiBusy(busy) {
        syncParfumiRunning = busy;
        if (syncParfumiStartBtn) syncParfumiStartBtn.disabled = busy;
        if (syncParfumiCancelBtn) syncParfumiCancelBtn.disabled = busy;
        if (syncParfumiCloseBtn) syncParfumiCloseBtn.disabled = busy;
        if (syncParfumiDryRunEl) syncParfumiDryRunEl.disabled = busy;
        if (syncParfumiStoresEl) {
            syncParfumiStoresEl.querySelectorAll('input[type="radio"]').forEach(r => {
                r.disabled = busy;
            });
        }
        if (syncParfumiStartLabel) {
            syncParfumiStartLabel.textContent = busy ? 'Sinhroniziram...' : (
                syncParfumiDryRunEl?.checked ? 'Simuliraj' : 'Sinhroniziraj'
            );
        }
    }

    function renderSyncParfumiResult(result, errorMsg) {
        if (!syncParfumiResultEl) return;
        syncParfumiResultEl.classList.remove('hidden');

        if (errorMsg) {
            syncParfumiResultEl.innerHTML = `
                <div class="text-sm p-3 rounded-md bg-red-50 text-red-800 border border-red-200">
                    <div class="font-semibold mb-1">Napaka</div>
                    <div class="text-xs">${escapeHtml(errorMsg)}</div>
                </div>`;
            return;
        }

        const r = result || {};
        const skippedSamples = (r.skipped_samples || []).slice(0, 20);
        const errorMessages = (r.error_messages || []).slice(0, 20);
        const durationSec = ((r.duration_ms || 0) / 1000).toFixed(1);

        let skippedHtml = '';
        if (skippedSamples.length) {
            skippedHtml = `
                <details class="text-xs mt-2">
                    <summary class="cursor-pointer font-medium text-amber-700">
                        Preskočeni primeri (${skippedSamples.length}${r.skipped > skippedSamples.length ? ` od ${r.skipped}` : ''})
                    </summary>
                    <ul class="mt-1.5 space-y-1 max-h-32 overflow-y-auto pl-2">
                        ${skippedSamples.map(s => `
                            <li class="text-amber-800 text-[10px] flex justify-between gap-2">
                                <span class="font-mono truncate">${escapeHtml((s.vendor || '') + ' ' + (s.product_no || ''))}</span>
                                <span class="opacity-70">${escapeHtml(s.reason || '')}</span>
                            </li>
                        `).join('')}
                    </ul>
                </details>`;
        }

        let errorsHtml = '';
        if (errorMessages.length) {
            errorsHtml = `
                <details class="text-xs mt-2">
                    <summary class="cursor-pointer font-medium text-red-700">Napake (${errorMessages.length})</summary>
                    <ul class="mt-1.5 space-y-1 max-h-32 overflow-y-auto pl-2">
                        ${errorMessages.map(m => `<li class="text-red-700 font-mono text-[10px]">${escapeHtml(m)}</li>`).join('')}
                    </ul>
                </details>`;
        }

        syncParfumiResultEl.innerHTML = `
            <div class="text-sm rounded-md border border-emerald-200 bg-emerald-50 p-3 space-y-2">
                <div class="flex items-baseline justify-between">
                    <span class="font-semibold text-emerald-900">Sinhronizacija končana</span>
                    <span class="text-[11px] text-emerald-700 tabular-nums">${durationSec}s</span>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Pridobljenih</div>
                        <div class="text-base font-bold tabular-nums">${r.fetched ?? 0}</div>
                    </div>
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Dodanih</div>
                        <div class="text-base font-bold tabular-nums text-emerald-800">${r.added ?? 0}</div>
                    </div>
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Posodobljenih</div>
                        <div class="text-base font-bold tabular-nums text-blue-800">${r.updated ?? 0}</div>
                    </div>
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Preskočenih</div>
                        <div class="text-base font-bold tabular-nums text-amber-800">${r.skipped ?? 0}</div>
                    </div>
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Napake</div>
                        <div class="text-base font-bold tabular-nums text-red-800">${r.errors ?? 0}</div>
                    </div>
                    <div class="bg-white/60 border border-emerald-100 rounded p-1.5">
                        <div class="text-[9px] uppercase tracking-wide text-gray-500 font-semibold">Trgovina</div>
                        <div class="font-mono text-[10px] truncate">${escapeHtml(r.shop_domain || '')}</div>
                    </div>
                </div>
                ${errorsHtml}
                ${skippedHtml}
            </div>`;
    }

    async function loadSyncParfumiStores() {
        if (!syncParfumiStoresEl) return;
        syncParfumiStoresEl.innerHTML = '<p class="text-sm text-gray-500">Nalagam trgovine...</p>';
        try {
            const res = await fetch('/api/shopify-stores');
            const data = await res.json().catch(() => ({}));
            const stores = (res.ok && data.success) ? (data.data || []) : [];
            if (!stores.length) {
                syncParfumiStoresEl.innerHTML = '<p class="text-sm text-red-600">Ni aktivnih Shopify trgovin.</p>';
                syncParfumiSelectedStore = '';
                return;
            }

            const defaultStore = stores.find(s => s.is_sync_default)?.shop_domain
                || stores.find(s => s.shop_domain === SYNC_PARFUMI_DEFAULT_STORE)?.shop_domain
                || stores[0].shop_domain;
            syncParfumiSelectedStore = defaultStore;

            syncParfumiStoresEl.innerHTML = stores.map(s => {
                const checked = s.shop_domain === defaultStore ? 'checked' : '';
                const inactive = s.is_active === false ? '<span class="text-[10px] text-amber-700">neaktivna</span>' : '';
                const defaultBadge = s.is_sync_default
                    ? '<div class="text-[10px] text-emerald-700 font-medium">★ Privzeto (master B2C)</div>'
                    : '';
                return `
                    <label class="flex items-center gap-2.5 px-3 py-2 rounded-md border cursor-pointer transition-colors border-gray-200 hover:bg-gray-50 has-[:checked]:border-emerald-500 has-[:checked]:bg-emerald-50">
                        <input type="radio" name="sync-parfumi-shop" value="${escapeHtml(s.shop_domain)}" ${checked} class="text-emerald-600 focus:ring-emerald-500">
                        <div class="flex-1">
                            <div class="font-mono text-sm">${escapeHtml(s.shop_domain)}</div>
                            ${defaultBadge}
                        </div>
                        ${inactive}
                    </label>`;
            }).join('');

            syncParfumiStoresEl.querySelectorAll('input[name="sync-parfumi-shop"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    if (radio.checked) syncParfumiSelectedStore = radio.value;
                });
            });
        } catch (err) {
            syncParfumiStoresEl.innerHTML = `<p class="text-sm text-red-600">Napaka pri nalaganju trgovin: ${escapeHtml(err.message || String(err))}</p>`;
            syncParfumiSelectedStore = '';
        }
    }

    function resetSyncParfumiModal() {
        if (syncParfumiResultEl) {
            syncParfumiResultEl.classList.add('hidden');
            syncParfumiResultEl.innerHTML = '';
        }
        setSyncParfumiProgress(false);
        if (syncParfumiDryRunEl) syncParfumiDryRunEl.checked = false;
        if (syncParfumiStartLabel) syncParfumiStartLabel.textContent = 'Sinhroniziraj';
        setSyncParfumiBusy(false);
    }

    async function openSyncParfumiModal() {
        if (!syncParfumiModal) {
            showToast('Modal za sinhronizacijo ni na voljo. Osveži stran.', 'danger');
            return;
        }
        resetSyncParfumiModal();
        setSyncParfumiModalOpen(true);
        await loadSyncParfumiStores();
    }

    async function runSyncParfumi() {
        if (!syncParfumiSelectedStore) {
            showToast('Izberi Shopify trgovino.', 'warning');
            return;
        }
        const dryRun = !!syncParfumiDryRunEl?.checked;
        setSyncParfumiBusy(true);
        setSyncParfumiProgress(
            true,
            dryRun
                ? 'Simuliram sinhronizacijo (dry run)…'
                : 'Sinhroniziram izdelke iz Shopify-ja… To lahko traja več minut.',
        );
        if (syncParfumiResultEl) {
            syncParfumiResultEl.classList.add('hidden');
            syncParfumiResultEl.innerHTML = '';
        }

        try {
            const response = await fetch('/api/sync-new-perfumes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    shop_domain: syncParfumiSelectedStore,
                    dry_run: dryRun,
                }),
            });

            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.error || `Strežnik je vrnil napako ${response.status}.`);
            }

            renderSyncParfumiResult(payload.result, null);
            showToast(payload.message || 'Sinhronizacija končana.', 'success');

            if (!dryRun) {
                await loadProizvajalci();
                if (searchProizvajalecSelect?.value) {
                    searchProizvajalecSelect.dispatchEvent(new Event('change'));
                }
            }
        } catch (error) {
            console.error('Napaka pri sinhronizaciji parfumov:', error);
            renderSyncParfumiResult(null, error.message);
            showToast(`Napaka pri sinhronizaciji: ${error.message}`, 'danger');
        } finally {
            setSyncParfumiProgress(false);
            setSyncParfumiBusy(false);
            if (syncParfumiStartLabel) {
                syncParfumiStartLabel.textContent = syncParfumiDryRunEl?.checked ? 'Simuliraj' : 'Ponovi';
            }
        }
    }

    if (syncNewPerfumesBtn) {
        syncNewPerfumesBtn.addEventListener('click', () => {
            openSyncParfumiModal();
        });
    }
    if (syncParfumiStartBtn) {
        syncParfumiStartBtn.addEventListener('click', runSyncParfumi);
    }
    if (syncParfumiCancelBtn) {
        syncParfumiCancelBtn.addEventListener('click', () => {
            if (!syncParfumiRunning) setSyncParfumiModalOpen(false);
        });
    }
    if (syncParfumiCloseBtn) {
        syncParfumiCloseBtn.addEventListener('click', () => {
            if (!syncParfumiRunning) setSyncParfumiModalOpen(false);
        });
    }
    if (syncParfumiModal) {
        syncParfumiModal.addEventListener('click', (e) => {
            if (e.target === syncParfumiModal && !syncParfumiRunning) {
                setSyncParfumiModalOpen(false);
            }
        });
    }
    if (syncParfumiDryRunEl) {
        syncParfumiDryRunEl.addEventListener('change', () => {
            if (!syncParfumiRunning && syncParfumiStartLabel) {
                syncParfumiStartLabel.textContent = syncParfumiDryRunEl.checked ? 'Simuliraj' : 'Sinhroniziraj';
            }
        });
    }

    if (syncDataStatusBtn) {
        syncDataStatusBtn.addEventListener('click', async function() {
            showToast('Začenjam sinhronizacijo statusov... To lahko traja nekaj časa.', 'info');
            setButtonLoading(this, true, 'Sinhroniziram...');
        
            try {
                const response = await fetch('/api/sync-data-status', {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Neznana napaka s strežnika.');
                }
                showToast(data.message, 'success');
            } catch (error) {
                console.error('Error:', error);
                showToast(`Napaka: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(this, false);
            }
        });
    }

    // Event listener za toggle-email-mode gumb
    const toggleEmailModeBtn = document.getElementById('toggle-email-mode-btn');
    if (toggleEmailModeBtn) {
        toggleEmailModeBtn.addEventListener('click', function() {
            if (typeof window.toggleEmailMode === 'function') {
                window.toggleEmailMode();
            } else {
                console.error('toggleEmailMode function not available');
            }
        });
    }

    // --- Logika za ZALOGO (Serije) ---
    
    // Event listenerji za serije
    document.addEventListener('submit', async function(e) {
        if (e.target.id === 'serija-form') {
            e.preventDefault();
            await addSerija();
        }
    });
    
    async function addSerija() {
        const form = document.getElementById('serija-form');
        const formData = new FormData(form);
        
        // Pridobi podatke iz forme
        const serijaData = {
            parfum_id: parseInt(formData.get('parfum_id')),
            rok_uporabe: formData.get('rok_uporabe'),
            serijska_stevilka: formData.get('serijska_stevilka'),
            stanje: formData.get('stanje') || 'NA ZALOGI',
            datum_odprtja: formData.get('datum_odprtja') || null,
            je_tester: formData.get('je_tester') === 'on'
        };
        
        // Preveri obvezna polja
        if (!serijaData.parfum_id || !serijaData.rok_uporabe) {
            showToast('Prosim izpolnite vsa obvezna polja', 'error');
            return;
        }
        
        const submitButton = document.getElementById('add-serija-button');
        setButtonLoading(submitButton, true, 'Dodajam...');
        
        try {
            // Preveri, ali smo online
            if (isOnline) {
                // Online način - pošlji na strežnik
                const response = await fetch('/api/serije', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(serijaData)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showToast('Serija uspešno dodana', 'success');
                    form.reset();
                    clearSerijaForm();
                    await loadSerijeForPerfume(serijaData.parfum_id);
                } else {
                    throw new Error(result.error || 'Napaka pri dodajanju serije');
                }
            } else {
                // Offline način - shrani lokalno
                await addSerijaOffline(serijaData);
                showToast('Serija dodana offline - sinhronizirana bo ob ponovni povezavi', 'success');
                form.reset();
                clearSerijaForm();
                await loadSerijeForPerfume(serijaData.parfum_id);
            }
        } catch (error) {
            console.error('Napaka pri dodajanju serije:', error);
            showToast(error.message, 'error');
        } finally {
            setButtonLoading(submitButton, false);
        }
    }
    
    // Odpri formo za dodajanje/urejanje serije (prazno za dodajanje)
    function openAddSerijaForm() {
        try {
            const section = document.getElementById('serije-section');
            const form = document.getElementById('serija-form');
            if (section) {
                section.style.display = 'block';
                section.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            if (form) {
                if (typeof clearSerijaForm === 'function') clearSerijaForm();
                const rok = document.getElementById('serija-rok');
                const serijska = document.getElementById('serija-stevilka');
                (rok || serijska)?.focus?.();
            }
        } catch (e) {
            console.warn('openAddSerijaForm error:', e);
        }
    }
    
    async function addSerijaOffline(serijaData) {
        try {
            // Dodaj v lokalno bazo
            const localSerija = {
                ...serijaData,
                id: Date.now(), // Privzeto ID
                created_at: new Date().toISOString(),
                vnesel_uporabnik: 'Offline User'
            };
            
            await localDB.add('serije', localSerija);
            
            // Dodaj v sync queue
            if (window.syncManager) {
                await syncManager.queueAddSerija(serijaData);
            }
            
            console.log('Serija dodana offline:', localSerija);
            
        } catch (error) {
            console.error('Napaka pri dodajanju serije offline:', error);
            throw new Error('Napaka pri shranjevanju offline');
        }
    }
    
    let serijePagination = { page: 1, perPage: 10, items: [] };

    async function loadSerijeForPerfume(perfumeId) {
        if (!serijeTableBody) return;
        serijeTableBody.innerHTML = '<tr><td colspan="6" class="text-center"><div class="spinner-border spinner-border-sm"></div></td></tr>';
        clearSerijaForm();
        document.getElementById('serija-parfum-id').value = perfumeId;
        
        // Takoj preveri zaklepanje serijske številke
        preveriZaklepanjeSerijske();

        try {
            // 1. Najprej poskusi naložiti iz lokalne baze
            let localSerije = [];
            if (window.localDB) {
                try {
                    localSerije = await localDB.getSerijeForPerfume(perfumeId);
                    console.log(`Naloženih ${localSerije.length} serij iz lokalne baze za parfum ${perfumeId}`);
                } catch (error) {
                    console.warn('Napaka pri nalaganju serij iz lokalne baze:', error);
                }
            }
            
            // 2. Če je online, sinhroniziraj z API in posodobi lokalno bazo
            let apiSerije = null;
            if (isOnline) {
        try {
            const response = await fetch(`/api/parfum/${perfumeId}/serije`);
                    if (response.ok) {
                        apiSerije = await response.json();
                        console.log(`Naloženih ${apiSerije.length} serij iz API za parfum ${perfumeId}`);
                        
                        // Shrani v lokalno bazo
                        if (window.localDB && apiSerije) {
                            await localDB.saveSerije(apiSerije);
                            console.log('Serije shranjene v lokalno bazo');
                        }
                    } else {
                        console.warn(`API napaka pri nalaganju serij: ${response.status}`);
                    }
                } catch (error) {
                    console.warn('Napaka pri API klicu za serije:', error);
                }
            }
            
            // 3. Določi, katere podatke uporabiti
            let serije = [];
            if (apiSerije && apiSerije.length >= 0) {
                serije = apiSerije;
                console.log('Uporabljam serije iz API');
            } else if (localSerije.length > 0) {
                serije = localSerije;
                console.log('Uporabljam serije iz lokalne baze (offline mode)');
                
                // Prikaži offline indikator
                if (window.showToast) {
                    window.showToast('Prikazujem serije iz lokalne baze (offline)', 'warning');
                }
            } else {
                console.log('Ni serij za prikaz');
            }

            // 4. Shranimo podatke in prikažemo paginirano
            serijePagination.items = serije;
            serijePagination.page = 1;
            renderSerijePage();
        } catch (error) {
            showToast(`Napaka pri nalaganju zaloge: ${error.message}`, 'danger');
            serijeTableBody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Napaka pri nalaganju.</td></tr>';
        }
        
        // Posodobi vizualne indikatorje za serijsko številko
        updateSerialNumberIndicators(perfumeId);

        // Inicializiraj scroll gumbe (desktop)
        try {
            const wrap = document.getElementById('serije-scroll-wrapper');
            if (wrap) {
                const up = wrap.querySelector('.scroll-up');
                const down = wrap.querySelector('.scroll-down');
                const left = wrap.querySelector('.scroll-left');
                const right = wrap.querySelector('.scroll-right');
                const sc = wrap; // same element has overflow
                const step = 80;
                const xstep = 120;
                const attach = (btn, fn) => { if (btn) { btn.onclick = fn; btn.classList.remove('hidden'); btn.classList.add('flex'); } };
                attach(up, () => sc.scrollBy({ top: -step, behavior: 'smooth' }));
                attach(down, () => sc.scrollBy({ top: step, behavior: 'smooth' }));
                attach(left, () => sc.scrollBy({ left: -xstep, behavior: 'smooth' }));
                attach(right, () => sc.scrollBy({ left: xstep, behavior: 'smooth' }));
            }
        } catch(e) { console.warn('Scroll buttons init failed', e); }
    }

    function renderSerijePage() {
        const start = (serijePagination.page - 1) * serijePagination.perPage;
        const end = start + serijePagination.perPage;
        const pageItems = serijePagination.items.slice(start, end);

        const totalPages = Math.max(1, Math.ceil(serijePagination.items.length / serijePagination.perPage));
        const pagEl = document.getElementById('serije-pagination');
        const pageEl = document.getElementById('serije-page');
        const totalEl = document.getElementById('serije-total-pages');
        const prevBtn = document.getElementById('serije-prev');
        const nextBtn = document.getElementById('serije-next');

        if (serijePagination.items.length > serijePagination.perPage) {
            if (pagEl) pagEl.style.display = 'flex';
            if (pageEl) pageEl.textContent = String(serijePagination.page);
            if (totalEl) totalEl.textContent = String(totalPages);
            if (prevBtn) {
                prevBtn.disabled = serijePagination.page <= 1;
                prevBtn.onclick = () => { serijePagination.page = Math.max(1, serijePagination.page - 1); renderSerijePage(); };
            }
            if (nextBtn) {
                nextBtn.disabled = serijePagination.page >= totalPages;
                nextBtn.onclick = () => { serijePagination.page = Math.min(totalPages, serijePagination.page + 1); renderSerijePage(); };
            }
        } else {
            if (pagEl) pagEl.style.display = 'none';
        }

        if (pageItems.length > 0) {
            serijeTableBody.innerHTML = pageItems.map(s => `
                    <tr>
                        <td class="w-24">${new Date(s.rok_uporabe).toLocaleDateString('sl-SI')}</td>
                        <td class="w-32">${s.serijska_stevilka || 'N/A'}</td>
                        <td class="w-24">${s.datum_odprtja ? new Date(s.datum_odprtja).toLocaleDateString('sl-SI') : 'N/A'}</td>
                        <td class="w-16 text-center">${s.je_tester ? '<i class="bi bi-check-circle-fill text-success"></i>' : '<i class="bi bi-x-circle text-muted"></i>'}</td>
                        <td class="w-32">${s.vnesel_uporabnik || 'N/A'}</td>
                        <td class="w-40 text-xs text-gray-600">${(s.updated_by ? `${s.updated_by}` : '-') + (s.updated_at ? ` · ${new Date(s.updated_at).toLocaleString('sl-SI')}` : '')}</td>
                        <td class="w-24">
                            ${s.can_edit ? `<button class="btn btn-sm btn-outline-primary edit-serija-btn" data-serija='${JSON.stringify(s)}'><i class="bi bi-pencil"></i></button>` : ''}
                            ${s.can_delete ? `<button class="btn btn-sm btn-outline-danger delete-serija-btn" data-id="${s.id}"><i class="bi bi-trash"></i></button>` : ''}
                            ${!s.can_edit && !s.can_delete ? '<span class="text-muted text-xs">Ni dovoljenj</span>' : ''}
                        </td>
                    </tr>
                `).join('');
                
                const proizvajalecIme = pageItems[0]?.ime_proizvajalca || '';
                document.getElementById('serija-stevilka').disabled = (proizvajalecIme.toUpperCase() === 'MISTRAL');

            } else {
                serijeTableBody.innerHTML = '<tr><td colspan="7" class="text-center">Za ta parfum ni vnesenih serij.</td></tr>';
                const selectedProizvajalecId = document.getElementById('search-proizvajalec').value;
                const selectedProizvajalecOption = document.querySelector(`#search-proizvajalec option[value='${selectedProizvajalecId}']`);
                if (selectedProizvajalecOption) {
                    document.getElementById('serija-stevilka').disabled = (selectedProizvajalecOption.textContent.toUpperCase() === 'MISTRAL');
                }
            }
    }

    // Funkcija za preverjanje in zaklepanje serijske številke
    async function preveriZaklepanjeSerijske() {
        console.log('preveriZaklepanjeSerijske called');
        
        const serijaStevilkaInput = document.getElementById('serija-stevilka');
        const requiredIndicator = document.getElementById('serija-stevilka-required');
        const helpText = document.getElementById('serija-stevilka-help');
        const florgardenFields = document.getElementById('florgarden-serial-fields');
        
        console.log('Found elements:', {
            serijaStevilkaInput: !!serijaStevilkaInput,
            requiredIndicator: !!requiredIndicator,
            helpText: !!helpText,
            florgardenFields: !!florgardenFields
        });
        
        if (!serijaStevilkaInput) {
            console.log('serija-stevilka input not found');
            return;
        }
        
        // Pridobi trenutno izbran parfum
        const selectedPerfumeId = document.getElementById('serija-parfum-id')?.value;
        if (!selectedPerfumeId) {
            console.log('No perfume selected');
            return;
        }
        
        try {
            const response = await fetch(`/api/parfum/${selectedPerfumeId}`);
            const perfume = await response.json();
            
                           console.log('API response for perfume:', perfume);
               console.log('Perfume object keys:', Object.keys(perfume));
               console.log('ime_proizvajalca value:', perfume.ime_proizvajalca);
               console.log('ime_proizvajalca type:', typeof perfume.ime_proizvajalca);
               console.log('proizvajalec value:', perfume.proizvajalec);
               console.log('ime value:', perfume.ime);
               console.log('naziv value:', perfume.naziv);
               
               // Preveri različne možne imena polj za proizvajalca
               let proizvajalec = perfume.ime_proizvajalca?.toUpperCase();
               
               // Če ni najdeno, preveri druge možnosti
               if (!proizvajalec) {
                   proizvajalec = perfume.proizvajalec?.toUpperCase();
               }
               if (!proizvajalec) {
                   proizvajalec = perfume.ime?.toUpperCase();
               }
               if (!proizvajalec) {
                   proizvajalec = perfume.naziv?.toUpperCase();
               }
               
               console.log('Checking serial number lock for:', proizvajalec);
               console.log('proizvajalec type:', typeof proizvajalec);
            
            if (proizvajalec === 'FLORGARDEN') {
                console.log('FLORGARDEN detected - showing special input field');
                
                // Odstrani MISTRAL omejitve
                serijaStevilkaInput.disabled = false;
                serijaStevilkaInput.readOnly = false;
                serijaStevilkaInput.classList.remove('bg-gray-100', 'cursor-not-allowed', 'mistral-locked');
                serijaStevilkaInput.classList.add('border-red-300', 'focus:border-red-500', 'focus:ring-red-500');
                
                // Posodobi indikatorje
                if (requiredIndicator) requiredIndicator.style.display = 'inline';
                if (helpText) {
                    helpText.style.display = 'block';
                    helpText.textContent = 'Za FLORGARDEN je serijska številka obvezna - vnesite podatke v razdeljena polja';
                }
                
                // Skrij standardno polje in prikaži FLORGARDEN polje
                serijaStevilkaInput.style.display = 'none';
                if (florgardenFields) {
                    florgardenFields.classList.remove('hidden');
                    florgardenFields.style.display = 'block'; // Eksplicitno nastavi display
                    florgardenFields.style.visibility = 'visible'; // Ponovno prikaži
                    florgardenFields.style.opacity = '1'; // Ponovno prikaži
                    florgardenFields.style.position = 'static'; // Vrni v normalni tok
                    florgardenFields.style.left = 'auto'; // Vrni na normalno pozicijo
                    console.log('FLORGARDEN fields should now be visible');
                    console.log('florgardenFields display style:', florgardenFields.style.display);
                    console.log('florgardenFields classList:', florgardenFields.classList.toString());
                    console.log('FLORGARDEN: florgardenFields visibility:', florgardenFields.style.visibility);
                    console.log('FLORGARDEN: florgardenFields opacity:', florgardenFields.style.opacity);
                    
                    // Inicializiraj FLORGARDEN input polja
                    setupFlorgardenInputs();
                } else {
                    console.log('florgardenFields element not found!');
                }
                
                // Prikaži label "Serijska št." za FLORGARDEN
                const serijaLabel = document.querySelector('label[for="serija-stevilka"]');
                if (serijaLabel) {
                    serijaLabel.style.display = 'block';
                }
                
            } else if (proizvajalec === 'MISTRAL') {
                console.log('MISTRAL detected - LOCKING serial number field');
                
                // Odstrani vse obstoječe event listener-je za MISTRAL
                const mistralEventListeners = serijaStevilkaInput._mistralEventListeners || [];
                mistralEventListeners.forEach(({event, listener}) => {
                    serijaStevilkaInput.removeEventListener(event, listener);
                });
                serijaStevilkaInput._mistralEventListeners = [];
                
                // Popolno skrij polje za MISTRAL
                serijaStevilkaInput.style.display = 'none';
                serijaStevilkaInput.disabled = true;
                serijaStevilkaInput.readOnly = true;
                serijaStevilkaInput.value = '';
                serijaStevilkaInput.placeholder = 'Za MISTRAL se serijska številka ne sme vnašati';
                serijaStevilkaInput.classList.add('bg-gray-100', 'cursor-not-allowed', 'mistral-locked');
                serijaStevilkaInput.classList.remove('border-red-300', 'focus:border-red-500', 'focus:ring-red-500');
                
                // Dodaj event listener-je za preprečevanje vnosa
                const keydownListener = function(e) {
                    e.preventDefault();
                    return false;
                };
                const inputListener = function(e) {
                    e.preventDefault();
                    this.value = '';
                    return false;
                };
                const pasteListener = function(e) {
                    e.preventDefault();
                    return false;
                };
                const dropListener = function(e) {
                    e.preventDefault();
                    return false;
                };
                
                serijaStevilkaInput.addEventListener('keydown', keydownListener);
                serijaStevilkaInput.addEventListener('input', inputListener);
                serijaStevilkaInput.addEventListener('paste', pasteListener);
                serijaStevilkaInput.addEventListener('drop', dropListener);
                
                // Shrani event listener-je za poznejše odstranjevanje
                serijaStevilkaInput._mistralEventListeners = [
                    {event: 'keydown', listener: keydownListener},
                    {event: 'input', listener: inputListener},
                    {event: 'paste', listener: pasteListener},
                    {event: 'drop', listener: dropListener}
                ];
                
                // Posodobi indikatorje
                if (requiredIndicator) requiredIndicator.style.display = 'none';
                if (helpText) {
                    helpText.style.display = 'none'; // Skrij help text za MISTRAL
                }
                if (florgardenFields) {
                    florgardenFields.classList.add('hidden');
                    florgardenFields.style.display = 'none'; // Eksplicitno skrij
                    florgardenFields.style.visibility = 'hidden'; // Dodatno skrivanje
                    florgardenFields.style.opacity = '0'; // Dodatno skrivanje
                    florgardenFields.style.position = 'absolute'; // Popolno odstrani iz toka
                    florgardenFields.style.left = '-9999px'; // Premakni iz vidnega polja
                    console.log('MISTRAL: FLORGARDEN fields should now be hidden');
                    console.log('MISTRAL: florgardenFields display style:', florgardenFields.style.display);
                    console.log('MISTRAL: florgardenFields classList:', florgardenFields.classList.toString());
                    console.log('MISTRAL: florgardenFields visibility:', florgardenFields.style.visibility);
                    console.log('MISTRAL: florgardenFields opacity:', florgardenFields.style.opacity);
                }
                
                // Skrij label "Serijska št." za MISTRAL
                const serijaLabel = document.querySelector('label[for="serija-stevilka"]');
                if (serijaLabel) {
                    serijaLabel.style.display = 'none';
                }
                
            } else {
                console.log('Other manufacturer - standard input field');
                
                // Odstrani vse omejitve
                serijaStevilkaInput.disabled = false;
                serijaStevilkaInput.readOnly = false;
                serijaStevilkaInput.style.display = 'block';
                serijaStevilkaInput.classList.remove('bg-gray-100', 'cursor-not-allowed', 'mistral-locked', 'border-red-300', 'focus:border-red-500', 'focus:ring-red-500');
                serijaStevilkaInput.placeholder = 'Serijska številka';
                
                // Posodobi indikatorje
                if (requiredIndicator) requiredIndicator.style.display = 'none';
                if (helpText) {
                    helpText.style.display = 'block';
                    helpText.textContent = 'Serijska številka je opcijska za ta proizvajalec';
                }
                if (florgardenFields) florgardenFields.classList.add('hidden');
                
                // Prikaži standardno polje in label za druge proizvajalce
                serijaStevilkaInput.style.display = 'block';
                serijaStevilkaInput.disabled = false;
                serijaStevilkaInput.readOnly = false;
                serijaStevilkaInput.classList.remove('bg-gray-100', 'cursor-not-allowed', 'mistral-locked');
                
                // Prikaži label "Serijska št." za druge proizvajalce
                const serijaLabel = document.querySelector('label[for="serija-stevilka"]');
                if (serijaLabel) {
                    serijaLabel.style.display = 'block';
                }
            }
            
        } catch (error) {
            console.error('Error checking serial number lock:', error);
        }
    }
    
    // Funkcija za posodobitev vizualnih indikatorjev za serijsko številko (za kompatibilnost)
    async function updateSerialNumberIndicators(perfumeId) {
        console.log('updateSerialNumberIndicators called with perfumeId:', perfumeId);
        
        // Počakaj malo, da se DOM posodobi
        setTimeout(() => {
            preveriZaklepanjeSerijske();
        }, 100);
    }

    function clearSerijaForm() {
        if (serijaForm) serijaForm.reset();
        const serijaIdEl = document.getElementById('serija-id');
        if (serijaIdEl) serijaIdEl.value = '';
    }
    
    if (clearSerijaFormButton) {
        clearSerijaFormButton.addEventListener('click', clearSerijaForm);
    }

    function fillSerijaForm(serija) {
        document.getElementById('serija-id').value = serija.id;
        document.getElementById('serija-rok').value = formatDateForInput(serija.rok_uporabe);
        document.getElementById('serija-datum-odprtja').value = formatDateForInput(serija.datum_odprtja);
        document.getElementById('serija-je-tester').checked = serija.je_tester;
        
        // Preveri, ali je FLORGARDEN in razčleni serijsko številko
        const selectedPerfumeId = document.getElementById('serija-parfum-id').value;
        if (selectedPerfumeId) {
            fetch(`/api/parfum/${selectedPerfumeId}`)
                .then(response => response.json())
                .then(perfume => {
                    const isFlorgarden = perfume.proizvajalec && perfume.proizvajalec.toUpperCase() === 'FLORGARDEN';
                    
                    if (isFlorgarden && serija.serijska_stevilka) {
                        // Razčleni v FLORGARDEN polja
                        parseFlorgardenSerialNumber(serija.serijska_stevilka);
                    } else {
                        // Standardno polje
                        document.getElementById('serija-stevilka').value = serija.serijska_stevilka || '';
                    }
                })
                .catch(error => {
                    console.error('Napaka pri pridobivanju podatkov o parfumu:', error);
                    // Fallback na standardno polje
                    document.getElementById('serija-stevilka').value = serija.serijska_stevilka || '';
                });
        } else {
            // Fallback na standardno polje
            document.getElementById('serija-stevilka').value = serija.serijska_stevilka || '';
        }
    }
    // Funkcija za avtomatsko določanje roka uporabe iz serijske številke FLORGARDEN
    function calculateExpiryDateFromSerial(serialNumber) {
        if (!serialNumber || typeof serialNumber !== 'string') return null;
        
        // Vzorec za FLORGARDEN serijsko številko: "24/14385 047/1608"
        const pattern = /(\d{2})\/(\d{5})\s+(\d{3})\/(\d{4})/;
        const match = serialNumber.match(pattern);
        
        if (!match) return null;
        
        try {
            const [, , , , lastFour] = match;
            
            // Zadnje štiri številke določajo DDMM
            const day = parseInt(lastFour.substring(0, 2));
            const month = parseInt(lastFour.substring(2, 4));
            
            // Prvi dve številki določata (YY+3)
            const yearCode = parseInt(lastFour.substring(0, 2));
            const year = 2000 + yearCode + 3; // YY + 3
            
            // Preveri veljavnost datuma
            const date = new Date(year, month - 1, day); // month - 1 ker je 0-based
            if (date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day) {
                return date.toISOString().split('T')[0]; // Vrne YYYY-MM-DD format
            }
        } catch (error) {
            console.error('Napaka pri izračunu datuma:', error);
        }
        
        return null;
    }

    // Funkcija za FLORGARDEN serijsko številko (kot kreditna kartica)
    function buildFlorgardenSerialNumber() {
        // Sestavi vrednost iz 4 ločenih polj
        const parts = ['fg-yy', 'fg-aaaaa', 'fg-bbb', 'fg-ddmm'].map(id => document.getElementById(id));
        
        if (parts.every(Boolean)) {
            const val = `${parts[0].value}/${parts[1].value} ${parts[2].value}/${parts[3].value}`;
            console.log('buildFlorgardenSerialNumber built:', val);
            return val;
        }
        
        // Fallback na skrito polje
        const hiddenInput = document.getElementById('serija-stevilka');
        if (hiddenInput) {
            console.log('buildFlorgardenSerialNumber fallback:', hiddenInput.value);
            return hiddenInput.value.trim();
        }
        
        return '';
    }
    
    // Funkcija za razčlenjevanje FLORGARDEN serijske številke
    function parseFlorgardenSerialNumber(serialNumber) {
        if (!serialNumber) return;
        
        const input = document.getElementById('florgarden-serial-input');
        if (input) {
            input.value = serialNumber;
            updateFlorgardenPlaceholders();
        }
    }
    
    // Funkcija za posodobitev placeholder-jev v FLORGARDEN polju
    function updateFlorgardenPlaceholders() {
        const input = document.getElementById('florgarden-serial-input');
        const placeholders = document.querySelectorAll('.florgarden-placeholder');
        
        if (!input || !placeholders.length) return;
        
        const value = input.value;
        
        placeholders.forEach(placeholder => {
            const pos = parseInt(placeholder.getAttribute('data-pos'));
            const char = value[pos];
            
            if (char && char !== ' ' && char !== '/') {
                placeholder.classList.add('filled');
                placeholder.classList.remove('empty');
            } else {
                placeholder.classList.remove('filled');
                placeholder.classList.add('empty');
            }
        });
    }
    
    // Event listener za avtomatsko določanje roka uporabe iz serijske številke
    const serijaStevilkaInput = document.getElementById('serija-stevilka');
    if (serijaStevilkaInput) {
        serijaStevilkaInput.addEventListener('input', async function() {
            const selectedPerfumeId = document.getElementById('serija-parfum-id').value;
            
            // Preveri, ali je proizvajalec FLORGARDEN
            if (selectedPerfumeId) {
                try {
                    const response = await fetch(`/api/parfum/${selectedPerfumeId}`);
                    const perfume = await response.json();
                    const isFlorgarden = perfume.proizvajalec && perfume.proizvajalec.toUpperCase() === 'FLORGARDEN';
                    
                    if (isFlorgarden) {
                        // Aplikiraj input mask za FLORGARDEN
                        applyFlorgardenInputMask(this);
                        
                        // Preveri avtomatski izračun roka uporabe
                        const serijskaStevilka = this.value.trim();
                        if (serijskaStevilka && serijskaStevilka.length === 17) {
                            const calculatedDate = calculateExpiryDateFromSerial(serijskaStevilka);
                            if (calculatedDate) {
                                document.getElementById('serija-rok').value = calculatedDate;
                                showToast(`Avtomatsko določen rok uporabe: ${new Date(calculatedDate).toLocaleDateString('sl-SI')}`, 'success');
                            }
                        }
                    }
                } catch (error) {
                    console.error('Napaka pri pridobivanju podatkov o parfumu:', error);
                }
            }
        });
    }
    
    // Event listener za FLORGARDEN polje (kot kreditna kartica)
    console.log('Looking for florgarden-serial-input element...');
    const florgardenInput = document.getElementById('florgarden-serial-input');
    const florgardenFields = document.getElementById('florgarden-serial-fields');
    
    console.log('FLORGARDEN elements check:', {
        florgardenInput: !!florgardenInput,
        florgardenFields: !!florgardenFields
    });
    
    if (florgardenInput) {
        console.log('Found florgarden-serial-input, setting up event listeners');
        // Samo številke in avtomatsko formatiranje
        florgardenInput.addEventListener('input', function(e) {
            let value = this.value.replace(/\D/g, ''); // Odstrani vse, kar ni številka
            
            // Aplikiraj format YY/AAAAA BBB/DDMM
            if (value.length > 0) {
                if (value.length > 2) { value = value.substring(0, 2) + '/' + value.substring(2); }
                if (value.length > 8) { value = value.substring(0, 8) + ' ' + value.substring(8); }
                if (value.length > 12) { value = value.substring(0, 12) + '/' + value.substring(12); }
            }
            
            // Omeji dolžino
            if (value.length > 17) { value = value.substring(0, 17); }
            
            this.value = value;
            updateFlorgardenPlaceholders();
            
            // Avtomatski izračun roka uporabe za FLORGARDEN
            if (value && value.length === 17) {
                const calculatedDate = calculateExpiryDateFromSerial(value);
                if (calculatedDate) {
                    document.getElementById('serija-rok').value = calculatedDate;
                    showToast(`Avtomatsko določen rok uporabe: ${new Date(calculatedDate).toLocaleDateString('sl-SI')}`, 'success');
                }
            }
        });
        
        // Prepreči vnos črk
        florgardenInput.addEventListener('keypress', function(e) {
            const char = String.fromCharCode(e.which);
            if (!/\d/.test(char)) {
                e.preventDefault();
                return false;
            }
        });
        
        // Prepreči paste črk
        florgardenInput.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedText = (e.clipboardData || window.clipboardData).getData('text');
            const numbersOnly = pastedText.replace(/\D/g, '');
            
            if (numbersOnly) {
                let value = this.value.replace(/\D/g, '') + numbersOnly;
                
                // Aplikiraj format
                if (value.length > 2) { value = value.substring(0, 2) + '/' + value.substring(2); }
                if (value.length > 8) { value = value.substring(0, 8) + ' ' + value.substring(8); }
                if (value.length > 12) { value = value.substring(0, 12) + '/' + value.substring(12); }
                if (value.length > 17) { value = value.substring(0, 17); }
                
                this.value = value;
                updateFlorgardenPlaceholders();
            }
        });
        
        // Posodobi placeholders ob focus
        florgardenInput.addEventListener('focus', function() {
            updateFlorgardenPlaceholders();
        });
        
        // Posodobi placeholders ob blur
        florgardenInput.addEventListener('blur', function() {
            updateFlorgardenPlaceholders();
        });
    }

    // Funkcija za input mask FLORGARDEN serijske številke
    function applyFlorgardenInputMask(input) {
        let value = input.value.replace(/\D/g, ''); // Odstrani vse, kar ni številka
        
        // Aplikiraj format YY/AAAAA BBB/DDMM
        if (value.length > 0) {
            // Dodaj prvi slash po 2 številkah
            if (value.length > 2) {
                value = value.substring(0, 2) + '/' + value.substring(2);
            }
            
            // Dodaj presledek po 7 številkah (2 + 5)
            if (value.length > 8) {
                value = value.substring(0, 8) + ' ' + value.substring(8);
            }
            
            // Dodaj drugi slash po 11 številkah (2 + 5 + 3)
            if (value.length > 12) {
                value = value.substring(0, 12) + '/' + value.substring(12);
            }
        }
        
        // Omeji na 17 znakov (YY/AAAAA BBB/DDMM)
        if (value.length > 17) {
            value = value.substring(0, 17);
        }
        
        input.value = value;
    }

    if (serijaForm) {
        serijaForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const button = this.querySelector('button[type="submit"]');
            const serijaId = document.getElementById('serija-id').value;
            
            // Preveri, ali je proizvajalec FLORGARDEN
            const selectedPerfumeId = document.getElementById('serija-parfum-id').value;
            let serijskaStevilka = document.getElementById('serija-stevilka').value;
            
            // Pridobi podatke o parfumu za preverjanje proizvajalca
            let isFlorgarden = false;
            if (selectedPerfumeId) {
                try {
                    const response = await fetch(`/api/parfum/${selectedPerfumeId}`);
                    const perfume = await response.json();
                    isFlorgarden = perfume.proizvajalec && perfume.proizvajalec.toUpperCase() === 'FLORGARDEN';
                } catch (error) {
                    console.error('Napaka pri pridobivanju podatkov o parfumu:', error);
                }
            }
            
            // Validacija za serijsko številko - obvezna samo za FLORGARDEN
            if (isFlorgarden && !serijskaStevilka.trim()) {
                showToast('Za proizvajalca FLORGARDEN je serijska številka obvezna!', 'danger');
                return;
            }
            
            // Validacija formata za FLORGARDEN
            if (isFlorgarden && serijskaStevilka.trim()) {
                const pattern = /^\d{2}\/\d{5}\s+\d{3}\/\d{4}$/;
                if (!pattern.test(serijskaStevilka.trim())) {
                    showToast('Serijska številka mora biti v formatu: YY/AAAAA BBB/DDMM', 'danger');
                    return;
                }
            }
            
            // Preveri, ali je FLORGARDEN ali MISTRAL in validiraj serijsko številko
            serijskaStevilka = serijskaStevilka.trim();
            
            try {
                const response = await fetch(`/api/parfum/${selectedPerfumeId}`);
                const perfume = await response.json();
                const isFlorgarden = perfume.proizvajalec && perfume.proizvajalec.toUpperCase() === 'FLORGARDEN';
                const isMistral = perfume.proizvajalec && perfume.proizvajalec.toUpperCase() === 'MISTRAL';
                
                if (isFlorgarden) {
                    serijskaStevilka = buildFlorgardenSerialNumber();
                    
                    // Preveri, ali je serijska številka izpolnjena
                    if (!serijskaStevilka || serijskaStevilka.length !== 17) {
                        showToast('Za FLORGARDEN mora biti serijska številka izpolnjena v formatu YY/AAAAA BBB/DDMM!', 'danger');
                        return;
                    }
                    
                    // Preveri format
                    const pattern = /^\d{2}\/\d{5}\s+\d{3}\/\d{4}$/;
                    if (!pattern.test(serijskaStevilka)) {
                        showToast('Serijska številka mora biti v formatu YY/AAAAA BBB/DDMM!', 'danger');
                        return;
                    }
                } else if (isMistral) {
                    // Za MISTRAL preveri, ali je serijska številka prazna
                    if (serijskaStevilka && serijskaStevilka.trim()) {
                        showToast('Za MISTRAL proizvajalca se serijska številka ne sme vnašati!', 'danger');
                        return;
                    }
                    // Nastavi na prazno
                    serijskaStevilka = '';
                }
            } catch (error) {
                console.error('Napaka pri pridobivanju podatkov o parfumu:', error);
            }
            
            const data = {
                parfum_id: selectedPerfumeId,
                rok_uporabe: document.getElementById('serija-rok').value,
                serijska_stevilka: serijskaStevilka,
                datum_odprtja: document.getElementById('serija-datum-odprtja').value || null,
                je_tester: document.getElementById('serija-je-tester').checked
            };
            
            console.log('Form submission data:', data);
            console.log('FLORGARDEN serial number being sent:', serijskaStevilka);

            const url = serijaId ? `/api/serije/${serijaId}` : '/api/serije';
            const method = serijaId ? 'PUT' : 'POST';

            setButtonLoading(button, true, 'Shranjujem...');
            try {
                // Pridobi podatke o uporabniku iz localStorage
                const currentUser = JSON.parse(localStorage.getItem('currentUser') || '{}');
                const headers = { 'Content-Type': 'application/json' };
                
                // Dodaj podatke o uporabniku v header (base64, da se izognemo ne-ISO znakom)
                if (currentUser && Object.keys(currentUser).length > 0) {
                    try {
                        const json = JSON.stringify(currentUser);
                        const b64 = btoa(unescape(encodeURIComponent(json)));
                        headers['X-User-Info'] = `b64:${b64}`;
                    } catch (_) {
                        // fallback: ne dodaj headerja
                    }
                }
                
                const response = await fetch(url, {
                    method: method,
                    headers: headers,
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                if (!response.ok) {
                    if (response.status === 403) {
                        showToast(`Nimate dovoljenj za urejanje te serije: ${result.error}`, 'danger');
                    } else if (response.status === 400 && result.error && result.error.includes('MISTRAL')) {
                        showToast(`Napaka: ${result.error}`, 'danger');
                    } else {
                        throw new Error(result.error);
                    }
                    return;
                }
                showToast(result.message);
                loadSerijeForPerfume(data.parfum_id);
            } catch (error) {
                showToast(`Napaka: ${error.message}`, 'danger');
            } finally {
                setButtonLoading(button, false);
            }
        });
    }

    if (serijeTableBody) {
        serijeTableBody.addEventListener('click', async function(e) {
            const button = e.target.closest('button');
            if (!button) return;
            
            const perfumeId = document.getElementById('serija-parfum-id').value;

            if (button.classList.contains('delete-serija-btn')) {
                const serijaId = button.dataset.id;
                if (!confirm('Ste prepričani, da želite izbrisati to serijo?')) return;
                
                try {
                    const response = await fetch(`/api/serije/${serijaId}`, { method: 'DELETE' });
                    const result = await response.json();
                    if (!response.ok) {
                        if (response.status === 403) {
                            showToast(`Nimate dovoljenj za brisanje te serije: ${result.error}`, 'danger');
                        } else {
                            throw new Error(result.error);
                        }
                        return;
                    }
                    showToast(result.message);
                    loadSerijeForPerfume(perfumeId);
                } catch (error) {
                    showToast(`Napaka: ${error.message}`, 'danger');
                }
            } else if (button.classList.contains('edit-serija-btn')) {
                const serijaData = JSON.parse(button.dataset.serija);
                fillSerijaForm(serijaData);
            }
        });
    }

    // --- Logika za ROČNI VNOS in TISKANJE ---
    let manualPerfumeSelect, printPerfumeSelect;
    let manualProizvajalecSelect, printProizvajalecSelect;
    let manualTabInitialized = false;

    function initializeManualAndPrintTab() {
        console.log('initializeManualAndPrintTab called');
        if (manualTabInitialized) {
            console.log('Manual tab already initialized, returning');
            return;
        }

        // Naloži proizvajalce
        loadProizvajalciForManualAndPrint();

        // Konfiguracija za TomSelect parfumov
        const perfumeConfig = {
            valueField: 'id',
            labelField: 'name',
            searchField: 'name',
            plugins: ['remove_button'],
            maxItems: null,
            maxOptions: 50,
            closeAfterSelect: true,
            dropdownParent: 'body',
            sortField: [
                { field: 'product_no_num', direction: 'asc' },
                { field: 'name', direction: 'asc' }
            ],
            score: function(search) {
                const q = (search || '').toLowerCase();
                const qNum = parseInt(q, 10);
                const hasNum = !isNaN(qNum);
                return function(item) {
                    const name = (item.name || '').toLowerCase();
                    // product_no may be embedded in name like "... (123)"
                    const match = name.match(/\((\d+)\)$/);
                    const pnStr = match ? match[1] : '';
                    const pnNum = parseInt(pnStr, 10) || item.product_no_num || 0;
                    let s = 0;
                    if (pnStr === q) s = 10000;
                    else if (pnStr && pnStr.startsWith(q)) s = 9000;
                    else if (hasNum && pnNum) s = 8000 - Math.abs(pnNum - qNum);
                    if (name.startsWith(q)) s = Math.max(s, 500);
                    if (name.includes(q)) s = Math.max(s, 100);
                    return s;
                };
            },
            onDropdownOpen: function(dropdown) {
                console.log('Manual/Print dropdown opened, window width:', window.innerWidth);
                if (window.innerWidth <= 768) {
                    dropdown.classList.add('mobile-optimized-dropdown');
                    document.body.classList.add('prevent-scroll');
                    console.log('Added mobile-optimized-dropdown class to manual/print dropdown');
                    console.log('Added prevent-scroll class to body');
                    console.log('Dropdown classes:', dropdown.className);
                } else {
                    // Desktop - odstrani mobile klase če obstajajo
                    dropdown.classList.remove('mobile-optimized-dropdown');
                    document.body.classList.remove('prevent-scroll');
                    console.log('Desktop mode - removed mobile classes');
                }
            },
            onDropdownClose: function() {
                document.body.classList.remove('prevent-scroll');
                console.log('Removed mobile class from body (manual/print)');
            },
            onChange: function(value) {
                // Počisti polje za iskanje po izboru
                this.setTextboxValue('');
            },
            render: {
                option: function(data, escape) {
                    const stockIndicator = data.na_zalogi ? '🟢' : '🔴';
                    return `<div class="py-2 px-3 hover:bg-gray-100 cursor-pointer">${stockIndicator} ${escape(data.name)}</div>`;
                },
                item: function(data, escape) {
                    const stockIndicator = data.na_zalogi ? '🟢' : '🔴';
                    return `<div class="py-1">${stockIndicator} ${escape(data.name)}</div>`;
                }
            },
            load: function(query, callback) {
                // Ta funkcija se bo spremenila, ko bo izbran proizvajalec
                callback();
            }
        };
        
        if (!manualPerfumeSelect) {
            console.log('Creating manual perfume TomSelect');
            manualPerfumeSelect = new TomSelect('#manual-perfume-select', perfumeConfig);
            console.log('Manual perfume TomSelect created:', manualPerfumeSelect);
        } else {
            console.log('Manual perfume TomSelect already exists:', manualPerfumeSelect);
        }
        if (!printPerfumeSelect) {
            console.log('Creating print perfume TomSelect');
            printPerfumeSelect = new TomSelect('#print-perfume-select', perfumeConfig);
            console.log('Print perfume TomSelect created:', printPerfumeSelect);
        } else {
            console.log('Print perfume TomSelect already exists:', printPerfumeSelect);
        }

        const manualSendForm = document.getElementById('manual-send-form');
        if (manualSendForm) {
            manualSendForm.addEventListener('submit', handleManualSend);
        }

        const printForm = document.getElementById('print-form');
        if (printForm) {
            printForm.addEventListener('click', handlePrintAction);
        }
        
        manualTabInitialized = true;
    }

    async function loadProizvajalciForManualAndPrint() {
        try {
            const response = await fetch('/api/proizvajalci');
            const proizvajalci = await response.json();
            
            const optionsHtml = '<option value="">Izberi proizvajalca</option>' + 
                proizvajalci.map(p => `<option value="${p.id}">${p.ime}</option>`).join('');
            
            // Nastavi proizvajalce za ročno pošiljanje
            const manualProizvajalecSelect = document.getElementById('manual-proizvajalec-select');
            if (manualProizvajalecSelect) {
                console.log('Setting up manual proizvajalec select');
                manualProizvajalecSelect.innerHTML = optionsHtml;
                manualProizvajalecSelect.addEventListener('change', function() {
                    console.log('=== MANUAL PROIZVAJALEC CHANGED ===');
                    console.log('Selected value:', this.value);
                    console.log('Selected text:', this.options[this.selectedIndex]?.text);
                    loadParfumiForManualAndPrint(this.value, 'manual');
                });
            } else {
                console.error('Manual proizvajalec select not found');
            }
            
            // Nastavi proizvajalce za tiskanje
            const printProizvajalecSelect = document.getElementById('print-proizvajalec-select');
            if (printProizvajalecSelect) {
                console.log('Setting up print proizvajalec select');
                printProizvajalecSelect.innerHTML = optionsHtml;
                printProizvajalecSelect.addEventListener('change', function() {
                    console.log('=== PRINT PROIZVAJALEC CHANGED ===');
                    console.log('Selected value:', this.value);
                    console.log('Selected text:', this.options[this.selectedIndex]?.text);
                    loadParfumiForManualAndPrint(this.value, 'print');
                });
            } else {
                console.error('Print proizvajalec select not found');
            }
            
            // Nastavi gumbe za počistitev
            const manualClearBtn = document.getElementById('manual-clear-perfumes');
            const printClearBtn = document.getElementById('print-clear-perfumes');
            
            if (manualClearBtn) {
                manualClearBtn.addEventListener('click', function() {
                    if (manualPerfumeSelect) {
                        manualPerfumeSelect.clear();
                        manualPerfumeSelect.clearOptions();
                        manualPerfumeSelect.disable();
                        this.style.display = 'none';
                    }
                });
            }
            
            if (printClearBtn) {
                printClearBtn.addEventListener('click', function() {
                    if (printPerfumeSelect) {
                        printPerfumeSelect.clear();
                        printPerfumeSelect.clearOptions();
                        printPerfumeSelect.disable();
                        this.style.display = 'none';
                    }
                });
            }
        } catch (error) {
            console.error('Napaka pri nalaganju proizvajalcev:', error);
        }
    }
    async function loadParfumiForManualAndPrint(proizvajalecId, type) {
        console.log(`loadParfumiForManualAndPrint called: proizvajalecId=${proizvajalecId}, type=${type}`);
        
        if (!proizvajalecId) {
            console.log('No proizvajalecId provided, clearing selects');
            // Počisti parfume, če ni izbran proizvajalec
            if (type === 'manual' && manualPerfumeSelect) {
                manualPerfumeSelect.clear();
                manualPerfumeSelect.clearOptions();
                manualPerfumeSelect.disable();
            }
            if (type === 'print' && printPerfumeSelect) {
                printPerfumeSelect.clear();
                printPerfumeSelect.clearOptions();
                printPerfumeSelect.disable();
            }
            return;
        }

        try {
            console.log(`=== FETCHING PARFUMI FOR PROIZVAJALEC ===`);
            console.log(`Proizvajalec ID: ${proizvajalecId}`);
            console.log(`Type: ${type}`);
            console.log(`API URL: /api/parfumi_by_proizvajalec/${proizvajalecId}`);
            
            const response = await fetch(`/api/parfumi_by_proizvajalec/${proizvajalecId}`);
            console.log(`Response status: ${response.status}`);
            console.log(`Response ok: ${response.ok}`);
            
            const parfumi = await response.json();
            console.log(`Received ${parfumi.length} parfumi:`, parfumi);
            
            const options = parfumi.map(p => ({
                id: p.id,
                name: `${p.ime_parfuma} (${p.product_no})`,
                na_zalogi: p.na_zalogi,
                product_no_num: parseInt(p.product_no, 10) || 0
            })).sort((a,b)=> (a.product_no_num - b.product_no_num) || (a.name||'').localeCompare(b.name||''));
            console.log('Mapped options:', options);
            
            if (type === 'manual' && manualPerfumeSelect) {
                console.log('=== UPDATING MANUAL PERFUME SELECT ===');
                console.log('Current options count before adding:', manualPerfumeSelect.options.length);
                
                // Shrani trenutno izbrane vrednosti
                const currentValues = manualPerfumeSelect.getValue();
                console.log('Current selected values:', currentValues);
                console.log('Current selected values type:', typeof currentValues);
                console.log('Current selected values length:', currentValues ? currentValues.length : 'null/undefined');
                
                // Počisti obstoječe opcije in dodaj samo nove (za trenutnega proizvajalca)
                manualPerfumeSelect.clearOptions();
                manualPerfumeSelect.addOptions(options);
                console.log(`Cleared and added ${options.length} new options for current manufacturer`);
                
                // Preveri, ali so vrednosti med novimi opcijami
                if (currentValues && currentValues.length > 0) {
                    console.log('About to restore values:', currentValues);
                    
                    // Preveri, ali so vse vrednosti med opcijami
                    const availableOptions = manualPerfumeSelect.options;
                    console.log('Available options count:', availableOptions ? Object.keys(availableOptions).length : 'undefined');
                    
                    const validValues = currentValues.filter(value => {
                        const exists = availableOptions && availableOptions[value];
                        console.log(`Checking if value '${value}' exists in options:`, exists);
                        return exists;
                    });
                    
                    console.log('Valid values to restore:', validValues);
                    
                    if (validValues.length > 0) {
                        manualPerfumeSelect.setValue(validValues);
                        console.log('Restored valid selected values:', validValues);
                    } else {
                        console.log('No valid values to restore - all values were not found in options');
                    }
                    
                    // Preveri, ali so vrednosti res nastavljene
                    const afterSetValue = manualPerfumeSelect.getValue();
                    console.log('Values after setValue:', afterSetValue);
                } else {
                    console.log('No values to restore (currentValues is empty or null)');
                }
                
                manualPerfumeSelect.enable();
                console.log('Enabled select');
                
                // Prikaži gumb za počistitev
                const clearBtn = document.getElementById('manual-clear-perfumes');
                if (clearBtn) clearBtn.style.display = 'block';
                console.log('Manual perfume select updated successfully');
                console.log('Final options count:', manualPerfumeSelect.options.length);
            }
            if (type === 'print' && printPerfumeSelect) {
                console.log('=== UPDATING PRINT PERFUME SELECT ===');
                console.log('Current options count before adding:', printPerfumeSelect.options.length);
                
                // Shrani trenutno izbrane vrednosti
                const currentValues = printPerfumeSelect.getValue();
                console.log('Current selected values:', currentValues);
                console.log('Current selected values type:', typeof currentValues);
                console.log('Current selected values length:', currentValues ? currentValues.length : 'null/undefined');
                
                // Počisti obstoječe opcije in dodaj samo nove (za trenutnega proizvajalca)
                printPerfumeSelect.clearOptions();
                printPerfumeSelect.addOptions(options);
                console.log(`Cleared and added ${options.length} new options for current manufacturer`);
                
                // Preveri, ali so vrednosti med novimi opcijami
                if (currentValues && currentValues.length > 0) {
                    console.log('About to restore values:', currentValues);
                    
                    // Preveri, ali so vse vrednosti med opcijami
                    const availableOptions = printPerfumeSelect.options;
                    console.log('Available options count:', availableOptions ? Object.keys(availableOptions).length : 'undefined');
                    
                    const validValues = currentValues.filter(value => {
                        const exists = availableOptions && availableOptions[value];
                        console.log(`Checking if value '${value}' exists in options:`, exists);
                        return exists;
                    });
                    
                    console.log('Valid values to restore:', validValues);
                    
                    if (validValues.length > 0) {
                        printPerfumeSelect.setValue(validValues);
                        console.log('Restored valid selected values:', validValues);
                    } else {
                        console.log('No valid values to restore - all values were not found in options');
                    }
                    
                    // Preveri, ali so vrednosti res nastavljene
                    const afterSetValue = printPerfumeSelect.getValue();
                    console.log('Values after setValue:', afterSetValue);
                } else {
                    console.log('No values to restore (currentValues is empty or null)');
                }
                
                printPerfumeSelect.enable();
                console.log('Enabled select');
                
                // Prikaži gumb za počistitev
                const clearBtn = document.getElementById('print-clear-perfumes');
                if (clearBtn) clearBtn.style.display = 'block';
                console.log('Print perfume select updated successfully');
                console.log('Final options count:', printPerfumeSelect.options.length);
            }
        } catch (error) {
            console.error('Napaka pri nalaganju parfumov:', error);
        }
    }

    async function handleManualSend(e) {
        e.preventDefault();
        const button = this.querySelector('button[type="submit"]');
        const email = document.getElementById('manual-email').value;
        const perfumes = manualPerfumeSelect.getValue();
        if (!perfumes.length) {
            showToast('Izberite vsaj en parfum.', 'danger');
            return;
        }
        
        setButtonLoading(button, true);
        try {
            console.log('Pošiljam ročno deklaracijo za:', { email, perfumes });
            const response = await fetch('/api/poslji-rocno', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, perfumes })
            });
            const result = await response.json();
            console.log('Odgovor od strežnika:', { status: response.status, result });
            
            if (!response.ok) {
                console.log('Strežnik je vrnil napako:', result.sporocilo);
                throw new Error(result.sporocilo);
            }
            
            console.log('Uspešno poslano:', result.sporocilo);
            showToast(result.sporocilo);
            this.reset();
            manualPerfumeSelect.clear();
        } catch (error) {
            console.log('Napaka pri pošiljanju ročne deklaracije:', error.message);
            showToast(`Napaka: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    async function handlePrintAction(e) {
        const target = e.target.closest('button');
        if (!target) return;
        e.preventDefault();

        const perfumes = printPerfumeSelect.getValue();
        if (!perfumes.length) {
            showToast('Izberite vsaj en parfum za tiskanje.', 'danger');
            return;
        }

        let url, button;
        if (target.id === 'print-pos-button') {
            url = '/api/generiraj-deklaracijo-za-tisk';
            button = target;
        } else if (target.id === 'print-pdf-button') {
            url = '/api/generiraj-pdf-rocno';
            button = target;
        } else {
            return;
        }

        setButtonLoading(button, true);
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ perfumes })
            });

            if (url.includes('tisk')) {
                if (!response.ok) {
                    const result = await response.json();
                    throw new Error(result.sporocilo);
                }
                const html = await response.text();
                const printWindow = window.open('', '_blank');
                printWindow.document.write(html);
                printWindow.document.close();
                printWindow.focus();
                setTimeout(() => { printWindow.print(); printWindow.close(); }, 250);
                showToast('Deklaracija uspešno natisnjena!');
                printPerfumeSelect.clear();
            } else {
                if (!response.ok) {
                    const result = await response.json();
                    throw new Error(result.sporocilo);
                }
                const blob = await response.blob();
                const pdfUrl = URL.createObjectURL(blob);
                window.open(pdfUrl, '_blank');
                showToast('PDF uspešno generiran!');
                printPerfumeSelect.clear();
            }
        } catch (error) {
            showToast(`Napaka: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    // --- Logika za OPOZORILA ---
    const expiringList = document.getElementById('expiring-list');
    const expiringSpinner = document.getElementById('expiring-spinner');
    const expiringBadge = document.getElementById('expiring-badge');
    const refreshExpiringButton = document.getElementById('refresh-expiring-button');

    async function fetchExpiringPerfumes() {
        console.log('fetchExpiringPerfumes() klicana, isOnline:', isOnline);
        if (!expiringSpinner) return;
        expiringSpinner.style.display = 'block';
        if (expiringList) expiringList.innerHTML = '';
        if (expiringBadge) expiringBadge.style.display = 'none';
        
        try {
            // 1. Najprej poskusi naložiti iz lokalne baze
            let localExpiringPerfumes = [];
            if (window.localDB && !isOnline) {
                try {
                    const allPerfumes = await localDB.getPerfumes();
                    // Filtriranje parfumov z bližajočim se rokom uporabe (30 dni)
                    const thirtyDaysFromNow = new Date();
                    thirtyDaysFromNow.setDate(thirtyDaysFromNow.getDate() + 30);
                    
                    localExpiringPerfumes = allPerfumes.filter(p => {
                        if (p.rok_uporabe) {
                            const expiryDate = new Date(p.rok_uporabe);
                            return expiryDate <= thirtyDaysFromNow;
                        }
                        return false;
                    });
                    console.log(`Naloženih ${localExpiringPerfumes.length} parfumov z bližajočim se rokom iz lokalne baze`);
                } catch (error) {
                    console.warn('Napaka pri nalaganju parfumov z bližajočim se rokom iz lokalne baze:', error);
                }
            }
            
            // 2. Če je online, sinhroniziraj z API
            let apiPerfumes = null;
            if (isOnline) {
                console.log('fetchExpiringPerfumes: Pošiljam API klic (online)');
        try {
            const response = await fetch('/api/expiring-perfumes');
            if (response.ok) {
                apiPerfumes = await response.json();
                console.log('Parfumi z bližajočim se rokom naloženi iz API:', apiPerfumes.length);
            } else if (response.status === 403) {
                console.warn('Ni dovoljenja za /api/expiring-perfumes, preskakujem prikaz opozoril.');
                apiPerfumes = [];
            } else {
                console.warn(`API napaka pri nalaganju parfumov z bližajočim se rokom: ${response.status}`);
            }
                } catch (error) {
                    console.warn('Napaka pri API klicu za parfume z bližajočim se rokom:', error);
                }
            }
            
            // 3. Določi, katere podatke uporabiti
            let perfumes = [];
            if (apiPerfumes && apiPerfumes.length >= 0) {
                perfumes = apiPerfumes;
                console.log('Uporabljam parfume z bližajočim se rokom iz API');
            } else if (localExpiringPerfumes.length > 0) {
                perfumes = localExpiringPerfumes;
                console.log('Uporabljam parfume z bližajočim se rokom iz lokalne baze (offline mode)');
                
                // Prikaži offline indikator
                if (window.showToast) {
                    window.showToast('Prikazujem opozorila iz lokalne baze (offline)', 'warning');
                }
            } else {
                console.log('Ni parfumov z bližajočim se rokom za prikaz');
            }

            console.log('Received expiring perfumes data:', perfumes);

            if (perfumes.length > 0) {
                expiringBadge.textContent = perfumes.length;
                expiringBadge.style.display = 'inline-block';
                // POPRAVEK: Izpis sedaj vključuje proizvajalca in ID parfuma za boljšo preglednost.
                expiringList.innerHTML = perfumes.map(p => {
                    console.log('Processing perfume:', p);
                    const canEdit = hasUserPermission('edit_perfumes') || hasUserPermission('edit_serije');
                    const clickHandler = canEdit ? `onclick="loadPerfumeForEditing(${p.id || p.parfum_id}); switchToKatalogTab();"` : '';
                    const cursorClass = canEdit ? 'cursor-pointer hover:bg-red-100' : 'cursor-not-allowed opacity-75';
                    const editText = canEdit ? 'Kliknite za urejanje serij' : 'Nimate dovoljenja za urejanje';
                    
                    return `
                    <li class="bg-red-50 border-l-4 border-red-400 p-4 rounded-lg ${cursorClass} transition-colors duration-200" ${clickHandler}>
                        <div class="flex items-start">
                            <div class="flex-shrink-0">
                                <i class="bi bi-exclamation-triangle text-red-400 text-xl"></i>
                            </div>
                            <div class="ml-3 flex-1">
                                <h4 class="text-sm font-medium text-red-800">
                                    <strong>(Šifra: ${p.product_no}) ${p.proizvajalec || 'N/A'} - ${p.ime_parfuma || p.ime}</strong>
                                </h4>
                                <div class="mt-2 text-sm text-red-700">
                                    <p><strong>Rok uporabe:</strong> ${p.rok_uporabe}</p>
                                    <p class="mt-1 font-semibold">${p.opozorilo || 'Rok uporabe se bliža'}</p>
                                </div>
                                <div class="mt-2 text-xs text-red-600">
                                    <i class="bi bi-cursor-pointer mr-1"></i> ${editText}
                                </div>
                            </div>
                        </div>
                    </li>
                `;
                }).join('');
            } else {
                expiringList.innerHTML = '<li class="list-group-item">Ni parfumov z bližajočim se rokom uporabe.</li>';
            }
        } catch (error) {
            console.log('Napaka pri nalaganju opozoril (verjetno offline):', error.message);
            // Ne prikazuj napake uporabniku, če je offline
            if (isOnline) {
            showToast(`Napaka pri nalaganju opozoril: ${error.message}`, 'danger');
            }
        } finally {
            expiringSpinner.style.display = 'none';
        }
    }
    
    if (refreshExpiringButton) {
        refreshExpiringButton.addEventListener('click', fetchExpiringPerfumes);
    }

    // Prikaži trenutnega uporabnika
    function displayCurrentUser() {
        console.log('=== DISPLAYING CURRENT USER ===');
        const currentUser = localStorage.getItem('currentUser');
        console.log('currentUser from localStorage:', currentUser);
        
        if (currentUser) {
            try {
                const user = JSON.parse(currentUser);
                console.log('Parsed user:', user);
                const isAdmin = user.username === 'admin';
                const adminBadge = isAdmin ? ' <span class="bg-red-100 text-red-800 text-xs font-medium px-2 py-1 rounded-full">ADMIN</span>' : '';
                document.getElementById('current-user-display').innerHTML = `${user.first_name} ${user.last_name}${adminBadge}`;
                console.log('User display successful');
            } catch (e) {
                console.error('Napaka pri branju podatkov o uporabniku:', e);
                localStorage.removeItem('currentUser');
            }
        } else {
            console.log('Ni uporabnika v localStorage');
        }
    }

    // Osveži podatke o trenutnem uporabniku
    async function refreshCurrentUser() {
        try {
            const response = await fetch('/api/current-user', {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    localStorage.setItem('currentUser', JSON.stringify(result.user));
                    currentUser = result.user;
                    console.log('Uporabniški podatki osveženi:', result.user);
                    return true;
                }
            }
        } catch (error) {
            console.error('Napaka pri osveževanju podatkov o uporabniku:', error);
        }
        return false;
    }

    async function hardRefreshApp() {
        try {
            try {
                localStorage.removeItem('user');
                localStorage.removeItem('auth_token');
                localStorage.removeItem('isAuthenticated');
                localStorage.removeItem('currentUser');
            } catch (_) {}
            if ('serviceWorker' in navigator) {
                const regs = await navigator.serviceWorker.getRegistrations();
                await Promise.all(regs.map(reg => reg.unregister()));
            }
            if ('caches' in window) {
                const keys = await caches.keys();
                await Promise.all(keys.map(key => caches.delete(key)));
            }
        } catch (e) {
            console.warn('Hard refresh cleanup failed:', e);
        } finally {
            const url = new URL('/login', window.location.origin);
            url.searchParams.set('hard', Date.now().toString());
            window.location.replace(url.toString());
        }
    }

    // --- Odjava ---
    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            if (confirm('Ali se res želite odjaviti?')) {
                localStorage.removeItem('currentUser');
                
                // Debug: Prikaži trenutno stanje
                console.log('Logout klik - isOnline:', isOnline, 'navigator.onLine:', navigator.onLine);
                
                // Dodatno preverjanje - če je navigator.onLine false, je offline
                const isActuallyOffline = !isOnline || !navigator.onLine;
                console.log('Dodatno preverjanje - isActuallyOffline:', isActuallyOffline);
                
                // Če je offline, preusmeri na login stran
                if (isActuallyOffline) {
                    console.log('Offline odjava - preusmerjam na login stran');
                    showToast('Odjavljeni ste (offline)', 'success');
                    setTimeout(() => {
                        window.location.href = '/login';
                    }, 1000);
                } else {
                    // Če je online, pošlji POST zahtevek za logout
                    console.log('Online odjava - pošiljam POST zahtevek na /logout');
                    fetch('/logout', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        }
                    })
                    .then(response => {
                        if (response.ok) {
                            console.log('Logout uspešen');
                            window.location.href = '/login';
                        } else {
                            console.error('Logout neuspešen:', response.status);
                            // Če POST ne deluje, preusmeri na login stran
                            window.location.href = '/login';
                        }
                    })
                    .catch(error => {
                        console.error('Napaka pri logout:', error);
                        // Če je napaka, preusmeri na login stran
                        window.location.href = '/login';
                    });
                }
            }
        });
    }

    const hardRefreshBtn = document.getElementById('hard-refresh-btn');
    if (hardRefreshBtn) {
        hardRefreshBtn.addEventListener('click', hardRefreshApp);
    }
    
    // Avtentikacija se preveri na serverju, JavaScript samo prikaže uporabnika
    displayCurrentUser();
    
    // Preveri, ali je uporabnik prijavljen iz localStorage
    const storedUser = localStorage.getItem('currentUser');
    if (storedUser) {
        try {
            const user = JSON.parse(storedUser);
            if (user.id && user.username) {
                console.log('Uporabnik je prijavljen iz localStorage:', user.username);
                // Nastavi globalno currentUser spremenljivko
                currentUser = user;
                
                // Posodobi UI, da prikaže, da je uporabnik prijavljen
                const userDisplay = document.getElementById('current-user-display');
                if (userDisplay) {
                    userDisplay.style.display = 'block';
                }
                
                // Skrij "Neprijavljen" tekst
                const notLoggedInText = document.querySelector('.text-red-600');
                if (notLoggedInText) {
                    notLoggedInText.style.display = 'none';
                }
                
                // Posodobi vidljivost zavihkov glede na dovoljenja
                updateTabVisibility().then(() => {
                    console.log('Tab visibility updated after user login');
                }).catch(error => {
                    console.error('Error updating tab visibility:', error);
                });
            }
        } catch (error) {
            console.error('Napaka pri branju podatkov o uporabniku:', error);
            localStorage.removeItem('currentUser');
        }
    }
    
    // Posodobi vidljivost zavihkov glede na dovoljenja (za primer, ko ni prijavljenega uporabnika)
    updateTabVisibility().then(() => {
        console.log('Tab visibility updated (no user)');
    }).catch(error => {
        console.error('Error updating tab visibility:', error);
    });

    // Inicializiraj zavihke
    initializeTabs();

    // Odstranjeno: overflow "Več" meni – vrnitev na prejšnje stanje

    // Začetno nalaganje za prvi zavihek (Naročila)
    if (document.getElementById('narocila-tab')?.classList.contains('active')) {
        if (!initialNarocilaRequested) {
            initialNarocilaRequested = true;
            fetchNarocila(1, null, 'init');
        }
    }
    fetchExpiringPerfumes();
    clearKatalogForm();

    // Service Worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => {
                console.log('Service Worker registriran.', reg);
                
                // Preveri, ali je nova verzija na voljo
                reg.addEventListener('updatefound', () => {
                    console.log('Nova verzija Service Worker-ja na voljo!');
                    const newWorker = reg.installing;
                    
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            console.log('Nova verzija Service Worker-ja nameščena. Posodabljam...');
                            // Prisilno posodobi Service Worker
                            newWorker.postMessage({ type: 'SKIP_WAITING' });
                            window.location.reload();
                        }
                    });
                });
                
                // Poslušaj sporočila od Service Worker-ja
                navigator.serviceWorker.addEventListener('message', event => {
                    if (event.data && event.data.type === 'RELOAD_PAGE') {
                        console.log('Service Worker zahteva osvežitev strani');
                        window.location.reload();
                    }
                });
            })
            .catch(err => console.log('Napaka pri registraciji Service Workerja.', err));
    }
    

    
    // Funkcija za posodobitev vizualnega stanja filter gumbov
    function updateFilterButtons(selectedValue) {
        document.querySelectorAll('input[name="order-filter"]').forEach(radio => {
            const label = document.querySelector(`label[for="${radio.id}"]`);
            if (radio.value === selectedValue) {
                // Aktivno stanje
                label.classList.remove('bg-gray-100', 'text-gray-700', 'border-gray-200', 'hover:bg-gray-200');
                label.classList.add('bg-primary-100', 'text-primary-700', 'border-primary-200', 'hover:bg-primary-200');
            } else {
                // Neaktivno stanje
                label.classList.remove('bg-primary-100', 'text-primary-700', 'border-primary-200', 'hover:bg-primary-200');
                label.classList.add('bg-gray-100', 'text-gray-700', 'border-gray-200', 'hover:bg-gray-200');
            }
        });
    }

    // Event listenerji za filter gumbe
    document.querySelectorAll('input[name="order-filter"]').forEach(radio => {
        radio.addEventListener('change', function() {
            if (this.checked) {
                currentFilter = this.value;
                lastOrdersUserChangeAt = Date.now();
                console.log('Filter spremenjen na:', currentFilter);
                // Posodobi vizualno stanje gumbov
                updateFilterButtons(currentFilter);
                const ddl = document.getElementById('order-filter-select');
                if (ddl) ddl.value = currentFilter;
                // Osveži naročila s prvim filterom
                fetchNarocila(1, null, 'filter');
            }
        });
    });

    // Mobile dropdown listener
    const orderFilterSelect = document.getElementById('order-filter-select');
    if (orderFilterSelect){
        orderFilterSelect.addEventListener('change', function(){
            currentFilter = this.value;
            lastOrdersUserChangeAt = Date.now();
            updateFilterButtons(currentFilter);
            // Sync radio buttons
            const radio = document.querySelector(`input[name=\"order-filter\"][value=\"${currentFilter}\"]`);
            if (radio){ radio.checked = true; }
            fetchNarocila(1, null, 'filter');
        });
    }

    // Inicializiraj filter gumbe glede na dejanski izbor v UI
    const initialFilterValue =
        document.querySelector('input[name="order-filter"]:checked')?.value ||
        document.getElementById('order-filter-select')?.value ||
        'all';
    currentFilter = initialFilterValue;
    updateFilterButtons(initialFilterValue);
    if (orderFilterSelect) {
        orderFilterSelect.value = initialFilterValue;
    }

    // Inicializiraj iskanje po številki naročila
    const orderSearchInput = document.getElementById('order-search');
    const clearSearchBtn = document.getElementById('clear-search');
    let searchTimeout = null;


    if (orderSearchInput) {
        orderSearchInput.addEventListener('input', function() {
            const searchTerm = this.value.trim();
            currentSearchTerm = searchTerm;
            lastOrdersUserChangeAt = Date.now();
            
            // Počisti prejšnji timeout
            if (searchTimeout) {
                clearTimeout(searchTimeout);
            }
            
            // Nastavi nov timeout za iskanje (300ms delay)
            searchTimeout = setTimeout(() => {
                console.log('Iskanje po številki naročila:', searchTerm);
                fetchNarocila(1, null, 'search');
            }, 300);
        });

        // Event listener za Enter tipko
        orderSearchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                lastOrdersUserChangeAt = Date.now();
                if (searchTimeout) {
                    clearTimeout(searchTimeout);
                }
                fetchNarocila(1, null, 'search');
            }
        });
    }

    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('click', function() {
            if (orderSearchInput) {
                orderSearchInput.value = '';
                currentSearchTerm = '';
                fetchNarocila(1);
            }
        });
    }
    // Event listener za dodajanje uporabnika
            const confirmAddUserBtn = document.getElementById('confirmAddUserBtn');
        if (confirmAddUserBtn) {
            confirmAddUserBtn.addEventListener('click', addUser);
        }

        // Event listener za modal dovoljenj
        const submitEditPermissionsBtn = document.getElementById('submit-edit-permissions-btn');
        if (submitEditPermissionsBtn) {
            submitEditPermissionsBtn.addEventListener('click', window.submitEditPermissions);
        }

    // Event listener za procesiranje fulfilled naročil
    const processFulfilledOrdersBtn = document.getElementById('process-fulfilled-orders-btn');
    if (processFulfilledOrdersBtn) {
        processFulfilledOrdersBtn.addEventListener('click', async function() {
            try {
                setButtonLoading(processFulfilledOrdersBtn, true, 'Procesiram...');
                
                const response = await fetch('/api/process-unprocessed-fulfilled-orders', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showToast(data.message, 'success');
                    // Osveži seznam naročil
                    fetchNarocila(1);
                } else {
                    showToast(data.error || 'Napaka pri procesiranju fulfilled naročil', 'error');
                }
            } catch (error) {
                console.error('Napaka pri procesiranju fulfilled naročil:', error);
                showToast('Napaka pri procesiranju fulfilled naročil', 'error');
            } finally {
                setButtonLoading(processFulfilledOrdersBtn, false);
            }
        });
    }

    // Event listener za sinhronizacijo fulfilled statusa
    const syncFulfilledStatusBtn = document.getElementById('sync-fulfilled-status-btn');
    if (syncFulfilledStatusBtn) {
        syncFulfilledStatusBtn.addEventListener('click', async function() {
            try {
                setButtonLoading(syncFulfilledStatusBtn, true, 'Sinhroniziram...');
                
                const response = await fetch('/api/sync-fulfilled-status', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    if (data.updated_count > 0) {
                        showToast(`Posodobljen fulfilled status za ${data.updated_count} naročil`, 'success');
                    } else {
                        showToast(data.message || 'Ni naročil za posodobitev fulfilled statusa', 'info');
                    }
                    // Osveži seznam naročil
                    fetchNarocila(1);
                } else {
                    showToast(data.error || 'Napaka pri sinhronizaciji fulfilled statusa', 'error');
                }
            } catch (error) {
                console.error('Napaka pri sinhronizaciji fulfilled statusa:', error);
                showToast('Napaka pri sinhronizaciji fulfilled statusa', 'error');
            } finally {
                setButtonLoading(syncFulfilledStatusBtn, false);
            }
        });
    }

    // Event listener za registracijo webhook-ov
    const registerWebhooksBtn = document.getElementById('register-webhooks-btn');
    if (registerWebhooksBtn) {
        registerWebhooksBtn.addEventListener('click', async function() {
            try {
                setButtonLoading(registerWebhooksBtn, true, 'Registriram...');
                
                const response = await fetch('/api/register-webhooks', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showToast(data.message, 'success');
                } else {
                    showToast(data.error || 'Napaka pri registraciji webhook-ov', 'error');
                }
            } catch (error) {
                console.error('Napaka pri registraciji webhook-ov:', error);
                showToast('Napaka pri registraciji webhook-ov', 'error');
            } finally {
                setButtonLoading(registerWebhooksBtn, false);
            }
        });
    }

    // Event listener za pregled webhook-ov
    const listWebhooksBtn = document.getElementById('list-webhooks-btn');
    if (listWebhooksBtn) {
        listWebhooksBtn.addEventListener('click', async function() {
            try {
                setButtonLoading(listWebhooksBtn, true, 'Nalagam...');
                
                const response = await fetch('/api/list-webhooks', {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    if (data.webhooks && data.webhooks.length > 0) {
                        let webhookList = 'Registrirani webhook-i:\n\n';
                        data.webhooks.forEach(webhook => {
                            webhookList += `• ${webhook.topic}: ${webhook.address}\n`;
                        });
                        alert(webhookList);
                    } else {
                        showToast('Ni registriranih webhook-ov', 'info');
                    }
                } else {
                    showToast(data.error || 'Napaka pri pridobivanju webhook-ov', 'error');
                }
            } catch (error) {
                console.error('Napaka pri pridobivanju webhook-ov:', error);
                showToast('Napaka pri pridobivanju webhook-ov', 'error');
            } finally {
                setButtonLoading(listWebhooksBtn, false);
            }
        });
    }
    
    // Spremenljivke za sledenje obvestilom
    let lastNotifiedOrder = null;
    let lastNotifiedFulfilledOrder = null;
    
    // Webhook preverjanje (brez timera)
    async function checkForNewOrders() {
        console.log('checkForNewOrders() klicana, isOnline:', isOnline);
        // Preveri, ali je aplikacija online
        if (!isOnline) {
            console.log('Offline mode - preskačem webhook preverjanje');
            return;
        }
        
        try {
            // Preveri webhook obvestila
            const webhookResponse = await fetch('/webhook/check-new-orders');
            const webhookData = await webhookResponse.json();
            
            if (webhookData.has_new_orders) {
                const orderNumber = webhookData.order_number;
                const timestamp = webhookData.timestamp;
                console.log(`Webhook obvestil o novem naročilu: ${orderNumber}`);
                
                // Preveri, ali smo že obvestili o tem naročilu (z upoštevanjem timestamp-a)
                const notificationKey = `notified_order_${orderNumber}_${timestamp}`;
                const alreadyNotified = localStorage.getItem(notificationKey);
                
                if (!alreadyNotified) {
                    showToast(`Novo naročilo ${orderNumber}! Osvežujem seznam...`, 'success');
                    fetchNarocila(1, null, 'webhook:new'); // Osveži prvo stran
                    localStorage.setItem(notificationKey, 'true');
                    console.log(`Obvestilo prikazano za naročilo: ${orderNumber}`);
                } else {
                    console.log(`Obvestilo za naročilo ${orderNumber} že prikazano, preskačem`);
                }
                return;
            }
            
            // Preveri tudi za fulfilled naročila
            if (webhookData.has_fulfilled_orders) {
                const orderNumber = webhookData.order_number;
                const timestamp = webhookData.timestamp;
                console.log(`Webhook obvestil o fulfilled naročilu: ${orderNumber}`);
                
                // Preveri, ali smo že obvestili o tem fulfilled naročilu (z upoštevanjem timestamp-a)
                const notificationKey = `notified_fulfilled_${orderNumber}_${timestamp}`;
                const alreadyNotified = localStorage.getItem(notificationKey);
                
                if (!alreadyNotified) {
                    showToast(`Naročilo ${orderNumber} je bilo izpolnjeno! Osvežujem seznam...`, 'success');
                    fetchNarocila(1, null, 'webhook:fulfilled'); // Osveži prvo stran
                    localStorage.setItem(notificationKey, 'true');
                    console.log(`Obvestilo prikazano za fulfilled naročilo: ${orderNumber}`);
                } else {
                    console.log(`Obvestilo za fulfilled naročilo ${orderNumber} že prikazano, preskačem`);
                }
                return;
            }
            
            console.log('Ni novih webhook obvestil');
        } catch (error) {
            // Samo logiraj napako, ne prikazuj uporabniku
            console.log('Webhook preverjanje ni uspelo (verjetno offline):', error.message);
        }
    }
    
    // Funkcija za čiščenje starih obvestil iz localStorage
    function cleanupOldNotifications() {
        const now = Date.now();
        const oneHourAgo = now - (60 * 60 * 1000); // 1 ura nazaj
        
        // Počisti stara obvestila
        for (let i = localStorage.length - 1; i >= 0; i--) {
            const key = localStorage.key(i);
            if (key && (key.startsWith('notified_order_') || key.startsWith('notified_fulfilled_'))) {
                try {
                    // Poskusi izvleči timestamp iz ključa
                    const parts = key.split('_');
                    const timestamp = parseInt(parts[parts.length - 1]);
                    if (timestamp && timestamp < oneHourAgo) {
                        localStorage.removeItem(key);
                        console.log(`Počistil staro obvestilo: ${key}`);
                    }
                } catch (e) {
                    // Če ne moremo razčleniti timestamp-a, odstrani ključ
                    localStorage.removeItem(key);
                }
            }
        }
    }

    // Počisti stara obvestila vsakih 10 minut
    setInterval(cleanupOldNotifications, 10 * 60 * 1000);
    
    // Počisti obvestila ob zagonu aplikacije
    cleanupOldNotifications();

    // Preveri za nova naročila vsakih 30 sekund (krajši interval za webhook)
    setInterval(checkForNewOrders, 30000);

    // --- Funkcije za slike naročil ---
    
    let currentOrderNumber = null;
    let orderImagesModal = null;
    
    // Inicializiraj modal - počakajmo, da se Bootstrap naloži
    function initializeModal() {
        console.log('=== INITIALIZING MODAL ===');
        
        // Preveri, ali je modal že inicializiran
        if (window.modalInitialized) {
            console.log('Modal already initialized, skipping...');
            return;
        }
        
        console.log('Document ready state:', document.readyState);
        console.log('Document body:', document.body ? 'exists' : 'null');
        console.log('Bootstrap available:', typeof bootstrap !== 'undefined');
        console.log('Bootstrap Modal available:', typeof bootstrap !== 'undefined' && typeof bootstrap.Modal !== 'undefined');
        console.log('Bootstrap object:', bootstrap);
        console.log('Bootstrap.Modal:', typeof bootstrap !== 'undefined' ? bootstrap.Modal : 'undefined');
        
        const modalElement = document.getElementById('orderImagesModal');
        console.log('Modal element found:', modalElement);
        console.log('Modal element HTML:', modalElement ? modalElement.outerHTML : 'null');
        
        // Modal je sedaj implementiran z lastno Tailwind CSS rešitvijo
        console.log('Modal initialization - using custom Tailwind implementation');
        orderImagesModal = modalElement; // Shranimo samo DOM element
        
        // Event listener za file input (desktop)
        const imageInput = document.getElementById('order-image-input');
        const uploadBtn = document.getElementById('upload-image-btn');
        
        console.log('Image upload elements found:', {
            imageInput: !!imageInput,
            uploadBtn: !!uploadBtn
        });
        
        // Mobilni event listenerji
        const cameraBtn = document.getElementById('camera-btn');
        const galleryBtn = document.getElementById('gallery-btn');
        const cameraInput = document.getElementById('camera-input');
        const mobileImageInput = document.getElementById('mobile-image-input');
        
        console.log('Mobile upload elements found:', {
            cameraBtn: !!cameraBtn,
            galleryBtn: !!galleryBtn,
            cameraInput: !!cameraInput,
            mobileImageInput: !!mobileImageInput
        });
        
        if (imageInput && uploadBtn) {
            console.log('Setting up desktop image input event listener');
            imageInput.addEventListener('change', function() {
                console.log('Desktop image input change event triggered');
                console.log('Files selected:', this.files.length);
                if (this.files.length > 0) {
                    const file = this.files[0];
                    console.log('File selected:', file.name, file.type, file.size);
                    // Client-side validation: type and size (match backend)
                    const allowed = ['image/jpeg','image/jpg','image/png','image/webp'];
                    const maxBytes = 10 * 1024 * 1024; // 10 MB
                    if (!allowed.includes((file.type || '').toLowerCase())) {
                        showToast('Napačen tip datoteke. Dovoljeni: JPG, PNG, WEBP', 'warning');
                        this.value = '';
                        uploadBtn.disabled = true;
                        hideSelectedImages();
                        return;
                    }
                    if (file.size > maxBytes) {
                        showToast('Datoteka je prevelika (max 10 MB)', 'warning');
                        this.value = '';
                        uploadBtn.disabled = true;
                        hideSelectedImages();
                        return;
                    }
                    uploadBtn.disabled = false;
                    // Prikaži izbrane slike
                    showSelectedImages(this.files);
                } else {
                    uploadBtn.disabled = true;
                    // Skrij prikaz izbranih slik
                    hideSelectedImages();
                }
            });
            
            // Event listener za upload gumb
            uploadBtn.addEventListener('click', handleUploadClick);
            console.log('Desktop image upload setup complete');
        } else {
            console.error('Desktop image input or upload button not found');
        }

        // Nalivalec UI handlers
        async function populateNalivalecUsers() {
            try {
                // Use dedicated endpoint with lenient permissions
                const res = await fetch('/api/nalivalci');
                if (!res.ok) return;
                const users = await res.json();
                const sel = document.getElementById('nalivalec-select');
                if (!sel) return;
                sel.innerHTML = '<option value="">Izberi osebo...</option>' +
                    users.map(u => `<option value="${u.id}">${u.first_name || ''} ${u.last_name || ''}</option>`).join('');
            } catch(_) {}
        }
        window.populateNalivalecUsers = populateNalivalecUsers;

        const nalivalecSelfBtn = document.getElementById('nalivalec-self-btn');
        const nalivalecSaveBtn = document.getElementById('nalivalec-save-btn');
        if (nalivalecSelfBtn) {
            nalivalecSelfBtn.addEventListener('click', async () => {
                const bar = document.getElementById('nalivalec-toolbar');
                const orderNo = bar?.dataset.orderNumber;
                if (!orderNo) return;
                // pridobi order id iz API po order_number
                const orderId = await resolveOrderId(orderNo);
                if (!orderId) { showToast('Napaka: order ID ni najden', 'danger'); return; }
                const currentUser = JSON.parse(localStorage.getItem('currentUser')||'{}');
                if (!currentUser?.id) { showToast('Napaka: ni prijavljenega uporabnika', 'danger'); return; }
                // Najprej UI: nastavi selekcijo in stil gumba
                const sel = document.getElementById('nalivalec-select');
                if (sel) {
                    sel.value = String(currentUser.id);
                }
                nalivalecSelfBtn.classList.remove('border-emerald-300','bg-emerald-50','text-emerald-700');
                nalivalecSelfBtn.classList.add('border-emerald-500','bg-emerald-100','text-emerald-800');
                await setPreparedBy(orderId, currentUser.id);
            });
        }
        if (nalivalecSaveBtn) {
            nalivalecSaveBtn.addEventListener('click', async () => {
                const bar = document.getElementById('nalivalec-toolbar');
                const orderNo = bar?.dataset.orderNumber;
                const sel = document.getElementById('nalivalec-select');
                const uid = sel?.value;
                if (!orderNo || !uid) return;
                const orderId = await resolveOrderId(orderNo);
                if (!orderId) { showToast('Napaka: order ID ni najden', 'danger'); return; }
                // UI feedback na gumbu
                nalivalecSaveBtn.classList.add('ring-2','ring-blue-300');
                await setPreparedBy(orderId, parseInt(uid, 10));
                setTimeout(()=> nalivalecSaveBtn.classList.remove('ring-2','ring-blue-300'), 400);
            });
        }

        async function resolveOrderId(orderNumber) {
            try {
                const res = await fetch(`/api/order-by-number/${encodeURIComponent(orderNumber)}`);
                if (!res.ok) return null;
                const data = await res.json();
                return data?.id || null;
            } catch(_) { return null; }
        }
        async function setPreparedBy(orderId, userId) {
            try {
                const res = await fetch(`/api/orders/${orderId}/set-prepared-by`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId })
                });
                const data = await res.json();
                if (!res.ok || !data.success) throw new Error(data.error || 'Pripravljalca ni bilo mogoče nastaviti.');
                showToast('Pripravljalec nastavljen', 'success');
                if (typeof fetchNarocila === 'function') fetchNarocila();
            } catch(e) { showToast(e.message, 'danger'); }
        }
        // Expose helpers globally for use outside this closure
        window.resolveOrderId = resolveOrderId;
        window.setPreparedBy = setPreparedBy;
        
        if (cameraBtn && cameraInput) {
            console.log('Setting up camera button event listener');
            cameraBtn.addEventListener('click', function() {
                console.log('Camera button clicked');
                cameraInput.click();
            });
            
            cameraInput.addEventListener('change', function() {
                console.log('Camera input change event triggered');
                console.log('Files selected:', this.files.length);
                if (this.files.length > 0) {
                    console.log('File selected from camera:', this.files[0].name);
                    if (uploadBtn) uploadBtn.disabled = false;
                    // Kopiraj file v desktop input za kompatibilnost
                    if (imageInput) {
                        imageInput.files = this.files;
                        console.log('File copied to desktop input');
                    }
                    // Prikaži izbrane slike
                    showSelectedImages(this.files);
                }
            });
            console.log('Camera upload setup complete');
        } else {
            console.error('Camera button or input not found');
        }
        
        if (galleryBtn && mobileImageInput) {
            console.log('Gallery button and mobile input found, setting up event listeners');
            galleryBtn.addEventListener('click', function() {
                console.log('Gallery button clicked, triggering file input');
                console.log('Mobile image input element:', mobileImageInput);
                console.log('Mobile image input type:', mobileImageInput.type);
                console.log('Mobile image input accept:', mobileImageInput.accept);
                mobileImageInput.click();
                console.log('File input click triggered');
            });
            
            mobileImageInput.addEventListener('change', function() {
                console.log('Mobile image input change event triggered');
                console.log('Files selected:', this.files.length);
                console.log('Files object:', this.files);
                if (this.files.length > 0) {
                    console.log('File selected:', this.files[0].name);
                    console.log('File size:', this.files[0].size);
                    console.log('File type:', this.files[0].type);
                    if (uploadBtn) {
                        uploadBtn.disabled = false;
                        console.log('Upload button enabled');
                    }
                    // Kopiraj file v desktop input za kompatibilnost
                    if (imageInput) {
                        imageInput.files = this.files;
                        console.log('File copied to desktop input');
                    }
                    // Prikaži izbrane slike
                    showSelectedImages(this.files);
                    console.log('Showing selected images');
                } else {
                    console.log('No files selected');
                }
            });
        } else {
            console.log('Gallery button or mobile input not found:', {
                galleryBtn: !!galleryBtn,
                mobileImageInput: !!mobileImageInput
            });
        }
            
            // Event delegation za brisanje slik
            const container = document.getElementById('order-images-list');
            if (container) {
                container.addEventListener('click', function(e) {
                    const btn = e.target.closest('.delete-image-btn');
                    if (btn) {
                        // Prepreči bubbling in multiple events
                        e.preventDefault();
                        e.stopPropagation();
                        
                        const imageId = btn.dataset.imageId;
                        console.log('=== DELETE BUTTON CLICKED VIA EVENT DELEGATION ===');
                        console.log('imageId from dataset:', imageId);
                        if (imageId) {
                            deleteOrderImage(imageId);
                        } else {
                            console.error('Manjka imageId na gumbu za brisanje');
                            showToast('Napaka: Manjka ID slike za brisanje', 'danger');
                        }
                    }
                });
            }
        
        // Označi modal kot inicializiran
        window.modalInitialized = true;
        console.log('Modal initialization complete');
    }
    
    // Poskusi inicializacijo takoj
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeModal);
    } else {
        // DOM je že naložen, počakajmo še malo za Bootstrap
        setTimeout(initializeModal, 100);
    }
    
    async function showUploadImagesModal(orderNumber) {
        console.log('showUploadImagesModal called with orderNumber:', orderNumber);
        
        // Počisti orderNumber - odstrani # znak, če obstaja
        if (orderNumber && orderNumber.startsWith('#')) {
            orderNumber = orderNumber.substring(1);
            console.log('Cleaned orderNumber in showUploadImagesModal:', orderNumber);
        }
        
        if (!orderNumber || orderNumber === 'undefined') {
            console.error('orderNumber ni veljaven:', orderNumber);
            showToast('Napaka: Manjka številka naročila za slike.', 'danger');
            return;
        }

        currentOrderNumber = orderNumber;
        const numberElement = document.getElementById('order-images-number');
        if (numberElement) {
            numberElement.textContent = orderNumber;
        }

        // Nastavi modal v "upload mode"
        const modalTitle = document.querySelector('#orderImagesModal .modal-title');
        if (modalTitle) {
            modalTitle.textContent = `Naloži slike za naročilo ${orderNumber}`;
        }

        // Prikaži modal in pripravi nalivalec toolbar (kot pri showOrderImages)
        if (orderImagesModal) {
            showModal('orderImagesModal');
            const nalivalecBar = document.getElementById('nalivalec-toolbar');
            if (nalivalecBar) {
                try {
                    const response = await fetch(`/api/orders/${orderNumber}`);
                    if (response.ok) {
                        const orderData = await response.json();
                        const narocilo = orderData.data || orderData;
                        const hasParfumi = hasParfumiProducts(narocilo);
                        const isBrezParfumov = narocilo.status === 'brez_parfumov';
                        if (hasParfumi && !isBrezParfumov) {
                            nalivalecBar.dataset.orderNumber = orderNumber;
                            nalivalecBar.classList.remove('hidden');
                            await populateNalivalecUsers();
                        } else {
                            nalivalecBar.classList.add('hidden');
                        }
                    } else {
                        nalivalecBar.classList.add('hidden');
                    }
                } catch (_) {
                    nalivalecBar.classList.add('hidden');
                }
            }
        } else {
            console.error('orderImagesModal is null - preveri, ali obstaja #orderImagesModal v HTML-ju');
            showToast('Napaka: Modal za slike ni bil najden', 'danger');
        }
    }
    async function showOrderImages(orderNumber) {
        console.log('showOrderImages called with orderNumber:', orderNumber);
        
        // Počisti orderNumber - odstrani # znak, če obstaja
        if (orderNumber && orderNumber.startsWith('#')) {
            orderNumber = orderNumber.substring(1);
            console.log('Cleaned orderNumber in showOrderImages:', orderNumber);
        }
        
        if (!orderNumber || orderNumber === 'undefined') {
            console.error('orderNumber ni veljaven:', orderNumber);
            showToast('Napaka: Manjka številka naročila za slike.', 'danger');
            return;
        }

        currentOrderNumber = orderNumber;
        const numberElement = document.getElementById('order-images-number');
        if (numberElement) {
            numberElement.textContent = orderNumber;
        }

        // Nastavi modal v "view mode"
        const modalTitle = document.querySelector('#orderImagesModal .modal-title');
        if (modalTitle) {
            modalTitle.textContent = `Slike za naročilo ${orderNumber}`;
        }

        await loadOrderImages(orderNumber);

        if (orderImagesModal) {
            showModal('orderImagesModal');
            
            // Pridobi podatke o naročilu, da preverimo, ali vsebuje parfume
            const nalivalecBar = document.getElementById('nalivalec-toolbar');
            if (nalivalecBar) {
                try {
                    // Poskusi dobiti podatke o naročilu iz API-ja
                    const response = await fetch(`/api/orders/${orderNumber}`);
                    if (response.ok) {
                        const orderData = await response.json();
                        const narocilo = orderData.data || orderData;
                        
                        console.log(`DEBUG showOrderImages - Raw API response:`, orderData);
                        console.log(`DEBUG showOrderImages - Extracted narocilo:`, narocilo);
                        console.log(`DEBUG showOrderImages - line_items:`, narocilo.line_items);
                        console.log(`DEBUG showOrderImages - line_items type:`, typeof narocilo.line_items);
                        
                        // Preveri, ali naročilo vsebuje Parfumi izdelke
                        const hasParfumi = hasParfumiProducts(narocilo);
                        const isBrezParfumov = narocilo.status === 'brez_parfumov';
                        
                        console.log(`showOrderImages - Order ${orderNumber}: hasParfumi=${hasParfumi}, status=${narocilo.status}, isBrezParfumov=${isBrezParfumov}`);
                        
                        // Prikaži nalivalec toolbar samo, če naročilo vsebuje parfume IN ni označeno kot "brez_parfumov"
                        if (hasParfumi && !isBrezParfumov) {
                            console.log(`Showing nalivalec toolbar for order ${orderNumber}`);
                            nalivalecBar.dataset.orderNumber = orderNumber;
                            nalivalecBar.classList.remove('hidden');
                            await populateNalivalecUsers();
                        } else {
                            console.log(`Hiding nalivalec toolbar for order ${orderNumber}: hasParfumi=${hasParfumi}, isBrezParfumov=${isBrezParfumov}`);
                            nalivalecBar.classList.add('hidden');
                        }
                    } else {
                        console.error('Napaka pri pridobivanju podatkov o naročilu:', response.status);
                        // V primeru napake skrij nalivalec toolbar
                        nalivalecBar.classList.add('hidden');
                    }
                } catch (error) {
                    console.error('Napaka pri preverjanju podatkov o naročilu:', error);
                    // V primeru napake skrij nalivalec toolbar
                    nalivalecBar.classList.add('hidden');
                }
            }
        } else {
            console.error('orderImagesModal is null - preveri, ali obstaja #orderImagesModal v HTML-ju');
            showToast('Napaka: Modal za slike ni bil najden', 'danger');
        }
    }
    
    // Avtomatsko ponastavi pripravil in nalivalec ko ni slik
    async function autoResetOrderFields(orderNumber) {
        if (!orderNumber) return;
        
        try {
            console.log(`🔄 Auto-resetting fields for order ${orderNumber} (no images)`);
            
            const response = await fetch(`/api/orders/${orderNumber}/reset-preparation`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                console.log(`✅ Auto-reset successful for order ${orderNumber}`);
                
                // Osveži nalivalec toolbar
                const nalivalecSelect = document.getElementById('nalivalec-select');
                if (nalivalecSelect) {
                    nalivalecSelect.value = '';
                }
                
                // Skrij gumb "Naročilo pripravljeno"
                const pripravljenoBtn = document.getElementById('narocilo-pripravljeno-btn');
                if (pripravljenoBtn) {
                    pripravljenoBtn.style.display = 'none';
                }
                
            } else {
                console.warn(`⚠️ Auto-reset failed for order ${orderNumber}: ${response.status}`);
            }
        } catch (error) {
            console.error(`❌ Auto-reset error for order ${orderNumber}:`, error);
        }
    }
    
    async function loadOrderImages(orderNumber) {
        console.log('loadOrderImages called with orderNumber:', orderNumber);
        
        // Počisti orderNumber - odstrani # znak, če obstaja
        if (orderNumber && orderNumber.startsWith('#')) {
            orderNumber = orderNumber.substring(1);
            console.log('Cleaned orderNumber in loadOrderImages:', orderNumber);
        }
        
        if (!orderNumber || orderNumber === 'undefined') {
            console.error('orderNumber ni podan v loadOrderImages:', orderNumber);
            return;
        }

        try {
            const url = `/api/order-images/${orderNumber}`;
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Napaka pri pridobivanju slik. HTTP status: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                displayOrderImages(data.images);
            } else {
                showToast('Napaka pri nalaganju slik', 'danger');
            }
        } catch (error) {
            console.error('Napaka pri nalaganju slik:', error);
            showToast('Napaka pri nalaganju slik', 'danger');
        }
    }
    
    function displayOrderImages(images) {
        const container = document.getElementById('order-images-list');
        
        if (images.length === 0) {
            container.innerHTML = '<div class="text-center text-gray-500 py-8">Ni naloženih slik za to naročilo.</div>';
            return;
        }
        
        console.log('Displaying images:', images);
        
        container.innerHTML = images.map(image => {
            console.log('Image URL:', image.s3_url);
            console.log('Image ID for delete button:', image.id);
            return `
            <div class="bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-shadow duration-200">
                <div class="aspect-w-16 aspect-h-12 relative">
                    <img src="${image.s3_url}" class="w-full h-48 object-cover cursor-pointer hover:opacity-90 transition-opacity duration-200" 
                         alt="Slika naročila" 
                         onerror="this.style.display='none'; console.error('Failed to load image:', this.src);"
                         onclick="openImageViewModal('${image.s3_url}')">
                    <div class="absolute top-2 right-2">
                        <button onclick="openImageViewModal('${image.s3_url}')" 
                                class="bg-white bg-opacity-80 hover:bg-opacity-100 text-gray-700 hover:text-gray-900 p-2 rounded-full shadow-md transition-all duration-200">
                            <i class="bi bi-zoom-in"></i>
                        </button>
                    </div>
                </div>
                <div class="p-4">
                    <div class="space-y-2 mb-3">
                        <div class="flex items-center text-sm text-gray-600">
                            <i class="bi bi-person mr-2"></i>
                            <span>${image.uploaded_by}</span>
                        </div>
                        <div class="flex items-center text-sm text-gray-600">
                            <i class="bi bi-calendar mr-2"></i>
                            <span>${new Date(image.uploaded_at).toLocaleString('sl-SI')}</span>
                        </div>
                    </div>
                    <div class="flex space-x-2">
                        <button class="flex-1 inline-flex items-center justify-center px-3 py-2 border border-blue-300 rounded-lg text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors duration-200" 
                                onclick="openImageViewModal('${image.s3_url}')">
                            <i class="bi bi-eye mr-2"></i> Ogled
                        </button>
                        <button class="flex-1 inline-flex items-center justify-center px-3 py-2 border ${image.can_delete ? 'border-red-300 text-red-700 bg-red-50 hover:bg-red-100' : 'border-gray-200 text-gray-400 bg-gray-100 cursor-not-allowed'} rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 ${image.can_delete ? 'focus:ring-red-500' : 'pointer-events-none'} transition-colors duration-200 delete-image-btn" data-image-id="${image.id}">
                            <i class="bi bi-trash mr-2"></i> Izbriši
                        </button>
                    </div>
                </div>
            </div>
        `;
        }).join('');
        
        // Event listeners se dodajo preko event delegation - odstranjen duplicated listener
        /* REMOVED DUPLICATE EVENT LISTENERS - using event delegation instead
        container.querySelectorAll('.delete-image-btn').forEach(btn => {
            btn.addEventListener('click', async function() {
                // ... removed duplicate logic ...
            });
        });
        */
    }
    
    function showSelectedImages(files) {
        console.log('showSelectedImages called with files:', files);
        console.log('Number of files:', files.length);
        
        const previewContainer = document.getElementById('selected-images-preview');
        const imagesList = document.getElementById('selected-images-list');
        
        console.log('Preview container found:', !!previewContainer);
        console.log('Images list found:', !!imagesList);
        
        if (!previewContainer || !imagesList) {
            console.error('Preview container or images list not found');
            return;
        }
        
        // Počisti prejšnje slike
        imagesList.innerHTML = '';
        
        // Dodaj vsako izbrano sliko
        Array.from(files).forEach((file, index) => {
            console.log(`Processing file ${index}:`, file.name, file.type, file.size);
            const reader = new FileReader();
            reader.onload = function(e) {
                console.log(`File ${index} loaded successfully`);
                const div = document.createElement('div');
                div.innerHTML = `
                    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
                        <img src="${e.target.result}" class="w-full h-24 object-cover" alt="Izbrana slika">
                        <div class="p-2">
                            <p class="text-xs text-gray-600 truncate">${file.name}</p>
                        </div>
                    </div>
                `;
                imagesList.appendChild(div.firstElementChild);
                console.log(`File ${index} added to preview`);
            };
            reader.onerror = function(e) {
                console.error(`Error reading file ${index}:`, e);
            };
            reader.readAsDataURL(file);
        });
        
        // Prikaži container
        previewContainer.classList.remove('hidden');
    }
    
    function hideSelectedImages() {
        const previewContainer = document.getElementById('selected-images-preview');
        if (previewContainer) {
            previewContainer.classList.add('hidden');
        }
    }

    // Funkcija za odpiranje modalnega okna za ogled slike
    window.openImageViewModal = function(imageUrl) {
        const modal = document.getElementById('imageViewModal');
        const image = document.getElementById('fullSizeImage');
        
        if (modal && image) {
            image.src = imageUrl;
            modal.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        }
    }

    // Funkcija za zapiranje modalnega okna za ogled slike
    window.closeImageViewModal = function() {
        const modal = document.getElementById('imageViewModal');
        
        if (modal) {
            modal.classList.add('hidden');
            document.body.style.overflow = 'auto';
        }
    }

    // Funkcija za prenos slike
    window.downloadImage = function() {
        const image = document.getElementById('fullSizeImage');
        if (!image || !image.src) {
            showToast('Ni slike za prenos', 'warning');
            return;
        }
        
        try {
            // Ustvari link za prenos
            const link = document.createElement('a');
            link.href = image.src;
            link.download = `slika_${Date.now()}.jpg`;
            link.target = '_blank';
            
            // Prožilni klik
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            showToast('Prenos slike se začne...', 'success');
        } catch (error) {
            console.error('Error downloading image:', error);
            showToast('Napaka pri prenosu slike', 'danger');
        }
    }
    
    // Preverimo validation PRED odprtjem file picker-ja ALI procesiramo že izbrane slike
    async function handleUploadClick(event) {
        console.log('🎯 handleUploadClick called - checking for selected files or opening picker');
        
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        
        if (!currentOrderNumber) {
            showToast('Napaka: Manjka številka naročila', 'danger');
            return;
        }

        // Preveri, ali so slike že izbrane (gallery/camera flow)
        const fileInput = document.getElementById('order-image-input');
        const hasSelectedFiles = fileInput && fileInput.files && fileInput.files.length > 0;
        
        console.log(`🔍 Checking files: input exists=${!!fileInput}, files=${fileInput?.files?.length || 0}`);
        
        if (hasSelectedFiles) {
            // Slike so že izbrane - direktno procesiramo upload
            console.log(`📁 Files already selected (${fileInput.files.length}), proceeding to upload`);
            await uploadOrderImage(event);
            return;
        }

        // Slik ni izbranih - izvedi validation in odpri file picker
        try {
            console.log(`🔍 No files selected - running validation before opening picker for order ${currentOrderNumber}`);
            
            // Vedno preveri, ali je za parfum naročila izbran pripravljalec
            const nalivalecSelect = document.getElementById('nalivalec-select');
            const uiSelectedPreparedBy = nalivalecSelect && nalivalecSelect.value && nalivalecSelect.value !== '';

            console.log(`🔍 UI pripravljalec check: select exists=${!!nalivalecSelect}, selected value="${nalivalecSelect?.value}", has selection=${uiSelectedPreparedBy}`);

            console.log(`🔍 Checking order data for upload precondition ${currentOrderNumber}`);
            const response = await fetch(`/api/orders/${currentOrderNumber}`);
            
            if (response.ok) {
                const orderData = await response.json();
                const narocilo = orderData.data || orderData;
                
                // Preveri, ali naročilo vsebuje Parfumi izdelke
                const hasParfumi = hasParfumiProducts(narocilo);
                const isBrezParfumov = narocilo.status === 'brez_parfumov';
                
                console.log(`🔍 Database validation: hasParfumi=${hasParfumi}, isBrezParfumov=${isBrezParfumov}`);
                
                // Če naročilo vsebuje parfume in ni "brez_parfumov", mora biti IZBRAN pripravljalec v UI
                const requiresPreparedBy = hasParfumi && !isBrezParfumov;
                const shouldBlock = requiresPreparedBy && !uiSelectedPreparedBy;
                
                console.log(`🔍 DATABASE VALIDATION:`, {
                    hasParfumi,
                    isBrezParfumov,
                    requiresPreparedBy,
                    uiSelectedPreparedBy,
                    shouldBlock
                });
                
                if (shouldBlock) {
                    console.log(`🚫 BLOCKING BEFORE FILE PICKER: Parfum order needs pripravljalec!`);
                    showToast('Prosimo označite pripravljalca preden naložite slike za naročila s parfumi', 'warning');
                    return;
                }
                
                console.log(`✅ DATABASE VALIDATION PASSED - Opening file picker`);
                
                // Če je validation uspešen, odpri file picker
                if (fileInput) {
                    fileInput.click();
                }
            } else {
                console.error(`❌ Failed to fetch order details for validation: ${response.status}`);
                showToast('Napaka pri preverjanju podatkov o naročilu', 'danger');
            }
        } catch (error) {
            console.error('❌ Pre-picker validation error:', error);
            showToast('Napaka pri preverjanju podatkov o naročilu', 'danger');
        }
    }
    
    async function compressOrderImageFile(file) {
        try {
            if (!file || !file.type || !file.type.startsWith('image/')) {
                return { file, optimized: false };
            }
            const maxW = 1200;
            const maxH = 800;
            const bitmap = await createImageBitmap(file);
            const ratio = Math.min(maxW / bitmap.width, maxH / bitmap.height, 1);
            const targetW = Math.max(1, Math.round(bitmap.width * ratio));
            const targetH = Math.max(1, Math.round(bitmap.height * ratio));
            const canvas = document.createElement('canvas');
            canvas.width = targetW;
            canvas.height = targetH;
            const ctx = canvas.getContext('2d', { alpha: false });
            ctx.drawImage(bitmap, 0, 0, targetW, targetH);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82));
            if (!blob) {
                return { file, optimized: false };
            }
            const optimizedFile = new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' });
            return { file: optimizedFile, optimized: true };
        } catch (e) {
            console.warn('Image optimization failed, uploading original.', e);
            return { file, optimized: false };
        }
    }

    async function uploadOrderImage(event) {
        console.log('🚀 uploadOrderImage called!', event);
        
        // Prepreči večkratne klikov
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        
        const uploadBtn = document.getElementById('upload-image-btn');
        
        // Zaščita proti dvojnemu kliku
        if (uploadBtn.disabled) {
            console.log('Upload že v teku, ignoriram klik');
            return;
        }
        
        const fileInput = document.getElementById('order-image-input');
        const file = fileInput.files[0];
        
        // Preveri, ali je slika izbrana
        if (!file) {
            showToast('Prosimo, izberite sliko za nalaganje', 'warning');
            return;
        }
        
        if (!currentOrderNumber) {
            showToast('Napaka: Manjka številka naročila', 'danger');
            return;
        }

        // Validation se sedaj izvaja v handleUploadClick PRED file picker
        console.log(`🚀 Processing file upload (validation already passed)`);
        
        // Onemogoči gumb in prikaži loading
        setButtonLoading(uploadBtn, true, 'Nalagam...');
        
        try {
            // Če naročilo vsebuje Parfumi, je pripravljalec obvezen pred nalaganjem.
            const nalivalecSelect = document.getElementById('nalivalec-select');
            const selectedPreparedById = nalivalecSelect && nalivalecSelect.value ? parseInt(nalivalecSelect.value, 10) : null;
            let requiresPreparedBy = false;
            try {
                const resp = await fetch(`/api/orders/${currentOrderNumber}`);
                if (resp.ok) {
                    const od = await resp.json();
                    const nar = od.data || od;
                    const hasParfumi = hasParfumiProducts(nar);
                    const isBrezParfumov = nar.status === 'brez_parfumov';
                    requiresPreparedBy = hasParfumi && !isBrezParfumov;
                }
            } catch(_) {}

            if (requiresPreparedBy && !selectedPreparedById) {
                showToast('Prosimo označite pripravljalca preden naložite slike za naročila s parfumi', 'warning');
                setButtonLoading(uploadBtn, false);
                return;
            }

            if (requiresPreparedBy && selectedPreparedById) {
                const orderId = await resolveOrderId(currentOrderNumber);
                if (!orderId) {
                    showToast('Napaka: order ID ni najden', 'danger');
                    setButtonLoading(uploadBtn, false);
                    return;
                }
                try {
                    const res = await fetch(`/api/orders/${orderId}/set-prepared-by`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: selectedPreparedById })
                    });
                    const data = await res.json();
                    if (!res.ok || !data.success) {
                        showToast(data.error || 'Pripravljalca ni bilo mogoče nastaviti', 'danger');
                        setButtonLoading(uploadBtn, false);
                        return;
                    }
                } catch (e) {
                    showToast('Napaka pri nastavljanju pripravljalca', 'danger');
                    setButtonLoading(uploadBtn, false);
                    return;
                }
            }

            // Pošlji kot multipart/form-data (hitreje, manjša obremenitev strežnika)
            const { file: uploadFile, optimized } = await compressOrderImageFile(file);
            const currentUser = JSON.parse(localStorage.getItem('currentUser') || '{}');
            let result = null;
            
            // Najprej poskusi direktni upload v S3 (presigned POST)
            try {
                const presignResp = await fetch(`/api/order-images/${currentOrderNumber}/presign`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content_type: uploadFile.type || 'image/jpeg',
                        file_size: uploadFile.size
                    })
                });
                const presignData = await presignResp.json();
                if (presignResp.ok && presignData && presignData.success && presignData.url) {
                    const s3Form = new FormData();
                    Object.entries(presignData.fields || {}).forEach(([k, v]) => s3Form.append(k, v));
                    s3Form.append('file', uploadFile);
                    const s3Resp = await fetch(presignData.url, {
                        method: 'POST',
                        body: s3Form
                    });
                    if (!s3Resp.ok) {
                        throw new Error('S3 upload failed');
                    }
                    const finalizeResp = await fetch(`/api/order-images/${currentOrderNumber}/finalize`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ s3_key: presignData.s3_key })
                    });
                    const finalizeData = await finalizeResp.json();
                    if (!finalizeResp.ok) {
                        throw new Error(finalizeData?.error || 'Finalize failed');
                    }
                    result = finalizeData;
                }
            } catch (e) {
                console.warn('Direct S3 upload failed, fallback to API upload.', e);
            }

            // Fallback: upload prek aplikacije
            if (!result) {
                const formData = new FormData();
                formData.append('image', uploadFile);
                formData.append('user_id', currentUser.username || 'admin');

                const response = await fetch(`/api/order-images/${currentOrderNumber}`, {
                    method: 'POST',
                    headers: optimized ? { 'X-Client-Optimized': '1' } : undefined,
                    body: formData
                });
                
                result = await response.json();
            }
            
            if (result.success) {
                showToast('Slika uspešno naložena', 'success');
                fileInput.value = '';
                
                // Počisti tudi mobilne inpute
                const cameraInput = document.getElementById('camera-input');
                const mobileImageInput = document.getElementById('mobile-image-input');
                if (cameraInput) cameraInput.value = '';
                if (mobileImageInput) mobileImageInput.value = '';
                
                // Skrij prikaz izbranih slik
                hideSelectedImages();
                
                document.getElementById('upload-image-btn').disabled = true;
                
                console.log('Osvežujem seznam slik...');
                // Osveži seznam slik
                loadOrderImages(currentOrderNumber);
                
                console.log('Osvežujem seznam naročil...');
                // Osveži seznam naročil, da se prikaže "Prikaži slike" gumb
                fetchNarocila(currentPage);
                console.log('Seznam naročil osvežen');
            } else {
                showToast(`Napaka: ${result.error}`, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri nalaganju slike:', error);
            showToast('Napaka pri nalaganju slike', 'danger');
        } finally {
            // Vedno ponastavi gumb na koncu
            setButtonLoading(uploadBtn, false);
        }
    }
    
    async function deleteOrderImage(imageId) {
        console.log('=== deleteOrderImage CALLED ===');
        console.log('imageId parameter:', imageId);
        console.log('imageId type:', typeof imageId);
        
        if (!confirm('Ali ste prepričani, da želite izbrisati to sliko?')) return;
        
        try {
            console.log('Sending DELETE request to:', `/api/order-images/${imageId}`);
            const response = await fetch(`/api/order-images/${imageId}`, {
                method: 'DELETE'
            });
            
            console.log('Response status:', response.status);
            console.log('Response ok:', response.ok);
            
            const result = await response.json();
            console.log('Response result:', result);
            
                    if (result.success) {
            if (result.prepared_by_reset) {
                showToast('Slika izbrisana. Status "Pripravil" je bil ponastavljen ker ni več slik.', 'info');
            } else {
                showToast('Slika uspešno izbrisana', 'success');
            }
            
            console.log('Osvežujem seznam slik po brisanju...');
            await loadOrderImages(currentOrderNumber);
            
            console.log('Osvežujem seznam naročil po brisanju...');
            // Osveži seznam naročil, da se posodobi število slik in "Pripravil" status
            await fetchNarocila(currentPage);
            console.log('Seznam naročil osvežen po brisanju');
        } else {
            showToast(`Napaka: ${result.error}`, 'danger');
        }
        } catch (error) {
            console.error('Napaka pri brisanju slike:', error);
            showToast('Napaka pri brisanju slike', 'danger');
        }
    }
    
    function fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = () => resolve(reader.result);
            reader.onerror = error => reject(error);
        });
    }
    
    // SAMODEJNI OSVEŽITEV OPOZORIL - vsakih 60 sekund (ohranimo za opozorila)
    setInterval(() => {
        console.log('Samodejni osvežitev opozoril...');
        fetchExpiringPerfumes();
    }, 60000); // 60 sekund

    async function syncAllInciFromShopify() {
        const button = document.getElementById('sync-all-inci-btn');
        if (!button) return;

        if (button.disabled) {
            showToast('Proces je že v teku, počakajte...', 'warning');
            return;
        }

        if (!confirm('⚠️  POZOR! To bo sinhroniziralo INCI podatke iz Shopify metafield-ov za vse parfume, ki nimajo INCI. Ali ste prepričani?')) {
            return;
        }

        setButtonLoading(button, true, 'Sinhroniziram...');
        showToast('Začenjam sinhronizacijo INCI podatkov iz Shopify... To lahko traja nekaj časa.', 'info');

        try {
            const response = await fetch('/api/sync-all-inci-from-shopify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (!response.ok) {
                let errorMsg = 'Neznana napaka';
                try {
                    const result = await response.json();
                    errorMsg = result.error || result.message || 'Neznana napaka';
                } catch (e) {
                    errorMsg = `Strežnik je vrnil napako ${response.status}.`;
                }
                throw new Error(errorMsg);
            }

            const result = await response.json();
            
            if (result.success) {
                showToast(result.message, 'success');
                // Osvežimo seznam naročil, če je bilo uspešno
                if (result.success_count > 0) {
                    await fetchNarocila();
                }
            } else {
                showToast(result.message, 'danger');
            }

        } catch (error) {
            console.error('Napaka pri sinhronizaciji INCI:', error);
            showToast(`Napaka pri sinhronizaciji: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }



    function showAddProizvajalecModal() {
        document.getElementById('proizvajalecIme').value = '';
        showModal('addProizvajalecModal');
    }

    function showDeleteProizvajalecModal() {
        loadProizvajalciForDelete();
        showModal('deleteProizvajalecModal');
    }

    async function loadProizvajalciForDelete() {
        try {
            const response = await fetch('/api/proizvajalci');
            const proizvajalci = await response.json();
            
            const select = document.getElementById('deleteProizvajalecSelect');
            select.innerHTML = '<option value="">Izberi proizvajalca...</option>';
            
            proizvajalci.forEach(proizvajalec => {
                const option = document.createElement('option');
                option.value = proizvajalec.id;
                option.textContent = proizvajalec.ime;
                select.appendChild(option);
            });
        } catch (error) {
            showToast('Napaka pri nalaganju proizvajalcev', 'danger');
        }
    }

    // Event listener za dodajanje proizvajalca
    document.getElementById('confirmAddProizvajalecBtn')?.addEventListener('click', async () => {
        const ime = document.getElementById('proizvajalecIme').value.trim();
        if (!ime) {
            showToast('Vnesite ime proizvajalca', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/proizvajalci', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ime })
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
            closeModal('addProizvajalecModal');
            loadProizvajalci();
        } catch (error) {
            showToast(`Napaka pri dodajanju proizvajalca: ${error.message}`, 'danger');
        }
    });

    // Event listener za brisanje proizvajalca
    document.getElementById('confirmDeleteProizvajalecBtn')?.addEventListener('click', async () => {
        const proizvajalecId = document.getElementById('deleteProizvajalecSelect').value;
        if (!proizvajalecId) {
            showToast('Izberite proizvajalca', 'warning');
            return;
        }

        if (!confirm('⚠️  POZOR! To bo izbrisalo vse parfume tega proizvajalca in vse povezane podatke. Ali ste prepričani?')) {
            return;
        }

        try {
            const response = await fetch(`/api/proizvajalci/${proizvajalecId}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
            closeModal('deleteProizvajalecModal');
            loadProizvajalci();
        } catch (error) {
            showToast(`Napaka pri brisanju proizvajalca: ${error.message}`, 'danger');
        }
    });

    // Event listener za spremembo izbire proizvajalca za brisanje
    document.getElementById('deleteProizvajalecSelect')?.addEventListener('change', function() {
        const confirmBtn = document.getElementById('confirmDeleteProizvajalecBtn');
        const infoDiv = document.getElementById('deleteProizvajalecInfo');
        
        if (this.value) {
            confirmBtn.disabled = false;
            infoDiv.style.display = 'block';
        } else {
            confirmBtn.disabled = true;
            infoDiv.style.display = 'none';
        }
    });

    async function autoEnableShopifySync() {
        const button = document.getElementById('auto-enable-sync-btn');
        if (!button) return;

        if (button.disabled) {
            showToast('Proces je že v teku, počakajte...', 'warning');
            return;
        }

        if (!confirm('⚠️  To bo avtomatsko vklopilo sinhronizacijo s Shopify za vse parfume, ki obstajajo v Shopify. Ali ste prepričani?')) {
            return;
        }

        setButtonLoading(button, true, 'Vklopim...');
        showToast('Začenjam avtomatsko vklopitev sinhronizacije... To lahko traja nekaj časa.', 'info');

        try {
            const response = await fetch('/api/auto-enable-shopify-sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
        } catch (error) {
            showToast(`Napaka pri avtomatski vklopitvi: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    async function autoDisableShopifySync() {
        const button = document.getElementById('auto-disable-sync-btn');
        if (!button) return;

        if (button.disabled) {
            showToast('Proces je že v teku, počakajte...', 'warning');
            return;
        }

        if (!confirm('⚠️  To bo avtomatsko izklopilo sinhronizacijo s Shopify za vse parfume, ki ne obstajajo v Shopify. Ali ste prepričani?')) {
            return;
        }

        setButtonLoading(button, true, 'Izklopim...');
        showToast('Začenjam avtomatsko izklopitev sinhronizacije... To lahko traja nekaj časa.', 'info');

        try {
            const response = await fetch('/api/auto-disable-shopify-sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
        } catch (error) {
            showToast(`Napaka pri avtomatski izklopitvi: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    async function migratePerfumesFromExcel() {
        const button = document.getElementById('migrate-perfumes-btn');
        if (!button) return;

        if (button.disabled) {
            showToast('Proces je že v teku, počakajte...', 'warning');
            return;
        }

        if (!confirm('⚠️  POZOR! To bo migriralo parfume iz Excel datoteke (zvezek "Parfumi"). Ali ste prepričani?')) {
            return;
        }

        setButtonLoading(button, true, 'Migriram...');
        showToast('Začenjam migracijo parfumov iz Excel datoteke... To lahko traja nekaj časa.', 'info');

        try {
            const response = await fetch('/api/migrate-perfumes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
            loadProizvajalci(); // Osvežimo seznam proizvajalcev
        } catch (error) {
            showToast(`Napaka pri migraciji parfumov: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    async function refreshPerfumeUI(perfumeId) {
        try {
            const response = await fetch(`/api/parfum/${perfumeId}`);
            if (!response.ok) throw new Error('Parfum ni najden.');
            const parfum = await response.json();
            
            // Posodobi samo UI elemente, ne pa vseh podatkov
            if (stockStatusSwitch) {
                stockStatusSwitch.checked = parfum.na_zalogi;
            }
            
            if (syncWithShopifySwitch) {
                syncWithShopifySwitch.checked = parfum.sinhroniziraj_s_shopify;
                // Posodobi tudi tooltip
                if (syncSwitchWrapper) {
                    syncSwitchWrapper.title = parfum.sinhroniziraj_s_shopify ? 
                        'Vklopi za sinhronizacijo s Shopify' : 
                        'Parfum ne obstaja v Shopify-ju';
                }
            }
            
            console.log('UI refreshed for perfume:', parfum.id);
            
        } catch (error) {
            console.error('Napaka pri osveževanju UI:', error);
        }
    }

    async function checkShopifyExists(perfumeId) {
        try {
            const response = await fetch(`/api/parfum/${perfumeId}/check-shopify-exists`);
            const result = await response.json();
            
            if (!response.ok) {
                console.error('Napaka pri preverjanju obstoja v Shopify:', result.error);
                return false;
            }
            
            // Posodobi UI glede na rezultat
            if (syncWithShopifySwitch) {
                if (result.exists_in_shopify) {
                    syncWithShopifySwitch.disabled = false;
                    syncSwitchWrapper.title = 'Vklopi za sinhronizacijo s Shopify';
                    
                    // Če parfum obstaja v Shopify-ju, avtomatsko vklopi sinhronizacijo
                    if (!syncWithShopifySwitch.checked) {
                        syncWithShopifySwitch.checked = true;
                        // Avtomatsko shrani nastavitev (brez dodatnega preverjanja)
                        try {
                            const response = await fetch(`/api/parfum/${perfumeId}/sync-status`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ sinhroniziraj_s_shopify: true })
                            });
                            const result = await response.json();
                            if (response.ok) {
                                showToast('Sinhronizacija s Shopify je avtomatsko vklopljena.', 'success');
                            }
                        } catch (error) {
                            console.error('Napaka pri avtomatski vklopitvi sinhronizacije:', error);
                        }
                    }
                } else {
                    syncWithShopifySwitch.disabled = true;
                    syncWithShopifySwitch.checked = false;
                    syncSwitchWrapper.title = 'Izdelek s to šifro in proizvajalcem ne obstaja v Shopify. Sinhronizacija ni mogoča.';
                }
            }
            
            return result.exists_in_shopify;
        } catch (error) {
            console.error('Napaka pri preverjanju obstoja v Shopify:', error);
            return false;
        }
    }

    // --- Funkcije za upravljanje uporabnikov ---

    // Seznam vseh možnih dovoljenj
    const ALL_PERMISSIONS = [
        { id: 'view_admin_tabs', name: 'Prikaz admin zavihkov', description: 'Lahko vidi admin zavihke (Globalne akcije, Uporabniki)', category: 'Vmesnik' },
        { id: 'manage_users', name: 'Upravljanje uporabnikov', description: 'Dodajanje/brisanje/upd dovoljenj/upd gesel', category: 'Uporabniki' },
        // Naročila
        { id: 'view_orders', name: 'Pregled naročil', description: 'Lahko si ogleda naročila', category: 'Naročila' },
        
        // Vmesnik / zavihek
        { id: 'view_global_actions', name: 'Prikaz Globalne akcije', description: 'Lahko vidi zavihek Globalne akcije', category: 'Vmesnik' },
        
        // Serije
        { id: 'add_serije', name: 'Dodajanje serij', description: 'Lahko doda nove serije', category: 'Serije' },
        { id: 'edit_serije', name: 'Urejanje serij', description: 'Lahko ureja serije', category: 'Serije' },
        { id: 'delete_serije', name: 'Brisanje serij', description: 'Lahko briše serije', category: 'Serije' },
        
        // Parfumi - osnovne operacije
        { id: 'view_perfumes', name: 'Pregled parfumov', description: 'Lahko si ogleda parfume', category: 'Parfumi' },
        { id: 'add_perfumes', name: 'Dodajanje parfumov', description: 'Lahko doda nove parfume', category: 'Parfumi' },
        { id: 'delete_perfumes', name: 'Brisanje parfumov', description: 'Lahko briše parfume', category: 'Parfumi' },
        
        // Parfumi - podrobne operacije
        { id: 'edit_perfumes', name: 'Urejanje parfumov', description: 'Lahko ureja osnovne podatke parfumov', category: 'Parfumi' },
        { id: 'edit_perfume_names', name: 'Urejanje imen parfumov', description: 'Lahko ureja imena parfumov', category: 'Parfumi' },
        { id: 'edit_perfume_inci', name: 'Urejanje INCI sestave', description: 'Lahko ureja INCI sestavo parfumov', category: 'Parfumi' },
        { id: 'edit_perfume_stock', name: 'Urejanje zaloge', description: 'Lahko spreminja status zaloge parfumov', category: 'Parfumi' },
        { id: 'edit_perfume_sync', name: 'Urejanje sinhronizacije', description: 'Lahko vklopi/izklopi Shopify sinhronizacijo', category: 'Parfumi' },
        { id: 'edit_perfume_shopify', name: 'Urejanje Shopify podatkov', description: 'Lahko ureja Shopify ID in metafields', category: 'Parfumi' },
        
        // Proizvajalci
        { id: 'view_proizvajalci', name: 'Pregled proizvajalcev', description: 'Lahko si ogleda proizvajalce', category: 'Proizvajalci' },
        { id: 'edit_proizvajalci', name: 'Urejanje proizvajalcev', description: 'Lahko ureja proizvajalce', category: 'Proizvajalci' },
        { id: 'add_proizvajalci', name: 'Dodajanje proizvajalcev', description: 'Lahko doda nove proizvajalce', category: 'Proizvajalci' },
        { id: 'delete_proizvajalci', name: 'Brisanje proizvajalcev', description: 'Lahko briše proizvajalce', category: 'Proizvajalci' },
        
        // Uporabniki
        { id: 'view_users', name: 'Pregled uporabnikov', description: 'Lahko si ogleda uporabnike', category: 'Uporabniki' },
        { id: 'edit_users', name: 'Urejanje uporabnikov', description: 'Lahko ureja uporabnike', category: 'Uporabniki' },
        { id: 'add_users', name: 'Dodajanje uporabnikov', description: 'Lahko doda nove uporabnike', category: 'Uporabniki' },
        { id: 'delete_users', name: 'Brisanje uporabnikov', description: 'Lahko briše uporabnike', category: 'Uporabniki' },
        
        // Sistemske operacije
        { id: 'shopify_sync', name: 'Shopify sinhronizacija', description: 'Lahko sinhronizira s Shopify', category: 'Sistem' },
        { id: 'generate_pdf', name: 'Generiranje PDF', description: 'Lahko generira PDF-je', category: 'Sistem' },
        { id: 'send_email', name: 'Pošiljanje emailov (ročno)', description: 'Lahko pošlje email iz zavihka Ročno pošiljanje & Tisk', category: 'Sistem' },
        { id: 'send_auto_declarations', name: 'Pošiljanje deklaracij (auto)', description: 'Lahko generira/ponovno pošlje iz seznama naročil', category: 'Sistem' },
        { id: 'manual_declarations', name: 'Ročne deklaracije', description: 'Lahko pošlje ročne deklaracije', category: 'Sistem' },
        { id: 'print_declarations', name: 'Tiskanje deklaracij', description: 'Lahko natisne deklaracije', category: 'Sistem' },
        { id: 'upload_images', name: 'Nalaganje slik', description: 'Lahko naloži slike za naročila', category: 'Sistem' }
    ];

    async function loadUsers() {
        try {
            const spinnerEl = document.getElementById('users-spinner');
            const listEl = document.getElementById('users-list');
            if (spinnerEl) spinnerEl.style.display = 'flex';
            if (listEl) listEl.style.display = '';

            const response = await fetch('/api/users');
            if (response.status === 403) {
                console.warn('Ni dovoljenja za /api/users, ne prikazujem opozorila.');
                if (spinnerEl) spinnerEl.style.display = 'none';
                return;
            }
            if (!response.ok) {
                console.warn('API napaka pri nalaganju uporabnikov:', response.status);
                if (spinnerEl) spinnerEl.style.display = 'none';
                return;
            }
            const payload = await response.json();
            const users = (payload && (payload.data || payload)) || [];
            if (Array.isArray(users)) {
                displayUsers(users);
            } else {
                console.warn('Nepričakovan format uporabnikov:', users);
            }
            if (spinnerEl) spinnerEl.style.display = 'none';
        } catch (error) {
            console.warn('Napaka pri nalaganju uporabnikov (verjetno brez dovoljenj ali offline):', error);
            const spinnerEl = document.getElementById('users-spinner');
            if (spinnerEl) spinnerEl.style.display = 'none';
        }
    }

    // Funkcija za prikaz modala za urejanje dovoljenj
    window.editUserPermissions = function(userId, username) {
        document.getElementById('edit-permissions-user-id').value = userId;
        document.getElementById('edit-permissions-username').textContent = username;
        
        // Naloži trenutne dovoljenja uporabnika
        loadUserPermissions(userId);
        
        showModal('editPermissionsModal');
    }

    async function loadUserPermissions(userId) {
        try {
            const response = await fetch('/api/users');
            const users = await response.json();
            const user = users.find(u => u.id === userId);
            
            if (user) {
                // Nastavi vlogo
                document.getElementById('user-role').value = user.role || 'user';
                
                // Ustvari seznam dovoljenj po kategorijah
                const permissionsList = document.getElementById('permissions-list');
                permissionsList.innerHTML = '';
                
                // Grupiraj dovoljenja po kategorijah
                const permissionsByCategory = {};
                ALL_PERMISSIONS.forEach(permission => {
                    if (!permissionsByCategory[permission.category]) {
                        permissionsByCategory[permission.category] = [];
                    }
                    permissionsByCategory[permission.category].push(permission);
                });
                
                // Prikaži dovoljenja po kategorijah
                Object.keys(permissionsByCategory).forEach(category => {
                    // Dodaj naslov kategorije
                    const categoryHeader = document.createElement('div');
                    categoryHeader.className = 'mt-4 mb-2';
                    categoryHeader.innerHTML = `
                        <h4 class="text-sm font-semibold text-gray-800 border-b border-gray-200 pb-1">
                            ${category}
                        </h4>
                    `;
                    permissionsList.appendChild(categoryHeader);
                    
                    // Dodaj dovoljenja v tej kategoriji
                    permissionsByCategory[category].forEach(permission => {
                        const isChecked = user.permissions && user.permissions.includes(permission.id);
                        const isAdmin = user.role === 'admin';
                        console.log(`Permission ${permission.id}: ${isChecked ? 'checked' : 'unchecked'}, isAdmin: ${isAdmin}`);
                        
                        const div = document.createElement('div');
                        div.className = 'flex items-start space-x-3 ml-2';
                        div.innerHTML = `
                            <input type="checkbox" id="perm-${permission.id}" value="${permission.id}" 
                                   class="mt-1 h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded" 
                                   ${isChecked || isAdmin ? 'checked' : ''} 
                                   ${isAdmin ? 'disabled' : ''}>
                            <div class="flex-1">
                                <label for="perm-${permission.id}" class="block text-sm font-medium ${isAdmin ? 'text-gray-500' : 'text-gray-700'} cursor-pointer">
                                    ${permission.name}
                                    ${isAdmin ? '<span class="text-xs text-gray-400 ml-1">(admin)</span>' : ''}
                                </label>
                                <p class="text-xs text-gray-500">${permission.description}</p>
                            </div>
                        `;
                        permissionsList.appendChild(div);
                    });
                });
            }
        } catch (error) {
            console.error('Napaka pri nalaganju dovoljenj:', error);
            showToast('Napaka pri nalaganju dovoljenj', 'danger');
        }
    }

    // Funkcija za preverjanje dovoljenj za gumbe
    function updateButtonPermissions() {
        console.log('updateButtonPermissions() klicana');
        
        // Gumb za shranjevanje parfuma
        const savePerfumeButton = document.getElementById('save-perfume-button');
        if (savePerfumeButton) {
            // Dovoli prikaz gumba, če ima uporabnik polno urejanje ali delna dovoljenja (zaloga/sync)
            const canEditFull = hasUserPermission('edit_perfumes');
            const canEditStock = hasUserPermission('edit_perfume_stock');
            const canEditSync = hasUserPermission('edit_perfume_sync');
            const canShowSave = canEditFull || canEditStock || canEditSync;
            savePerfumeButton.style.display = canShowSave ? 'inline-flex' : 'none';
            console.log('Save perfume button visibility:', canShowSave);
        }
        
        // Gumb za sinhronizacijo s Shopify
        const syncSwitch = document.getElementById('sinhroniziraj-s-shopify');
        if (syncSwitch) {
            const canEditSync = hasUserPermission('edit_perfume_sync');
            syncSwitch.disabled = !canEditSync;
            syncSwitch.parentElement.style.opacity = canEditSync ? '1' : '0.5';
            // Onemogoči interakcije (tudi z labelo) ko ni dovoljenja
            const syncLabel = document.querySelector('label[for="sinhroniziraj-s-shopify"]');
            const syncWrapper = syncSwitch.parentElement;
            if (!canEditSync) {
                // Popoln lock: brez pointer dogodkov in fokusiranja
                if (syncWrapper) syncWrapper.style.pointerEvents = 'none';
                if (syncLabel) {
                    syncLabel.style.pointerEvents = 'none';
                    syncLabel.classList.remove('cursor-pointer');
                    syncLabel.classList.add('cursor-not-allowed');
                }
                syncSwitch.tabIndex = -1;
            } else {
                if (syncWrapper) syncWrapper.style.pointerEvents = 'auto';
                if (syncLabel) {
                    syncLabel.style.pointerEvents = 'auto';
                    syncLabel.classList.add('cursor-pointer');
                    syncLabel.classList.remove('cursor-not-allowed');
                }
                syncSwitch.tabIndex = 0;
            }
            console.log('Sync switch enabled:', canEditSync);
        }
        
        // Gumb za zalogo
        const stockSwitch = document.getElementById('na-zalogi-switch');
        if (stockSwitch) {
            const canEditStock = hasUserPermission('edit_perfume_stock');
            stockSwitch.disabled = !canEditStock;
            stockSwitch.parentElement.style.opacity = canEditStock ? '1' : '0.5';
            console.log('Stock switch enabled:', canEditStock);
        }
        
        // Polja za urejanje
        const editFields = ['product-no', 'ime-parfuma', 'sestava-inci'];
        editFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                const canEdit = hasUserPermission('edit_perfumes');
                field.disabled = !canEdit;
                field.style.opacity = canEdit ? '1' : '0.5';
                console.log(`Field ${fieldId} enabled:`, canEdit);
            }
        });
        
        // Select za proizvajalca
        const proizvajalecSelect = document.getElementById('proizvajalec-id');
        if (proizvajalecSelect) {
            const canEdit = hasUserPermission('edit_perfumes');
            proizvajalecSelect.disabled = !canEdit;
            proizvajalecSelect.style.opacity = canEdit ? '1' : '0.5';
            console.log('Proizvajalec select enabled:', canEdit);
        }

        // Navodila admin tools (samo admin oz. uporabnik z edit_users)
        const adminTools = document.getElementById('navodila-admin-tools');
        if (adminTools) {
            const canManage = hasUserPermission('edit_users');
            adminTools.style.display = canManage ? 'flex' : 'none';
        }
    }

    // Funkcija za shranjevanje dovoljenj
    window.submitEditPermissions = async function() {
        const userId = document.getElementById('edit-permissions-user-id').value;
        const role = document.getElementById('user-role').value;
        
        console.log('=== SUBMIT EDIT PERMISSIONS ===');
        console.log('User ID:', userId);
        console.log('Role:', role);
        
        // Zberi izbrana dovoljenja
        const selectedPermissions = [];
        ALL_PERMISSIONS.forEach(permission => {
            const checkbox = document.getElementById(`perm-${permission.id}`);
            if (checkbox && checkbox.checked) {
                selectedPermissions.push(permission.id);
                console.log(`Selected permission: ${permission.id}`);
            }
        });
        
        console.log('Selected permissions before admin check:', selectedPermissions);
        
        // Če je uporabnik admin, dodaj vsa dovoljenja
        if (role === 'admin') {
            console.log('User is admin, adding all permissions');
            ALL_PERMISSIONS.forEach(permission => {
                if (!selectedPermissions.includes(permission.id)) {
                    selectedPermissions.push(permission.id);
                    console.log(`Added admin permission: ${permission.id}`);
                }
            });
        }
        
        console.log('Final selected permissions:', selectedPermissions);
        
        const requestBody = {
            role: role,
            permissions: selectedPermissions
        };
        
        console.log('Request body:', requestBody);
        
        try {
            const response = await fetch(`/api/users/${userId}/permissions`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            
            console.log('Response status:', response.status);
            console.log('Response ok:', response.ok);
            
            const result = await response.json();
            console.log('Response result:', result);
            
            if (response.ok) {
                showToast('Dovoljenja uspešno posodobljena', 'success');
                closeModal('editPermissionsModal');
                loadUsers(); // Osveži seznam uporabnikov
            } else {
                showToast(result.error || 'Napaka pri posodabljanju dovoljenj', 'danger');
            }
        } catch (error) {
            console.error('Napaka pri posodabljanju dovoljenj:', error);
            showToast('Napaka pri posodabljanju dovoljenj', 'danger');
        }
    }
    function displayUsers(users) {
        const tbody = document.getElementById('users-table-body');
        if (!tbody) return;
        if (!Array.isArray(users) || users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="px-6 py-6 text-center text-sm text-gray-500">Ni uporabnikov za prikaz.</td>
                </tr>`;
            return;
        }

        tbody.innerHTML = users.map(user => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${user.username}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${user.first_name}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${user.last_name}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${user.email || '-'}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                        ${user.is_active ? 'Aktiven' : 'Neaktiven'}
                    </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    <div class="flex flex-col space-y-1">
                        <span class="inline-flex items-center px-2 py-1 rounded text-xs font-medium ${user.role === 'admin' ? 'bg-purple-100 text-purple-800' : 'bg-blue-100 text-blue-800'}">
                            ${user.role === 'admin' ? 'Admin' : 'Uporabnik'}
                        </span>
                        ${user.permissions && user.permissions.length > 0 ? 
                            `<span class="text-xs text-gray-600">${user.permissions.length} dovoljenj</span>` : 
                            '<span class="text-xs text-gray-400">Brez dovoljenj</span>'
                        }
                    </div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${user.created_at ? new Date(user.created_at).toLocaleDateString('sl-SI') : '-'}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    <div class="flex items-center space-x-2">
                        <input type="text" inputmode="numeric" pattern="\\d*" maxlength="6"
                               class="w-20 px-2 py-1 border border-gray-300 rounded-md text-sm"
                               id="user-pin-${user.id}" value="${user.kiosk_pin_plain || ''}" placeholder="PIN">
                        <button class="px-2 py-1 text-xs border border-blue-300 text-blue-700 bg-blue-50 rounded-md hover:bg-blue-100"
                                onclick="saveUserPin(${user.id})">Shrani</button>
                    </div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    <div class="flex items-center space-x-2">
                        <input type="color" class="w-8 h-8 border border-gray-300 rounded"
                               id="user-color-${user.id}" value="${user.color_hex || '#cccccc'}">
                        <button class="px-2 py-1 text-xs border border-blue-300 text-blue-700 bg-blue-50 rounded-md hover:bg-blue-100"
                                onclick="saveUserColor(${user.id})">Shrani</button>
                    </div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <div class="flex space-x-2">
                        <button class="inline-flex items-center px-3 py-2 border border-blue-300 rounded-lg text-sm font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors duration-200" onclick="changeUserPassword(${user.id}, '${user.username}')">
                            <i class="bi bi-key mr-2"></i> Spremeni geslo
                        </button>
                        <button class="inline-flex items-center px-3 py-2 border border-green-300 rounded-lg text-sm font-medium text-green-700 bg-green-50 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 transition-colors duration-200" onclick="editUserPermissions(${user.id}, '${user.username}')">
                            <i class="bi bi-shield-check mr-2"></i> Dovoljenja
                        </button>
                        ${user.username !== 'admin' ? 
                            `<button class="inline-flex items-center px-3 py-2 border border-red-300 rounded-lg text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors duration-200" onclick="deleteUser(${user.id})">
                                <i class="bi bi-trash mr-2"></i> Izbriši
                            </button>` : 
                            '<span class="text-gray-400">Admin - ni mogoče izbrisati</span>'
                        }
                    </div>
                </td>
            </tr>
        `).join('');
    }

    // Funkcija za prikaz modala za dodajanje uporabnika (globalna)
    window.showAddUserModal = function() {
        console.log('=== showAddUserModal CALLED ===');
        const modalElement = document.getElementById('addUserModal');
        console.log('Modal element:', modalElement);
        
        showModal('addUserModal');
        console.log('Modal shown successfully');
    }

    window.saveUserPin = async function(userId) {
        const input = document.getElementById(`user-pin-${userId}`);
        if (!input) return;
        const pin = (input.value || '').trim();
        try {
            const response = await fetch(`/api/users/${userId}/kiosk-pin`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Napaka');
            showToast('PIN shranjen', 'success');
            await loadUsers();
        } catch (error) {
            showToast(error.message || 'Napaka pri shranjevanju PIN', 'danger');
        }
    }

    window.saveUserColor = async function(userId) {
        const input = document.getElementById(`user-color-${userId}`);
        if (!input) return;
        const color_hex = (input.value || '').trim();
        try {
            const response = await fetch(`/api/users/${userId}/color`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ color_hex })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Napaka');
            showToast('Barva shranjena', 'success');
            await loadUsers();
        } catch (error) {
            showToast(error.message || 'Napaka pri shranjevanju barve', 'danger');
        }
    }

    // Funkcija za preverjanje dovoljenj uporabnika
    function hasUserPermission(permission) {
        console.log(`hasUserPermission('${permission}') klicana`);
        // Poskusi inicializirati currentUser iz localStorage, če še ni nastavljen (da ikone/gumbi ne manjkajo pri prvem renderju)
        if (!currentUser) {
            try {
                const stored = localStorage.getItem('currentUser');
                if (stored) {
                    currentUser = JSON.parse(stored);
                }
            } catch (_) { /* ignore */ }
        }

        console.log('currentUser:', currentUser);
        console.log('currentUser.permissions:', currentUser?.permissions);
        console.log('currentUser.role:', currentUser?.role);
        console.log('currentUser.permissions type:', typeof currentUser?.permissions);
        console.log('currentUser.permissions length:', currentUser?.permissions?.length);
        
        // Admin ima vedno vsa dovoljenja (po vlogi ali uporabniškem imenu)
        if (currentUser && (currentUser.role === 'admin' || currentUser.username === 'admin')) {
            console.log(`hasUserPermission('${permission}'): true - admin user`);
            return true;
        }
        
        if (!currentUser || !currentUser.permissions) {
            console.log(`hasUserPermission('${permission}'): false - no user or permissions`);
            return false;
        }
        
        // Preveri, ali je permissions array
        if (!Array.isArray(currentUser.permissions)) {
            console.log(`hasUserPermission('${permission}'): false - permissions is not an array`);
            return false;
        }
        
        const hasPermission = currentUser.permissions.includes(permission);
        console.log(`hasUserPermission('${permission}'): ${hasPermission}`);
        return hasPermission;
    }

    // Funkcija za skrivanje/pokazovanje zavihkov glede na dovoljenja
    async function updateTabVisibility() {
        console.log('updateTabVisibility() klicana');
        console.log('currentUser:', currentUser);
        
        // Če currentUser nima permissions ali so prazna, poskusi osvežiti podatke
        if (currentUser && (!Array.isArray(currentUser.permissions) || currentUser.permissions.length === 0)) {
            console.log('Current user nima permissions, osvežujem podatke...');
            const refreshed = await refreshCurrentUser();
            if (refreshed) {
                console.log('Podatki osveženi, ponovno preverjam dovoljenja...');
            }
        }
        
        const globalActionsTab = document.getElementById('akcije-tab');
        const katalogTab = document.getElementById('katalog-tab');
        const parfumLookupTab = document.getElementById('parfum-lookup-tab');
        const usersTab = document.getElementById('users-tab');
        const emailLogsTab = document.getElementById('email-logs-tab');
        const navodilaTab = document.getElementById('navodila-tab');
        const navodilaPanel = document.getElementById('navodila-panel');
        const searchSynonymsTab = document.getElementById('search-synonyms-tab');
        const searchSynonymsPanel = document.getElementById('search-synonyms-panel');
        
        console.log('Tabs found:', { globalActionsTab: !!globalActionsTab, katalogTab: !!katalogTab, usersTab: !!usersTab, emailLogsTab: !!emailLogsTab, navodilaTab: !!navodilaTab });

        // Navodila: vedno vidno za prijavljene uporabnike
        if (navodilaTab) {
            if (currentUser && currentUser.username) {
                navodilaTab.style.display = '';
                if (navodilaPanel) navodilaPanel.style.display = '';
            } else {
                navodilaTab.style.display = 'none';
                if (navodilaPanel) navodilaPanel.style.display = 'none';
            }
        }
        
        // Skrij "Globalne akcije" – pokaži, če ima view_admin_tabs ali view_global_actions
        if (globalActionsTab) {
            const canShowGlobal = hasUserPermission('view_admin_tabs') || hasUserPermission('view_global_actions');
            console.log('Global permissions check:', {
                view_admin_tabs: hasUserPermission('view_admin_tabs'),
                view_global_actions: hasUserPermission('view_global_actions'),
                shopify_sync: hasUserPermission('shopify_sync'),
                generate_pdf: hasUserPermission('generate_pdf'),
                send_email: hasUserPermission('send_email'),
                canShowGlobal
            });

            const globalActionsPanel = document.getElementById('akcije-panel');
            if (!canShowGlobal) {
                globalActionsTab.style.display = 'none';
                if (globalActionsPanel) globalActionsPanel.style.display = 'none';
                console.log('Global actions tab hidden');
            } else {
                globalActionsTab.style.display = 'block';
                if (globalActionsPanel) globalActionsPanel.style.display = '';
                console.log('Global actions tab shown');
            }
        }

        // Skrij "Katalog" če nima dovoljenja za parfume
        if (katalogTab) {
            const canViewPerfumes = hasUserPermission('view_perfumes');
            if (!canViewPerfumes) {
                katalogTab.style.display = 'none';
                console.log('Katalog tab hidden');
            } else {
                katalogTab.style.display = '';
            }
        }

        // Skrij "Iskalec parfumov" če nima dovoljenja za parfume
        if (parfumLookupTab) {
            const canViewPerfumes = hasUserPermission('view_perfumes');
            if (!canViewPerfumes) {
                parfumLookupTab.style.display = 'none';
                console.log('Perfume lookup tab hidden');
            } else {
                parfumLookupTab.style.display = '';
            }
        }
        
        // Skrij "Uporabniki" – videno le z dovoljenjem za admin zavihke
        if (usersTab) {
            const canShowUsersTab = hasUserPermission('view_admin_tabs');
            if (!canShowUsersTab) {
                usersTab.style.display = 'none';
                console.log('Users tab hidden');
            } else {
                usersTab.style.display = 'block';
                console.log('Users tab shown');
            }
        }

        // Skrij "Search sinonimi" – videno le z dovoljenjem za urejanje parfumov
        if (searchSynonymsTab) {
            const canShowSearchSynonyms = hasUserPermission('edit_perfumes') || hasUserPermission('view_admin_tabs');
            if (!canShowSearchSynonyms) {
                searchSynonymsTab.style.display = 'none';
                if (searchSynonymsPanel) searchSynonymsPanel.style.display = 'none';
                console.log('Search synonyms tab hidden');
            } else {
                searchSynonymsTab.style.display = 'block';
                if (searchSynonymsPanel) searchSynonymsPanel.style.display = '';
                console.log('Search synonyms tab shown');
            }
        }

        // In users panel, only show list, hide management buttons without manage_users
        const canManageUsers = hasUserPermission('manage_users');
        const addUserBtn = document.getElementById('add-user-btn');
        if (addUserBtn) addUserBtn.style.display = canManageUsers ? '' : 'none';
        
        // Force-hide legacy Email Logs and show new Logs tab
        if (emailLogsTab) { emailLogsTab.style.display = 'none'; emailLogsTab.setAttribute('aria-hidden','true'); }
        const emailLogsPanel = document.getElementById('email-logs-panel');
        if (emailLogsPanel) { emailLogsPanel.style.display = 'none'; emailLogsPanel.setAttribute('aria-hidden','true'); }
        const logsTab = document.getElementById('logs-tab');
        if (logsTab) { logsTab.style.display = ''; }
        const logsPanel = document.getElementById('logs-panel');
        if (logsPanel && !logsPanel.classList.contains('active')) { /* keep hidden by default, shown on click */ }
        
        // Posodobi dovoljenja za gumbe
        updateButtonPermissions();
    }

    async function addUser() {
        console.log('=== addUser FUNCTION CALLED ===');
        
        const username = document.getElementById('username').value.trim();
        const firstName = document.getElementById('first-name').value.trim();
        const lastName = document.getElementById('last-name').value.trim();
        const email = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value.trim();

        console.log('Form data:', { username, firstName, lastName, email, password: password ? '***' : 'not set' });

        if (!username || !firstName || !lastName) {
            showToast('Prosimo, izpolnite vsa obvezna polja', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: username,
                    first_name: firstName,
                    last_name: lastName,
                    email: email || null,
                    password: password || null
                })
            });

            const result = await response.json();

            if (result.success) {
                // Prikaži geslo uporabniku
                const passwordMessage = result.password ? `Geslo: ${result.password}` : '';
                showToast(`Uporabnik uspešno dodan. ${passwordMessage}`, 'success');
                
                // Če je geslo nastavljeno, prikaži modal z geslom
                if (result.password) {
                    showPasswordModal(result.password, username);
                }
                
                closeModal('addUserModal');
                document.getElementById('add-user-form').reset();
                await loadUsers();
            } else {
                showToast(`Napaka: ${result.error}`, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri dodajanju uporabnika:', error);
            showToast('Napaka pri dodajanju uporabnika', 'danger');
        }
    }

    // Uvozi MK račune (zadnjih N dni)
    async function mkSyncBills() {
        try {
            const btn = document.getElementById('mk-sync-bills-btn');
            const daysInput = document.getElementById('mk-sync-days');
            const typeSel = document.getElementById('mk-sync-doc-type');
            if (!btn) return;
            btn.disabled = true;
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i> Uvažam...';
            const days = Math.max(1, parseInt(daysInput?.value || '1', 10));
            const doc_types = (typeSel && typeSel.value) ? [typeSel.value] : undefined;
            const resp = await fetch('/api/mk/sync-bills', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days, doc_types })
            });
            const data = await resp.json();
            if (data && data.success && data.started) {
                showToast('Uvoz zagnan v ozadju. Uporabi gumb "Status uvoza" za spremljanje.', 'info');
            } else if (data && data.success) {
                showToast(`Uvoženih/posodobljenih računov: ${data.imported ?? 0}`, 'success');
            } else {
                showToast(`Napaka: ${data?.error || 'Neznana napaka'}`, 'danger');
            }
            btn.innerHTML = original;
            btn.disabled = false;
        } catch (e) {
            showToast('Napaka pri uvozu računov', 'danger');
            const btn = document.getElementById('mk-sync-bills-btn');
            if (btn) btn.disabled = false;
        }
    }

    async function mkSyncBillsStatus() {
        try {
            const btn = document.getElementById('mk-sync-status-btn');
            if (btn) { btn.disabled = true; setTimeout(()=>{btn.disabled=false}, 1500); }
            const resp = await fetch('/api/mk/sync-bills/status');
            const data = await resp.json();
            console.log('MK SYNC STATUS', data);
            if (data && data.success) {
                const s = data.status || {}; const p = data.progress || {};
                const byType = (s.details && s.details.by_type) || p.counts_by_type || {};
                const byTypeStr = Object.keys(byType).length ? ' | by_type=' + Object.entries(byType).map(([k,v])=>`${k}:${v}`).join(',') : '';
                showToast(`Status: ${s.status || 'n/a'} | phase=${p.phase || '-'} | imported=${(s.imported||s.details?.search_tail||0)}${byTypeStr} | cancelled=${data.cancelled?'da':'ne'}`, 'info');
            } else {
                showToast(`Napaka pri statusu: ${data?.error || 'neznano'}`, 'danger');
            }
        } catch (e) {
            showToast('Napaka pri branju statusa', 'danger');
        }
    }

    async function mkSyncBillsCancel() {
        try {
            const btn = document.getElementById('mk-sync-cancel-btn');
            if (btn) { btn.disabled = true; setTimeout(()=>{btn.disabled=false}, 1500); }
            const resp = await fetch('/api/mk/sync-bills/cancel', { method: 'POST' });
            const data = await resp.json();
            if (data && data.success) {
                showToast('Uvoz preklican. Ustavlja se ...', 'warning');
            } else {
                showToast(`Napaka pri preklicu: ${data?.error || 'neznano'}`, 'danger');
            }
        } catch (e) {
            showToast('Napaka pri preklicu', 'danger');
        }
    }

    // Registracija handlerja po DOM loadu in z delegacijo (za primer, ko je handler dodan po loadu)
    (function registerMkSyncHandler() {
        try {
            const mkBtn = document.getElementById('mk-sync-bills-btn');
            if (mkBtn && !mkBtn.dataset.bound) {
                mkBtn.addEventListener('click', mkSyncBills);
                mkBtn.dataset.bound = 'true';
            }
            const stBtn = document.getElementById('mk-sync-status-btn');
            if (stBtn && !stBtn.dataset.bound) {
                stBtn.addEventListener('click', mkSyncBillsStatus);
                stBtn.dataset.bound = 'true';
            }
            const cancelBtn = document.getElementById('mk-sync-cancel-btn');
            if (cancelBtn && !cancelBtn.dataset.bound) {
                cancelBtn.addEventListener('click', mkSyncBillsCancel);
                cancelBtn.dataset.bound = 'true';
            }
        } catch {}
        // Delegacija NI potrebna za te gumbe (da se ne sproži 2x)
    })();

    // ----- Logs panel -----
    (function registerLogsPanel(){
        async function loadLogs(){
            try {
                const cat = (document.getElementById('logs-category')?.value || '').trim();
                const lvl = (document.getElementById('logs-level')?.value || '').trim();
                const q = (document.getElementById('logs-q')?.value || '').trim();
                const params = new URLSearchParams();
                if (cat) params.set('category', cat);
                if (lvl) params.set('level', lvl);
                if (q) params.set('q', q);
                params.set('limit', '200');
                const resp = await fetch(`/api/logs?${params.toString()}`);
                const data = await resp.json();
                if (!data?.success) { showToast(`Napaka pri branju logov: ${data?.error||'neznano'}`, 'danger'); return; }
                const tbody = document.getElementById('logs-tbody'); if (!tbody) return;
                tbody.innerHTML = '';
                (data.rows||[]).forEach(r => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b';
                    const payload = typeof r.data === 'object' ? JSON.stringify(r.data) : (r.data || '');
                    let tsLocal = '';
                    try {
                        if (r.ts) {
                            const dt = new Date(r.ts);
                            tsLocal = new Intl.DateTimeFormat('sl-SI', { timeZone: 'Europe/Ljubljana', dateStyle: 'short', timeStyle: 'medium' }).format(dt);
                        }
                    } catch(_) { tsLocal = r.ts || ''; }
                    tr.innerHTML = `
                        <td class="px-3 py-2 whitespace-nowrap">${tsLocal}</td>
                        <td class="px-3 py-2">${r.category || ''}</td>
                        <td class="px-3 py-2">${r.level || ''}</td>
                        <td class="px-3 py-2">${r.message || ''}</td>
                        <td class="px-3 py-2 text-gray-600">${payload}</td>
                    `;
                    tbody.appendChild(tr);
                });
                showToast(`Prikazanih logov: ${data.count}`, 'info');
            } catch(e){ showToast('Napaka pri nalaganju logov', 'danger'); }
        }
        try {
            const btn = document.getElementById('logs-refresh');
            if (btn && !btn.dataset.bound){ btn.addEventListener('click', loadLogs); btn.dataset.bound='true'; }
            const cat = document.getElementById('logs-category'); if (cat && !cat.dataset.bound){ cat.addEventListener('change', loadLogs); cat.dataset.bound='true'; }
            const lvl = document.getElementById('logs-level'); if (lvl && !lvl.dataset.bound){ lvl.addEventListener('change', loadLogs); lvl.dataset.bound='true'; }
            const q = document.getElementById('logs-q'); if (q && !q.dataset.bound){ let t; q.addEventListener('input', ()=>{ clearTimeout(t); t=setTimeout(loadLogs, 400); }); q.dataset.bound='true'; }
            const logsTab = document.getElementById('logs-tab');
            if (logsTab && !logsTab.dataset.bound){ logsTab.addEventListener('click', ()=>{ const panel=document.getElementById('logs-panel'); if (panel) loadLogs(); }); logsTab.dataset.bound='true'; }
        } catch {}
    })();

    // ----- MK bills list panel -----
    (function registerMkBillsPanel(){
        async function loadMkBills(){
            try {
                const q = (document.getElementById('mk-bills-search')?.value || '').trim();
                const pub = (document.getElementById('mk-bills-published')?.value || '').trim();
                const dt = (document.getElementById('mk-bills-doc-type')?.value || '').trim();
                const params = new URLSearchParams();
                params.set('limit', '100');
                if (q) params.set('q', q);
                if (pub) params.set('published', pub);
                if (dt) params.set('doc_type', dt);
                const resp = await fetch(`/api/mk/bills?${params.toString()}`);
                const data = await resp.json();
                if (!data?.success) {
                    showToast(`Napaka pri branju računov: ${data?.error || 'neznano'}`, 'danger');
                    return;
                }
                const tbody = document.getElementById('mk-bills-tbody');
                if (!tbody) return;
                tbody.innerHTML = '';
                (data.rows || []).forEach(r => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b hover:bg-indigo-50/40';
                    tr.innerHTML = `
                        <td class="px-3 py-2 whitespace-nowrap text-indigo-800">${r.mk_id || ''}</td>
                        <td class="px-3 py-2">${r.doc_type || ''}</td>
                        <td class="px-3 py-2">${r.title || ''}</td>
                        <td class="px-3 py-2">${r.buyer_order || ''}</td>
                        <td class="px-3 py-2">${r.count_code || ''}</td>
                        <td class="px-3 py-2">${r.publish_ts || ''}</td>
                        <td class="px-3 py-2">${r.total ?? ''}</td>
                    `;
                    tbody.appendChild(tr);
                });
                showToast(`Najdenih računov: ${data.total}`, 'success');
            } catch(e){
                showToast('Napaka pri nalaganju računov', 'danger');
            }
        }

        function togglePanel(){
            const panel = document.getElementById('mk-bills-panel');
            if (!panel) return;
            const wasHidden = panel.classList.contains('hidden');
            panel.classList.toggle('hidden');
            if (wasHidden) {
                loadMkBills();
                // Scroll into view for desktop
                setTimeout(()=>{ panel.scrollIntoView({behavior:'smooth', block:'start'}); }, 50);
            }
        }

        try {
            const openBtn = document.getElementById('mk-bills-open-btn');
            if (openBtn && !openBtn.dataset.bound) {
                openBtn.addEventListener('click', togglePanel);
                openBtn.dataset.bound = 'true';
            }
            const refreshBtn = document.getElementById('mk-bills-refresh');
            if (refreshBtn && !refreshBtn.dataset.bound) {
                refreshBtn.addEventListener('click', loadMkBills);
                refreshBtn.dataset.bound = 'true';
            }
            const search = document.getElementById('mk-bills-search');
            if (search && !search.dataset.bound) {
                let t; search.addEventListener('input', ()=>{ clearTimeout(t); t = setTimeout(loadMkBills, 400); });
                search.dataset.bound = 'true';
            }
            const published = document.getElementById('mk-bills-published');
            if (published && !published.dataset.bound) {
                published.addEventListener('change', loadMkBills);
                published.dataset.bound = 'true';
            }
            const docType = document.getElementById('mk-bills-doc-type');
            if (docType && !docType.dataset.bound) {
                docType.addEventListener('change', loadMkBills);
                docType.dataset.bound = 'true';
            }
        } catch {}
    })();

    // ----- Global action: Preveži serije -----
    (function registerRebindSeries(){
        async function runRebind(){
            try {
                const btn = document.getElementById('rebind-run');
                const vendor = (document.getElementById('rebind-vendor')?.value || '').trim();
                const oldNo = (document.getElementById('rebind-old')?.value || '').trim();
                const newNo = (document.getElementById('rebind-new')?.value || '').trim();
                if (!vendor || !oldNo || !newNo){
                    showToast('Vnesite dobavitelja, staro in novo številko.', 'warning');
                    return;
                }
                btn.disabled = true; const original = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i> Prevezujem...';
                const resp = await fetch('/api/serije/rebind', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vendor, old_product_no: oldNo, new_product_no: newNo })
                });
                const data = await resp.json();
                if (data?.success){
                    showToast(`Prevezanih serij: ${data.moved}`, 'success');
                } else {
                    showToast(`Napaka: ${data?.error || 'neznano'}`, 'danger');
                }
                btn.innerHTML = original; btn.disabled = false;
            } catch(e){
                showToast('Napaka pri prevezavi', 'danger');
                const btn = document.getElementById('rebind-run'); if (btn) btn.disabled = false;
            }
        }
        try {
            const btn = document.getElementById('rebind-run');
            if (btn && !btn.dataset.bound){ btn.addEventListener('click', runRebind); btn.dataset.bound='true'; }
        } catch {}
    })();

    // ----- Global action: Manual order -----
    (function registerManualOrder(){
        const items = [];
        function render(){
            const tbody = document.getElementById('manord-items'); if (!tbody) return;
            tbody.innerHTML = '';
            items.forEach(it => {
                const tr = document.createElement('tr');
                tr.className = 'border-b';
                tr.innerHTML = `
                    <td class="px-3 py-2">${it.product_no}</td>
                    <td class="px-3 py-2">${it.vendor}</td>
                    <td class="px-3 py-2 text-right">${it.quantity}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        function addItem(){
            const pn = (document.getElementById('manord-item-pn')?.value || '').trim();
            const vendor = (document.getElementById('manord-item-vendor')?.value || '').trim();
            const qty = Math.max(1, parseInt(document.getElementById('manord-item-qty')?.value||'1',10));
            if (!pn || !vendor){ showToast('Vnesite product št. in dobavitelja', 'warning'); return; }
            items.push({ product_no: pn, vendor, quantity: qty });
            render();
            document.getElementById('manord-item-pn').value='';
            document.getElementById('manord-item-qty').value='1';
            document.getElementById('manord-item-pn').focus();
        }
        async function createOrder(){
            try{
                if (items.length === 0){ showToast('Dodajte vsaj en artikel', 'warning'); return; }
                const name = (document.getElementById('manord-name')?.value || '').trim();
                const email = (document.getElementById('manord-email')?.value || '').trim();
                const cc = (document.getElementById('manord-country')?.value || 'SI').trim();
                const ch = (document.getElementById('manord-channel')?.value || 'manual').trim();
                const btn = document.getElementById('manord-create'); btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i> Ustvarjam...';
                const mkid = (document.getElementById('manord-mk-id')?.value || '').trim();
                const resp = await fetch('/api/orders/manual', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_name: name, customer_email: email, country_code: cc, channel: ch, items, mk_id: mkid || undefined }) });
                const data = await resp.json();
                if (data?.success){
                    showToast(`Naročilo ustvarjeno: ${data.order_number}`, 'success');
                    items.length = 0; render();
                } else {
                    showToast(`Napaka: ${data?.error || 'neznano'}`, 'danger');
                }
                btn.innerHTML = orig; btn.disabled = false;
            }catch(e){
                showToast('Napaka pri ustvarjanju naročila', 'danger');
                const btn = document.getElementById('manord-create'); if (btn) btn.disabled=false;
            }
        }
        try{
            const addBtn = document.getElementById('manord-add-item'); if (addBtn && !addBtn.dataset.bound){ addBtn.addEventListener('click', addItem); addBtn.dataset.bound='true'; }
            const createBtn = document.getElementById('manord-create'); if (createBtn && !createBtn.dataset.bound){ createBtn.addEventListener('click', createOrder); createBtn.dataset.bound='true'; }
        }catch{}
    })();

    // ----- Global action: Import MK order by mk_id -----
    (function registerMkImport(){
        async function runImport(){
            try {
                const btn = document.getElementById('mk-import-run');
                const mkid = (document.getElementById('mk-import-id')?.value || '').trim();
                if (!mkid){ showToast('Vnesite mk_id', 'warning'); return; }
                btn.disabled = true; const original = btn.innerHTML; btn.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i> Uvažam...';
                const resp = await fetch('/api/mk/import-order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mk_id: mkid }) });
                const data = await resp.json();
                if (data?.success){
                    showToast(`Naročilo uvoženo: ${data.order_number}`, 'success');
                } else {
                    showToast(`Napaka uvoza: ${data?.error || 'neznano'}`, 'danger');
                }
                btn.innerHTML = original; btn.disabled = false;
            } catch(e) {
                showToast('Napaka pri uvozu naročila', 'danger');
                const btn = document.getElementById('mk-import-run'); if (btn) btn.disabled=false;
            }
        }
        try{
            const btn = document.getElementById('mk-import-run'); if (btn && !btn.dataset.bound){ btn.addEventListener('click', runImport); btn.dataset.bound='true'; }
        }catch{}
    })();

    function showPasswordModal(password, username) {
        const modalHTML = `
            <div id="passwordModal" style="display: block; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0, 0, 0, 0.5); z-index: 9999;">
                <div style="position: relative; top: 80px; margin: 0 auto; max-width: 400px; width: 90%; background: white; border-radius: 8px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);">
                    <div style="padding: 16px 20px; border-bottom: 1px solid #e5e7eb; background: linear-gradient(to right, #eff6ff, #e0e7ff); border-radius: 8px 8px 0 0;">
                        <div style="display: flex; align-items: center; justify-content: space-between;">
                            <h5 style="margin: 0; font-size: 16px; font-weight: 600; color: #111827; display: flex; align-items: center;">
                                <i class="bi bi-shield-lock" style="color: #2563eb; margin-right: 8px;"></i>
                                Geslo za ${username}
                            </h5>
                            <button type="button" onclick="closePasswordModal()" style="background: none; border: none; color: #9ca3af; cursor: pointer; padding: 4px; border-radius: 4px; transition: color 0.2s;" onmouseover="this.style.color='#4b5563'" onmouseout="this.style.color='#9ca3af'">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    </div>
                    <div style="padding: 16px 20px;">
                        <div style="background: linear-gradient(to right, #fef3c7, #fed7aa); border: 1px solid #fbbf24; border-radius: 8px; padding: 12px; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);">
                            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                <i class="bi bi-exclamation-triangle" style="color: #d97706; margin-right: 8px;"></i>
                                <span style="font-size: 14px; font-weight: 600; color: #92400e;">Zapomnite si geslo!</span>
                            </div>
                            <div style="background: white; border: 1px solid #f59e0b; border-radius: 6px; padding: 8px; margin-bottom: 8px;">
                                <p style="font-size: 12px; color: #374151; margin: 0 0 4px 0;">Geslo:</p>
                                <p class="password-text" style="font-size: 16px; font-family: monospace; font-weight: bold; color: #111827; background: #f9fafb; padding: 8px; border-radius: 4px; border: 1px solid #d1d5db; margin: 0; cursor: pointer; user-select: all;" onclick="copyPassword('${password}')">${password}</p>
                            </div>
                            <p style="font-size: 12px; color: #b45309; margin: 0;">
                                <i class="bi bi-info-circle" style="margin-right: 4px;"></i>
                                Prikaže se samo enkrat. Kliknite na geslo za kopiranje.
                            </p>
                        </div>
                    </div>
                    <div style="padding: 16px 20px; border-top: 1px solid #e5e7eb; background: #f9fafb; border-radius: 0 0 8px 8px; display: flex; justify-content: flex-end;">
                        <button type="button" onclick="closePasswordModal()" style="padding: 8px 16px; background: #2563eb; border: 1px solid transparent; border-radius: 6px; font-size: 14px; font-weight: 500; color: white; cursor: pointer; transition: background-color 0.2s; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);" onmouseover="this.style.backgroundColor='#1d4ed8'" onmouseout="this.style.backgroundColor='#2563eb'">
                            <i class="bi bi-check-lg" style="margin-right: 4px;"></i>
                            Razumem
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Odstrani obstoječi modal, če obstaja
        const existingModal = document.getElementById('passwordModal');
        if (existingModal) {
            existingModal.remove();
        }
        
        // Dodaj nov modal
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        
        // Preprost prikaz modala brez Bootstrap konstruktora
        const modalEl = document.getElementById('passwordModal');
        if (modalEl) modalEl.style.display = 'block';
        
        // Odstrani modal iz DOM-a po zaprtju
        // Zapiranje ob kliku izven vsebine
        modalEl.addEventListener('click', function(ev) {
            if (ev.target.id === 'passwordModal') {
                closePasswordModal();
            }
        });
        
        // Dodaj funkcionalnost za kopiranje gesla
        const passwordElement = document.querySelector('#passwordModal .password-text');
        if (passwordElement) {
            passwordElement.addEventListener('click', function() {
                navigator.clipboard.writeText(password).then(() => {
                    showToast('Geslo kopirano v odložišče', 'success');
                }).catch(() => {
                    showToast('Napaka pri kopiranju gesla', 'danger');
                });
            });
        }
    }

    // Globalne funkcije za modal gesla
    window.closePasswordModal = function() {
        const modal = document.getElementById('passwordModal');
        if (modal) modal.remove();
    }
    window.copyPassword = function(pwd) {
        try {
            navigator.clipboard.writeText(pwd);
            showToast('Geslo kopirano v odložišče', 'success');
        } catch (e) {
            console.warn('Copy failed', e);
        }
    }

    // Funkcija za zapiranje modalnega okna
    window.closePasswordModal = function() {
        const modal = document.getElementById('passwordModal');
        if (modal) {
            modal.remove();
        }
        
        // Zapri tudi addUserModal
        const addUserModal = document.getElementById('addUserModal');
        if (addUserModal) {
            addUserModal.classList.add('hidden');
            document.body.style.overflow = 'auto';
        }
        
        // Osveži seznam uporabnikov
        loadUsers();
    }

    // Funkcija za kopiranje gesla
    window.copyPassword = function(password) {
        navigator.clipboard.writeText(password).then(() => {
            showToast('Geslo kopirano v odložišče', 'success');
        }).catch(() => {
            showToast('Napaka pri kopiranju gesla', 'danger');
        });
    }

    // Funkcija za preklop e-mail načina
    window.toggleEmailMode = async function() {
        const button = document.getElementById('toggle-email-mode-btn');
        const textSpan = document.getElementById('email-mode-text');
        
        if (button.disabled) return;
        
        button.disabled = true;
        const originalText = button.innerHTML;
        button.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i> Preklapljam...';
        
        try {
            const response = await fetch('/api/toggle-email-mode', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Posodobi UI
                if (result.test_mode === 'true') {
                    textSpan.textContent = 'Test način';
                    button.className = button.className.replace('bg-green-600 hover:bg-green-700 bg-orange-600 hover:bg-orange-700', 'bg-purple-600 hover:bg-purple-700');
                    showToast('E-mail način preklopljen na TEST (samo admin)', 'success');
                } else if (result.test_mode === 'false') {
                    textSpan.textContent = 'Produkcija';
                    button.className = button.className.replace('bg-purple-600 hover:bg-purple-700 bg-orange-600 hover:bg-orange-700', 'bg-green-600 hover:bg-green-700');
                    showToast('E-mail način preklopljen na PRODUKCIJA (samo customer)', 'success');
                } else {
                    textSpan.textContent = 'Oba (admin + customer)';
                    button.className = button.className.replace('bg-purple-600 hover:bg-purple-700 bg-green-600 hover:bg-green-700', 'bg-orange-600 hover:bg-orange-700');
                    showToast('E-mail način preklopljen na OBA (admin + customer)', 'success');
                }
            } else {
                showToast(`Napaka: ${result.error}`, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri preklopu e-mail načina:', error);
            showToast('Napaka pri preklopu e-mail načina', 'danger');
        } finally {
            button.disabled = false;
            button.innerHTML = originalText;
        }
    }

    // Funkcija za nalaganje trenutnega e-mail načina
    window.loadEmailMode = async function() {
        try {
            const response = await fetch('/api/email-mode', {
                method: 'GET'
            });
            
            const result = await response.json();
            
            if (result.success) {
                const button = document.getElementById('toggle-email-mode-btn');
                const textSpan = document.getElementById('email-mode-text');
                
                if (result.test_mode === 'true') {
                    textSpan.textContent = 'Test način';
                    button.className = button.className.replace('bg-green-600 hover:bg-green-700 bg-orange-600 hover:bg-orange-700', 'bg-purple-600 hover:bg-purple-700');
                } else if (result.test_mode === 'false') {
                    textSpan.textContent = 'Produkcija';
                    button.className = button.className.replace('bg-purple-600 hover:bg-purple-700 bg-orange-600 hover:bg-orange-700', 'bg-green-600 hover:bg-green-700');
                } else {
                    textSpan.textContent = 'Oba (admin + customer)';
                    button.className = button.className.replace('bg-purple-600 hover:bg-purple-700 bg-green-600 hover:bg-green-700', 'bg-orange-600 hover:bg-orange-700');
                }
            }
        } catch (error) {
            console.error('Napaka pri nalaganju e-mail načina:', error);
        }
    }

    // Funkcija za nalaganje e-mail logov
    window.loadEmailLogs = async function() {
        try {
            const spinner = document.getElementById('email-logs-spinner');
            const tableBody = document.getElementById('email-logs-table-body');
            
            spinner.style.display = 'flex';
            tableBody.innerHTML = '';
            
            const response = await fetch('/api/email-logs', {
                method: 'GET'
            });
            
            const result = await response.json();
            
            if (result.success) {
                displayEmailLogs(result.logs);
            } else {
                showToast(`Napaka: ${result.error}`, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri nalaganju e-mail logov:', error);
            showToast('Napaka pri nalaganju e-mail logov', 'danger');
        } finally {
            document.getElementById('email-logs-spinner').style.display = 'none';
        }
    }

    // Funkcija za prikaz e-mail logov
    function displayEmailLogs(logs) {
        const tableBody = document.getElementById('email-logs-table-body');
        
        console.log('displayEmailLogs called with logs:', logs);
        
        if (logs.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="5" class="px-6 py-4 text-center text-gray-500">
                        Ni najdenih e-mail logov
                    </td>
                </tr>
            `;
            return;
        }
        
        tableBody.innerHTML = logs.map(log => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    ${log.order_number}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    <div>
                        <div class="font-medium">${log.email_recipient || 'N/A'}</div>
                        ${log.customer_email && log.customer_email !== log.email_recipient ? 
                            `<div class="text-xs text-gray-500">Original: ${log.customer_email}</div>` : ''}
                    </div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    ${log.email_sent_at ? new Date(log.email_sent_at).toLocaleString('sl-SI') : 'N/A'}
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Poslan
                    </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    ${log.order_number && log.order_number !== 'null' && log.order_number !== 'undefined' ? 
                        `<button class="text-blue-600 hover:text-blue-900" onclick="viewEmailDetails('${log.order_number}')">
                            <i class="bi bi-eye mr-1"></i> Ogled
                        </button>` : 
                        '<span class="text-gray-400">Ni podatkov</span>'
                    }
                </td>
            </tr>
        `).join('');
    }

    // Funkcija za ogled podrobnosti e-maila
    window.viewEmailDetails = async function(orderNumber) {
        try {
            console.log('viewEmailDetails called with orderNumber:', orderNumber, 'type:', typeof orderNumber);
            
            if (!orderNumber || orderNumber === 'null' || orderNumber === 'undefined' || orderNumber === '') {
                showToast('Ni podatkov o naročilu za ogled', 'warning');
                return;
            }
            
            // Odstrani # predpono, če obstaja
            const cleanOrderNumber = orderNumber.startsWith('#') ? orderNumber.substring(1) : orderNumber;
            console.log('Clean order number:', cleanOrderNumber);
            
            const response = await fetch(`/api/email-details/${cleanOrderNumber}`);
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || 'Napaka pri pridobivanju podrobnosti');
            }
            
            displayEmailDetails(result.email_details);
        } catch (error) {
            console.error('Napaka pri pridobivanju podrobnosti emaila:', error);
            showToast(`Napaka: ${error.message}`, 'danger');
        }
    }

    // Funkcija za prikaz podrobnosti emaila v modal
    function displayEmailDetails(emailDetails) {
        const modal = document.getElementById('emailDetailsModal');
        const content = document.getElementById('emailDetailsContent');
        
        if (!modal || !content) {
            showToast('Napaka pri prikazu modala', 'danger');
            return;
        }
        
        // Ustvari HTML vsebino
        const html = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <h4 class="font-semibold text-gray-900 mb-2">Osnovni podatki</h4>
                    <div class="space-y-2 text-sm">
                        <div><span class="font-medium">Naročilo:</span> ${emailDetails.order_number}</div>
                        <div><span class="font-medium">Status:</span> <span class="px-2 py-1 text-xs rounded ${emailDetails.status === 'fulfilled' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}">${emailDetails.status}</span></div>
                        <div><span class="font-medium">Država:</span> ${emailDetails.country_code}</div>
                        <div><span class="font-medium">Shopify ID:</span> ${emailDetails.shopify_order_id || 'N/A'}</div>
                    </div>
                </div>
                
                <div>
                    <h4 class="font-semibold text-gray-900 mb-2">Email podatki</h4>
                    <div class="space-y-2 text-sm">
                        <div><span class="font-medium">Prejemnik:</span> ${emailDetails.email_recipient}</div>
                        <div><span class="font-medium">Customer email:</span> ${emailDetails.customer_email || 'N/A'}</div>
                        <div><span class="font-medium">Poslano:</span> ${emailDetails.email_sent_at ? new Date(emailDetails.email_sent_at).toLocaleString('sl-SI') : 'N/A'}</div>
                        <div><span class="font-medium">Skupna cena:</span> ${emailDetails.total_price || 0} ${emailDetails.currency || 'EUR'}</div>
                    </div>
                </div>
            </div>
            
            <div class="mt-6">
                <h4 class="font-semibold text-gray-900 mb-2">Izdelki v naročilu</h4>
                ${emailDetails.line_items && emailDetails.line_items.length > 0 ? `
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Izdelek</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Količina</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Cena</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Tip</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Proizvajalec</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200">
                                ${emailDetails.line_items.map(item => `
                                    <tr>
                                        <td class="px-3 py-2 text-sm text-gray-900">${item.title}</td>
                                        <td class="px-3 py-2 text-sm text-gray-900">${item.quantity}</td>
                                        <td class="px-3 py-2 text-sm text-gray-900">${item.price} ${emailDetails.currency || 'EUR'}</td>
                                        <td class="px-3 py-2 text-sm text-gray-900">${item.product_type}</td>
                                        <td class="px-3 py-2 text-sm text-gray-900">${item.proizvajalec}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                ` : '<p class="text-gray-500 text-sm">Ni podatkov o izdelkih</p>'}
            </div>
        `;
        
        content.innerHTML = html;
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }

    // Funkcija za zapiranje modala za podrobnosti emaila
    window.closeEmailDetailsModal = function() {
        const modal = document.getElementById('emailDetailsModal');
        if (modal) {
            modal.classList.add('hidden');
            document.body.style.overflow = 'auto';
        }
    }

    // Funkcija za brisanje uporabnika (globalna)
    window.deleteUser = async function(userId) {
        if (!confirm('Ali ste prepričani, da želite izbrisati tega uporabnika?')) {
            return;
        }

        try {
            const response = await fetch(`/api/users/${userId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showToast('Uporabnik uspešno izbrisan', 'success');
                await loadUsers();
            } else {
                showToast(`Napaka: ${result.error}`, 'danger');
            }
        } catch (error) {
            console.error('Napaka pri brisanju uporabnika:', error);
            showToast('Napaka pri brisanju uporabnika', 'danger');
        }
    }

    // Funkcija za spreminjanje gesla uporabnika (globalna - admin flow)
    window.changeUserPassword = async function(userId, username) {
        // Prikaži modal za spreminjanje gesla
        const modal = document.getElementById('changePasswordModal');
        const userIdInput = document.getElementById('change-password-user-id');
        const usernameDisplay = document.getElementById('change-password-username');
        
        if (userIdInput && usernameDisplay) {
            userIdInput.value = userId;
            usernameDisplay.textContent = username;
        }
        
        if (modal) {
            modal.classList.remove('hidden');
        }
    }

    // Odpri modal za samostojno spremembo gesla (trenutni uporabnik)
    window.openSelfChangePassword = function() {
        const modal = document.getElementById('changePasswordModal');
        const usernameDisplay = document.getElementById('change-password-username');
        const userIdInput = document.getElementById('change-password-user-id');
        const currentRow = document.getElementById('current-password-row');
        if (!currentUser || !currentUser.username) {
            showToast('Niste prijavljeni.', 'danger');
            return;
        }
        if (usernameDisplay) usernameDisplay.textContent = currentUser.username;
        if (userIdInput) userIdInput.value = currentUser.id || '';
        if (currentRow) currentRow.style.display = '';
        if (modal) modal.classList.remove('hidden');
    }

    // Funkcija za pošiljanje spremembe gesla (admin menja komurkoli)
    window.submitChangePassword = async function() {
        const userId = document.getElementById('change-password-user-id').value;
        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;
        const button = document.getElementById('submit-change-password-btn');

        if (!newPassword || !confirmPassword) {
            showToast('Vsa polja so obvezna.', 'danger');
            return;
        }

        if (newPassword !== confirmPassword) {
            showToast('Novi gesli se ne ujemata.', 'danger');
            return;
        }

        if (newPassword.length < 6) {
            showToast('Geslo mora biti dolgo vsaj 6 znakov.', 'danger');
            return;
        }

        setButtonLoading(button, true, 'Spreminjam...');

        try {
            const response = await fetch('/api/admin/change-user-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: userId,
                    new_password: newPassword,
                    confirm_password: confirmPassword
                })
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Neznana napaka');
            
            showToast(result.message, 'success');
            closeChangePasswordModal();
        } catch (error) {
            showToast(`Napaka pri spreminjanju gesla: ${error.message}`, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    // Samostojna sprememba gesla (trenutni uporabnik)
    window.submitSelfChangePassword = async function() {
        const username = currentUser?.username;
        const currentPassword = document.getElementById('current-password')?.value || '';
        const newPassword = document.getElementById('new-password')?.value || '';
        const confirmPassword = document.getElementById('confirm-password')?.value || '';
        const button = document.getElementById('submit-change-password-btn');

        if (!username) {
            showToast('Niste prijavljeni.', 'danger');
            return;
        }
        if (!currentPassword || !newPassword || !confirmPassword) {
            showToast('Vsa polja so obvezna.', 'danger');
            return;
        }
        if (newPassword !== confirmPassword) {
            showToast('Novi gesli se ne ujemata.', 'danger');
            return;
        }
        if (newPassword.length < 6) {
            showToast('Geslo mora biti dolgo vsaj 6 znakov.', 'danger');
            return;
        }

        setButtonLoading(button, true, 'Spreminjam...');
        try {
            const res = await fetch('/api/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, current_password: currentPassword, new_password: newPassword })
            });
            const data = await res.json().catch(()=>({success:false,error:'Napaka'}));
            if (!res.ok || !data.success) throw new Error(data.error || 'Napaka pri spreminjanju gesla');
            showToast('Geslo uspešno spremenjeno', 'success');
            closeChangePasswordModal();
        } catch (err) {
            showToast(err.message, 'danger');
        } finally {
            setButtonLoading(button, false);
        }
    }

    // Funkcija za zapiranje modala za spreminjanje gesla (globalna)
    window.closeChangePasswordModal = function() {
        const modal = document.getElementById('changePasswordModal');
        if (modal) {
            modal.classList.add('hidden');
        }
        
        // Počisti polja
        const newPasswordInput = document.getElementById('new-password');
        const confirmPasswordInput = document.getElementById('confirm-password');
        const currentPasswordInput = document.getElementById('current-password');
        const currentRow = document.getElementById('current-password-row');
        if (newPasswordInput) newPasswordInput.value = '';
        if (confirmPasswordInput) confirmPasswordInput.value = '';
        if (currentPasswordInput) currentPasswordInput.value = '';
        if (currentRow) currentRow.style.display = 'none';
    }

    // Inicializacija aplikacije
    console.log('Inicializiram aplikacijo...');
    
    // Prikaži uporabnika
    displayCurrentUser();
    
    // Inicializiraj zavihke
    initializeTabs();
    
    // Inicializiraj filter gumbe (sinhronizirano z dejanskim izborom)
    {
        const initialFilterValue =
            document.querySelector('input[name="order-filter"]:checked')?.value ||
            document.getElementById('order-filter-select')?.value ||
            'all';
        currentFilter = initialFilterValue;
        updateFilterButtons(initialFilterValue);
        const ddl = document.getElementById('order-filter-select');
        if (ddl) ddl.value = initialFilterValue;
    }
    
    // Naloži prva naročila (samo enkrat)
    if (!initialNarocilaRequested) {
        initialNarocilaRequested = true;
        fetchNarocila(1, null, 'init');
    }
    
    // Inicializiraj ostale zavihke
    initializeManualAndPrintTab();
    loadProizvajalci();
    fetchExpiringPerfumes();
    // Naloži uporabnike samo, če ima dovoljenje za ogled/uporabnike zavihek
    if (hasUserPermission('view_users') || hasUserPermission('edit_users') || hasUserPermission('add_users') || hasUserPermission('delete_users')) {
        loadUsers();
    } else {
        console.log('Preskakujem loadUsers() - uporabnik nima dovoljenja');
    }
    
    // Prikaži gumb za samostojno spremembo gesla, če je prijavljen uporabnik
    const selfPwdBtn = document.getElementById('self-change-password-btn');
    if (selfPwdBtn) {
        if (currentUser && currentUser.username) {
            selfPwdBtn.style.display = '';
        } else {
            selfPwdBtn.style.display = 'none';
        }
    }

    console.log('Aplikacija inicializirana!');

    // Funkcija za preklop na zavihek Katalog & Zaloga
    function switchToKatalogTab() {
        const tabButtons = document.querySelectorAll('[data-tab]');
        const tabPanels = document.querySelectorAll('.tab-pane');
        
        // Odstrani aktivni razred iz vseh zavihkov
        tabButtons.forEach(btn => {
            btn.classList.remove('active', 'border-primary-500', 'text-primary-600');
            btn.classList.add('border-transparent', 'text-gray-500');
        });
        
        // Skrij vse tab panele
        tabPanels.forEach(panel => {
            panel.classList.remove('show', 'active');
            panel.style.display = 'none';
        });
        
        // Aktiviraj zavihek Katalog & Zaloga
        const katalogTab = document.querySelector('[data-tab="katalog"]');
        if (katalogTab) {
            katalogTab.classList.add('active', 'border-primary-500', 'text-primary-600');
            katalogTab.classList.remove('border-transparent', 'text-gray-500');
        }
        
        // Prikaži panel Katalog & Zaloga
        const katalogPanel = document.getElementById('katalog-panel');
        if (katalogPanel) {
            katalogPanel.classList.add('show', 'active');
            katalogPanel.style.display = 'block';
        }
    }
    // Naredimo funkcije globalno dostopne
    window.switchToKatalogTab = switchToKatalogTab;
    window.loadPerfumeForEditing = loadPerfumeForEditing;
    window.initializeTabs = initializeTabs;
    window.initializeModal = initializeModal;
    window.initializeManualAndPrintTab = initializeManualAndPrintTab;
    // Procurement tab init
    window.initializeProcurementTab = async function initializeProcurementTab() {
        const supplierSelect = document.getElementById('proc-supplier');
        const proizvajalecSelect = null; // proizvajalca določimo z izbranim supplierjem
        const stockBody = document.getElementById('proc-stock-body');
        const addBtn = document.getElementById('proc-add-to-cart');
        const bulkOnhandBtn = document.getElementById('proc-bulk-onhand-save');
        const clearBtn = document.getElementById('proc-clear-cart');
        const submitBtn = document.getElementById('proc-submit-order');
        const openOnhandBtn = document.getElementById('proc-open-onhand-modal');
        const onhandModal = document.getElementById('proc-onhand-modal');
        const onhandBody = document.getElementById('proc-onhand-body');
        const onhandSupplierLbl = document.getElementById('proc-onhand-supplier');
        const onhandClose = document.getElementById('proc-onhand-close');
        const onhandSave = document.getElementById('proc-onhand-save');
        const onhandSearch = document.getElementById('proc-onhand-search');
        const onhandCount = document.getElementById('proc-onhand-count');
        const productNoInput = document.getElementById('proc-product-no');
        const productSearch = document.getElementById('proc-product-search');
        const productResults = document.getElementById('proc-product-results');
        let prodActiveIndex = -1; // keyboard selection index for product results
        const qtyInput = document.getElementById('proc-qty');
        const stockSearch = document.getElementById('proc-stock-search');
        const hideZero = document.getElementById('proc-hide-zero');
        const poOrdersBody = document.getElementById('po-orders-body');
        const poStatusFilter = document.getElementById('po-status-filter');
        const poReceiveModal = document.getElementById('po-receive-modal');
        const poReceiveTitle = document.getElementById('po-receive-title');
        const poReceiveBody = document.getElementById('po-receive-body');
        const poReceiveClose = document.getElementById('po-receive-close');
        const poReceiveSubmit = document.getElementById('po-receive-submit');
        const poAllReceived = document.getElementById('po-all-received');
        const poImagesModal = document.getElementById('po-images-modal');
        const poImagesTitle = document.getElementById('po-images-title');
        const poImagesClose = document.getElementById('po-images-close');
        const poOpenImages = document.getElementById('po-open-images');
        const poImageFile = document.getElementById('po-image-file');
        const poImageUpload = document.getElementById('po-image-upload');
        const poImagesList = document.getElementById('po-images-list');
        const poReceiveImageFile = document.getElementById('po-receive-image-file');
        const poReceiveImageUpload = document.getElementById('po-receive-image-upload');
        const poReceiveImagesList = document.getElementById('po-receive-images-list');
        // Manual receive refs
        const manualOpen = document.getElementById('proc-open-manual-receive');
        const manualModal = document.getElementById('manual-receive-modal');
        const manualClose = document.getElementById('manual-receive-close');
        const manualSupplier = document.getElementById('manual-receive-supplier');
        const manualSearch = document.getElementById('manual-receive-product-search');
        const manualResults = document.getElementById('manual-receive-results');
        const manualQty = document.getElementById('manual-receive-qty');
        const manualAdd = document.getElementById('manual-receive-add');
        const manualBody = document.getElementById('manual-receive-body');
        const manualImgFile = document.getElementById('manual-receive-image-file');
        const manualImgUpload = document.getElementById('manual-receive-image-upload');
        const manualImgs = document.getElementById('manual-receive-images');
        const manualSubmit = document.getElementById('manual-receive-submit');
        let manualPOId = null;
        let currentPOId = null;
        let addInFlight = false; // Guard against multiple quick Enter presses
        if (typeof window.__procAddInFlight === 'undefined') window.__procAddInFlight = false;
        

        if (!document.getElementById('procurement-panel')) return;

        async function fetchSuppliers() {
            try {
                // razširjena lista dobaviteljev (vključuje procurement-only)
                const res = await fetch('/api/procurement/suppliers/all');
                const json = await res.json();
                if (!json.success) return;
                const list = Array.isArray(json.data) ? json.data : [];
                supplierSelect.innerHTML = '<option value="">Izberi dobavitelja</option>' +
                    list.map(s => `<option value="${s}">${s}</option>`).join('');
            } catch {}
        }

        async function fetchProizvajalci() { /* odstranjeno - ni potrebno */ }

        function isProcOnlySupplier(name){ const n=(name||'').toUpperCase(); return n && n!=='FLORGARDEN' && n!=='MISTRAL'; }

        async function searchProducts() {
            const q = (productSearch.value || '').trim();
            const supplier = (supplierSelect.value || '').toUpperCase();
            if (q.length < 1 || !supplier) { productResults.classList.add('hidden'); productResults.innerHTML = ''; prodActiveIndex = -1; return; }
            let rows = [];
                if (isProcOnlySupplier(supplier)) {
                const resp = await fetch(`/api/procurement2/search?q=${encodeURIComponent(q)}&supplier=${encodeURIComponent(supplier)}`);
                const json = await resp.json();
                rows = (json.success ? (json.data||[]) : []);
                if (rows.length === 0) { productResults.classList.add('hidden'); productResults.innerHTML=''; prodActiveIndex = -1; return; }
                    productResults.innerHTML = rows.map(r => `
                    <div data-sku="${r.sku}" data-name="${(r.name||'').replace(/"/g,'&quot;')}" class="px-3 py-2 hover:bg-gray-100 cursor-pointer">
                        <div class="text-sm font-medium">${r.name || ''}</div>
                        <div class="text-xs text-gray-600">${r.sku}</div>
                    </div>
                `).join('');
            } else {
                const resp = await fetch(`/api/procurement/search-perfumes?q=${encodeURIComponent(q)}&limit=50&supplier=${encodeURIComponent(supplier)}`);
                const json = await resp.json();
                rows = (json.success ? (json.data||[]) : []).filter(r => (r.proizvajalec || '').toUpperCase() === supplier);
                // Natural sort: by numeric product_no then by name
                rows = rows.map(r => ({...r, _pn: parseInt(r.product_no, 10) || 0}))
                           .sort((a,b)=> (a._pn - b._pn) || (a.ime_parfuma||'').localeCompare(b.ime_parfuma||''));
                if (rows.length === 0) { productResults.classList.add('hidden'); productResults.innerHTML=''; prodActiveIndex = -1; return; }
                    productResults.innerHTML = rows.map(r => `
                    <div data-product-no="${r.product_no}" data-proizvajalec-id="${r.proizvajalec_id}" data-name="${(r.ime_parfuma||'').replace(/"/g,'&quot;')}" class="px-3 py-2 hover:bg-gray-100 cursor-pointer">
                        <div class="text-sm font-medium">${r.ime_parfuma || ''}</div>
                        <div class="text-xs text-gray-600">${r.product_no} • ${r.proizvajalec}</div>
                    </div>
                `).join('');
            }
            // reset selection and scroll on fresh results
            prodActiveIndex = -1;
            productResults.scrollTop = 0;
            productResults.classList.remove('hidden');
        }

        function bindProductResults() {
            if (!productResults) return;
            productResults.addEventListener('click', (e) => {
                const item = e.target.closest('[data-product-no]');
                const item2 = e.target.closest('[data-sku]');
                if (!item && !item2) return;
                if (item) {
                    const pn = item.getAttribute('data-product-no');
                    if (productNoInput) productNoInput.value = pn;
                    const name = item.getAttribute('data-name') || pn;
                    if (productSearch) productSearch.value = name;
                } else if (item2) {
                    const sku = item2.getAttribute('data-sku');
                    if (productNoInput) productNoInput.value = sku; // reuse field to carry SKU for proc-only
                    const name = item2.getAttribute('data-name') || sku;
                    if (productSearch) productSearch.value = name;
                }
                productResults.innerHTML = '';
                productResults.classList.add('hidden');
                // move focus to quantity for quick flow
                if (qtyInput && !qtyInput.disabled) { qtyInput.focus(); qtyInput.select(); }
            });
            document.addEventListener('click', (e) => {
                if (productResults.contains(e.target) || (productSearch && productSearch.contains(e.target))) return;
                productResults.classList.add('hidden');
            });
        }

        async function fetchStock() {
            const supplier = supplierSelect.value;
            if (!supplier) { stockBody.innerHTML = ''; return; }
            const q = (stockSearch && stockSearch.value) ? `&q=${encodeURIComponent(stockSearch.value)}` : '';
            try {
                let rows = [];
                if (isProcOnlySupplier(supplier)) {
                    const res = await fetch(`/api/procurement2/stock?supplier=${encodeURIComponent(supplier)}${q}`);
                    const json = await res.json();
                    if (!json.success) { stockBody.innerHTML = ''; return; }
                    rows = json.data || [];
                } else {
                    const res = await fetch(`/api/procurement/stock?supplier=${encodeURIComponent(supplier)}${q}`);
                    const json = await res.json();
                    if (!json.success) { stockBody.innerHTML = ''; return; }
                    rows = json.data || [];
                }
                if (hideZero && hideZero.checked) {
                    rows = rows.filter(r => ((r.on_order_pending||r.pending) || 0) > 0);
                }
                const filterOut = document.getElementById('proc-filter-out');
                const filterLow = document.getElementById('proc-filter-low');
                if (filterOut && filterOut.checked) {
                    rows = rows.filter(r => (r.on_hand || 0) === 0);
                }
                if (filterLow && filterLow.checked) {
                    rows = rows.filter(r => typeof r.min_on_hand === 'number' && (r.on_hand || 0) > 0 && (r.on_hand < r.min_on_hand));
                }
                stockBody.innerHTML = rows.map(r => {
                    let stateClass = '';
                    if (typeof r.min_on_hand === 'number') {
                        if (r.on_hand <= 0) stateClass = 'bg-red-50';
                        else if (r.on_hand < r.min_on_hand) stateClass = 'bg-orange-50';
                        else stateClass = 'bg-green-50';
                    }
                    const isProc = isProcOnlySupplier(supplier);
                    const idCell = isProc ? (r.sku || '') : (r.product_no || '');
                    const nameCell = isProc ? (r.name || '') : (r.ime_parfuma || '');
                    const pendingVal = isProc ? (r.pending||0) : (r.on_order_pending||0);
                    const committedVal = isProc ? (r.committed||0) : (r.on_order_committed||0);
                    const minVal = (typeof r.min_on_hand === 'number') ? r.min_on_hand : 0;
                    const trAttrs = isProc ? `data-sku="${r.sku}" data-proc-id="${r.id||''}"` : `data-product-no="${r.product_no}" data-proizvajalec-id="${r.proizvajalec_id}"`;
                    const keyAttr = isProc ? (r.sku || '') : (r.product_no || '');
                    const delBtn = (isProc && hasUserPermission && hasUserPermission('delete_users'))
                        ? '<button class="px-2 py-1 border rounded text-xs text-red-600 proc-del-item" title="Izbriši">Izbriši</button>'
                        : '';
                    return `
                    <tr ${trAttrs} data-key="${keyAttr}">
                        <td class="px-4 py-2 font-mono" data-label="Product No">${idCell}</td>
                        <td class="px-4 py-2 ${stateClass}" data-label="Parfum">${nameCell}</td>
                        <td class="px-4 py-2 ${stateClass}" data-label="Na zalogi">${r.on_hand||0}</td>
                        <td class="px-4 py-2" data-label="Min"><input type="number" min="0" class="w-16 px-2 py-1 border rounded min-input" value="${minVal}" /></td>
                        <td class="px-4 py-2" data-label="Naročilo"><input type="number" min="0" class="w-24 px-2 py-1 border rounded pending-input" value="${pendingVal}" /></td>
                        <td class="px-4 py-2" data-label="Oddano">${committedVal}</td>
                        <td class="px-4 py-2 proc-last-sale" data-label="Zadnja prodaja"><span class="text-xs text-gray-400">…</span></td>
                        <td class="px-4 py-2 hidden sm:table-cell" data-label="Akcije">
                            <div class="flex items-center gap-2 flex-wrap">
                                <button class="px-2 py-1 border rounded text-xs save-pending" title="Shrani spremembe za to vrstico">Shrani</button>
                                <button class="px-2 py-1 border rounded text-xs proc-history" title="Zgodovina gibanj">Zgodovina</button>
                                ${delBtn}
                            </div>
                        </td>
                    </tr>`
                }).join('');
                // Asynchronously load last-sale per row and update "Zadnja prodaja" cells.
                (async () => {
                    try {
                        const isProc = isProcOnlySupplier(supplier);
                        const url = isProc
                            ? `/api/procurement2/stock-movements/last?supplier=${encodeURIComponent(supplier)}`
                            : `/api/procurement/stock-movements/last?supplier=${encodeURIComponent(supplier)}`;
                        const resp = await fetch(url);
                        const json = await resp.json().catch(() => ({}));
                        const map = (json && json.success && json.data) ? json.data : {};
                        const fmt = (iso) => {
                            try {
                                const d = new Date(iso);
                                const today = new Date();
                                const diffMs = today - d;
                                const days = Math.floor(diffMs / 86400000);
                                if (days <= 0) return 'danes';
                                if (days === 1) return 'včeraj';
                                if (days < 7) return `pred ${days} dnevi`;
                                return d.toLocaleDateString('sl-SI');
                            } catch (_) { return ''; }
                        };
                        const sourceIcon = (s) => {
                            if (s === 'serija') return '<i class="bi bi-droplet-half text-cyan-600" title="Iztok (serija)"></i>';
                            if (s && s.startsWith('shopify')) return '<i class="bi bi-shop text-emerald-600" title="Shopify"></i>';
                            if (s && s.startsWith('mk')) return '<i class="bi bi-cash-coin text-amber-600" title="MetaKocka"></i>';
                            return '<i class="bi bi-circle text-gray-400"></i>';
                        };
                        stockBody.querySelectorAll('tr').forEach(tr => {
                            const key = tr.getAttribute('data-key') || '';
                            const cell = tr.querySelector('.proc-last-sale');
                            if (!cell) return;
                            const info = map[key];
                            if (!info) {
                                cell.innerHTML = '<span class="text-xs text-gray-400">—</span>';
                                return;
                            }
                            cell.innerHTML = `<span class="text-xs text-gray-700">${sourceIcon(info.source)} ${fmt(info.last_at)}</span>`;
                        });
                    } catch (_) {
                        stockBody.querySelectorAll('.proc-last-sale').forEach(c => { c.innerHTML = '<span class="text-xs text-gray-400">—</span>'; });
                    }
                })();
                // Wire up history popovers.
                stockBody.querySelectorAll('.proc-history').forEach(btn => {
                    btn.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        const tr = ev.target.closest('tr');
                        if (tr) window.__openProcHistory(tr, supplier);
                    });
                });
                // Auto-save min_on_hand on blur.
                stockBody.querySelectorAll('.min-input').forEach(input => {
                    input.addEventListener('blur', async () => {
                        const tr = input.closest('tr');
                        if (!tr) return;
                        const supplierCur = supplierSelect.value;
                        const isProc = isProcOnlySupplier(supplierCur);
                        const val = Math.max(0, parseInt(input.value || '0', 10));
                        try {
                            if (isProc) {
                                const sku = tr.getAttribute('data-sku');
                                await fetch('/api/procurement2/stock/min', {
                                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ supplier: supplierCur, sku, min_on_hand: val })
                                });
                            } else {
                                const product_no = tr.getAttribute('data-product-no');
                                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id') || '0', 10);
                                await fetch('/api/procurement/stock/bulk-min', {
                                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ supplier: supplierCur, updates: [{ product_no, proizvajalec_id, min_on_hand: val }] })
                                });
                            }
                        } catch (_) {}
                    });
                });
                // track pending changes for bulk save bar
                const bar = document.getElementById('proc-bulk-pending-bar');
                const cnt = document.getElementById('proc-bulk-count');
                const updateBar = () => {
                    let changes = 0;
                    stockBody.querySelectorAll('tr').forEach(tr => {
                        const input = tr.querySelector('.pending-input');
                        if (!input) return;
                        const isProc = isProcOnlySupplier(supplier);
                        const current = isProc ? parseInt((tr.getAttribute('data-current-pending')||'0'),10) : parseInt((tr.getAttribute('data-current-pending')||'0'),10);
                        const val = Math.max(0, parseInt((input.value||'0'),10));
                        if (!isNaN(val) && val !== current) changes++;
                    });
                    if (cnt) cnt.textContent = String(changes);
                    if (bar) bar.classList.toggle('hidden', changes === 0);
                };
                // Auto-save a single row's pending value (debounced) and show a
                // small inline indicator next to the input.
                const flashSaved = (input, ok = true) => {
                    if (!input) return;
                    const cell = input.closest('td');
                    if (!cell) return;
                    let badge = cell.querySelector('.proc-saved-badge');
                    if (!badge) {
                        badge = document.createElement('span');
                        badge.className = 'proc-saved-badge ml-2 text-xs font-medium align-middle';
                        cell.appendChild(badge);
                    }
                    badge.textContent = ok ? '✓ Shranjeno' : '✗ Napaka';
                    badge.style.color = ok ? '#0a8a3a' : '#b91c1c';
                    badge.style.opacity = '1';
                    badge.style.transition = 'opacity 1.2s ease';
                    setTimeout(() => { try { badge.style.opacity = '0'; } catch (_) {} }, 1200);
                };
                const autoSaveRow = async (tr) => {
                    const supplierCur = supplierSelect.value; if (!supplierCur || !tr) return;
                    const input = tr.querySelector('.pending-input'); if (!input) return;
                    const isProc = isProcOnlySupplier(supplierCur);
                    const current = parseInt(tr.getAttribute('data-current-pending') || '0', 10);
                    const val = Math.max(0, parseInt((input.value || '0'), 10));
                    if (isNaN(val) || val === current) return;
                    const product_no = tr.getAttribute('data-product-no');
                    const proizvajalec_id = tr.getAttribute('data-proizvajalec-id') ? parseInt(tr.getAttribute('data-proizvajalec-id'), 10) : null;
                    const sku = tr.getAttribute('data-sku');
                    try {
                        const endpoint = isProc ? '/api/procurement2/cart/bulk-set' : '/api/procurement/cart/bulk-set';
                        const body = isProc
                            ? { supplier: supplierCur, items: [{ sku, qty: val }] }
                            : { supplier: supplierCur, items: [{ product_no, proizvajalec_id, qty: val }] };
                        const resp = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                        const json = await resp.json().catch(() => ({ success: false }));
                        if (!resp.ok || !json.success) { flashSaved(input, false); return; }
                        tr.setAttribute('data-current-pending', String(val));
                        flashSaved(input, true);
                        updateBar();
                    } catch (_) { flashSaved(input, false); }
                };
                // annotate current pending as attribute and bind input listeners
                stockBody.querySelectorAll('tr').forEach(tr => {
                    const isProc = isProcOnlySupplier(supplier);
                    const sku = tr.getAttribute('data-sku');
                    const input = tr.querySelector('.pending-input');
                    if (!input) return;
                    const pending = (() => {
                        try {
                            const row = rows[tr.rowIndex-1] || {};
                            return isProc ? (row.pending||0) : (row.on_order_pending||0);
                        } catch { return 0; }
                    })();
                    tr.setAttribute('data-current-pending', String(pending));
                    // Debounced auto-save on typing (1.5 s after last keystroke).
                    let debTimer = null;
                    input.addEventListener('input', () => {
                        updateBar();
                        clearTimeout(debTimer);
                        debTimer = setTimeout(() => autoSaveRow(tr), 1500);
                    });
                    // Immediate save on blur or Enter.
                    input.addEventListener('blur', () => { clearTimeout(debTimer); autoSaveRow(tr); });
                    input.addEventListener('keydown', (ev) => {
                        if (ev.key === 'Enter') {
                            ev.preventDefault();
                            clearTimeout(debTimer);
                            autoSaveRow(tr);
                            // Jump to next row's pending input for fast data entry.
                            const allInputs = Array.from(stockBody.querySelectorAll('.pending-input'));
                            const idx = allInputs.indexOf(input);
                            const next = allInputs[idx + 1];
                            if (next) { next.focus(); next.select(); }
                            else { input.blur(); }
                        } else if (ev.key === 'ArrowDown') {
                            ev.preventDefault();
                            const allInputs = Array.from(stockBody.querySelectorAll('.pending-input'));
                            const idx = allInputs.indexOf(input);
                            const next = allInputs[idx + 1];
                            if (next) { next.focus(); next.select(); }
                        } else if (ev.key === 'ArrowUp') {
                            ev.preventDefault();
                            const allInputs = Array.from(stockBody.querySelectorAll('.pending-input'));
                            const idx = allInputs.indexOf(input);
                            const prev = allInputs[idx - 1];
                            if (prev) { prev.focus(); prev.select(); }
                        }
                    });
                });
                updateBar();
                // bind save buttons
                stockBody.querySelectorAll('.save-pending').forEach(btn => {
                    btn.addEventListener('click', async (e) => {
                        const tr = e.target.closest('tr');
                        const supplier = supplierSelect.value; if (!supplier || !tr) return;
                        const isProc = isProcOnlySupplier(supplier);
                        const product_no = tr.getAttribute('data-product-no');
                        const proizvajalec_id = tr.getAttribute('data-proizvajalec-id') ? parseInt(tr.getAttribute('data-proizvajalec-id'), 10) : null;
                        const sku = tr.getAttribute('data-sku');
                        const input = tr.querySelector('.pending-input');
                        const qty = Math.max(0, parseInt((input && input.value) || '0', 10));
                        if (isProc && sku) {
                            await fetch('/api/procurement2/cart/bulk-set', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier, items:[{sku, qty}]})});
                        } else {
                            await fetch('/api/procurement/cart/bulk-set', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier, items:[{product_no, proizvajalec_id, qty}]})});
                        }
                        await fetchStock();
                        window.showToast && window.showToast('Naročilo shranjeno', 'success');
                    });
                });
                // admin-only delete for proc-only
                stockBody.querySelectorAll('.proc-del-item').forEach(btn => {
                    btn.addEventListener('click', async (e) => {
                        const tr = e.target.closest('tr');
                        const supplier = supplierSelect.value; if (!supplier || !tr) return;
                        const sku = tr.getAttribute('data-sku'); const id = tr.getAttribute('data-proc-id');
                        if (!sku) return;
                        if (!confirm(`Izbrišem artikel ${sku}?`)) return;
                        const resp = await fetch(`/api/procurement2/products/${encodeURIComponent(supplier)}/${encodeURIComponent(sku)}`, { method: 'DELETE' });
                        const j = await resp.json().catch(()=>({success:false}));
                        if (!resp.ok || !j.success) { window.showToast && window.showToast(j.error || 'Brisanje ni uspelo', 'danger'); return; }
                        window.showToast && window.showToast('Artikel izbrisan', 'success');
                        await fetchStock();
                    });
                });
                // totals
                const totalsEl = document.getElementById('proc-totals');
                try {
                    const sumOnHand = rows.reduce((a,r)=>a+(r.on_hand||0),0);
                    const sumPending = rows.reduce((a,r)=> a + (typeof r.pending === 'number' ? r.pending : (r.on_order_pending||0)), 0);
                    const sumCommitted = rows.reduce((a,r)=> a + (typeof r.committed === 'number' ? r.committed : (r.on_order_committed||0)), 0);
                    if (totalsEl) {
                        totalsEl.style.display = '';
            totalsEl.textContent = `Skupaj — V predalu: ${sumOnHand} | Na naročilu: ${sumPending} | Na oddanem: ${sumCommitted}`;
                    }
                } catch {}
                // no remove buttons anymore
            } catch {
                stockBody.innerHTML = '';
            }
        }

        // Bulk save handlers
        const bulkSaveBtn = document.getElementById('proc-bulk-save');
        const bulkCancelBtn = document.getElementById('proc-bulk-cancel');
        async function bulkSetPending() {
            const supplier = supplierSelect.value; if (!supplier) return;
            const updates = [];
            stockBody.querySelectorAll('tr').forEach(tr => {
                const input = tr.querySelector('.pending-input');
                if (!input) return;
                const isProc = isProcOnlySupplier(supplier);
                const val = Math.max(0, parseInt((input.value||'0'),10));
                const current = parseInt(tr.getAttribute('data-current-pending')||'0',10);
                if (val === current) return;
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = tr.getAttribute('data-proizvajalec-id') ? parseInt(tr.getAttribute('data-proizvajalec-id'),10) : null;
                const sku = tr.getAttribute('data-sku');
                if (isProc && sku) updates.push({ sku, qty: val });
                else if (product_no && proizvajalec_id) updates.push({ product_no, proizvajalec_id, qty: val });
            });
            if (updates.length === 0) { window.showToast && window.showToast('Ni neshranjenih sprememb.', 'info'); return; }
            try {
                const endpoint = isProcOnlySupplier(supplier) ? '/api/procurement2/cart/bulk-set' : '/api/procurement/cart/bulk-set';
                const resp = await fetch(endpoint, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ supplier, items: updates })});
                const json = await resp.json().catch(()=>({success:false}));
                if (!resp.ok || !json.success) { window.showToast && window.showToast(json.error || 'Napaka pri shranjevanju.', 'danger'); return; }
                window.showToast && window.showToast('Spremembe shranjene.', 'success');
                await fetchStock();
            } catch (e) {
                window.showToast && window.showToast('Napaka pri shranjevanju.', 'danger');
            }
        }
        function bulkCancel() { fetchStock(); }
        if (bulkSaveBtn && !bulkSaveBtn.dataset.bound) {
            bulkSaveBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); bulkSetPending(); });
            bulkSaveBtn.dataset.bound = '1';
        }
        if (bulkCancelBtn && !bulkCancelBtn.dataset.bound) {
            bulkCancelBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); bulkCancel(); });
            bulkCancelBtn.dataset.bound = '1';
        }

        async function fetchPOs() {
            if (!poOrdersBody) return;
            const supplier = supplierSelect.value;
            if (!supplier) { poOrdersBody.innerHTML = ''; return; }
            const status = (poStatusFilter && poStatusFilter.value && poStatusFilter.value !== 'ALL') ? `&status=${encodeURIComponent(poStatusFilter.value)}` : '';
            const res = await fetch(`/api/procurement/orders?supplier=${encodeURIComponent(supplier)}${status}`);
            const json = await res.json();
            const orders = (json.success ? (json.data && json.data.orders) : []) || [];
            const tStatus = (s) => {
                switch ((s||'').toUpperCase()) {
                    case 'SUBMITTED': return 'Oddano';
                    case 'PARTIAL_RECEIVED': return 'Delno prejeto';
                    case 'RECEIVED': return 'Prejeto';
                    case 'DRAFT': return 'Osnutek';
                    case 'ARCHIVED': return 'Arhivirano';
                    default: return s || '';
                }
            };
            poOrdersBody.innerHTML = orders.map(o => {
                const dt = o.submitted_at || o.created_at || o.updated_at;
                const when = dt ? new Date(dt).toLocaleString('sl-SI') : '';
                const isDraft = o.status === 'DRAFT';
                const canReceive = (o.status === 'SUBMITTED' || o.status === 'PARTIAL_RECEIVED');
                const canViewImages = true; // omogoči ogled slik v vseh statusih
                return `
                    <tr data-po-id="${o.id}" class="hover:bg-gray-50">
                        <td class="px-4 py-2">${o.id}</td>
                        <td class="px-4 py-2">${o.supplier}</td>
                        <td class="px-4 py-2">${tStatus(o.status)}</td>
                        <td class="px-4 py-2">${when}</td>
                        <td class="px-4 py-2 text-right">${o.items_count}</td>
                        <td class="px-4 py-2 text-right">${o.total_requested}</td>
                        <td class="px-4 py-2 text-right">${o.total_received}</td>
                        <td class="px-4 py-2">
                            <div class="flex items-center gap-2 flex-wrap">
                                ${isDraft ? `<button class="po-btn-resubmit inline-flex items-center px-2 py-1 border rounded text-xs"><i class=\"bi bi-send mr-1\"></i> Ponovno oddaj</button>` : ''}
                                ${canReceive ? `<button class=\"po-btn-receive inline-flex items-center px-2 py-1 border rounded text-xs\"><i class=\"bi bi-box-arrow-in-down mr-1\"></i> Prejem</button>` : ''}
                                <a href="/api/procurement/orders/${o.id}/print" target="_blank" class="inline-flex items-center px-2 py-1 border rounded text-xs"><i class="bi bi-printer mr-1"></i> Natisni</a>
                                <a href="/api/procurement/orders/${o.id}/xlsx" target="_blank" class="inline-flex items-center px-2 py-1 border rounded text-xs"><i class="bi bi-file-earmark-excel mr-1"></i> Excel</a>
                                ${canViewImages ? `<button class=\"po-btn-images inline-flex items-center px-2 py-1 border rounded text-xs\"><i class=\"bi bi-images mr-1\"></i> Slike</button>` : ''}
                                <button class="po-btn-dup inline-flex items-center px-2 py-1 border rounded text-xs"><i class="bi bi-files mr-1"></i> Podvoji</button>
                                <button class="po-btn-arch inline-flex items-center px-2 py-1 border rounded text-xs text-red-700"><i class="bi bi-archive mr-1"></i> Arhiviraj</button>
                                <button class="po-btn-del inline-flex items-center px-2 py-1 border rounded text-xs text-red-700"><i class="bi bi-trash3 mr-1"></i> Izbriši</button>
                            </div>
                        </td>
                    </tr>
                `
            }).join('');
            // Bind actions
            poOrdersBody.querySelectorAll('.po-btn-resubmit').forEach(btn => btn.addEventListener('click', async (e) => {
                const tr = e.target.closest('tr'); if (!tr) return;
                const poId = parseInt(tr.getAttribute('data-po-id'), 10);
                await resubmitDraft(poId);
            }));
            poOrdersBody.querySelectorAll('.po-btn-receive').forEach(btn => btn.addEventListener('click', openReceiveModal));
        poOrdersBody.querySelectorAll('.po-btn-images').forEach(btn => btn.addEventListener('click', openImagesModal));
            poOrdersBody.querySelectorAll('.po-btn-dup').forEach(btn => btn.addEventListener('click', duplicatePO));
            poOrdersBody.querySelectorAll('.po-btn-arch').forEach(btn => btn.addEventListener('click', archivePO));
            poOrdersBody.querySelectorAll('.po-btn-del').forEach(btn => btn.addEventListener('click', async (e) => {
                const tr = e.target.closest('tr'); if (!tr) return;
                const poId = parseInt(tr.getAttribute('data-po-id'), 10);
                if (!confirm('Ali res želite izbrisati naročilo? Dejanje je nepovratno.')) return;
                const resp = await fetch(`/api/procurement/orders/${poId}`, {method:'DELETE'});
                const json = await resp.json().catch(()=>({success:false}));
                if (!resp.ok || !json.success) { showToast && showToast(json.error || 'Brisanje ni uspelo (potrebna vloga admin).', 'danger'); return; }
                showToast && showToast('Naročilo izbrisano', 'success');
                await fetchPOs();
                await fetchStock();
            }));
        }

        async function openReceiveModal(e) {
            const tr = e.target.closest('tr'); if (!tr) return;
            const poId = parseInt(tr.getAttribute('data-po-id'), 10);
            currentPOId = poId;
            if (poReceiveModal) poReceiveModal.dataset.poId = String(poId);
            const res = await fetch(`/api/procurement/orders/${poId}`);
            const json = await res.json();
            if (!json.success) return;
            const order = json.data.order; const items = json.data.items || [];
            poReceiveTitle.textContent = `PO #${order.id} – ${order.supplier}`;
            poReceiveBody.innerHTML = items.map(it => {
                const back = Math.max(0, (it.requested_qty||0) - (it.received_qty||0));
                return `
                    <tr data-product-no="${it.product_no}" data-proizvajalec-id="${it.proizvajalec_id}">
                        <td class="px-4 py-2 font-mono">${it.product_no}</td>
                        <td class="px-4 py-2">${it.ime_parfuma || ''}</td>
                        <td class="px-4 py-2 text-right">${it.requested_qty || 0}</td>
                        <td class="px-4 py-2 text-right">${it.received_qty || 0}</td>
                        <td class="px-4 py-2 text-right"><input type="number" class="w-24 px-2 py-1 border rounded po-recv-input" min="0" max="${back}" value="${back}" /></td>
                        <td class="px-4 py-2 text-right">${back}</td>
                    </tr>
                `
            }).join('');
            // osveži mini galerijo slik v modalu
            try { await refreshImages(); } catch {}
            poReceiveModal.classList.remove('hidden');
            poReceiveModal.classList.add('flex');
        }

        function closeReceiveModal() {
            poReceiveModal.classList.add('hidden');
            poReceiveModal.classList.remove('flex');
        }

        async function submitReceive() {
            try {
            if (!currentPOId) {
                const fallback = poReceiveModal && poReceiveModal.dataset && poReceiveModal.dataset.poId ? parseInt(poReceiveModal.dataset.poId, 10) : null;
                if (fallback) { currentPOId = fallback; }
            }
            if (!currentPOId) { showToast && showToast('Napaka: manjka ID naročila.', 'danger'); return; }
            // preveri slike (obvezne)
            try {
                const r = await fetch(`/api/purchase-orders/${currentPOId}/images`);
                let imgs; try { imgs = await r.json(); } catch { imgs = []; }
                const images = Array.isArray(imgs) ? imgs : (imgs && Array.isArray(imgs.data) ? imgs.data : []);
                if (!images || images.length === 0) {
                    showToast && showToast('Za prejem je obvezna vsaj ena slika.', 'danger');
                    return;
                }
            } catch {
                showToast && showToast('Za prejem je obvezna vsaj ena slika.', 'danger');
                return;
            }

            const items = [];
            poReceiveBody.querySelectorAll('tr').forEach(tr => {
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id'), 10);
                const input = tr.querySelector('.po-recv-input');
                const received_qty = Math.max(0, parseInt((input && input.value) || '0', 10));
                if (received_qty > 0) items.push({product_no, proizvajalec_id, received_qty});
            });
            if (items.length === 0) { showToast && showToast('Vnesi količine za prejem.', 'warning'); return; }
            const all_received = !!(poAllReceived && poAllReceived.checked);
            if (poReceiveSubmit) poReceiveSubmit.disabled = true;
            try {
                const resp = await fetch(`/api/procurement/orders/${currentPOId}/receive`, {
                    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({items, all_received, require_image: true})
                });
                const json = await resp.json().catch(() => ({success:false}));
                if (!resp.ok || !json.success) { showToast && showToast(json.error || 'Napaka pri prejemu', 'danger'); return; }
                showToast && showToast('Prejem uspešen', 'success');
                closeReceiveModal();
                await fetchPOs();
                await fetchStock();
            } finally {
                if (poReceiveSubmit) poReceiveSubmit.disabled = false;
            }
            } catch (err) {
                console.error('submitReceive error:', err);
                showToast && showToast('Napaka pri prejemu.', 'danger');
            }
        }

        async function openImagesModal(e) {
            const tr = e.target.closest('tr'); if (!tr) return;
            const poId = parseInt(tr.getAttribute('data-po-id'), 10);
            currentPOId = poId;
            poImagesTitle.textContent = `PO #${poId}`;
            await refreshImages();
            poImagesModal.classList.remove('hidden');
            poImagesModal.classList.add('flex');
        }

        async function duplicatePO(e) {
            const tr = e.target.closest('tr'); if (!tr) return;
            const poId = parseInt(tr.getAttribute('data-po-id'), 10);
            const resp = await fetch(`/api/procurement/orders/${poId}/duplicate`, {method:'POST'});
            const json = await resp.json();
            if (!json.success) { showToast && showToast(json.error || 'Napaka pri podvajanju', 'danger'); return; }
            showToast && showToast('Naročilo podvojeno (DRAFT)', 'success');
            await fetchPOs();
        }

        async function archivePO(e) {
            const tr = e.target.closest('tr'); if (!tr) return;
            const poId = parseInt(tr.getAttribute('data-po-id'), 10);
            if (!confirm('Arhiviram naročilo?')) return;
            const resp = await fetch(`/api/procurement/orders/${poId}/archive`, {method:'POST'});
            const json = await resp.json();
            if (!json.success) { showToast && showToast(json.error || 'Napaka pri arhiviranju', 'danger'); return; }
            showToast && showToast('Naročilo arhivirano', 'success');
            await fetchPOs();
        }

        function closeImagesModal() {
            poImagesModal.classList.add('hidden');
            poImagesModal.classList.remove('flex');
        }

        async function refreshImages() {
            if (!currentPOId) return;
            const res = await fetch(`/api/purchase-orders/${currentPOId}/images`);
            let json;
            try { json = await res.json(); } catch { json = []; }
            const images = Array.isArray(json) ? json : (json && Array.isArray(json.data) ? json.data : []);
            poImagesList.innerHTML = images.map(img => `
                <div class="border rounded overflow-hidden">
                    <div class="p-2 flex items-center justify-between text-xs">
                        <span>${(img.uploaded_at||'').toString().slice(0,19).replace('T',' ')}</span>
                        <div class="flex items-center gap-2">
                            <a href="/api/purchase-orders/proxy/${encodeURIComponent(img.s3_key)}" target="_blank" class="text-blue-600 hover:underline">Odpri</a>
                            <a href="/api/purchase-orders/proxy/${encodeURIComponent(img.s3_key)}" download class="text-blue-600 hover:underline">Prenesi</a>
                            <button data-id="${img.id}" class="po-img-del text-red-600 hover:underline">Izbriši</button>
                        </div>
                    </div>
                    <img src="/api/purchase-orders/proxy/${encodeURIComponent(img.s3_key)}" class="w-full h-40 object-cover" />
                </div>
            `).join('');
            poImagesList.querySelectorAll('.po-img-del').forEach(btn => btn.addEventListener('click', async (e) => {
                const id = parseInt(e.target.getAttribute('data-id'), 10);
                await fetch(`/api/purchase-orders/images/${id}`, {method:'DELETE'});
                await refreshImages();
            }));
        }

        async function uploadImage() {
            const file = poImageFile && poImageFile.files && poImageFile.files[0];
            if (!file || !currentPOId) return;
            const fd = new FormData();
            fd.append('image', file);
            await fetch(`/api/purchase-orders/${currentPOId}/images`, {method:'POST', body: fd});
            poImageFile.value = '';
            await refreshImages();
        }


        async function addToCart() {
            if (window.__procAddInFlight) return;
            const product_no = (productNoInput.value || '').trim();
            const supplier = (supplierSelect.value || '').toUpperCase();
            const qty = Math.max(1, parseInt(qtyInput.value || '1', 10));
            if (!product_no || !supplier) return;
            try {
                const targetEl = document.getElementById('proc-manual-target');
                const target = targetEl ? targetEl.value : 'order';
                if (addBtn && addBtn.disabled) return;
                window.__procAddInFlight = true;
                if (addBtn) addBtn.disabled = true;
                const isProc = isProcOnlySupplier(supplier);
                if (target === 'order') {
                    if (isProc) {
                        const resp = await fetch('/api/procurement2/cart/add', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ supplier, sku: product_no, qty })
                        });
                        const j = await resp.json().catch(()=>({success:false}));
                        if (!resp.ok || !j.success) {
                            const errMsg = (j && j.error && (j.error.message || j.error)) || 'SKU ne obstaja pri dobavitelju';
                            window.showToast && window.showToast(errMsg, 'danger');
                            return;
                        }
                        await fetchStock();
                        window.showToast && window.showToast('Dodano na naročilo', 'success');
                    } else {
                        // pridobi proizvajalec_id za izbran product_no in supplier
                        let proizvajalec_id = null;
                        try {
                            const res = await fetch(`/api/procurement/search-perfumes?q=${encodeURIComponent(product_no)}&limit=5&supplier=${encodeURIComponent(supplier)}`);
                            const js = await res.json();
                            const rows = (js.success ? (js.data||[]) : []).filter(r => (r.proizvajalec||'').toUpperCase() === supplier && r.product_no === product_no);
                            if (rows.length > 0) proizvajalec_id = rows[0].proizvajalec_id;
                        } catch {}
                        if (!proizvajalec_id) return;
                        const resp = await fetch('/api/procurement/cart/add', {
                            method: 'POST', headers: {'Content-Type':'application/json'},
                            body: JSON.stringify({product_no, proizvajalec_id, qty})
                        });
                        await resp.json();
                        await fetchStock();
                        window.showToast && window.showToast('Dodano na naročilo', 'success');
                    }
                } else {
                    if (isProc) {
                        const resp = await fetch('/api/procurement2/stock/add-onhand', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ supplier, sku: product_no, qty })
                        });
                        const j = await resp.json().catch(()=>({success:false}));
                        if (!resp.ok || !j.success) {
                            const errMsg = (j && j.error && (j.error.message || j.error)) || 'SKU ne obstaja pri dobavitelju';
                            window.showToast && window.showToast(errMsg, 'danger');
                            return;
                        }
                        await fetchStock();
                        window.showToast && window.showToast('Dodano v predal', 'success');
                    } else {
                        // pridobi proizvajalec_id kot zgoraj
                        let proizvajalec_id = null;
                        try {
                            const res = await fetch(`/api/procurement/search-perfumes?q=${encodeURIComponent(product_no)}&limit=5&supplier=${encodeURIComponent(supplier)}`);
                            const js = await res.json();
                            const rows = (js.success ? (js.data||[]) : []).filter(r => (r.proizvajalec||'').toUpperCase() === supplier && r.product_no === product_no);
                            if (rows.length > 0) proizvajalec_id = rows[0].proizvajalec_id;
                        } catch {}
                        if (!proizvajalec_id) return;
                        await fetch('/api/procurement/stock/add-onhand', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({product_no, proizvajalec_id, qty})});
                        await fetchStock();
                        window.showToast && window.showToast('Dodano v predal', 'success');
                    }
                }
                if (productSearch) productSearch.value = '';
                if (productNoInput) productNoInput.value = '';
                if (qtyInput) qtyInput.value = '1';
                if (productSearch) productSearch.focus();
            } catch {}
            finally { window.__procAddInFlight = false; if (addBtn) addBtn.disabled = false; }
        }
        async function clearCart() {
            const supplier = supplierSelect.value;
            if (!supplier) return;
            try {
                const resp = await fetch(`/api/procurement/cart/clear?supplier=${encodeURIComponent(supplier)}`, {method:'POST'});
                await resp.json();
                await fetchStock();
                window.showToast && window.showToast('Košarica izpraznjena', 'info');
            } catch {}
        }
        async function submitOrder() {
            const supplier = supplierSelect.value;
            if (!supplier) { window.showToast && window.showToast('Izberi dobavitelja.', 'danger'); return; }
            if (submitBtn && submitBtn.disabled) return;
            if (submitBtn) submitBtn.disabled = true;
            try {
                const resp = await fetch('/api/procurement/orders/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier})});
                const json = await resp.json().catch(() => ({success:false}));
                if (!resp.ok || !json.success) {
                    window.showToast && window.showToast(json.error || 'Košarica je prazna ali napaka pri ustvarjanju naročila.', 'danger');
                    return;
                }
                const id = json.data && json.data.purchase_order_id;
                if (!id) { window.showToast && window.showToast('Napaka: manjka ID naročila.', 'danger'); return; }
                const resp2 = await fetch(`/api/procurement/orders/submit/${id}`, {method:'POST'});
                const json2 = await resp2.json().catch(() => ({success:false}));
                if (!resp2.ok || !json2.success) {
                    window.showToast && window.showToast(json2.error || 'Napaka pri oddaji naročila.', 'danger');
                    return;
                }
                await fetchStock();
                window.showToast && window.showToast('Naročilo oddano', 'success');
            } catch (e) {
                window.showToast && window.showToast('Napaka pri oddaji naročila.', 'danger');
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        }

        // Ponovno oddaj DRAFT -> SUBMITTED (uporabi gumb v tabeli, ko je status DRAFT)
        async function resubmitDraft(poId) {
            // Submit že obstoječ DRAFT: transponiramo requested_qty v committed in status na SUBMITTED
            const resp = await fetch(`/api/procurement/orders/submit/${poId}`, {method:'POST'});
            const json = await resp.json();
            if (!json.success) { showToast && showToast(json.error || 'Napaka pri oddaji', 'danger'); return; }
            showToast && showToast('Naročilo ponovno oddano', 'success');
            await fetchPOs();
            await fetchStock();
        }

        supplierSelect && supplierSelect.addEventListener('change', () => {
            // Persist last selection so the user can resume work without
            // re-picking a supplier on every page load.
            try {
                if (supplierSelect.value) localStorage.setItem('proc:lastSupplier', supplierSelect.value);
                else localStorage.removeItem('proc:lastSupplier');
            } catch (_) {}
            // počisti izbor artikla in osveži odvisnosti
            if (productSearch) productSearch.value = '';
            if (productNoInput) productNoInput.value = '';
            fetchStock(); fetchPOs(); fetchProizvajalci();
            // Enable/disable dependent controls with hints
            const hasSupplier = !!(supplierSelect && supplierSelect.value);
            if (productSearch) {
                productSearch.disabled = !hasSupplier;
                productSearch.classList.toggle('cursor-not-allowed', !hasSupplier);
                productSearch.classList.toggle('opacity-60', !hasSupplier);
                productSearch.placeholder = hasSupplier ? 'Išči parfum po imenu ali Product No...' : 'Najprej izberi dobavitelja';
            }
            if (qtyInput) {
                qtyInput.disabled = !hasSupplier;
                qtyInput.classList.toggle('cursor-not-allowed', !hasSupplier);
                qtyInput.classList.toggle('opacity-60', !hasSupplier);
            }
            const stockSearchEl = document.getElementById('proc-stock-search');
            if (stockSearchEl) {
                stockSearchEl.disabled = !hasSupplier;
                stockSearchEl.classList.toggle('cursor-not-allowed', !hasSupplier);
                stockSearchEl.classList.toggle('opacity-60', !hasSupplier);
                stockSearchEl.placeholder = hasSupplier ? 'Išči parfum ali Product No...' : 'Najprej izberi dobavitelja';
            }
        }, { once: false });
        stockSearch && stockSearch.addEventListener('input', () => {
            // debounce
            clearTimeout(window.__procStockTimer);
            window.__procStockTimer = setTimeout(async () => {
                await fetchStock();
                // Consolidated search: if the table is empty after a search
                // AND the supplier is procurement-only (not perfume), offer to
                // add the SKU as a new product right from the search box.
                try {
                    const sup = (supplierSelect.value || '').toUpperCase();
                    const q = (stockSearch.value || '').trim();
                    if (!sup || !q || !isProcOnlySupplier(sup)) return;
                    if (stockBody.children.length > 0) return;
                    stockBody.innerHTML = `
                        <tr class="proc-add-suggestion">
                            <td colspan="8" class="px-4 py-4 text-center">
                                <button id="proc-quick-add" class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white" style="background-color:#00AEB3;">
                                    <i class="bi bi-plus-lg"></i> Dodaj nov artikel "<span class="font-mono">${q.replace(/[<>&"]/g, '')}</span>" k dobavitelju ${sup}
                                </button>
                                <div class="text-xs text-gray-500 mt-2">Odpre pogovorno okno s polji za ime, ceno in zalogo.</div>
                            </td>
                        </tr>`;
                    const qbtn = document.getElementById('proc-quick-add');
                    if (qbtn) qbtn.addEventListener('click', async () => {
                        const name = prompt(`Ime artikla za SKU "${q}"?`, q);
                        if (!name) return;
                        const priceStr = prompt('Cena (EUR)?', '0');
                        const price = parseFloat((priceStr || '0').replace(',', '.')) || 0;
                        try {
                            // Reuse the Excel import endpoint with a single row.
                            const fd = new FormData();
                            const csv = `supplier,sku,name,unit,price,min_on_hand,on_hand\n${sup},${q},${name.replace(/,/g, ' ')},kos,${price},0,0\n`;
                            // Build a minimal xlsx-equivalent via blob+filename; backend accepts xlsx only.
                            // Instead, use /api/procurement2/stock/add-onhand pre-create path:
                            //   first create row via vendors/import is complex — fallback to a tiny dedicated endpoint
                            const resp = await fetch('/api/procurement2/products/quick-add', {
                                method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ supplier: sup, sku: q, name, price })
                            });
                            const json = await resp.json().catch(() => ({ success: false }));
                            if (!resp.ok || !json.success) {
                                window.showToast && window.showToast(json.error || 'Dodajanje ni uspelo', 'danger');
                                return;
                            }
                            window.showToast && window.showToast(`Dodan artikel ${q}`, 'success');
                            stockSearch.value = '';
                            await fetchStock();
                        } catch (e) {
                            window.showToast && window.showToast('Napaka pri dodajanju artikla', 'danger');
                        }
                    });
                } catch (_) {}
            }, 200);
        });
        hideZero && hideZero.addEventListener('change', fetchStock);
        const moreFilters = document.getElementById('proc-more-filters');
        if (moreFilters && !moreFilters.dataset.bound){
            moreFilters.addEventListener('change', ()=>{
                const val = moreFilters.value;
                const out = document.getElementById('proc-filter-out');
                const low = document.getElementById('proc-filter-low');
                if (out) out.checked = (val === 'out');
                if (low) low.checked = (val === 'low');
                fetchStock();
            });
            moreFilters.dataset.bound='1';
        }
        // Potrdi čiščenje naročila (idempotentno binding) – skrij za ne-admin
        if (clearBtn && !clearBtn.dataset.boundConfirm) {
            clearBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!confirm('Ali res želite počistiti naročilo?')) return;
                if (!supplierSelect || !supplierSelect.value) { window.showToast && window.showToast('Najprej izberi dobavitelja.', 'warning'); return; }
                // izberi pravilen endpoint
                const supplier = (supplierSelect.value||'').toUpperCase();
                const isProc = isProcOnlySupplier(supplier);
                const url = isProc ? `/api/procurement2/cart/clear?supplier=${encodeURIComponent(supplier)}` : `/api/procurement/cart/clear?supplier=${encodeURIComponent(supplier)}`;
                try {
                    const resp = await fetch(url, { method:'POST' });
                    const js = await resp.json().catch(()=>({success:false}));
                    if (!resp.ok || !js.success) { window.showToast && window.showToast(js.error || 'Čiščenje ni uspelo (samo za admin).', 'danger'); return; }
                    await fetchStock();
                    window.showToast && window.showToast('Košarica izpraznjena', 'info');
                } catch {
                    window.showToast && window.showToast('Napaka pri čiščenju.', 'danger');
                }
            });
            clearBtn.dataset.boundConfirm = '1';
            try {
                const isAdmin = typeof hasUserPermission === 'function' ? hasUserPermission('edit_users') : false;
                if (!isAdmin) { clearBtn.style.display = 'none'; }
            } catch {}
        }
        if (addBtn && !addBtn.dataset.bound) {
            addBtn.addEventListener('click', addToCart);
            addBtn.dataset.bound = '1';
        }
        if (productSearch && !productSearch.dataset.boundInput) {
            productSearch.addEventListener('input', () => {
                clearTimeout(window.__procProdTimer);
                window.__procProdTimer = setTimeout(searchProducts, 200);
            });
            productSearch.dataset.boundInput = '1';
        }
        // Admin-only import/template UI + hide users tab actions without manage_users
        try {
            const isAdmin = typeof hasUserPermission === 'function' ? hasUserPermission('view_admin_tabs') : false;
            const importLabel = document.getElementById('proc-import-label');
            const importTpl = document.getElementById('proc-import-template');
            if (!isAdmin) {
                if (importLabel) importLabel.style.display = 'none';
                if (importTpl) importTpl.style.display = 'none';
            }
            // In users panel, hide dangerous actions unless manage_users
            const canManageUsers = typeof hasUserPermission === 'function' ? hasUserPermission('manage_users') : false;
            const addUserBtn = document.getElementById('add-user-btn');
            if (addUserBtn) addUserBtn.style.display = canManageUsers ? '' : 'none';
            document.querySelectorAll('#users-table-body button').forEach(btn => {
                if (/Dovoljenja|Izbriši|Spremeni geslo/.test(btn.innerText)) {
                    btn.style.display = canManageUsers ? '' : 'none';
                }
            });
        } catch {}
        // Keyboard navigation for product results (UP/DOWN + Enter highlight)
        if (productSearch && productResults && !productSearch.dataset.boundKeyNav) {
            const scrollIfNeeded = (container, el) => {
                if (!container || !el) return;
                const top = el.offsetTop;
                const bottom = top + el.offsetHeight;
                const viewTop = container.scrollTop;
                const viewBottom = viewTop + container.clientHeight;
                if (top < viewTop) {
                    container.scrollTop = top;
                } else if (bottom > viewBottom) {
                    container.scrollTop = bottom - container.clientHeight;
                }
            };
            productSearch.addEventListener('keydown', (e) => {
                const items = Array.from(productResults.querySelectorAll('[data-product-no], [data-sku]'));
                if (!items.length) return;
                if (prodActiveIndex < -1 || prodActiveIndex >= items.length) prodActiveIndex = -1;
                const clearHighlights = () => items.forEach(el => el.classList.remove('ts-active-item','bg-cyan-100'));
                const applyHighlight = (el) => { el.classList.add('ts-active-item','bg-cyan-100'); };
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    prodActiveIndex = (prodActiveIndex < 0) ? 0 : Math.min(items.length - 1, prodActiveIndex + 1);
                    clearHighlights();
                    applyHighlight(items[prodActiveIndex]);
                    // Only scroll if out of view to avoid initial jump
                    scrollIfNeeded(productResults, items[prodActiveIndex]);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    prodActiveIndex = (prodActiveIndex < 0) ? 0 : Math.max(0, prodActiveIndex - 1);
                    clearHighlights();
                    applyHighlight(items[prodActiveIndex]);
                    scrollIfNeeded(productResults, items[prodActiveIndex]);
                }
            });
            productSearch.dataset.boundKeyNav = '1';
        }
        // ENTER na iskalnem polju: če je označen rezultat, ga izberi (nastavi name + product_no/SKU) in fokus premakni na količino
        if (productSearch && !productSearch.dataset.boundEnter) {
            productSearch.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter') return;
                e.preventDefault();
                const highlighted = productResults && productResults.querySelector('.ts-active-item');
                let pick = highlighted;
                if (!pick) {
                    const list = productResults && productResults.querySelectorAll('[data-product-no], [data-sku]');
                    if (list && list.length) pick = list[0];
                }
                if (pick) {
                    if (pick.hasAttribute('data-product-no')) {
                        const pn = pick.getAttribute('data-product-no');
                        if (productNoInput) productNoInput.value = pn;
                    } else if (pick.hasAttribute('data-sku')) {
                        const sku = pick.getAttribute('data-sku');
                        if (productNoInput) productNoInput.value = sku;
                    }
                    const nm = pick.getAttribute('data-name') || '';
                    if (nm && productSearch) productSearch.value = nm;
                    if (productResults) { productResults.innerHTML = ''; productResults.classList.add('hidden'); }
                    prodActiveIndex = -1;
                }
                if (qtyInput && !qtyInput.disabled) { qtyInput.focus(); qtyInput.select(); }
            });
            productSearch.dataset.boundEnter = '1';
        }

        // ENTER na količini sproži dodajanje; če je izbran po imenu, najprej razreši product_no/SKU
        if (qtyInput && !qtyInput.dataset.boundEnter) {
            qtyInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    // Ensure product_no/SKU resolved when user selected by name
                    const supplier = (supplierSelect.value||'').toUpperCase();
                    const typed = (productSearch && productSearch.value || '').trim();
                    const picked = (productNoInput && productNoInput.value || '').trim();
                    if (!picked && typed) {
                        // Try resolve to product_no for perfumes if needed
                        if (!isProcOnlySupplier(supplier)) {
                            fetch(`/api/procurement/search-perfumes?q=${encodeURIComponent(typed)}&limit=1&supplier=${encodeURIComponent(supplier)}`)
                              .then(r=>r.json()).then(js=>{
                                  const rows = (js.success ? (js.data||[]) : []).filter(r => (r.proizvajalec||'').toUpperCase() === supplier);
                                  if (rows.length && productNoInput) productNoInput.value = rows[0].product_no;
                              }).finally(()=>addToCart());
                            return;
                        } else {
                            fetch(`/api/procurement2/search?q=${encodeURIComponent(typed)}&supplier=${encodeURIComponent(supplier)}`)
                              .then(r=>r.json()).then(js=>{
                                  const rows = (js.success ? (js.data||[]) : []);
                                  if (rows.length && productNoInput) productNoInput.value = rows[0].sku;
                              }).finally(()=>addToCart());
                            return;
                        }
                    }
                    addToCart();
                }
            });
            qtyInput.dataset.boundEnter = '1';
        }
        bindProductResults();
        if (submitBtn && !submitBtn.dataset.bound) {
            submitBtn.addEventListener('click', async () => {
                await submitOrder();
                await fetchPOs();
            });
            submitBtn.dataset.bound = '1';
        }
        poStatusFilter && poStatusFilter.addEventListener('change', fetchPOs);
        poReceiveClose && poReceiveClose.addEventListener('click', closeReceiveModal);
        if (poReceiveSubmit && !poReceiveSubmit.dataset.bound) {
            poReceiveSubmit.addEventListener('click', submitReceive);
            poReceiveSubmit.dataset.bound = '1';
        }
        poImagesClose && poImagesClose.addEventListener('click', closeImagesModal);
        poOpenImages && poOpenImages.addEventListener('click', async () => {
            if (!currentPOId) {
                const fallback = poReceiveModal && poReceiveModal.dataset && poReceiveModal.dataset.poId ? parseInt(poReceiveModal.dataset.poId, 10) : null;
                if (fallback) { currentPOId = fallback; }
            }
            if (!currentPOId) return;
            poImagesTitle.textContent = `PO #${currentPOId}`;
            await refreshImages();
            poImagesModal.classList.remove('hidden');
            poImagesModal.classList.add('flex');
        });
        poImageUpload && poImageUpload.addEventListener('click', uploadImage);

        // Prejem naročila – identična UX kot Vrnjeni & poškodovani za nalaganje slik
        const prCamBtn = document.getElementById('po-rec-camera-btn');
        const prGalBtn = document.getElementById('po-rec-gallery-btn');
        const prFileBtn = document.getElementById('po-rec-file-btn');
        const prCamInput = document.getElementById('po-rec-camera-input');
        const prMobInput = document.getElementById('po-rec-mobile-image-input');
        const prFile = document.getElementById('po-rec-images');
        const prPreview = document.getElementById('po-rec-selected-images-preview');
        const prList = document.getElementById('po-rec-selected-images-list');

        function prShowSelected(files) {
            if (!prPreview || !prList) return;
            // Ne briši že izbranih; dodajaj nove (kot pri Vrnjeni & poškodovani)
            Array.from(files || []).forEach((file) => {
                const reader = new FileReader();
                reader.onload = (e) => {
                    const div = document.createElement('div');
                    div.innerHTML = `<div class="bg-white rounded-lg border border-gray-200 overflow-hidden"><img src="${e.target.result}" class="w-full h-24 object-cover" alt="Izbrana slika"></div>`;
                    prList.appendChild(div.firstElementChild);
                };
                reader.readAsDataURL(file);
            });
            prPreview.classList.remove('hidden');
        }

        const prOnAnyChange = async (e) => {
            e && e.stopPropagation && e.stopPropagation();
            const files = e && e.target && e.target.files ? e.target.files : prFile && prFile.files;
            if (!files || !files.length) return;
            prShowSelected(files);
            // tudi naloži na strežnik (kot RD) – zahteva currentPOId
            if (!currentPOId) return;
            for (const file of Array.from(files)) {
                const fd = new FormData(); fd.append('image', file);
                const up = await fetch(`/api/purchase-orders/${currentPOId}/images`, {method:'POST', body: fd});
                if (!up.ok) { showToast && showToast('Napaka pri nalaganju slike.', 'danger'); break; }
            }
            await refreshImages();
        };

        if (prCamBtn && prCamInput && !prCamBtn.dataset.bound) { prCamBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); prCamInput.click(); }); prCamBtn.dataset.bound = '1'; }
        if (prGalBtn && prMobInput && !prGalBtn.dataset.bound) { prGalBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); prMobInput.click(); }); prGalBtn.dataset.bound = '1'; }
        if (prFileBtn && prFile && !prFileBtn.dataset.bound) { prFileBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); prFile.click(); }); prFileBtn.dataset.bound = '1'; }
        if (prCamInput && !prCamInput.dataset.bound) { prCamInput.addEventListener('change', prOnAnyChange); prCamInput.dataset.bound = '1'; }
        if (prMobInput && !prMobInput.dataset.bound) { prMobInput.addEventListener('change', prOnAnyChange); prMobInput.dataset.bound = '1'; }
        if (prFile && !prFile.dataset.bound) { prFile.addEventListener('change', prOnAnyChange); prFile.dataset.bound = '1'; }

        // Inicialno naloži sezname
        await fetchPOs();
        
        // Manual receive logic
        async function manualEnsurePO() {
            if (manualPOId) return manualPOId;
            const sup = (manualSupplier && manualSupplier.value || '').toUpperCase();
            if (!sup) { showToast && showToast('Izberi dobavitelja.', 'danger'); return null; }
            const res = await fetch('/api/procurement/receive/manual/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier: sup})});
            const js = await res.json();
            if (!js.success) { showToast && showToast(js.error || 'Napaka pri kreiranju prejemnice', 'danger'); return null; }
            manualPOId = js.data.purchase_order_id;
            return manualPOId;
        }

        async function manualRefreshImages() {
            if (!manualPOId) return;
            const r = await fetch(`/api/purchase-orders/${manualPOId}/images`);
            let j; try { j = await r.json(); } catch { j = []; }
            const images = Array.isArray(j) ? j : (j && Array.isArray(j.data) ? j.data : []);
            if (manualImgs) manualImgs.innerHTML = images.map(img => `<img src="/api/purchase-orders/proxy/${encodeURIComponent(img.s3_key)}" class="w-full h-28 object-cover rounded border" />`).join('');
        }

        async function manualSearchProducts() {
            const q = (manualSearch && manualSearch.value || '').trim();
            const sup = (manualSupplier && manualSupplier.value || '').toUpperCase();
            if (!q || !sup) { manualResults && (manualResults.classList.add('hidden'), manualResults.innerHTML=''); return; }
            const resp = await fetch(`/api/procurement/search-perfumes?q=${encodeURIComponent(q)}&limit=50&supplier=${encodeURIComponent(sup)}`);
            let js;
            try { js = await resp.json(); } catch { js = {success:false, data: []}; }
            const base = Array.isArray(js) ? js : (js && js.data ? js.data : []);
            const rows = base.filter(r => (r.proizvajalec||'').toUpperCase() === sup);
            if (!rows.length) { manualResults && (manualResults.classList.add('hidden'), manualResults.innerHTML=''); return; }
            manualResults.innerHTML = rows.map(r => `<div data-product-no="${r.product_no}" data-proizvajalec-id="${r.proizvajalec_id}" class="px-3 py-2 hover:bg-gray-100 cursor-pointer"><div class="text-sm font-medium">${r.ime_parfuma||''}</div><div class="text-xs text-gray-600">${r.product_no} • ${r.proizvajalec}</div></div>`).join('');
            manualResults.classList.remove('hidden');
            manualResults.querySelectorAll('div[data-product-no]')
                .forEach(el => el.addEventListener('click', () => {
                    const pno = el.getAttribute('data-product-no');
                    const pid = parseInt(el.getAttribute('data-proizvajalec-id'), 10);
                    manualSearch.value = `${pno}`;
                    manualSearch.dataset.productNo = pno;
                    manualSearch.dataset.proizvajalecId = String(pid);
                    manualResults.classList.add('hidden');
                }));
        }

        async function manualAddItem() {
            const sup = (manualSupplier && manualSupplier.value || '').toUpperCase(); if (!sup) { showToast && showToast('Izberi dobavitelja.', 'danger'); return; }
            const pno = manualSearch && manualSearch.dataset.productNo; const pid = manualSearch && parseInt(manualSearch.dataset.proizvajalecId||'0',10);
            const qty = Math.max(1, parseInt(manualQty && manualQty.value || '1', 10));
            if (!pno || !pid || qty <= 0) { showToast && showToast('Izberi artikel in količino.', 'danger'); return; }
            await manualEnsurePO(); if (!manualPOId) return;
            // render into table (client-only, commit later)
            const row = document.createElement('tr');
            row.setAttribute('data-product-no', pno);
            row.setAttribute('data-proizvajalec-id', String(pid));
            row.innerHTML = `<td class=\"px-4 py-2 font-mono\">${pno}</td><td class=\"px-4 py-2\">${manualSearch.value}</td><td class=\"px-4 py-2 text-right\"><input type=\"number\" class=\"w-24 px-2 py-1 border rounded manual-recv-input\" min=\"1\" value=\"${qty}\" /></td><td class=\"px-4 py-2 text-right\"><button class=\"manual-recv-del px-2 py-1 border rounded text-xs\">Odstrani</button></td>`;
            manualBody && manualBody.appendChild(row);
            row.querySelector('.manual-recv-del').addEventListener('click', () => row.remove());
            manualSearch.value = '';
            delete manualSearch.dataset.productNo; delete manualSearch.dataset.proizvajalecId;
        }

        async function manualUploadImage() {
            if (!manualPOId) { await manualEnsurePO(); }
            if (!manualPOId) return;
            const file = manualImgFile && manualImgFile.files && manualImgFile.files[0];
            if (!file) return;
            const fd = new FormData(); fd.append('image', file);
            await fetch(`/api/purchase-orders/${manualPOId}/images`, {method:'POST', body: fd});
            manualImgFile.value = '';
            await manualRefreshImages();
        }

        async function openManualReceive() {
            manualPOId = null; manualBody && (manualBody.innerHTML = ''); manualImgs && (manualImgs.innerHTML = ''); manualSearch && (manualSearch.value = '');
            // load suppliers
            try {
                const res = await fetch('/api/procurement/suppliers');
                const js = await res.json();
                if (js.success && manualSupplier) {
                    manualSupplier.innerHTML = '<option value=\"\">Izberi dobavitelja</option>' + js.data.map(s => `<option value=\"${s}\">${s}</option>`).join('');
                }
            } catch {}
            manualModal && manualModal.classList.remove('hidden');
            manualModal && manualModal.classList.add('flex');
        }

        async function closeManualReceive() {
            manualModal && manualModal.classList.add('hidden');
            manualModal && manualModal.classList.remove('flex');
        }

        async function manualCommit() {
            if (!manualPOId) { showToast && showToast('Dodaj vsaj en artikel.', 'danger'); return; }
            // require image
            const r = await fetch(`/api/purchase-orders/${manualPOId}/images`); let j; try { j = await r.json(); } catch { j = []; }
            const imgs = Array.isArray(j) ? j : (j && Array.isArray(j.data) ? j.data : []);
            if (!imgs || imgs.length === 0) { showToast && showToast('Za prejem je obvezna vsaj ena slika.', 'danger'); return; }
            const items = [];
            manualBody && manualBody.querySelectorAll('tr').forEach(tr => {
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id'), 10);
                const input = tr.querySelector('.manual-recv-input');
                const received_qty = Math.max(1, parseInt((input && input.value) || '1', 10));
                if (received_qty > 0) items.push({product_no, proizvajalec_id, received_qty});
            });
            if (!items.length) { showToast && showToast('Dodaj vsaj en artikel.', 'danger'); return; }
            manualSubmit && (manualSubmit.disabled = true);
            const resp = await fetch(`/api/procurement/receive/manual/commit/${manualPOId}`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({items, require_image: true})});
            const js = await resp.json().catch(() => ({success:false}));
            manualSubmit && (manualSubmit.disabled = false);
            if (!resp.ok || !js.success) { showToast && showToast(js.error || 'Napaka pri potrditvi prejema', 'danger'); return; }
            showToast && showToast('Prejem ročno uspešen', 'success');
            await closeManualReceive();
            await fetchStock();
            await fetchPOs();
        }

        manualOpen && manualOpen.addEventListener('click', openManualReceive);
        manualClose && manualClose.addEventListener('click', closeManualReceive);
        manualSearch && manualSearch.addEventListener('input', () => { clearTimeout(window.__manRecvTimer); window.__manRecvTimer = setTimeout(manualSearchProducts, 250); });
        manualAdd && manualAdd.addEventListener('click', manualAddItem);
        manualImgUpload && manualImgUpload.addEventListener('click', manualUploadImage);
        manualSubmit && manualSubmit.addEventListener('click', manualCommit);
        bulkOnhandBtn && bulkOnhandBtn.addEventListener('click', async () => {
            const supplier = supplierSelect.value; if (!supplier) return;
            const updates = [];
            stockBody.querySelectorAll('tr').forEach(tr => {
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id'), 10);
                const input = tr.querySelector('.onhand-input');
                const val = parseInt((input && input.value) || '0', 10);
                if (!isNaN(val)) updates.push({product_no, proizvajalec_id, on_hand: val});
            });
            if (updates.length === 0) return;
            await fetch('/api/procurement/stock/bulk-onhand', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier, updates})});
            await fetchStock();
            window.showToast && window.showToast('Shranjeno V predalu', 'success');
        });

        function openOnhandModal() {
            const supplier = supplierSelect.value; if (!supplier) return;
            onhandSupplierLbl.textContent = supplier;
            onhandSearch.value = '';
            onhandModal.classList.remove('hidden');
            onhandModal.classList.add('flex');
            loadOnhandTable();
        }

        function closeOnhandModal() {
            onhandModal.classList.add('hidden');
            onhandModal.classList.remove('flex');
        }

        async function loadOnhandTable() {
            const supplier = supplierSelect.value; if (!supplier) return;
            const res = await fetch(`/api/procurement/stock?supplier=${encodeURIComponent(supplier)}`);
            const json = await res.json();
            const rows = (json.success ? (json.data||[]) : []);
            const q = (onhandSearch.value||'').toLowerCase();
            const filtered = rows.filter(r => !q || (r.ime_parfuma||'').toLowerCase().includes(q) || (r.product_no||'').toLowerCase().includes(q));
            onhandBody.innerHTML = filtered.map(r => `
                <tr data-product-no="${r.product_no}" data-proizvajalec-id="${r.proizvajalec_id}">
                    <td class="px-4 py-2 font-mono">${r.product_no}</td>
                    <td class="px-4 py-2">${r.ime_parfuma || ''}</td>
                    <td class="px-4 py-2"><input type="number" class="w-24 px-2 py-1 border rounded onhand-input" value="${r.on_hand}" /></td>
                    <td class="px-4 py-2">${r.on_order_pending}</td>
                    <td class="px-4 py-2">${r.on_order_committed}</td>
                    <td class="px-4 py-2"><input type="number" class="w-20 px-2 py-1 border rounded min-onhand-input" value="${typeof r.min_on_hand==='number' ? r.min_on_hand : 0}" /></td>
                </tr>
            `).join('');
            onhandCount.textContent = `Število parfumov: ${filtered.length}`;
        }

        async function saveOnhandModal() {
            const supplier = supplierSelect.value; if (!supplier) return;
            const updates = [];
            onhandBody.querySelectorAll('tr').forEach(tr => {
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id'), 10);
                const input = tr.querySelector('.onhand-input');
                const val = parseInt((input && input.value) || '0', 10);
                if (!isNaN(val)) updates.push({product_no, proizvajalec_id, on_hand: val});
            });
            if (updates.length === 0) { closeOnhandModal(); return; }
            await fetch('/api/procurement/stock/bulk-onhand', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier, updates})});
            // Save thresholds
            const thresh = [];
            onhandBody.querySelectorAll('tr').forEach(tr => {
                const product_no = tr.getAttribute('data-product-no');
                const proizvajalec_id = parseInt(tr.getAttribute('data-proizvajalec-id'), 10);
                const input = tr.querySelector('.min-onhand-input');
                const val = parseInt((input && input.value) || '0', 10);
                thresh.push({product_no, proizvajalec_id, min_on_hand: Math.max(0, isNaN(val)?0:val)});
            });
            if (thresh.length>0) {
                await fetch('/api/procurement/stock/bulk-min', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({supplier, updates: thresh})});
            }
            await fetchStock();
            closeOnhandModal();
            window.showToast && window.showToast('V predalu shranjeno', 'success');
        }

        openOnhandBtn && openOnhandBtn.addEventListener('click', () => {
            if (!supplierSelect || !supplierSelect.value) {
                window.showToast && window.showToast('Najprej izberi dobavitelja.', 'warning');
                return;
            }
            openOnhandModal();
        });
        onhandClose && onhandClose.addEventListener('click', closeOnhandModal);
        onhandSave && onhandSave.addEventListener('click', saveOnhandModal);
        onhandSearch && onhandSearch.addEventListener('input', loadOnhandTable);

        await fetchSuppliers();
        await fetchProizvajalci();
        // Restore last picked supplier (saved in localStorage on change).
        try {
            const saved = localStorage.getItem('proc:lastSupplier');
            if (saved && supplierSelect && Array.from(supplierSelect.options).some(o => o.value === saved)) {
                supplierSelect.value = saved;
                supplierSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
        } catch (_) {}
        // Excel import za procurement-only
        try {
            const importInput = document.getElementById('proc-import-file');
            if (importInput && !importInput.dataset.bound) {
                importInput.dataset.bound = '1';
                importInput.addEventListener('change', async () => {
                    const file = importInput.files && importInput.files[0];
                    if (!file) return;
                    try {
                        const fd = new FormData(); fd.append('file', file);
                        const resp = await fetch('/api/procurement/vendors/import', { method: 'POST', body: fd });
                        const json = await resp.json().catch(()=>({success:false}));
                        if (!resp.ok || !json.success) { window.showToast && window.showToast(json.error || 'Napaka pri uvozu', 'danger'); return; }
                        window.showToast && window.showToast('Uvoz uspešen', 'success');
                        await fetchSuppliers();
                        await fetchStock();
                    } catch (e) {
                        console.error('Import error:', e);
                        window.showToast && window.showToast('Napaka pri uvozu', 'danger');
                    } finally {
                        importInput.value = '';
                    }
                });
            }
        } catch(_) {}
        // avtomatsko naloži stock, če je izbran dobavitelj
        if (supplierSelect && supplierSelect.value) {
            fetchStock();
        }

        // Stock movements history modal (last 20 entries for one row).
        window.__openProcHistory = async function(tr, supplierVal) {
            const modal = document.getElementById('proc-history-modal');
            const body = document.getElementById('proc-history-body');
            const subtitle = document.getElementById('proc-history-subtitle');
            if (!modal || !body) return;
            const isProc = isProcOnlySupplier(supplierVal);
            const key = tr.getAttribute(isProc ? 'data-sku' : 'data-product-no') || '';
            const nameCell = tr.querySelector('td:nth-child(2)');
            const name = nameCell ? nameCell.textContent.trim() : key;
            if (subtitle) subtitle.textContent = `${name} • ${supplierVal} • ${key}`;
            body.innerHTML = '<div class="text-gray-500 text-sm">Nalagam…</div>';
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            try {
                const url = isProc
                    ? `/api/procurement2/stock-movements?supplier=${encodeURIComponent(supplierVal)}&sku=${encodeURIComponent(key)}&limit=30`
                    : `/api/procurement/stock-movements?supplier=${encodeURIComponent(supplierVal)}&product_no=${encodeURIComponent(key)}&limit=30`;
                const resp = await fetch(url);
                const json = await resp.json().catch(() => ({}));
                const rows = (json && json.success && Array.isArray(json.data)) ? json.data : [];
                if (rows.length === 0) {
                    body.innerHTML = '<div class="text-gray-500 text-sm">Ni zapisov o gibanjih zaloge.</div>';
                    return;
                }
                const fmt = (iso) => { try { return new Date(iso).toLocaleString('sl-SI'); } catch (_) { return ''; } };
                const sourceLabel = (s) => {
                    if (s === 'serija') return 'Iztok (serija)';
                    if (s === 'shopify_orders/paid') return 'Shopify prodaja';
                    if (s === 'shopify_orders/cancelled') return 'Shopify preklic';
                    if (s === 'shopify_refund') return 'Shopify vračilo';
                    if (s === 'mk_bill') return 'MetaKocka račun';
                    if (s === 'mk_stock_webhook') return 'MetaKocka stock';
                    return s || '—';
                };
                body.innerHTML = rows.map(r => {
                    const at = fmt(r.at);
                    if (isProc) {
                        const delta = r.delta || 0;
                        const sign = delta > 0 ? '+' : '';
                        const color = delta < 0 ? 'text-red-600' : (delta > 0 ? 'text-green-700' : 'text-gray-700');
                        return `<div class="flex items-center justify-between border-b border-gray-100 py-2">
                            <div>
                                <div class="font-medium">${sourceLabel(r.source)}</div>
                                <div class="text-xs text-gray-500">${at}${r.source_ref ? ' • ' + r.source_ref : ''}${r.note ? ' • ' + r.note : ''}</div>
                            </div>
                            <div class="text-right">
                                <div class="font-mono ${color}">${sign}${delta}</div>
                                <div class="text-xs text-gray-500">${r.on_hand_before} → ${r.on_hand_after}</div>
                            </div>
                        </div>`;
                    } else {
                        return `<div class="flex items-center justify-between border-b border-gray-100 py-2">
                            <div>
                                <div class="font-medium">${sourceLabel(r.source)} ${r.serijska_stevilka ? `• ${r.serijska_stevilka}` : ''}</div>
                                <div class="text-xs text-gray-500">${at}${r.vnesel_uporabnik ? ' • ' + r.vnesel_uporabnik : ''}</div>
                            </div>
                            <div class="text-right text-xs text-gray-600">${r.stanje || ''}${r.rok_uporabe ? ' • do ' + r.rok_uporabe : ''}</div>
                        </div>`;
                    }
                }).join('');
            } catch (_) {
                body.innerHTML = '<div class="text-red-600 text-sm">Napaka pri nalaganju zgodovine.</div>';
            }
        };
        // Close button + backdrop click for history modal.
        const histModalEl = document.getElementById('proc-history-modal');
        const histCloseBtn = document.getElementById('proc-history-close');
        if (histCloseBtn && !histCloseBtn.dataset.bound) {
            histCloseBtn.dataset.bound = '1';
            histCloseBtn.addEventListener('click', () => {
                if (histModalEl) { histModalEl.classList.add('hidden'); histModalEl.classList.remove('flex'); }
            });
        }
        if (histModalEl && !histModalEl.dataset.bound) {
            histModalEl.dataset.bound = '1';
            histModalEl.addEventListener('click', (ev) => {
                if (ev.target === histModalEl) { histModalEl.classList.add('hidden'); histModalEl.classList.remove('flex'); }
            });
        }

        // Global keyboard shortcuts inside the procurement panel:
        //   "/"   focus stock search (when not typing in another field)
        //   "Esc" close any open proc modal
        // Bound once via a sentinel attribute on document.body.
        if (!document.body.dataset.procKbdBound) {
            document.body.dataset.procKbdBound = '1';
            document.addEventListener('keydown', (ev) => {
                const panel = document.getElementById('procurement-panel');
                if (!panel || panel.style.display === 'none') return;
                const tag = (ev.target && ev.target.tagName) ? ev.target.tagName.toLowerCase() : '';
                const isField = (tag === 'input' || tag === 'textarea' || tag === 'select') || (ev.target && ev.target.isContentEditable);
                if (ev.key === '/' && !isField) {
                    const el = document.getElementById('proc-stock-search');
                    if (el && !el.disabled) { ev.preventDefault(); el.focus(); el.select && el.select(); }
                } else if (ev.key === 'Escape') {
                    // Close any open procurement-related modal.
                    ['proc-history-modal', 'proc-onhand-modal', 'po-receive-modal', 'po-images-modal', 'manual-receive-modal'].forEach(id => {
                        const m = document.getElementById(id);
                        if (m && !m.classList.contains('hidden')) {
                            m.classList.add('hidden');
                            m.classList.remove('flex');
                        }
                    });
                }
            });
        }
    }
    window.loadProizvajalci = loadProizvajalci;
    window.fetchNarocila = fetchNarocila;
    window.fetchExpiringPerfumes = fetchExpiringPerfumes;
    window.displayCurrentUser = displayCurrentUser;
    window.initializeTooltips = initializeTooltips;
    
    // Navodila - nalaganje kategorij in navodil
    window.loadInstructionCategories = async function() {
        try {
            const res = await fetch('/api/instruction-categories');
            if (!res.ok) return;
            const cats = await res.json();
            const select = document.getElementById('instruction-category');
            if (!select) return;
            // ohrani prvo 'Vse kategorije'
            select.innerHTML = '<option value="">Vse kategorije</option>' +
                cats.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
            select.onchange = () => window.loadInstructions(select.value || '');
        } catch (e) {
            console.warn('Napaka pri nalaganju kategorij navodil:', e);
        }
    }
    window.loadInstructions = async function(categoryId = '') {
        try {
            const url = categoryId ? `/api/instructions?category_id=${encodeURIComponent(categoryId)}` : '/api/instructions';
            const res = await fetch(url);
            if (!res.ok) return;
            const items = await res.json();
            const list = document.getElementById('instructions-list');
            if (!list) return;
            if (!items || items.length === 0) {
                list.innerHTML = '<div class="text-gray-500">Ni navodil za prikaz.</div>';
                return;
            }
            const canManage = typeof hasUserPermission === 'function' ? hasUserPermission('edit_users') : false;
            list.innerHTML = items.map(i => {
                const meta = `${i.created_by ? `Avtor: ${i.created_by}` : ''} ${i.created_at ? ` · ${new Date(i.created_at).toLocaleString('sl-SI')}` : ''}`;
                const actions = canManage ? `
                    <div class="mt-3 flex items-center gap-2">
                        <button class="px-3 py-1 border rounded text-sm" data-action="edit-instruction" data-id="${i.id}">Uredi</button>
                        <label class="px-3 py-1 border rounded text-sm cursor-pointer">
                            Dodaj sliko
                            <input type="file" accept="image/*" data-action="upload-instruction-image" data-id="${i.id}" style="display:none" />
                        </label>
                        <button class="px-3 py-1 border rounded text-sm text-red-600" data-action="delete-instruction" data-id="${i.id}">Izbriši</button>
                    </div>
                ` : '';
                return `
                <div class="border border-gray-200 rounded-lg p-4" data-instruction="${i.id}">
                    <h4 class="text-md font-semibold text-gray-900 mb-2">${i.title}</h4>
                    <div class="instructions-content prose-sm max-w-none text-gray-800" data-role="content">${i.content}</div>
                    <div class="mt-2 text-xs text-gray-500">${meta}</div>
                    ${actions}
                    ${canManage ? `
                    <div class="mt-3 hidden" data-role="editor">
                        <input type="text" class="w-full mb-2 px-3 py-2 border rounded" data-field="title" value="${i.title}" />
                        <textarea class="w-full mb-2 px-3 py-2 border rounded" rows="8" data-field="content">${i.content.replace(/</g,'&lt;')}</textarea>
                        <div class="flex items-center gap-2">
                            <button class="px-3 py-2 bg-primary-600 text-white rounded" data-action="save-instruction" data-id="${i.id}">Shrani</button>
                            <button class="px-3 py-2 border rounded" data-action="cancel-edit" data-id="${i.id}">Prekliči</button>
                        </div>
                    </div>
                    ` : ''}
                </div>`;
            }).join('');

            if (canManage) {
                // Delegacija dogodkov za urejanje
                list.addEventListener('click', async (e) => {
                    const btn = e.target.closest('button, label');
                    if (!btn) return;
                    const action = btn.getAttribute('data-action');
                    const id = btn.getAttribute('data-id');
                    if (!action || !id) return;
                    const card = list.querySelector(`[data-instruction="${id}"]`);
                    if (!card) return;
                    const contentView = card.querySelector('[data-role="content"]');
                    const editor = card.querySelector('[data-role="editor"]');
                    if (action === 'edit-instruction') {
                        if (editor) editor.classList.remove('hidden');
                        if (contentView) contentView.style.display = 'none';
                    } else if (action === 'cancel-edit') {
                        if (editor) editor.classList.add('hidden');
                        if (contentView) contentView.style.display = '';
                    } else if (action === 'save-instruction') {
                        const titleEl = editor.querySelector('[data-field="title"]');
                        const contentEl = editor.querySelector('[data-field="content"]');
                        try {
                            const resSave = await fetch(`/api/instructions/${id}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ title: titleEl.value, content: contentEl.value })
                            });
                            if (!resSave.ok) throw new Error('Napaka pri shranjevanju navodila');
                            showToast('Navodilo shranjeno', 'success');
                            await window.loadInstructions(categoryId);
                        } catch (err) {
                            showToast(err.message, 'danger');
                        }
                    } else if (action === 'delete-instruction') {
                        if (!confirm('Ste prepričani, da želite izbrisati navodilo?')) return;
                        try {
                            const resDel = await fetch(`/api/instructions/${id}`, { method: 'DELETE' });
                            if (!resDel.ok) throw new Error('Napaka pri brisanju navodila');
                            showToast('Navodilo izbrisano', 'success');
                            await window.loadInstructions(categoryId);
                        } catch (err) {
                            showToast(err.message, 'danger');
                        }
                    }
                });

                // Upload slike
                list.addEventListener('change', async (e) => {
                    const input = e.target;
                    if (input.getAttribute('data-action') !== 'upload-instruction-image') return;
                    const id = input.getAttribute('data-id');
                    if (!input.files || input.files.length === 0) return;
                    const file = input.files[0];
                    const formData = new FormData();
                    formData.append('image', file);
                    try {
                        const resUp = await fetch(`/api/instructions/${id}/images`, { method: 'POST', body: formData });
                        if (!resUp.ok) throw new Error('Napaka pri nalaganju slike');
                        const data = await resUp.json();
                        // Vstavi sliko na konec vsebine
                        const card = list.querySelector(`[data-instruction="${id}"]`);
                        const editor = card?.querySelector('[data-role="editor"]');
                        const contentEl = editor?.querySelector('[data-field="content"]');
                        if (contentEl) {
                            contentEl.value = `${contentEl.value}\n\n<img src="${data.url}" alt="" />`;
                        }
                        showToast('Slika naložena', 'success');
                    } catch (err) {
                        showToast(err.message, 'danger');
                    } finally {
                        input.value = '';
                    }
                });
            }
        } catch (e) {
            console.warn('Napaka pri nalaganju navodil:', e);
        }
    }

    // --- Vrnjeni & poškodovani paketi ---
    let currentRDPage = 1;
    let currentRDSearch = '';
    let currentRDTypeFilter = '';
    
    window.loadReturnedDamaged = async function(page = 1, search = '', typeFilter = '') {
        try {
            console.log('loadReturnedDamaged called with:', { page, search, typeFilter });
            // Postavi parametre
            const params = new URLSearchParams({
                page: page.toString(),
                per_page: '10',
                search: search,
                type: typeFilter
            });
            
            console.log('Fetching:', `/api/returns?${params}`);
            const res = await fetch(`/api/returns?${params}`);
            console.log('API response status:', res.status, res.ok);
            if (!res.ok) {
                console.error('API response not OK:', res.status, res.statusText);
                return;
            }
            const data = await res.json();
            console.log('API response data:', data);
            console.log('API response data.data:', data.data);
            console.log('API response data.data?.all_items:', data.data?.all_items);
            console.log('API response data.data?.pagination:', data.data?.pagination);
            
            // Shrani trenutne filter vrednosti
            currentRDPage = page;
            currentRDSearch = search;
            currentRDTypeFilter = typeFilter;
            
            // Elementi
            const unifiedList = document.getElementById('rd-unified-list');
            const emptyDiv = document.getElementById('rd-unified-empty');
            const resultsInfo = document.getElementById('rd-results-info');
            const pagination = document.getElementById('rd-pagination');
            const pageInfo = document.getElementById('rd-page-info');
            const totalInfo = document.getElementById('rd-total-info');
            const prevBtn = document.getElementById('rd-prev-btn');
            const nextBtn = document.getElementById('rd-next-btn');
            
            console.log('DOM elements found:', {
                unifiedList: !!unifiedList,
                emptyDiv: !!emptyDiv,
                resultsInfo: !!resultsInfo,
                pagination: !!pagination
            });
            
            if (!unifiedList) {
                console.error('rd-unified-list element not found!');
                return;
            }
            const cardHtml = (rec) => `
                <div class="bg-white border border-gray-200 rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow">
                    <!-- Header with order number and actions -->
                    <div class="flex justify-between items-start mb-3">
                        <div class="flex-1">
                            <h5 class="text-sm font-semibold text-gray-900 mb-1">Naročilo ${rec.order_number}</h5>
                            <span class="inline-block px-2 py-1 rounded-full text-xs font-medium ${rec.type === 'returned' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                                ${rec.type === 'returned' ? 'Vrnjeno' : 'Poškodovano'}
                            </span>
                        </div>
                        <div class="flex gap-1 ml-2">
                            <button class="view-images-btn px-2 py-1 text-xs bg-blue-50 text-blue-600 rounded hover:bg-blue-100 transition-colors" 
                                    title="Poglej slike"
                                    data-order="${rec.order_number}" data-type="${rec.type}">
                                <i class="bi bi-eye"></i>
                            </button>
                            <button onclick="deleteReturnedDamagedRecord(${rec.id})" 
                                    class="px-2 py-1 text-xs bg-red-50 text-red-600 rounded hover:bg-red-100 transition-colors" 
                                    title="Izbriši zapis">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                    
                    <!-- Created by info -->
                    <div class="text-xs text-gray-500 mb-2">
                        <i class="bi bi-person-fill mr-1"></i>
                        Dodal: ${rec.created_by_name || 'Neznano'}
                    </div>
                    
                    <!-- Note if present -->
                    ${rec.note ? `
                        <div class="text-sm text-gray-600 mb-3 p-2 bg-gray-50 rounded border-l-4 border-gray-300">
                            ${rec.note.length > 100 ? `
                                <div id="note-short-${rec.id}">${rec.note.substring(0, 100)}...</div>
                                <div id="note-full-${rec.id}" class="hidden">${rec.note}</div>
                                <button onclick="toggleFullNote(${rec.id})" class="mt-1 text-xs text-blue-600 hover:text-blue-800 font-medium">
                                    <span id="note-btn-${rec.id}">Prikaži celotno opombo</span>
                                </button>
                            ` : rec.note}
                        </div>
                    ` : ''}
                    
                    <!-- Images section -->
                    ${Array.isArray(rec.images) && rec.images.length ? `
                        <div class="mt-3">
                            <div class="text-xs text-gray-500 mb-2 font-medium">${rec.images.length} ${rec.images.length === 1 ? 'slika' : rec.images.length < 5 ? 'slike' : 'slik'}</div>
                            <div class="grid grid-cols-3 gap-2">
                                ${rec.images.slice(0, 3).map(u => `<img src="${u}" alt="" class="view-images-btn w-full h-20 object-cover rounded border hover:shadow-sm cursor-pointer" onload="this.style.opacity=1" onerror="setTimeout(() => { if (!this.complete || this.naturalWidth === 0) this.style.display='none'; }, 3000)" style="opacity: 0; transition: opacity 0.3s;" data-order="${rec.order_number}" data-type="${rec.type}" />`).join('')}
                                ${rec.images.length > 3 ? `<div class="view-images-btn w-full h-20 bg-gray-100 border rounded flex items-center justify-center text-xs text-gray-500 font-medium cursor-pointer hover:bg-gray-200" data-order="${rec.order_number}" data-type="${rec.type}">+${rec.images.length - 3}</div>` : ''}
                            </div>
                        </div>
                    ` : `<div class="mt-3 text-xs text-gray-400 text-center py-4 border border-dashed border-gray-200 rounded">Ni slik</div>`}
                    
                    <!-- Footer with date -->
                    <div class="mt-3 pt-2 border-t border-gray-100">
                        <div class="text-xs text-gray-400">${new Date(rec.created_at).toLocaleDateString('sl-SI', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</div>
                    </div>
                </div>`;
            // Handle both old and new API response formats
            const responseData = data.data || data; // make_ok wraps data in 'data' property
            const allItems = responseData.all_items || [];
            const paginationData = responseData.pagination || {};
            
            console.log('Processing data:', { 
                allItemsCount: allItems.length, 
                paginationData, 
                unifiedList: !!unifiedList,
                emptyDiv: !!emptyDiv,
                fullDataStructure: responseData
            });
            
            if (allItems.length > 0) {
                console.log('Sample data item:', allItems[0]);
            }
            
            // Prikaži results info
            if (resultsInfo) {
                let filterText = '';
                if (search) filterText += ` za "${search}"`;
                if (typeFilter) filterText += ` (${typeFilter === 'returned' ? 'vrnjeni' : 'poškodovani'})`;
                resultsInfo.textContent = `Prikažem ${allItems.length} od ${paginationData.total_count || 0} zapisov${filterText}`;
            }
            
            // Prikaži/skrij unified seznam
            if (allItems.length > 0) {
                console.log('Showing records, setting innerHTML...');
                unifiedList.innerHTML = allItems.map(cardHtml).join('');
                unifiedList.classList.remove('hidden');
                emptyDiv?.classList.add('hidden');
                console.log('Records displayed, innerHTML length:', unifiedList.innerHTML.length);
                
                // Dodaj event listenere za prikaz slik
                const viewImagesBtns = unifiedList.querySelectorAll('.view-images-btn');
                console.log('Found view-images buttons:', viewImagesBtns.length);
                viewImagesBtns.forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const orderNumber = btn.dataset.order;
                        const type = btn.dataset.type;
                        console.log('Image button clicked:', orderNumber, type);
                        window.viewReturnedDamagedImages(orderNumber, type);
                    });
                });
            } else {
                console.log('No records to show, showing empty state');
                unifiedList.innerHTML = '';
                unifiedList.classList.add('hidden');
                emptyDiv?.classList.remove('hidden');
            }
            
            // Posodobi pagination
            if (pagination && paginationData.total_pages > 1) {
                pagination.classList.remove('hidden');
                
                if (pageInfo) {
                    pageInfo.textContent = `Stran ${paginationData.page} od ${paginationData.total_pages}`;
                }
                
                if (totalInfo) {
                    totalInfo.textContent = `Skupaj: ${paginationData.total_count} zapisov`;
                }
                
                if (prevBtn) {
                    prevBtn.disabled = !paginationData.has_prev;
                }
                
                if (nextBtn) {
                    nextBtn.disabled = !paginationData.has_next;
                }
            } else {
                pagination?.classList.add('hidden');
            }
        } catch (e) {
            console.error('Napaka pri nalaganju vrnjenih/poškodovanih:', e);
            console.error('Stack trace:', e.stack);
        }
    }
    
    // Funkcija za brisanje zapisa
    window.deleteReturnedDamagedRecord = async function(recordId) {
        if (!confirm('Ali ste prepričani, da želite izbrisati ta zapis?')) return;
        
        try {
            const res = await fetch(`/api/returns/${recordId}`, { method: 'DELETE' });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.error || 'Napaka pri brisanju');
            }
            
            showToast('Zapis uspešno izbrisan', 'success');
            await window.loadReturnedDamaged();
        } catch (e) {
            showToast(e.message, 'danger');
        }
    }
    
    // Funkcija za preklapljanje med kratko in celotno opombo
    window.toggleFullNote = function(recordId) {
        const shortDiv = document.getElementById(`note-short-${recordId}`);
        const fullDiv = document.getElementById(`note-full-${recordId}`);
        const btnSpan = document.getElementById(`note-btn-${recordId}`);
        
        if (shortDiv && fullDiv && btnSpan) {
            if (shortDiv.classList.contains('hidden')) {
                // Prikaži kratko, skrij celotno
                shortDiv.classList.remove('hidden');
                fullDiv.classList.add('hidden');
                btnSpan.textContent = 'Prikaži celotno opombo';
            } else {
                // Prikaži celotno, skrij kratko
                shortDiv.classList.add('hidden');
                fullDiv.classList.remove('hidden');
                btnSpan.textContent = 'Prikaži krajšo opombo';
            }
        }
    };

    // Funkcija za ogled slik - preprosta implementacija ki uporablja obstoječi modal
    window.viewReturnedDamagedImages = async function(orderNumber, type) {
        try {
            console.log(`=== VIEW RETURNED/DAMAGED IMAGES ===`);
            console.log(`Order: ${orderNumber}, Type: ${type}`);
            
            // Pridobi slike iz API-ja
            const response = await fetch(`/api/returns/images?order_number=${orderNumber}&type=${type}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            console.log('API response:', data);
            
            if (!data.success || !data.images || data.images.length === 0) {
                showToast('Ni slik za prikaz', 'warning');
                return;
            }
            
            // Preprosto odpri prvo sliko z obstoječim modalom
            // Če je več slik, lahko uporabnik klikne na naslednje v seznamu
            window.openImageViewModal(data.images[0]);
            
        } catch (error) {
            console.error('Error loading returned/damaged images:', error);
            showToast('Napaka pri nalaganju slik', 'danger');
        }
    }


    
    // Inicializacija filtrov in paginacije
    window.initializeRDFilters = function() {
        const searchInput = document.getElementById('rd-search-input');
        const typeFilter = document.getElementById('rd-type-filter');
        const prevBtn = document.getElementById('rd-prev-btn');
        const nextBtn = document.getElementById('rd-next-btn');
        
        let searchTimeout;
        
        // Search input z debounce
        if (searchInput && !searchInput.dataset.bound) {
            searchInput.dataset.bound = '1';
            searchInput.addEventListener('input', () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    currentRDPage = 1; // Reset na prvo stran
                    currentRDTypeFilter = typeFilter ? typeFilter.value : '';
                    window.loadReturnedDamaged(1, searchInput.value.trim(), currentRDTypeFilter);
                }, 300);
            });
        }
        
        // Type filter
        if (typeFilter && !typeFilter.dataset.bound) {
            typeFilter.dataset.bound = '1';
            typeFilter.addEventListener('change', () => {
                currentRDPage = 1; // Reset na prvo stran
                currentRDSearch = searchInput ? searchInput.value.trim() : '';
                window.loadReturnedDamaged(1, currentRDSearch, typeFilter.value);
            });
        }
        
        // Pagination buttons
        if (prevBtn && !prevBtn.dataset.bound) {
            prevBtn.dataset.bound = '1';
            prevBtn.addEventListener('click', () => {
                if (currentRDPage > 1) {
                    window.loadReturnedDamaged(currentRDPage - 1, currentRDSearch, currentRDTypeFilter);
                }
            });
        }
        
        if (nextBtn && !nextBtn.dataset.bound) {
            nextBtn.dataset.bound = '1';
            nextBtn.addEventListener('click', () => {
                window.loadReturnedDamaged(currentRDPage + 1, currentRDSearch, currentRDTypeFilter);
            });
        }
    }
    // Funkcija za inicializacijo RD zavihka - kličemo jo ko je potrebno
    function initializeReturnedDamagedTab() {
        console.log('RD: initializeReturnedDamagedTab called');
        
        // Preveri če je že inicializiran
        if (window.rdInitialized) {
            console.log('RD: Already initialized, skipping');
            return;
        }
        
        // Preveri če so elementi v DOM-u
        const rdElements = {
            submitBtn: document.getElementById('rd-submit'),
            submitBtnDesktop: document.getElementById('rd-submit-desktop'),
            rdFile: document.getElementById('rd-images'),
            rdCamBtn: document.getElementById('rd-camera-btn'),
            rdGalBtn: document.getElementById('rd-gallery-btn'),
            rdFileBtn: document.getElementById('rd-file-btn'),
            rdCamInput: document.getElementById('rd-camera-input'),
            rdMobInput: document.getElementById('rd-mobile-image-input'),
            rdPreview: document.getElementById('rd-selected-images-preview'),
            rdList: document.getElementById('rd-selected-images-list')
        };
        
        console.log('RD: All elements check:', rdElements);
        
        const submitBtn = rdElements.submitBtn;
        const submitBtnDesktop = rdElements.submitBtnDesktop;
        // Naloži seznam naročil v datalist
                // Note: RD Order Combobox is now handled by rdOrderCombo.js

        // RD upload handlers - mirror order images UI - use predefined elements
        const rdFile = rdElements.rdFile;
        const rdCamBtn = rdElements.rdCamBtn;
        const rdGalBtn = rdElements.rdGalBtn;
        const rdFileBtn = rdElements.rdFileBtn;
        const rdCamInput = rdElements.rdCamInput;
        const rdMobInput = rdElements.rdMobInput;
        const rdPreview = rdElements.rdPreview;
        const rdList = rdElements.rdList;
        
        console.log('RD: Elements found:', {
            submitBtn, rdFile, rdCamBtn, rdGalBtn, rdFileBtn, 
            rdCamInput, rdMobInput, rdPreview, rdList
        });

        function rdShowSelected(files){
            console.log('RD: rdShowSelected called with files:', files?.length || 0);
            console.log('RD: Preview/List elements:', { rdPreview, rdList });
            console.log('RD: Files details:', files ? Array.from(files).map(f => ({name: f.name, size: f.size, type: f.type})) : 'no files');
            
            if (!rdPreview || !rdList) {
                console.warn('RD: Missing preview or list elements');
                return;
            }
            
            rdList.innerHTML = '';
            console.log('RD: Cleared list, processing files...');
            
            Array.from(files || []).forEach((file, index) => {
                console.log(`RD: Processing file ${index + 1}: ${file.name}`);
                const reader = new FileReader();
                reader.onload = e => {
                    console.log(`RD: File ${index + 1} loaded successfully`);
                    const div = document.createElement('div');
                    div.innerHTML = `<div class="bg-white rounded-lg border border-gray-200 overflow-hidden"><img src="${e.target.result}" class="w-full h-24 object-cover" alt="Izbrana slika"><div class="p-2"><p class="text-xs text-gray-600 truncate">${file.name}</p></div></div>`;
                    rdList.appendChild(div.firstElementChild);
                };
                reader.readAsDataURL(file);
            });
            
            const shouldShow = !!(files && files.length);
            console.log('RD: Showing preview:', shouldShow);
            rdPreview.classList.toggle('hidden', !shouldShow);
        }

        if (rdCamBtn && rdCamInput){ 
            console.log('RD: Adding camera button listener');
            rdCamBtn.addEventListener('click', (e)=>{ 
                console.log('RD Camera button clicked');
                e.preventDefault(); 
                rdCamInput.click(); 
            }); 
        } else {
            console.warn('RD Camera elements not found:', { rdCamBtn, rdCamInput });
        }
        if (rdGalBtn && rdMobInput){ 
            console.log('RD: Adding gallery button listener');
            rdGalBtn.addEventListener('click', (e)=>{ 
                console.log('RD Gallery button clicked - preventing default and triggering file input');
                e.preventDefault(); 
                e.stopPropagation();
                console.log('RD: About to click rdMobInput:', rdMobInput);
                rdMobInput.click(); 
                console.log('RD: rdMobInput.click() called');
            }); 
        } else {
            console.warn('RD Gallery elements not found:', { rdGalBtn, rdMobInput });
        }
        if (rdFileBtn && rdFile){ 
            console.log('RD: Adding file button listener');
            rdFileBtn.addEventListener('click', (e)=> {
                console.log('RD File button clicked');
                e.preventDefault();
                rdFile.click();
            }); 
        } else {
            console.warn('RD File elements not found:', { rdFileBtn, rdFile });
        }
        const onAnyChange = (e)=>{
            console.log('RD: onAnyChange triggered by:', e.target.id);
            const files = e.target.files;
            console.log('RD: Files from input:', files?.length || 0);
            
            if (!files || !files.length) {
                console.log('RD: No files selected, returning');
                return;
            }
            
            console.log('RD: Files selected:', files.length, 'files');
            
            // Kopiraj v glavni skriti input za submit - uporabi FileList kot DataTransfer
            if (rdFile) {
                try { 
                    const dt = new DataTransfer();
                    Array.from(files).forEach(file => {
                        console.log('RD: Adding file to DataTransfer:', file.name);
                        dt.items.add(file);
                    });
                    rdFile.files = dt.files;
                    console.log('RD: Files copied to main input, count:', rdFile.files.length);
                } catch(err) {
                    console.warn('RD: Could not copy files to main input:', err);
                }
            } else {
                console.warn('RD: Main file input (rdFile) not found!');
            }
            
            console.log('RD: Calling rdShowSelected...');
            rdShowSelected(files);
        };
        
        if (rdCamInput) {
            rdCamInput.addEventListener('change', onAnyChange);
            console.log('RD: Camera input change listener added');
        }
        if (rdMobInput) {
            rdMobInput.addEventListener('change', onAnyChange);
            console.log('RD: Mobile input change listener added');
        }
        if (rdFile) {
            rdFile.addEventListener('change', (e)=> {
                console.log('RD: Main file input changed, files:', e.target.files?.length || 0);
                rdShowSelected(e.target.files);
            });
            console.log('RD: Main file input change listener added');
        }

        // Osveži seznam naročil ob odprtju zavihka
        // Prejšnja select logika odstranjena

        // Create submit handler function
        const handleSubmit = async (e, buttonElement) => {
            console.log('RD Submit button clicked!', e);
            
            // Preprečimo dvojno klikanje - check both buttons
            if ((submitBtn && submitBtn.disabled) || (submitBtnDesktop && submitBtnDesktop.disabled)) {
                console.log('RD: Submit already in progress, ignoring click');
                return;
            }
            
            const orderNumber = document.getElementById('rd-order-control')?.value?.trim();
            const type = document.getElementById('rd-type')?.value || 'returned';
            const note = document.getElementById('rd-note')?.value?.trim() || '';
            const files = document.getElementById('rd-images')?.files;
            
            // Validacija polj z jasnimi sporočili
            let errors = [];
            
            if (!orderNumber) {
                errors.push('Št. naročila je obvezno polje');
                document.getElementById('rd-order-control')?.classList.add('border-red-500');
            } else {
                document.getElementById('rd-order-control')?.classList.remove('border-red-500');
                // Osnovni format check za številko naročila
                if (!/^#?\d+$/.test(orderNumber)) {
                    errors.push('Nepravilna št. naročila (samo številke, npr. 11879 ali #11879)');
                    document.getElementById('rd-order-control')?.classList.add('border-red-500');
                }
            }
            
            if (!files || !files.length) {
                errors.push('Dodajanje slike je obvezno');
                // Označi vse gumbe za slike z rdečo barvo
                [rdCamBtn, rdGalBtn, rdFileBtn].forEach(btn => {
                    if (btn) btn.classList.add('border-red-500', 'bg-red-50', 'text-red-700');
                });
                if (rdPreview) rdPreview.classList.add('ring-2','ring-red-400');
            } else {
                // Odstrani rdeče oznake
                [rdCamBtn, rdGalBtn, rdFileBtn].forEach(btn => {
                    if (btn) btn.classList.remove('border-red-500', 'bg-red-50', 'text-red-700');
                });
                if (rdPreview) rdPreview.classList.remove('ring-2','ring-red-400');
                // Preveri velikost datotek (max 10MB na sliko)
                for (const file of files) {
                    if (file.size > 10 * 1024 * 1024) {
                        errors.push(`Slika "${file.name}" je prevelika (max 10MB)`);
                    }
                }
            }
            
            if (errors.length > 0) {
                showToast(`Napaka pri dodajanju zapisa:\n• ${errors.join('\n• ')}`, 'danger');
                return;
            }
            
            // Onemogočimo oba gumba med procesom
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i>Dodajam...';
            }
            if (submitBtnDesktop) {
                submitBtnDesktop.disabled = true;
                submitBtnDesktop.innerHTML = '<i class="bi bi-hourglass-split mr-2"></i>Dodajam...';
            }
            
            try {
                // Preverimo ali že obstaja zapis za to naročilo in tip
                const existingRes = await fetch('/api/returns');
                if (existingRes.ok) {
                    const existingData = await existingRes.json();
                    // Handle both old and new API response formats
                    const responseData = existingData.data || existingData;
                    const allItems = [...(responseData.returned || []), ...(responseData.damaged || [])];
                    const existing = allItems.find(item => 
                        item.order_number === orderNumber && item.type === type
                    );
                    
                    if (existing) {
                        throw new Error(`Za naročilo ${orderNumber} že obstaja zapis tipa "${type === 'returned' ? 'Vrnjeno' : 'Poškodovano'}"`);
                    }
                }
                const form = new FormData();
                form.append('order_number', orderNumber);
                form.append('type', type);
                form.append('note', note);
                if (files && files.length) {
                    for (const f of files) form.append('images', f);
                }
                const res = await fetch('/api/returns', { method: 'POST', body: form });
                const data = await res.json().catch(()=>({success:false,error:'Napaka pri obdelavi odgovora strežnika'}));
                if (!res.ok) {
                    // HTTP napake z bolj specifičnimi sporočili
                    let errorMsg = 'Napaka pri shranjevanju';
                    if (res.status === 400) {
                        errorMsg = data.error || 'Nepravilni podatki - preverite vnos';
                    } else if (res.status === 404) {
                        errorMsg = 'Naročilo s to številko ni bilo najdeno';
                    } else if (res.status === 413) {
                        errorMsg = 'Slike so prevelike - zmanjšajte velikost';
                    } else if (res.status >= 500) {
                        errorMsg = 'Napaka na strežniku - poskusite ponovno';
                    }
                    throw new Error(errorMsg);
                }
                if (!data.success) {
                    throw new Error(data.error || 'Napaka pri shranjevanju');
                }
                showToast('Zapis uspešno dodan', 'success');
                // Po uspehu resetiraj polja in osveži seznam
                document.getElementById('rd-order-control').value = '';
                document.getElementById('rd-note').value = '';
                if (document.getElementById('rd-images')) document.getElementById('rd-images').value = '';
                if (rdMobInput) rdMobInput.value = '';
                if (rdCamInput) rdCamInput.value = '';
                if (rdPreview) rdPreview.classList.add('hidden');
                
                // Resetiraj vizualne indikatorje napak
                document.getElementById('rd-order-control')?.classList.remove('border-red-500');
                [rdCamBtn, rdGalBtn, rdFileBtn].forEach(btn => {
                    if (btn) btn.classList.remove('border-red-500', 'bg-red-50', 'text-red-700');
                });
                
                await window.loadReturnedDamaged();
            } catch (e) {
                showToast(e.message, 'danger');
            } finally {
                // Omogočimo oba gumba nazaj
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="bi bi-plus-circle mr-2"></i>Dodaj zapis';
                }
                if (submitBtnDesktop) {
                    submitBtnDesktop.disabled = false;
                    submitBtnDesktop.innerHTML = '<i class="bi bi-plus-circle mr-2"></i>Dodaj zapis';
                }
            }
        };

        // Bind submit handler to both buttons
        if (submitBtn && !submitBtn.dataset.bound) {
            console.log('RD: Adding mobile submit button listener');
            submitBtn.dataset.bound = '1';
            submitBtn.addEventListener('click', (e) => handleSubmit(e, submitBtn));
        }
        
        if (submitBtnDesktop && !submitBtnDesktop.dataset.bound) {
            console.log('RD: Adding desktop submit button listener');
            submitBtnDesktop.dataset.bound = '1';
            submitBtnDesktop.addEventListener('click', (e) => handleSubmit(e, submitBtnDesktop));
        }
        
        if (!submitBtn && !submitBtnDesktop) {
            console.warn('RD: No submit buttons found!');
        }
        
        // Označi kot inicializiran
        window.rdInitialized = true;
        console.log('RD: Initialization completed');
    }
    
    // Naredi funkcijo globalno dostopno
    window.initializeReturnedDamagedTab = initializeReturnedDamagedTab;
    
    // Inicializiraj RD če je zavihek že aktiven ob nalaganju strani
    document.addEventListener('DOMContentLoaded', () => {
        const activeTab = document.querySelector('.tab-button.active')?.dataset?.tab;
        if (activeTab === 'returned-damaged') {
            console.log('RD: Tab already active on page load, initializing...');
            initializeReturnedDamagedTab();
            window.initializeRDFilters();
        }
    });

    // --- Inicializacija zavihkov ---

    function setupFlorgardenInputs() {
        console.log('setupFlorgardenInputs called');
        
        const parts = ['fg-yy', 'fg-aaaaa', 'fg-bbb', 'fg-ddmm'].map(id => document.getElementById(id));
        const hiddenInput = document.getElementById('serija-stevilka');
        
        console.log('FLORGARDEN input elements:', {
            parts: parts.map((el, i) => ({ id: ['fg-yy', 'fg-aaaaa', 'fg-bbb', 'fg-ddmm'][i], found: !!el })),
            hiddenInput: !!hiddenInput
        });
        
        if (!parts.every(Boolean) || !hiddenInput) {
            console.log('setupFlorgardenInputs: Some elements not found, returning');
            return;
        }
        parts.forEach((input, idx) => {
            input.addEventListener('input', () => {
                input.value = input.value.replace(/\D/g, '');
                const maxLength = input.getAttribute('maxlength');
                if (input.value.length >= maxLength && idx < parts.length - 1) {
                    parts[idx + 1].focus();
                }
                const val = `${parts[0].value}/${parts[1].value} ${parts[2].value}/${parts[3].value}`;
                hiddenInput.value = val;
                console.log('FLORGARDEN serial number built:', val);
                console.log('Hidden input value:', hiddenInput.value);
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && input.value.length === 0 && idx > 0) {
                    parts[idx - 1].focus();
                }
            });
        });
        
        console.log('setupFlorgardenInputs: Event listeners added successfully');
    }

    // Prepisujemo placeholder funkcije z dejanskimi implementacijami
    window.loadProizvajalci = loadProizvajalci;
    window.fetchExpiringPerfumes = fetchExpiringPerfumes;
    window.loadUsers = loadUsers;
    window.loadProizvajalciForManualAndPrint = loadProizvajalciForManualAndPrint;
    window.handleManualSend = handleManualSend;
    window.handlePrintAction = handlePrintAction;
    
    function initializeTabScroll() {
        // Inicializacija Florgarden inputov
        try {
            setupFlorgardenInputs();
        } catch (error) {
            console.error('ERROR in setupFlorgardenInputs():', error);
        }

        try {
            // Scroll puščice za zavihke na desktopu
        const tabsContainer = document.getElementById('main-tabs');
        const leftBtn = document.getElementById('tabs-scroll-left');
        const rightBtn = document.getElementById('tabs-scroll-right');
        
        function updateTabArrows() {
            console.log('=== updateTabArrows CALLED ===');
            if (!tabsContainer || !leftBtn || !rightBtn) {
                console.log('Missing elements - returning early');
                return;
            }
            
            const scrollLeft = tabsContainer.scrollLeft;
            const maxScrollLeft = tabsContainer.scrollWidth - tabsContainer.clientWidth;
            
            console.log('Current button visibility before update:', {
                leftBtnDisplay: leftBtn.style.display,
                rightBtnDisplay: rightBtn.style.display,
                leftBtnHidden: leftBtn.classList.contains('hidden'),
                rightBtnHidden: rightBtn.classList.contains('hidden')
            });
            
            console.log('Tab scroll state:', { 
                scrollLeft, 
                maxScrollLeft, 
                scrollWidth: tabsContainer.scrollWidth, 
                clientWidth: tabsContainer.clientWidth,
                isScrollNeeded: maxScrollLeft > 0
            });
            
            console.log('Scroll analysis:', {
                maxScrollLeft,
                scrollLeft,
                needsScroll: maxScrollLeft > 0,
                atBeginning: scrollLeft <= 1,
                atEnd: scrollLeft >= maxScrollLeft - 1
            });

            // Če ni potrebe za scroll (vsi zavihki se vidijo), skrij oba gumba
            if (maxScrollLeft <= 0) {
                leftBtn.style.display = 'none';
                rightBtn.style.display = 'none';
                console.log('No scroll needed - hiding both buttons');
                return;
            }
            
            // Levi gumb: prikaži samo če lahko scrollamo v levo (nismo na začetku)
            if (scrollLeft <= 0.5) { // Strict check za skrajno levo pozicijo
                leftBtn.style.display = 'none';
                console.log('At beginning - hiding left button');
            } else {
                leftBtn.style.display = '';
                console.log('Not at beginning - showing left button');
            }
            
            // Desni gumb: prikaži če obstaja možnost scrollanja v desno
            if (scrollLeft >= maxScrollLeft - 0.5) { // Strict check za skrajno desno pozicijo
                rightBtn.style.display = 'none';
                console.log('At end - hiding right button');
            } else {
                rightBtn.style.display = '';
                console.log('Not at end - showing right button');
            }
            
            console.log('Button visibility after update:', {
                leftBtnDisplay: leftBtn.style.display,
                rightBtnDisplay: rightBtn.style.display,
                leftBtnHidden: leftBtn.classList.contains('hidden'),
                rightBtnHidden: rightBtn.classList.contains('hidden'),
                leftBtnClasses: leftBtn.className,
                rightBtnClasses: rightBtn.className
            });
        }
        
        console.log('Tab elements found:', {
            tabsContainer: !!tabsContainer,
            leftBtn: !!leftBtn,
            rightBtn: !!rightBtn,
            tabsContainerWidth: tabsContainer?.clientWidth,
            tabsScrollWidth: tabsContainer?.scrollWidth,
            tabsScrollLeft: tabsContainer?.scrollLeft
        });

        if (tabsContainer && leftBtn && rightBtn) {
            // Najprej skrij oba gumba na začetku
            console.log('=== INITIAL SETUP: Before hiding buttons ===');
            console.log('Before hiding - Left button classes:', leftBtn.className);
            console.log('Before hiding - Right button classes:', rightBtn.className);
            
            leftBtn.style.display = 'none';
            rightBtn.style.display = 'none';
            
            console.log('=== INITIAL SETUP: After hiding buttons ===');
            console.log('After hiding - Left button classes:', leftBtn.className);
            console.log('After hiding - Right button classes:', rightBtn.className);
            console.log('Initial state: hiding both buttons');
            
            // Onemogoči ročno scrolling na desktopu (lg+)
            function preventManualScroll(e) {
                if (window.innerWidth >= 1024) { // lg breakpoint
                    if (e.type === 'wheel' && e.deltaX !== 0) { // horizontalno wheel scrollanje
                        e.preventDefault();
                        e.stopPropagation();
                        console.log('Prevented manual wheel scroll on desktop');
                    } else if (e.type === 'touchstart' || e.type === 'touchmove') { // touch events
                        e.preventDefault();
                        e.stopPropagation();
                        console.log('Prevented touch scroll on desktop');
                    }
                }
            }
            
            function preventDragScroll(e) {
                if (window.innerWidth >= 1024) { // lg breakpoint
                    e.preventDefault();
                    console.log('Prevented drag scroll on desktop');
                }
            }
            
            // Event listeneri
            tabsContainer.addEventListener('scroll', updateTabArrows);
            
            // Prepreči ročno scrollanje na desktopu
            tabsContainer.addEventListener('wheel', preventManualScroll, { passive: false });
            tabsContainer.addEventListener('touchstart', preventManualScroll, { passive: false });
            tabsContainer.addEventListener('touchmove', preventManualScroll, { passive: false });
            tabsContainer.addEventListener('dragstart', preventDragScroll);
            
            window.addEventListener('resize', updateTabArrows);
            
            leftBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('=== LEFT BUTTON CLICKED ===');
                console.log('Before scroll:', {
                    scrollLeft: tabsContainer.scrollLeft,
                    scrollWidth: tabsContainer.scrollWidth,
                    clientWidth: tabsContainer.clientWidth
                });
                
                tabsContainer.scrollBy({ left: -200, behavior: 'smooth' });
                
                setTimeout(() => {
                    console.log('After scroll:', {
                        scrollLeft: tabsContainer.scrollLeft,
                        scrollWidth: tabsContainer.scrollWidth,
                        clientWidth: tabsContainer.clientWidth
                    });
                    updateTabArrows();
                }, 150);
            });
            
            rightBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('=== RIGHT BUTTON CLICKED ===');
                console.log('Before scroll:', {
                    scrollLeft: tabsContainer.scrollLeft,
                    scrollWidth: tabsContainer.scrollWidth,
                    clientWidth: tabsContainer.clientWidth
                });
                
                tabsContainer.scrollBy({ left: 200, behavior: 'smooth' });
                
                setTimeout(() => {
                    console.log('After scroll:', {
                        scrollLeft: tabsContainer.scrollLeft,
                        scrollWidth: tabsContainer.scrollWidth,
                        clientWidth: tabsContainer.clientWidth
                    });
                    updateTabArrows();
                }, 150);
            });
            
            // Inicializacija z večjim zamikom
            setTimeout(() => {
                console.log('Initializing tab arrows...');
                updateTabArrows();
            }, 500);
        }
        } catch (error) {
            console.error('ERROR in tab scroll initialization:', error);
        }
        
        console.log('=== TAB SCROLL INITIALIZATION COMPLETED ===');
    }
    
    // Izvršimo takoj, če je DOM že pripravljen, ali počakajmo nanj
    if (document.readyState === 'loading') {
        console.log('DOM still loading, waiting for DOMContentLoaded...');
        document.addEventListener('DOMContentLoaded', initializeTabScroll);
    } else {
        console.log('DOM already ready, initializing tab scroll immediately...');
        initializeTabScroll();
    }
});

// --- Local First funkcionalnosti ---
// Funkcija za obnovitev prijave iz localStorage, ko je aplikacija offline
async function restoreOfflineLogin() {
    try {
        console.log('Poskušam obnoviti prijavo iz localStorage...');
        
        const currentUser = localStorage.getItem('currentUser');
        if (!currentUser) {
            console.log('Ni shranjenih podatkov o uporabniku v localStorage');
            return false;
        }
        
        const user = JSON.parse(currentUser);
        console.log('Podatki o uporabniku iz localStorage:', user);
        
        // Preveri, ali so podatki o uporabniku veljavni
        if (!user.id || !user.username) {
            console.log('Neveljavni podatki o uporabniku v localStorage');
            localStorage.removeItem('currentUser');
            return false;
        }
        
        // Posodobi prikaz uporabnika
        displayCurrentUser();
        
        // Posodobi UI, da prikaže, da je uporabnik prijavljen
        const userDisplay = document.getElementById('current-user-display');
        if (userDisplay) {
            userDisplay.style.display = 'block';
        }
        
        // Skrij "Neprijavljen" tekst
        const notLoggedInText = document.querySelector('.text-red-600');
        if (notLoggedInText) {
            notLoggedInText.style.display = 'none';
        }
        
        console.log('Prijava uspešno obnovljena iz localStorage');
        showToast('Prijava obnovljena iz lokalnega pomnilnika (offline)', 'warning');
        return true;
        
    } catch (error) {
        console.error('Napaka pri obnovitvi prijave iz localStorage:', error);
        localStorage.removeItem('currentUser');
        return false;
    }
}
async function initializeLocalFirst() {
    try {
        console.log('Inicializiram Local First funkcionalnosti...');
        
        // Preveri, ali je IndexedDB na voljo
        if (!window.localDB) {
            console.error('IndexedDB ni na voljo');
            return;
        }
        
        // Inicializiraj IndexedDB
        try {
            await localDB.init();
            console.log('IndexedDB uspešno inicializiran');
        } catch (error) {
            console.error('Napaka pri inicializaciji IndexedDB:', error);
            return;
        }
        
        // Preveri pravo povezavo
        const connectionOk = await checkConnection();
        isOnline = connectionOk;
        window.isOnline = isOnline;
        console.log('Povezava preverjena - isOnline:', isOnline);
        
        // Nastavi event listenerje za online/offline
        console.log('Nastavljam event listenerje za online/offline...');
        window.addEventListener('online', handleOnline);
        window.addEventListener('offline', handleOffline);
        console.log('Event listenerji nastavljeni');
        
        // Posodobi UI glede na trenutno stanje
        updateOnlineStatus();
        
        // Če je aplikacija online ob inicializaciji, osveži parfume v lokalni bazi
        if (isOnline) {
            console.log('Aplikacija je online ob inicializaciji - osvežujem parfume v lokalni bazi');
            await refreshLocalPerfumes();
        } else {
            // Če je offline, poskusi obnoviti prijavo iz localStorage
            console.log('Aplikacija je offline - poskušam obnoviti prijavo iz localStorage');
            await restoreOfflineLogin();
        }
        
        // Začni periodično sinhronizacijo
        startPeriodicSync();
        
        console.log('Local First funkcionalnosti uspešno inicializirane');
        
    } catch (error) {
        console.error('Napaka pri inicializaciji Local First:', error);
    }
}

// Funkcija za osvežitev parfumov v lokalni bazi
async function refreshLocalPerfumes() {
    try {
        console.log('Osvežujem parfume v lokalni bazi...');
        
        // Naloži vse parfume iz API za vsakega proizvajalca
        const proizvajalci = await localDB.getProizvajalci();
        console.log(`Naloženih ${proizvajalci.length} proizvajalcev za osvežitev parfumov`);
        
        let totalPerfumes = 0;
        
        for (const proizvajalec of proizvajalci) {
            try {
                const response = await fetch(`/api/parfumi_by_proizvajalec/${proizvajalec.id}`);
                if (response.ok) {
                    const parfumi = await response.json();
                    console.log(`Naloženih ${parfumi.length} parfumov za proizvajalca ${proizvajalec.ime} (ID: ${proizvajalec.id})`);
                    
                    // Shrani parfume v lokalno bazo
                    await localDB.savePerfumes(parfumi);
                    totalPerfumes += parfumi.length;
                } else {
                    console.error(`Napaka pri nalaganju parfumov za proizvajalca ${proizvajalec.ime}: ${response.status}`);
                }
            } catch (error) {
                console.error(`Napaka pri osveževanju parfumov za proizvajalca ${proizvajalec.ime}:`, error);
            }
        }
        
        console.log(`Osvežitev parfumov končana - skupaj ${totalPerfumes} parfumov`);
        
        // Naloži tudi serije iz API-ja
        console.log('Osvežujem serije v lokalni bazi...');
        try {
            const serijeResponse = await fetch('/api/serije');
            if (serijeResponse.ok) {
                const serije = await serijeResponse.json();
                if (Array.isArray(serije)) {
                    await localDB.saveSerije(serije);
                    console.log(`Naloženih ${serije.length} serij v lokalno bazo`);
                    // Obvestilo izklopljeno na zahtevo
                } else {
                    console.error('Neveljaven format serij:', serije);
                    // Obvestilo izklopljeno na zahtevo
                }
            } else {
                console.error(`Napaka pri nalaganju serij: ${serijeResponse.status}`);
                // Obvestilo izklopljeno na zahtevo
            }
        } catch (error) {
            console.error('Napaka pri osveževanju serij:', error);
            // Obvestilo izklopljeno na zahtevo
        }
        
    } catch (error) {
        console.error('Napaka pri osveževanju parfumov:', error);
        showToast('Napaka pri osveževanju parfumov', 'error');
    }
}

async function handleOnline() {
    console.log('Povezava vzpostavljena - preverjam...');
    
    // Preveri pravo povezavo
    const connectionOk = await checkConnection();
    isOnline = connectionOk;
    window.isOnline = isOnline;
    
    console.log('Povezava preverjena - isOnline:', isOnline);
    updateOnlineStatus();
    
    if (isOnline) {
        offlineSince = null;
        // Počisti TomSelect opcije in ponovno onemogoči polje
        if (searchParfumSelect) {
            searchParfumSelect.clear();
            searchParfumSelect.clearOptions();
            searchParfumSelect.disable();
        }
        
        // Osveži parfume v lokalni bazi za pravilno offline funkcionalnost
        await refreshLocalPerfumes();
        
        // Začni sinhronizacijo
        if (window.syncManager) {
            syncManager.syncAll();
        }
        
        showToast('Povezava vzpostavljena - sinhroniziram podatke', 'success');

        // Če smo na zavihku Naročila, osveži seznam iz API
        if (document.getElementById('narocila-tab')?.classList.contains('active')) {
            fetchNarocila(1, null, 'online');
        }
    }
}

async function handleOffline() {
    console.log('=== OFFLINE EVENT TRIGGERED ===');
    console.log('Povezava prekinjena - preverjam...');
    console.log('Pred checkConnection - isOnline:', isOnline, 'navigator.onLine:', navigator.onLine);
    
    // Preveri pravo povezavo
    const connectionOk = await checkConnection();
    isOnline = connectionOk;
    window.isOnline = isOnline;
    
    console.log('Povezava preverjena - isOnline:', isOnline);
    console.log('=== OFFLINE EVENT COMPLETED ===');
    updateOnlineStatus();
    
    if (!isOnline) {
        if (!offlineSince) {
            offlineSince = Date.now();
        }
        // Poskusi obnoviti prijavo iz localStorage
        await restoreOfflineLogin();
        
        // Naloži parfume iz lokalne baze za offline dostop
        if (window.localDB && typeof loadAllPerfumesForOffline === 'function') {
            loadAllPerfumesForOffline();
        }
        
        showToast('Povezava prekinjena - delujem offline', 'warning');

        // Če smo na zavihku Naročila, preklopi prikaz na lokalno bazo
        if (document.getElementById('narocila-tab')?.classList.contains('active')) {
            fetchNarocila(1, null, 'offline');
        }
    }
}

function updateOnlineStatus() {
    const offlineIndicator = document.getElementById('offline-indicator');
    const syncStatus = document.getElementById('sync-status');
    
    if (offlineIndicator) {
        if (isOnline) {
            offlineIndicator.classList.add('hidden');
        } else {
            offlineIndicator.classList.remove('hidden');
        }
    }
    
    if (syncStatus && window.syncManager) {
        if (syncManager.syncInProgress) {
            syncStatus.classList.remove('hidden');
        } else {
            syncStatus.classList.add('hidden');
        }
    }
}

function startPeriodicSync() {
    // Sinhroniziraj vsakih 5 minut
    setInterval(async () => {
        if (isOnline && window.syncManager && !syncManager.syncInProgress) {
            console.log('Periodična sinhronizacija...');
            await syncManager.syncAll();
        }
    }, 5 * 60 * 1000); // 5 minut
}

// Sync status UI funkcije
async function updateSyncStatusUI() {
    if (!window.syncManager) return;
    
    try {
        const status = await syncManager.getSyncStatus();
        const syncStatusElement = document.getElementById('sync-status');
        const offlineIndicator = document.getElementById('offline-indicator');
        
        // Posodobi online/offline indikator
        if (offlineIndicator) {
            if (status.isOnline) {
                offlineIndicator.classList.add('hidden');
            } else {
                offlineIndicator.classList.remove('hidden');
            }
        }
        
        // Posodobi sync status
        if (syncStatusElement) {
            if (status.syncInProgress) {
                syncStatusElement.classList.remove('hidden');
                syncStatusElement.innerHTML = `
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                        <i class="bi bi-arrow-repeat mr-1 animate-spin"></i> Sinhroniziram...
                    </span>
                `;
            } else {
                syncStatusElement.classList.add('hidden');
            }
        }
        
        // Prikaži obvestila o konfliktih
        const conflictsButton = document.getElementById('conflicts-button');
        if (conflictsButton) {
            if (status.conflicts > 0) {
                conflictsButton.classList.remove('hidden');
                conflictsButton.innerHTML = `
                    <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        <i class="bi bi-exclamation-triangle mr-1"></i> ${status.conflicts} konfliktov
                    </span>
                `;
            } else {
                conflictsButton.classList.add('hidden');
            }
        }
        
        // Posodobi lastSyncTime
        if (status.lastSyncTime) {
            lastSyncTime = status.lastSyncTime;
        }
        
    } catch (error) {
        console.error('Napaka pri posodabljanju sync status UI:', error);
    }
}

// Funkcija za prikaz konfliktov
async function showConflictsModal() {
    if (!window.syncManager) return;
    
    try {
        const conflicts = await syncManager.getConflicts();
        
        if (conflicts.length === 0) {
            showToast('Ni konfliktov za rešitev', 'info');
            return;
        }
        
        // Ustvari modal za konflikte
        const modalHTML = `
            <div id="conflicts-modal" class="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50">
                <div class="relative top-20 mx-auto p-5 border w-11/12 md:w-3/4 lg:w-1/2 shadow-lg rounded-md bg-white">
                    <div class="mt-3">
                        <h3 class="text-lg font-medium text-gray-900 mb-4">Konflikti pri sinhronizaciji</h3>
                        <div class="space-y-4 max-h-96 overflow-y-auto">
                            ${conflicts.map(conflict => `
                                <div class="border rounded-lg p-4">
                                    <div class="flex justify-between items-start mb-2">
                                        <h4 class="font-medium">${getConflictTitle(conflict)}</h4>
                                        <span class="text-xs text-gray-500">${new Date(conflict.conflict_at).toLocaleString('sl-SI')}</span>
                                    </div>
                                    <p class="text-sm text-gray-600 mb-3">${getConflictDescription(conflict)}</p>
                                    <div class="flex space-x-2">
                                        <button onclick="resolveConflict(${conflict.id}, 'local')" class="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600">
                                            Uporabi lokalno
                                        </button>
                                        <button onclick="resolveConflict(${conflict.id}, 'remote')" class="px-3 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600">
                                            Uporabi oddaljeno
                                        </button>
                                        <button onclick="resolveConflict(${conflict.id}, 'merge')" class="px-3 py-1 text-xs bg-yellow-500 text-white rounded hover:bg-yellow-600">
                                            Združi
                                        </button>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                        <div class="flex justify-end mt-4">
                            <button onclick="closeConflictsModal()" class="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400">
                                Zapri
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Dodaj modal v DOM
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        
    } catch (error) {
        console.error('Napaka pri prikazu konfliktov:', error);
        showToast('Napaka pri nalaganju konfliktov', 'error');
    }
}

function getConflictTitle(conflict) {
    switch (conflict.type) {
        case 'add_serija':
            return 'Dodajanje serije';
        case 'update_serija':
            return 'Posodobitev serije';
        case 'delete_serija':
            return 'Brisanje serije';
        default:
            return 'Neznan konflikt';
    }
}

function getConflictDescription(conflict) {
    switch (conflict.type) {
        case 'add_serija':
            return `Serija za parfum ID: ${conflict.data.parfum_id}`;
        case 'update_serija':
            return `Posodobitev serije ID: ${conflict.data.id}`;
        case 'delete_serija':
            return `Brisanje serije ID: ${conflict.data.id}`;
        default:
            return 'Neznan tip konflikta';
    }
}

async function resolveConflict(itemId, resolution) {
    try {
        if (!window.syncManager) return;
        
        await syncManager.resolveConflict(itemId, resolution);
        showToast(`Konflikt rešen z ${resolution} strategijo`, 'success');
        
        // Osveži modal
        await showConflictsModal();
        
    } catch (error) {
        console.error('Napaka pri reševanju konflikta:', error);
        showToast('Napaka pri reševanju konflikta', 'error');
    }
}

function closeConflictsModal() {
    const modal = document.getElementById('conflicts-modal');
    if (modal) {
        modal.remove();
    }
}

// Periodično posodabljanje sync status UI
setInterval(updateSyncStatusUI, 10000); // Vsakih 10 sekund

// --- Inicializacija aplikacije ---
document.addEventListener('DOMContentLoaded', function() {
    // Zaznava mobilnih naprav
    function detectMobile() {
        const isMobile = window.innerWidth <= 768;
        console.log('Window width:', window.innerWidth, 'Is mobile:', isMobile);
        
        if (isMobile) {
            document.body.classList.add('mobile');
            console.log('Added mobile class to body');
        } else {
            document.body.classList.remove('mobile');
            console.log('Removed mobile class from body');
        }
        
        // Preveri, ali je razred res dodan
        console.log('Body classes:', document.body.className);
    }
    
    // Začetna zaznava
    detectMobile();
    
    // Poslušaj spremembe velikosti okna
    window.addEventListener('resize', function() {
        detectMobile();
        
        // Posodobi dropdownParent za TomSelect instance
        if (typeof searchParfumSelect !== 'undefined' && searchParfumSelect) {
            searchParfumSelect.settings.dropdownParent = 'body';
        }
        if (typeof manualPerfumeSelect !== 'undefined' && manualPerfumeSelect) {
            manualPerfumeSelect.settings.dropdownParent = 'body';
        }
        if (typeof printPerfumeSelect !== 'undefined' && printPerfumeSelect) {
            printPerfumeSelect.settings.dropdownParent = 'body';
        }
    });
    
    // Inicializacija vseh komponent
    if (typeof initializeTabs === 'function') {
        initializeTabs();
    } else {
        console.error('initializeTabs function is not defined');
    }
    
    // initializeModal se kliče ob nalaganju strani, ne potrebujemo ga klicati tukaj
    
    if (typeof initializeManualAndPrintTab === 'function') {
        initializeManualAndPrintTab();
    } else {
        console.error('initializeManualAndPrintTab function is not defined');
    }
    
    // Inicializiraj Local First funkcionalnosti in nato naloži podatke
    console.log('Kličem initializeLocalFirst...');
    if (typeof initializeLocalFirst === 'function') {
        console.log('initializeLocalFirst funkcija najdena, kličem...');
        initializeLocalFirst().then(() => {
            // Naloži začetne podatke po Local First inicializaciji
            if (typeof loadProizvajalci === 'function') {
                loadProizvajalci();
            }
            
            if (typeof fetchNarocila === 'function') {
                if (!initialNarocilaRequested) {
                    initialNarocilaRequested = true;
                    fetchNarocila(1, null, 'init');
                }
            }
            
            if (typeof fetchExpiringPerfumes === 'function') {
                fetchExpiringPerfumes();
            }
            
            // Če je offline, naloži tudi parfume iz lokalne baze
            if (!isOnline && typeof loadAllPerfumesForOffline === 'function') {
                setTimeout(() => {
                    loadAllPerfumesForOffline();
                }, 2000); // Počakaj, da se ostali podatki naložijo
            }
        }).catch(error => {
            console.error('Napaka pri inicializaciji Local First:', error);
            // Kljub napaki poskusi naložiti podatke
            if (typeof loadProizvajalci === 'function') {
                loadProizvajalci();
            }
            
            if (typeof fetchNarocila === 'function') {
                if (!initialNarocilaRequested) {
                    initialNarocilaRequested = true;
                    fetchNarocila(1, null, 'init');
                }
            }
            
            if (typeof fetchExpiringPerfumes === 'function') {
                fetchExpiringPerfumes();
            }
            
            // Če je offline, naloži tudi parfume iz lokalne baze
            if (!isOnline && typeof loadAllPerfumesForOffline === 'function') {
                setTimeout(() => {
                    loadAllPerfumesForOffline();
                }, 2000); // Počakaj, da se ostali podatki naložijo
            }
        });
    } else {
        // Če Local First ni na voljo, naloži podatke direktno
        if (typeof loadProizvajalci === 'function') {
            loadProizvajalci();
        }
        
        if (typeof fetchNarocila === 'function') {
            fetchNarocila(1, null, 'init');
        }
        
        if (typeof fetchExpiringPerfumes === 'function') {
            fetchExpiringPerfumes();
        }
        
        // Če je offline, naloži tudi parfume iz lokalne baze
        if (!isOnline && typeof loadAllPerfumesForOffline === 'function') {
            setTimeout(() => {
                loadAllPerfumesForOffline();
            }, 2000); // Počakaj, da se ostali podatki naložijo
        }
    }
    
    // Prikaži trenutnega uporabnika
    if (typeof displayCurrentUser === 'function') {
        displayCurrentUser();
    }
    
    // Če je offline, poskusi obnoviti prijavo iz localStorage takoj
    if (!navigator.onLine && typeof restoreOfflineLogin === 'function') {
        console.log('Aplikacija je offline ob nalaganju - poskušam obnoviti prijavo...');
        restoreOfflineLogin().then(success => {
            if (success) {
                console.log('Prijava uspešno obnovljena ob nalaganju strani');
            } else {
                console.log('Prijava ni bila obnovljena ob nalaganju strani');
            }
        });
    }
    
    // Inicializacija tooltipov
    if (typeof initializeTooltips === 'function') {
        initializeTooltips();
    }
    
    // Naloži e-mail način
    if (typeof loadEmailMode === 'function') {
        loadEmailMode();
    }
});

console.log('=== MAIN.JS DATOTEKA KONČANA - KONEC DATOTEKE ===');
console.log('Final JavaScript state:', {
    documentReadyState: document.readyState,
    timestamp: Date.now()
});