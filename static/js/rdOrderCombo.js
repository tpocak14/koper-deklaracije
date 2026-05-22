/**
 * RD Order Combobox - Searchable order number input with dropdown
 */

class RDOrderCombo {
    constructor() {
        this.input = null;
        this.dropdown = null;
        this.wrapper = null;
        this.isInitialized = false;
        this.debounceTimer = null;
        this.abortController = null;
        this.activeIndex = -1;
        this.items = [];
        this.blurTimer = null;
    }

    init() {
        if (this.isInitialized) return;
        
        this.input = document.getElementById('rd-order-control');
        this.dropdown = document.getElementById('rd-order-dropdown');
        this.wrapper = document.getElementById('rd-order-combobox');
        
        if (!this.input || !this.dropdown || !this.wrapper) {
            console.warn('RD Order Combobox: Required elements not found');
            return;
        }

        this.setupEvents();
        this.isInitialized = true;
        console.log('RD Order Combobox: Initialized successfully');
    }

    setupEvents() {
        // Input events
        this.input.addEventListener('input', (e) => this.onInput(e));
        this.input.addEventListener('focus', (e) => this.onFocus(e));
        this.input.addEventListener('blur', (e) => this.onBlur(e));
        this.input.addEventListener('keydown', (e) => this.onKeydown(e));

        // Dropdown events
        this.dropdown.addEventListener('click', (e) => this.onDropdownClick(e));

        // Click outside
        document.addEventListener('click', (e) => this.onClickOutside(e));
    }

    onInput(e) {
        const query = e.target.value.trim();
        this.debounceSearch(query);
    }

    onFocus(e) {
        const query = this.input.value.trim();
        if (!query) {
            // Show recent orders on empty focus
            this.search('', true);
        } else {
            this.debounceSearch(query);
        }
    }

    onBlur(e) {
        // Delay hiding to allow dropdown clicks
        this.blurTimer = setTimeout(() => {
            this.hideDropdown();
        }, 150);
    }

