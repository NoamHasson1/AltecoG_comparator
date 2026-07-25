document.addEventListener('DOMContentLoaded', () => {
    const altecoZone = document.getElementById('alteco-drop-zone');
    const electraZone = document.getElementById('electra-drop-zone');
    const continueBtn = document.getElementById('continue-btn');
    const continueSpinner = document.getElementById('continue-spinner');
    const inspectStatus = document.getElementById('inspect-status');
    const reconcileBtn = document.getElementById('reconcile-btn');
    const reconcileSpinner = document.getElementById('reconcile-spinner');
    const mappingRoot = document.getElementById('mapping-root');
    const overlay = document.getElementById('overlay');
    const paletteTitle = document.getElementById('palette-title');
    const paletteSearch = document.getElementById('palette-search');
    const paletteList = document.getElementById('palette-list');

    let altecoFile = null;
    let electraFile = null;
    let sheetsData = null; // populated by /inspect-file once the client file is selected

    // ---- Mapping state (built up as the user plays the matching game) ----
    let fieldMatches = {};      // direct field key -> {sheet, column, mode?}
    let activeFilterState = { enabled: false, sheet: '', column: '', value: '' };
    let lineItemsState = { sheet: '', group_by_column: '' };
    let calcState = {};         // calc field key -> {value_column, filter: {column, match_type, values}}

    function escapeHtml(str) {
        return String(str).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    // ============ Step Navigation ============
    function goToStep(n) {
        document.querySelectorAll('.panel').forEach((p) => p.classList.remove('is-visible'));
        document.getElementById(`panel-${n}`).classList.add('is-visible');
        document.querySelectorAll('.step').forEach((s) => {
            const stepNum = parseInt(s.dataset.step, 10);
            s.classList.toggle('is-active', stepNum === n);
            s.classList.toggle('is-done', stepNum < n);
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    document.getElementById('back-to-upload-btn').addEventListener('click', () => goToStep(1));
    document.getElementById('back-to-mapping-btn').addEventListener('click', () => goToStep(2));

    function updateContinueButtonState() {
        continueBtn.disabled = !(altecoFile && electraFile && sheetsData !== null);
    }

    // ============ Drop Zones (Step 1) ============
    function setupDropZone(zone, setFileCallback, clearFileCallback, onFileChange) {
        const input = zone.querySelector('.drop-zone-input');
        const promptText = zone.querySelector('.prompt-text');
        const formatHint = zone.querySelector('.format-hint');
        const uploadIcon = zone.querySelector('.upload-icon');
        const fileDisplay = zone.querySelector('.file-display');
        const fileNameDisplay = zone.querySelector('.file-name');
        const removeBtn = zone.querySelector('.remove-file-btn');

        function handleFileSelection(file) {
            if (file) {
                setFileCallback(file);
                promptText.style.display = 'none';
                formatHint.style.display = 'none';
                uploadIcon.style.display = 'none';
                fileDisplay.style.display = 'flex';
                fileNameDisplay.textContent = file.name;
                updateContinueButtonState();
                if (onFileChange) onFileChange(file);
            }
        }

        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('highlight'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('highlight'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('highlight');
            const file = e.dataTransfer.files[0];
            if (file) { input.files = e.dataTransfer.files; handleFileSelection(file); }
        });
        input.addEventListener('change', () => {
            if (input.files.length > 0) handleFileSelection(input.files[0]);
        });
        removeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            clearFileCallback();
            input.value = '';
            fileDisplay.style.display = 'none';
            fileNameDisplay.textContent = '';
            promptText.style.display = 'block';
            formatHint.style.display = 'block';
            uploadIcon.style.display = 'block';
            updateContinueButtonState();
            if (onFileChange) onFileChange(null);
        });
    }

    setupDropZone(altecoZone, (file) => { altecoFile = file; }, () => { altecoFile = null; });
    setupDropZone(electraZone, (file) => { electraFile = file; }, () => { electraFile = null; }, handleElectraFileChange);

    continueBtn.addEventListener('click', () => goToStep(2));

    // ============ Saved-mappings popover (static markup, wired once) ============
    const mappingsMenuBtn = document.getElementById('mappings-menu-btn');
    const mappingsPopover = document.getElementById('mappings-popover');

    function closeMappingsPopover() {
        mappingsPopover.classList.remove('is-open');
        mappingsMenuBtn.setAttribute('aria-expanded', 'false');
    }

    mappingsMenuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = mappingsPopover.classList.toggle('is-open');
        mappingsMenuBtn.setAttribute('aria-expanded', String(isOpen));
        if (isOpen) loadSavedMappingsList();
    });

    document.addEventListener('click', (e) => {
        if (!mappingsPopover.classList.contains('is-open')) return;
        if (mappingsPopover.contains(e.target) || mappingsMenuBtn.contains(e.target)) return;
        closeMappingsPopover();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMappingsPopover();
    });

    document.getElementById('load-mapping-btn').addEventListener('click', onLoadMappingClick);
    document.getElementById('save-mapping-btn').addEventListener('click', onSaveMappingClick);
    document.getElementById('delete-mapping-btn').addEventListener('click', onDeleteMappingClick);
    document.getElementById('reset-all-mappings-btn').addEventListener('click', onResetAllMappingsClick);

    // ============ Field Definitions ============
    const DIRECT_FIELDS = [
        { key: 'billing_month', label: 'Billing Month', derivable: true },
        { key: 'customer_id', label: 'Customer ID', required: true },
        { key: 'customer_name', label: 'Customer Name' },
        { key: 'tax_id', label: 'Customer Tax' },
        { key: 'iec_contract', label: 'Electricity Contract Number' },
        { key: 'meter_number', label: 'Meter Number', required: true },
        { key: 'voltage', label: 'Voltage' },
        { key: 'tou', label: 'Energy Consumption' },
        { key: 'billing_type', label: 'Billing Type' },
        { key: 'tariff', label: 'Tariff' },
        { key: 'fixed_payment', label: 'Fixed Payment' },
        { key: 'contract_start_date', label: 'Contract Start Date' },
        { key: 'kva', label: 'KVA' },
    ];

    // Sensible starting keywords for each calculation's filter — a hint, not a silent guess:
    // the column still has to be chosen explicitly before anything is actually matched.
    const CALC_FIELD_DEFAULTS = {
        total_kwh: { match_type: 'equals', values: ['Detail usage'] },
        total_payment: { match_type: 'contains_any', values: [] },
        kva_fixed_charge: { match_type: 'contains_any', values: ['KVA'] },
        supply_fixed_charge: { match_type: 'contains_any', values: ['אספקה'] },
        distribution_fixed_charge: { match_type: 'contains_any', values: ['חלוקה'] },
    };

    const CALCULATED_FIELDS = [
        { key: 'total_kwh', label: 'Total kWh Consumption' },
        { key: 'total_payment', label: 'Total Payment (including VAT) ₪' },
        { key: 'kva_fixed_charge', label: 'Fixed KVA Billing ₪' },
        { key: 'supply_fixed_charge', label: 'Supply Fixed Charge ₪' },
        { key: 'distribution_fixed_charge', label: 'Distribution Fixed Charge ₪' },
    ];

    // ============ Inspecting the client file ============
    async function handleElectraFileChange(file) {
        if (!file) {
            sheetsData = null;
            inspectStatus.style.display = 'none';
            updateContinueButtonState();
            return;
        }

        inspectStatus.style.display = 'block';
        inspectStatus.className = 'inspect-status';
        inspectStatus.textContent = 'Reading file structure...';
        continueSpinner.style.display = 'inline-block';

        try {
            const formData = new FormData();
            formData.append('file', file);
            const response = await fetch('/inspect-file', { method: 'POST', body: formData });
            const data = await response.json();
            if (response.status !== 200) throw new Error(data.detail || 'Could not read file');
            sheetsData = data.sheets;

            // Start from a blank mapping every time — a saved mapping (including the
            // bundled default) is only applied if the user explicitly loads it below.
            applyMappingConfig(null);
            renderMappingPanel();

            inspectStatus.className = 'inspect-status is-ready';
            inspectStatus.textContent = `Found ${sheetsData.length} sheet(s) — ready to map fields.`;
        } catch (error) {
            sheetsData = null;
            inspectStatus.className = 'inspect-status is-error';
            inspectStatus.textContent = `Error reading file: ${error.message}`;
        } finally {
            continueSpinner.style.display = 'none';
            updateContinueButtonState();
        }
    }

    function sampleValueFor(sheetName, column) {
        const sheet = sheetsData && sheetsData.find((s) => s.name === sheetName);
        if (!sheet) return '';
        for (const row of sheet.sample_rows) {
            if (row[column] !== null && row[column] !== undefined && row[column] !== '') {
                return String(row[column]);
            }
        }
        return '';
    }

    // Up to `limit` example rows for a column, shown on both the draggable
    // source card and the filled drop-zone so the user can eyeball a match.
    function sampleValuesFor(sheetName, column, limit) {
        const sheet = sheetsData && sheetsData.find((s) => s.name === sheetName);
        if (!sheet) return [];
        return sheet.sample_rows.slice(0, limit || 3).map((row) => {
            const v = row[column];
            return (v === null || v === undefined || v === '') ? '—' : String(v);
        });
    }

    // ============ Palette popover (sheet or column picker) ============
    let paletteContext = null; // {type: 'sheet'|'column', scopeSheet: string|null, onPick: fn}

    function openPalette(title, type, scopeSheet, onPick) {
        paletteContext = { type, scopeSheet, onPick };
        paletteTitle.textContent = title;
        paletteSearch.value = '';
        renderPaletteList('');
        overlay.classList.add('is-open');
        setTimeout(() => paletteSearch.focus(), 50);
    }

    function closePalette() {
        overlay.classList.remove('is-open');
        paletteContext = null;
    }

    overlay.addEventListener('click', (e) => { if (e.target === overlay) closePalette(); });
    paletteSearch.addEventListener('input', () => renderPaletteList(paletteSearch.value.toLowerCase()));

    function renderPaletteList(term) {
        if (!sheetsData || !paletteContext) {
            paletteList.innerHTML = '<div class="palette-empty">No file loaded</div>';
            return;
        }

        if (paletteContext.type === 'sheet') {
            const filtered = sheetsData.filter((s) => s.name.toLowerCase().includes(term));
            paletteList.innerHTML = filtered.map((s) => `
                <div class="palette-chip" data-sheet="${escapeHtml(s.name)}">
                    <span class="palette-chip-col">${escapeHtml(s.name)}</span>
                    <span class="palette-chip-sample">${s.columns.length} columns</span>
                </div>
            `).join('') || '<div class="palette-empty">No matching sheets</div>';
            paletteList.querySelectorAll('.palette-chip').forEach((chip) => {
                chip.addEventListener('click', () => {
                    const onPick = paletteContext.onPick;
                    closePalette();
                    onPick(chip.dataset.sheet);
                });
            });
            return;
        }

        const sheetsToShow = paletteContext.scopeSheet
            ? sheetsData.filter((s) => s.name === paletteContext.scopeSheet)
            : sheetsData;
        let html = '';
        sheetsToShow.forEach((sheet) => {
            const cols = sheet.columns.filter((c) => c.toLowerCase().includes(term));
            if (cols.length === 0) return;
            if (!paletteContext.scopeSheet) html += `<div class="palette-sheet-label">${escapeHtml(sheet.name)}</div>`;
            cols.forEach((col) => {
                const sample = sampleValueFor(sheet.name, col);
                html += `<div class="palette-chip" data-sheet="${escapeHtml(sheet.name)}" data-col="${escapeHtml(col)}">
                    <span class="palette-chip-col">${escapeHtml(col)}</span>
                    <span class="palette-chip-sample">${escapeHtml(sample)}</span>
                </div>`;
            });
        });
        paletteList.innerHTML = html || '<div class="palette-empty">No matching columns</div>';
        paletteList.querySelectorAll('.palette-chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const onPick = paletteContext.onPick;
                closePalette();
                onPick(chip.dataset.sheet, chip.dataset.col);
            });
        });
    }

    // Two-step convenience: pick a sheet, then immediately pick a column within it.
    function openSheetThenColumnPalette(sheetTitle, columnTitle, onPick) {
        openPalette(sheetTitle, 'sheet', null, (sheet) => {
            openPalette(columnTitle, 'column', sheet, (_, col) => onPick(sheet, col));
        });
    }

    // Changing the shared line-items sheet invalidates whatever was picked against the old
    // one (the group-by column and every calc field's value/filter columns).
    function setLineItemsSheet(sheet) {
        if (lineItemsState.sheet !== sheet) {
            lineItemsState.group_by_column = '';
            Object.values(calcState).forEach((cfg) => {
                cfg.value_column = '';
                cfg.filter.column = '';
            });
        }
        lineItemsState.sheet = sheet;
    }

    // ============ Mapping config <-> UI state ============
    function blankCalcState() {
        const state = {};
        CALCULATED_FIELDS.forEach((f) => {
            const d = CALC_FIELD_DEFAULTS[f.key] || { match_type: 'contains_any', values: [] };
            state[f.key] = { value_column: '', filter: { column: '', match_type: d.match_type, values: [...d.values] } };
        });
        return state;
    }

    function applyMappingConfig(config) {
        fieldMatches = {};
        calcState = blankCalcState();
        activeFilterState = { enabled: false, sheet: '', column: '', value: '' };
        lineItemsState = { sheet: '', group_by_column: '' };

        if (!config) return;

        const fm = config.field_mappings || {};
        Object.keys(fm).forEach((key) => {
            fieldMatches[key] = { sheet: fm[key].sheet, column: fm[key].column };
        });

        if (config.billing_month) {
            fieldMatches.billing_month = {
                sheet: config.billing_month.sheet,
                column: config.billing_month.column,
                mode: config.billing_month.mode,
            };
        }

        if (config.active_filter) {
            activeFilterState = {
                enabled: true,
                sheet: config.active_filter.sheet,
                column: config.active_filter.column,
                value: config.active_filter.value,
            };
        }

        if (config.line_items) {
            lineItemsState = {
                sheet: config.line_items.sheet,
                group_by_column: config.line_items.group_by_column,
            };
        }

        const cf = config.calculated_fields || {};
        Object.keys(cf).forEach((key) => {
            if (!calcState[key]) return;
            const rule = cf[key];
            const first = (rule.filters && rule.filters[0]) || { column: '', match_type: 'contains_any', values: [] };
            calcState[key] = {
                value_column: rule.value_column || '',
                filter: { column: first.column || '', match_type: first.match_type || 'contains_any', values: [...(first.values || [])] },
            };
        });
    }

    function gatherMappingConfig() {
        const fieldMappingsOut = {};
        let billingMonthOut = null;

        DIRECT_FIELDS.forEach((field) => {
            const cfg = fieldMatches[field.key];
            if (!cfg || !cfg.sheet || !cfg.column) return;
            if (field.key === 'billing_month') {
                billingMonthOut = { sheet: cfg.sheet, column: cfg.column, mode: cfg.mode === 'derive_from_date' ? 'derive_from_date' : 'direct' };
            } else {
                fieldMappingsOut[field.key] = { sheet: cfg.sheet, column: cfg.column };
            }
        });

        let activeFilterOut = null;
        if (activeFilterState.enabled && activeFilterState.sheet && activeFilterState.column && activeFilterState.value && activeFilterState.value.trim()) {
            activeFilterOut = { sheet: activeFilterState.sheet, column: activeFilterState.column, value: activeFilterState.value.trim() };
        }

        let lineItemsOut = null;
        if (lineItemsState.sheet && lineItemsState.group_by_column) {
            lineItemsOut = { sheet: lineItemsState.sheet, group_by_column: lineItemsState.group_by_column };
        }

        const calculatedFieldsOut = {};
        CALCULATED_FIELDS.forEach((field) => {
            const cfg = calcState[field.key];
            if (!cfg || !cfg.value_column) return;
            const f = cfg.filter;
            const filters = (f && f.column && f.values && f.values.length)
                ? [{ column: f.column, match_type: f.match_type, values: f.values }]
                : [];
            calculatedFieldsOut[field.key] = { value_column: cfg.value_column, filters };
        });

        return {
            field_mappings: fieldMappingsOut,
            active_filter: activeFilterOut,
            billing_month: billingMonthOut,
            line_items: lineItemsOut,
            calculated_fields: calculatedFieldsOut,
        };
    }

    // ============ Rendering the mapping game ============

    // Left sidebar: every column from every sheet, grouped, draggable onto a slot.
    function sourceSidebarHtml() {
        if (!sheetsData) return '';
        const usedKeys = new Set();
        DIRECT_FIELDS.forEach((f) => {
            const cfg = fieldMatches[f.key];
            if (cfg && cfg.sheet && cfg.column) usedKeys.add(`${cfg.sheet}|${cfg.column}`);
        });

        return sheetsData.map((sheet) => `
            <div class="sheet-group-label">${escapeHtml(sheet.name)}</div>
            ${sheet.columns.map((col) => {
                const isUsed = usedKeys.has(`${sheet.name}|${col}`);
                const samples = sampleValuesFor(sheet.name, col, 3);
                return `
                    <div class="source-card ${isUsed ? 'is-used' : ''}" draggable="true" data-sheet="${escapeHtml(sheet.name)}" data-col="${escapeHtml(col)}">
                        <div class="source-card-head"><span class="drag-handle">⠿</span> ${escapeHtml(col)}</div>
                        <div class="source-samples">${samples.map((s, i) => `<div class="source-sample-row"><span class="source-sample-idx">${i + 1}</span>${escapeHtml(s)}</div>`).join('')}</div>
                    </div>
                `;
            }).join('')}
        `).join('');
    }

    // Right side: one drop-target slot per direct field (Alteco's fixed fields).
    function directSlotHtml(field) {
        const cfg = fieldMatches[field.key];
        const isMatched = !!(cfg && cfg.sheet && cfg.column);
        const deriveChecked = field.derivable && cfg && cfg.mode === 'derive_from_date';

        const dropZoneInner = isMatched
            ? `<span class="filled-sheet-tag">${escapeHtml(cfg.sheet)}</span>
               <div class="filled-head">${escapeHtml(cfg.column)}</div>
               <div class="filled-samples">${sampleValuesFor(cfg.sheet, cfg.column, 3).map((s, i) => `<div class="filled-sample-row"><span class="filled-sample-idx">${i + 1}</span>${escapeHtml(s)}</div>`).join('')}</div>`
            : `<span class="drop-zone-prompt">Drag a column here<br>or <span class="map-select-link">select</span></span>`;

        return `
            <div class="slot" data-field="${field.key}">
                <div class="slot-label ${field.required ? 'slot-required' : ''}">
                    <span class="slot-label-text">${escapeHtml(field.label)}</span>
                    <span class="map-clear-link" style="${isMatched ? '' : 'display:none;'}">Clear</span>
                </div>
                <div class="map-drop-zone ${isMatched ? 'is-filled' : ''}">${dropZoneInner}</div>
                ${field.derivable && isMatched ? `<label class="map-derive"><input type="checkbox" class="map-derive-toggle" ${deriveChecked ? 'checked' : ''}> Derive month from this date</label>` : ''}
            </div>
        `;
    }

    function activeFilterToggleHtml() {
        const { enabled, column, value } = activeFilterState;
        const scopeSheet = fieldMatches.meter_number ? fieldMatches.meter_number.sheet : null;
        const sample = (scopeSheet && column) ? sampleValueFor(scopeSheet, column) : '';
        const locked = !scopeSheet;

        return `
            <div class="toggle-card">
                <div class="toggle-row">
                    <div>
                        <span class="toggle-label">Only include active rows</span>
                        <p class="toggle-caption">Skips meters that are no longer in service (e.g. disconnected). ${locked ? 'Match Meter Number above first — that tells us which sheet to check.' : `Looks in the same sheet as Meter Number: <code>${escapeHtml(scopeSheet)}</code>`}</p>
                    </div>
                    <button type="button" class="toggle-switch ${enabled ? 'is-on' : ''} ${locked ? 'is-locked' : ''}" data-role="af-toggle" role="switch" aria-checked="${enabled}" ${locked ? 'disabled' : ''}>
                        <span class="toggle-knob"></span>
                    </button>
                </div>
                ${enabled && !locked ? `
                <div class="toggle-detail">
                    <button type="button" class="picker-btn ${column ? 'is-set' : ''}" data-role="af-column-btn">
                        ${column ? `${escapeHtml(column)}${sample ? ' · ' + escapeHtml(sample) : ''}` : 'Choose the status column'}
                    </button>
                    <span class="toggle-equals">equals</span>
                    <input type="text" id="af-value" placeholder="e.g. פעיל" value="${escapeHtml(value || '')}">
                </div>` : ''}
            </div>
        `;
    }

    function sharedConfigHtml() {
        const { sheet, group_by_column: groupBy } = lineItemsState;
        const label = (sheet && groupBy) ? `${escapeHtml(groupBy)} (in ${escapeHtml(sheet)})` : 'Click to choose';
        return `
            <div class="lineitems-card">
                <p class="lineitems-hint">Your consumption &amp; financial numbers are calculated from a detail sheet — one row per billing line. Which column there identifies each customer?</p>
                <button type="button" class="picker-btn ${(sheet && groupBy) ? 'is-set' : ''}" data-role="li-combined-btn">${label}</button>
            </div>
        `;
    }

    function calcSentenceHtml(cfg) {
        if (!cfg.value_column) return 'Not configured yet — pick a value column below.';
        let sentence = `Sum <code>${escapeHtml(cfg.value_column)}</code>`;
        const f = cfg.filter;
        if (f && f.column && f.values && f.values.length) {
            sentence += f.match_type === 'equals'
                ? ` for this customer, where <code>${escapeHtml(f.column)}</code> equals "${escapeHtml(f.values[0])}".`
                : ` for this customer, where <code>${escapeHtml(f.column)}</code> contains any of: ${f.values.map((v) => `"${escapeHtml(v)}"`).join(', ')}.`;
        } else {
            sentence += ' across every line item for this customer.';
        }
        return sentence;
    }

    function calcFilterBlockHtml(cfg) {
        const filter = cfg.filter;
        const tags = (filter.values || []).map((v) => `
            <span class="tag-chip">${escapeHtml(v)} <button type="button" data-value="${escapeHtml(v)}">✕</button></span>
        `).join('');
        return `
            <div class="calc-filter-block">
                <label class="calc-filter-label">Filter (optional)</label>
                <button type="button" class="picker-btn ${filter.column ? 'is-set' : ''}" data-role="calc-filter-btn">
                    ${filter.column ? escapeHtml(filter.column) : 'Click to choose which column to check'}
                </button>
                <div class="pill-toggle">
                    <button type="button" data-mt="contains_any" class="${filter.match_type !== 'equals' ? 'is-active' : ''}">Contains any of</button>
                    <button type="button" data-mt="equals" class="${filter.match_type === 'equals' ? 'is-active' : ''}">Equals exactly</button>
                </div>
                <div class="tag-input-wrap">
                    ${tags}
                    <input type="text" class="tag-input" placeholder="Type a keyword, press Enter…">
                </div>
            </div>
        `;
    }

    function calcCardHtml(field) {
        const cfg = calcState[field.key];
        const sheet = lineItemsState.sheet;
        return `
            <div class="calc-card" data-field="${field.key}">
                <div class="calc-card-title ${cfg.value_column ? 'is-done' : ''}">${escapeHtml(field.label)}</div>
                <p class="calc-sentence">${calcSentenceHtml(cfg)}</p>
                <div class="calc-row-inline">
                    <button type="button" class="picker-btn ${sheet ? 'is-set' : ''}" data-role="calc-sheet-btn">
                        Sheet: ${sheet ? escapeHtml(sheet) : 'not set'}
                    </button>
                    <button type="button" class="picker-btn ${cfg.value_column ? 'is-set' : ''}" data-role="calc-value-btn">
                        ${cfg.value_column ? escapeHtml(cfg.value_column) : 'Click to choose the value column'}
                    </button>
                </div>
                <p class="calc-shared-hint">Same sheet as the other calculations below — changing it resets their columns too.</p>
                ${calcFilterBlockHtml(cfg)}
            </div>
        `;
    }

    function renderMappingPanel() {
        mappingRoot.innerHTML = `
            <div class="progress-track">
                <div class="progress-count"><span class="n" id="progress-n">0</span> / <span id="progress-total">0</span> fields matched</div>
                <div class="progress-bar-bg"><div class="progress-bar-fill" id="progress-fill"></div></div>
            </div>

            <div class="celebrate" id="celebrate">
                <div class="celebrate-icon">✓</div>
                <div class="celebrate-text"><strong>All fields matched!</strong><span>You're ready to run the reconciliation.</span></div>
            </div>

            <h3 class="mapping-group-title">Customer &amp; Contract Details</h3>
            <div class="dragdrop-mapper">
                <div class="mapper-toolbar">
                    <span class="mapper-hint">Drag a column from the left onto a field, or click "select"</span>
                    <button type="button" class="clear-all-link" id="clear-all-direct">Clear All</button>
                </div>
                <div class="mapper-body">
                    <div class="source-sidebar">${sourceSidebarHtml()}</div>
                    <div class="slots-scroll"><div class="slots-row">${DIRECT_FIELDS.map(directSlotHtml).join('')}</div></div>
                </div>
            </div>
            ${activeFilterToggleHtml()}

            <h3 class="mapping-group-title">Consumption &amp; Financial Calculations</h3>
            ${sharedConfigHtml()}
            <div class="calc-grid">${CALCULATED_FIELDS.map(calcCardHtml).join('')}</div>
        `;

        updateProgressUI();
    }

    function updateProgressUI() {
        const doneDirect = DIRECT_FIELDS.filter((f) => fieldMatches[f.key] && fieldMatches[f.key].sheet && fieldMatches[f.key].column).length;
        const doneCalc = CALCULATED_FIELDS.filter((f) => calcState[f.key] && calcState[f.key].value_column).length;
        const total = DIRECT_FIELDS.length + CALCULATED_FIELDS.length;
        const done = doneDirect + doneCalc;

        const progressN = document.getElementById('progress-n');
        const progressTotal = document.getElementById('progress-total');
        const progressFill = document.getElementById('progress-fill');
        if (progressN) progressN.textContent = done;
        if (progressTotal) progressTotal.textContent = total;
        if (progressFill) progressFill.style.width = `${(done / total) * 100}%`;

        const celebrate = document.getElementById('celebrate');
        if (celebrate) celebrate.classList.toggle('is-shown', done === total);

        updateReconcileButtonState();
    }

    function updateReconcileButtonState() {
        const cid = fieldMatches.customer_id;
        const meter = fieldMatches.meter_number;
        const ready = !!(cid && cid.sheet && cid.column) && !!(meter && meter.sheet && meter.column);
        reconcileBtn.disabled = !ready;
    }

    // ============ Drag & drop: source column -> direct field slot ============
    let draggedSource = null; // {sheet, col}

    mappingRoot.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.source-card');
        if (!card) return;
        draggedSource = { sheet: card.dataset.sheet, col: card.dataset.col };
        card.classList.add('is-dragging');
        e.dataTransfer.effectAllowed = 'copy';
    });

    mappingRoot.addEventListener('dragend', (e) => {
        const card = e.target.closest('.source-card');
        if (card) card.classList.remove('is-dragging');
        draggedSource = null;
    });

    mappingRoot.addEventListener('dragover', (e) => {
        const dz = e.target.closest('.map-drop-zone');
        if (!dz) return;
        e.preventDefault();
        dz.classList.add('is-dragover');
    });

    mappingRoot.addEventListener('dragleave', (e) => {
        const dz = e.target.closest('.map-drop-zone');
        if (dz) dz.classList.remove('is-dragover');
    });

    mappingRoot.addEventListener('drop', (e) => {
        const dz = e.target.closest('.map-drop-zone');
        if (!dz) return;
        e.preventDefault();
        dz.classList.remove('is-dragover');
        if (!draggedSource) return;
        const key = dz.closest('[data-field]').dataset.field;
        fieldMatches[key] = { ...(fieldMatches[key] || {}), sheet: draggedSource.sheet, column: draggedSource.col };
        draggedSource = null;
        renderMappingPanel();
    });

    // ============ Mapping panel event delegation ============
    mappingRoot.addEventListener('click', (e) => {
        const clearAllDirect = e.target.closest('#clear-all-direct');
        if (clearAllDirect) {
            DIRECT_FIELDS.forEach((f) => delete fieldMatches[f.key]);
            renderMappingPanel();
            return;
        }

        const clearLink = e.target.closest('.map-clear-link');
        if (clearLink) {
            const slot = clearLink.closest('[data-field]');
            delete fieldMatches[slot.dataset.field];
            renderMappingPanel();
            return;
        }

        const selectLink = e.target.closest('.map-select-link');
        if (selectLink) {
            const key = selectLink.closest('[data-field]').dataset.field;
            const field = DIRECT_FIELDS.find((f) => f.key === key);
            openPalette(`Match "${field.label}"`, 'column', null, (sheet, col) => {
                fieldMatches[key] = { ...(fieldMatches[key] || {}), sheet, column: col };
                renderMappingPanel();
            });
            return;
        }

        if (e.target.closest('.map-derive')) return; // handled by the checkbox's own change event

        const afToggle = e.target.closest('[data-role="af-toggle"]');
        if (afToggle) {
            activeFilterState.enabled = !activeFilterState.enabled;
            renderMappingPanel();
            return;
        }

        const afColBtn = e.target.closest('[data-role="af-column-btn"]');
        if (afColBtn) {
            const scopeSheet = fieldMatches.meter_number ? fieldMatches.meter_number.sheet : null;
            if (!scopeSheet) { alert('Match "Meter Number" first — this filter uses the same sheet.'); return; }
            openPalette('Choose the status column', 'column', scopeSheet, (sheet, col) => {
                activeFilterState.sheet = sheet;
                activeFilterState.column = col;
                renderMappingPanel();
            });
            return;
        }

        const liCombinedBtn = e.target.closest('[data-role="li-combined-btn"]');
        if (liCombinedBtn) {
            openSheetThenColumnPalette(
                'Choose your line-items sheet',
                'Choose the column that identifies each customer',
                (sheet, col) => {
                    setLineItemsSheet(sheet);
                    lineItemsState.group_by_column = col;
                    renderMappingPanel();
                }
            );
            return;
        }

        const calcSheetBtn = e.target.closest('[data-role="calc-sheet-btn"]');
        if (calcSheetBtn) {
            openPalette('Which sheet has this data?', 'sheet', null, (sheet) => {
                setLineItemsSheet(sheet);
                renderMappingPanel();
            });
            return;
        }

        const calcValueBtn = e.target.closest('[data-role="calc-value-btn"]');
        if (calcValueBtn) {
            if (!lineItemsState.sheet) { alert('Choose the line-items sheet first.'); return; }
            const key = calcValueBtn.closest('[data-field]').dataset.field;
            const field = CALCULATED_FIELDS.find((f) => f.key === key);
            openPalette(`${field.label}: choose the value column to sum`, 'column', lineItemsState.sheet, (sheet, col) => {
                calcState[key].value_column = col;
                renderMappingPanel();
            });
            return;
        }

        const calcFilterBtn = e.target.closest('[data-role="calc-filter-btn"]');
        if (calcFilterBtn) {
            if (!lineItemsState.sheet) { alert('Choose the line-items sheet first.'); return; }
            const key = calcFilterBtn.closest('[data-field]').dataset.field;
            openPalette('Choose which column to check', 'column', lineItemsState.sheet, (sheet, col) => {
                calcState[key].filter.column = col;
                renderMappingPanel();
            });
            return;
        }

        const pillBtn = e.target.closest('.pill-toggle button');
        if (pillBtn) {
            const key = pillBtn.closest('[data-field]').dataset.field;
            calcState[key].filter.match_type = pillBtn.dataset.mt;
            renderMappingPanel();
            return;
        }

        const tagRemove = e.target.closest('.tag-chip button');
        if (tagRemove) {
            const key = tagRemove.closest('[data-field]').dataset.field;
            const val = tagRemove.dataset.value;
            calcState[key].filter.values = calcState[key].filter.values.filter((v) => v !== val);
            renderMappingPanel();
        }
    });

    mappingRoot.addEventListener('change', (e) => {
        if (e.target.classList.contains('map-derive-toggle')) {
            const key = e.target.closest('[data-field]').dataset.field;
            fieldMatches[key] = { ...(fieldMatches[key] || {}), mode: e.target.checked ? 'derive_from_date' : 'direct' };
        }
    });

    mappingRoot.addEventListener('input', (e) => {
        if (e.target.id === 'af-value') {
            activeFilterState.value = e.target.value;
        }
    });

    mappingRoot.addEventListener('keydown', (e) => {
        if (e.target.classList.contains('tag-input') && e.key === 'Enter') {
            e.preventDefault();
            const val = e.target.value.trim();
            if (!val) return;
            const key = e.target.closest('[data-field]').dataset.field;
            if (!calcState[key].filter.values.includes(val)) {
                calcState[key].filter.values.push(val);
            }
            renderMappingPanel();
        }
    });

    // ============ Saved mappings ============
    async function loadSavedMappingsList() {
        const select = document.getElementById('saved-mapping-select');
        if (!select) return;
        try {
            const response = await fetch('/mappings');
            const names = await response.json();
            select.innerHTML = '<option value="">— Load a saved mapping —</option>' +
                names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
        } catch (e) {
            // Non-fatal: the saved-mapping list is a convenience, not required to run a reconciliation.
        }
    }

    async function onLoadMappingClick() {
        const select = document.getElementById('saved-mapping-select');
        const name = select.value;
        if (!name) return;
        try {
            const response = await fetch(`/mappings/${encodeURIComponent(name)}`);
            if (response.status !== 200) throw new Error('Could not load mapping');
            const config = await response.json();
            applyMappingConfig(config);
            renderMappingPanel();
        } catch (e) {
            alert(`Error loading mapping: ${e.message}`);
        }
    }

    async function onSaveMappingClick() {
        const status = document.getElementById('mapping-save-status');
        const nameInput = document.getElementById('save-mapping-name');
        const name = nameInput.value.trim();
        if (!name) {
            alert('Enter a name to save this mapping under.');
            return;
        }
        const config = gatherMappingConfig();
        try {
            const response = await fetch(`/mappings/${encodeURIComponent(name)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config),
            });
            if (response.status !== 200) throw new Error('Save failed');
            status.textContent = `Saved as "${name}"`;
            loadSavedMappingsList();
        } catch (e) {
            status.textContent = `Error: ${e.message}`;
        }
    }

    async function onDeleteMappingClick() {
        const select = document.getElementById('saved-mapping-select');
        const name = select.value;
        if (!name) {
            alert('Pick a saved mapping from the dropdown first.');
            return;
        }
        if (name === 'electra_default') {
            alert('The bundled "electra_default" mapping is protected and can\'t be deleted.');
            return;
        }
        if (!confirm(`Delete the saved mapping "${name}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/mappings/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (response.status !== 200) throw new Error('Delete failed');
            loadSavedMappingsList();
            document.getElementById('mapping-save-status').textContent = `Deleted "${name}"`;
        } catch (e) {
            alert(`Error deleting mapping: ${e.message}`);
        }
    }

    async function onResetAllMappingsClick() {
        if (!confirm('Delete every saved mapping except the bundled default? This can\'t be undone.')) return;
        try {
            const response = await fetch('/mappings', { method: 'DELETE' });
            if (response.status !== 200) throw new Error('Reset failed');
            loadSavedMappingsList();
            document.getElementById('mapping-save-status').textContent = 'All saved mappings deleted (default kept).';
        } catch (e) {
            alert(`Error resetting mappings: ${e.message}`);
        }
    }

    // ============ Run Reconciliation ============
    reconcileBtn.addEventListener('click', async () => {
        if (!altecoFile || !electraFile) return;

        const mappingConfig = gatherMappingConfig();

        const formData = new FormData();
        formData.append('alteco_file', altecoFile);
        formData.append('electra_file', electraFile);
        formData.append('mapping', JSON.stringify(mappingConfig));

        reconcileBtn.disabled = true;
        reconcileBtn.querySelector('.btn-text').textContent = 'Processing...';
        reconcileSpinner.style.display = 'inline-block';

        try {
            const response = await fetch('/reconcile', { method: 'POST', body: formData });
            const results = await response.json();

            if (response.status !== 200) {
                throw new Error(results.error || results.detail || 'An unknown error occurred.');
            }

            renderSummaryStrip(results);
            renderPhaseData(results.step0, 'step0-table-container', 'step0-badge', 'step0-search');
            renderPhaseData(results.step1, 'step1-table-container', 'step1-badge', 'step1-search');
            renderPhaseData(results.step2, 'step2-table-container', 'step2-badge', 'step2-search');
            renderPhaseData(results.step3, 'step3-table-container', 'step3-badge', 'step3-search');

            goToStep(3);
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            reconcileBtn.disabled = false;
            reconcileBtn.querySelector('.btn-text').textContent = 'Run Reconciliation';
            reconcileSpinner.style.display = 'none';
            updateReconcileButtonState();
        }
    });

    // ============ Results rendering (unchanged from before) ============
    function renderSummaryStrip(results) {
        const strip = document.getElementById('summary-strip');
        const tiles = [
            { label: 'Coverage Gaps', count: (results.step0 || []).length },
            { label: 'Metadata Issues', count: (results.step1 || []).length },
            { label: 'Consumption Issues', count: (results.step2 || []).length },
            { label: 'Financial Issues', count: (results.step3 || []).length },
        ];

        strip.innerHTML = tiles.map(t => `
            <div class="stat-tile ${t.count === 0 ? 'is-clean' : 'is-flagged'}">
                <span class="stat-label">${t.label}</span>
                <div class="stat-value">${t.count}</div>
            </div>
        `).join('');
    }

    function renderPhaseData(dataArray, containerId, badgeId, searchId) {
        const container = document.getElementById(containerId);
        const badge = document.getElementById(badgeId);
        const searchInput = document.getElementById(searchId);

        if (!dataArray || dataArray.length === 0) {
            badge.textContent = '0 Issues';
            badge.className = 'badge success';
            container.innerHTML = '<p class="success-msg">No discrepancies found.</p>';
            if (searchInput) {
                searchInput.style.display = 'none';
                searchInput.value = '';
            }
            return;
        }

        badge.textContent = `${dataArray.length} Mismatches`;
        badge.className = 'badge error';
        container.innerHTML = createTable(dataArray);

        if (searchInput) {
            searchInput.style.display = 'block';
            searchInput.value = '';
            searchInput.oninput = () => {
                const term = searchInput.value.trim().toLowerCase();
                const filtered = term === '' ? dataArray : dataArray.filter(row => rowMatchesSearch(row, term));
                container.innerHTML = filtered.length > 0
                    ? createTable(filtered)
                    : '<p class="no-results-msg">No results match your search.</p>';
            };
        }
    }

    function rowMatchesSearch(row, term) {
        return Object.values(row).some((value) =>
            value !== null && value !== undefined && String(value).toLowerCase().includes(term)
        );
    }

    const MONO_COLUMNS = new Set(['Meter Number', 'Customer ID', 'Value', 'Alteco Value', 'Client Value']);

    function createTable(data) {
        const headers = Object.keys(data[0]).filter(h => h !== 'Phase');

        const headerHtml = headers.map(h => `<th>${h}</th>`).join('');
        const bodyHtml = data.map(row => {
            const cells = headers.map(h => {
                const cls = MONO_COLUMNS.has(h) ? ' class="cell-mono"' : '';
                return `<td${cls}>${row[h]}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        return `
            <table>
                <thead><tr>${headerHtml}</tr></thead>
                <tbody>${bodyHtml}</tbody>
            </table>
        `;
    }
});