    onKeydown(e) {
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.navigateDown();
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.navigateUp();
                break;
            case 'Enter':
                e.preventDefault();
                this.selectCurrent();
                break;
            case 'Escape':
                this.hideDropdown();
                break;
        }
    }

    onDropdownClick(e) {
        if (this.blurTimer) {
            clearTimeout(this.blurTimer);
            this.blurTimer = null;
        }

        const option = e.target.closest('[role="option"]');
        if (option) {
            const orderNumber = option.dataset.orderNumber;
            if (orderNumber) {
                this.selectOption(orderNumber);
            }
        }
    }

    onClickOutside(e) {
        if (!this.wrapper.contains(e.target)) {
            this.hideDropdown();
        }
    }

    debounceSearch(query) {
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }
        
        this.debounceTimer = setTimeout(() => {
            this.search(query);
        }, 250);
    }

    async search(query, isRecent = false) {
        try {
            // Cancel previous request
            if (this.abortController) {
                this.abortController.abort();
            }
            this.abortController = new AbortController();

            // Show loading
            this.showLoading();

            let url;
            if (!query || query.length < 2) {
                // Get recent orders (empty query or too short)
                url = '/api/orders/search?limit=20';
            } else {
                // Search with query
                url = `/api/orders/search?q=${encodeURIComponent(query)}&limit=20`;
            }

            const response = await fetch(url, {
                signal: this.abortController.signal
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            let results = [];
            
            // Handle different response formats
            if (data.success === false) {
                throw new Error(data.error?.message || 'Search failed');
            }
            
            if (data.data && Array.isArray(data.data.results)) {
                results = data.data.results;
            } else if (Array.isArray(data.results)) {
                results = data.results;
            } else if (Array.isArray(data)) {
                results = data;
            }

            this.renderResults(results);

        } catch (error) {
            if (error.name === 'AbortError') return;
            
            console.warn('RD Order Combobox search error:', error.message);
            this.showError('Napaka pri iskanju');
        }
    }

    showLoading() {
        this.dropdown.innerHTML = '<div class="ts-option loading">Loading…</div>';
        this.showDropdown();
    }

    showError(message) {
        this.dropdown.innerHTML = `<div class="ts-option error">${message}</div>`;
        this.showDropdown();
    }

    renderResults(results) {
        if (!results || results.length === 0) {
            this.dropdown.innerHTML = '<div class="ts-option empty">Ni zadetkov</div>';
            this.showDropdown();
            return;
        }

        const html = results.map((item, index) => {
            const orderNumber = item.order_number || '';
            const customerName = item.customer_name || '';
            const date = item.date ? this.formatDate(item.date) : '';
            
            let displayText = orderNumber;
            if (customerName) displayText += ` — ${customerName}`;
            if (date) displayText += ` — ${date}`;

            return `<div role="option" 
                         data-order-number="${orderNumber}" 
                         class="ts-option"
                         id="rd-option-${index}">
                        ${displayText}
                    </div>`;
        }).join('');

        this.dropdown.innerHTML = html;
        this.items = results;
        this.activeIndex = -1;
        this.showDropdown();
    }

    formatDate(dateStr) {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('sl-SI');
        } catch (e) {
            return dateStr;
        }
    }

    showDropdown() {
        this.dropdown.classList.remove('hidden');
        this.input.setAttribute('aria-expanded', 'true');
    }

    hideDropdown() {
        this.dropdown.classList.add('hidden');
        this.input.setAttribute('aria-expanded', 'false');
        this.activeIndex = -1;
        this.updateAriaActive();
    }

    navigateDown() {
        if (this.dropdown.classList.contains('hidden')) return;
        
        this.activeIndex = Math.min(this.activeIndex + 1, this.items.length - 1);
        this.updateActiveOption();
    }

    navigateUp() {
        if (this.dropdown.classList.contains('hidden')) return;
        
        this.activeIndex = Math.max(this.activeIndex - 1, 0);
        this.updateActiveOption();
    }

    updateActiveOption() {
        // Remove previous active state
        this.dropdown.querySelectorAll('.ts-option').forEach(opt => {
            opt.classList.remove('active');
            opt.removeAttribute('aria-selected');
        });

        // Set new active state
        if (this.activeIndex >= 0 && this.activeIndex < this.items.length) {
            const activeOption = this.dropdown.querySelector(`#rd-option-${this.activeIndex}`);
            if (activeOption) {
                activeOption.classList.add('active');
                activeOption.setAttribute('aria-selected', 'true');
            }
        }

        this.updateAriaActive();
    }

    updateAriaActive() {
        if (this.activeIndex >= 0) {
            this.input.setAttribute('aria-activedescendant', `rd-option-${this.activeIndex}`);
        } else {
            this.input.removeAttribute('aria-activedescendant');
        }
    }

    selectCurrent() {
        if (this.activeIndex >= 0 && this.activeIndex < this.items.length) {
            const item = this.items[this.activeIndex];
            this.selectOption(item.order_number);
        } else {
            // Free text entry
            const value = this.input.value.trim();
            if (value) {
                this.selectOption(value);
            }
        }
    }

    selectOption(orderNumber) {
        // Normalize order number (remove # if present for consistent display)
        const normalizedNumber = orderNumber.replace(/^#/, '');
        
        this.input.value = normalizedNumber;
        this.hideDropdown();
        
        // Dispatch custom event
        document.dispatchEvent(new CustomEvent('rd:orderSelected', {
            detail: { orderNumber: normalizedNumber }
        }));

        console.log('RD Order Combobox: Selected order', normalizedNumber);
    }

    validate() {
        const value = this.input.value.trim();
        if (!value) {
            this.input.classList.add('border-red-500');
            return false;
        }
        
        this.input.classList.remove('border-red-500');
        return true;
    }
}

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    if (!window.rdOrderCombo) {
        window.rdOrderCombo = new RDOrderCombo();
        window.rdOrderCombo.init();
    }
});

// Export for manual initialization if needed
window.RDOrderCombo = RDOrderCombo;

