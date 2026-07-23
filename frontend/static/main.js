document.addEventListener('DOMContentLoaded', () => {
    const altecoZone = document.getElementById('alteco-drop-zone');
    const electraZone = document.getElementById('electra-drop-zone');
    const reconcileBtn = document.getElementById('reconcile-btn');
    const btnText = reconcileBtn.querySelector('.btn-text');
    const spinner = reconcileBtn.querySelector('.spinner');
    const resultsContainer = document.getElementById('results-container');

    let altecoFile = null;
    let electraFile = null;

    // Checks if both files are present and enables/disables the button
    function updateReconcileButtonState() {
        if (altecoFile && electraFile) {
            reconcileBtn.disabled = false;
        } else {
            reconcileBtn.disabled = true;
        }
    }

    function setupDropZone(zone, setFileCallback, clearFileCallback) {
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
                // Hide default prompt UI
                promptText.style.display = 'none';
                formatHint.style.display = 'none';
                uploadIcon.style.display = 'none';
                // Show file name & remove button
                fileDisplay.style.display = 'flex';
                fileNameDisplay.textContent = file.name;
                updateReconcileButtonState();
            }
        }

        // Drag & Drop Events
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('highlight');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('highlight');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('highlight');
            const file = e.dataTransfer.files[0];
            if (file) {
                input.files = e.dataTransfer.files; // Sync with hidden input
                handleFileSelection(file);
            }
        });

        // Click Event (via hidden input)
        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                handleFileSelection(input.files[0]);
            }
        });

        // Remove File Event
        removeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation(); // Prevents triggering the file input click
            
            clearFileCallback();
            input.value = ''; // Clear hidden input
            
            // Restore default prompt UI
            fileDisplay.style.display = 'none';
            fileNameDisplay.textContent = '';
            promptText.style.display = 'block';
            formatHint.style.display = 'block';
            uploadIcon.style.display = 'block';
            
            updateReconcileButtonState();
        });
    }

    // Initialize Drop Zones
    setupDropZone(
        altecoZone, 
        (file) => { altecoFile = file; }, 
        () => { altecoFile = null; }
    );
    
    setupDropZone(
        electraZone, 
        (file) => { electraFile = file; }, 
        () => { electraFile = null; }
    );

    // API Call & UI State Management
    reconcileBtn.addEventListener('click', async () => {
        if (!altecoFile || !electraFile) return;

        const formData = new FormData();
        formData.append('alteco_file', altecoFile);
        formData.append('electra_file', electraFile);

        // UI Loading State
        reconcileBtn.disabled = true;
        btnText.textContent = 'Processing...';
        spinner.style.display = 'inline-block';
        resultsContainer.style.display = 'none';

        try {
            const response = await fetch('/reconcile', {
                method: 'POST',
                body: formData,
            });

            const results = await response.json();

            if (response.status !== 200) {
                throw new Error(results.error || 'An unknown error occurred.');
            }

            // Reveal the results section
            resultsContainer.style.display = 'flex';

            // Render Phase 0
            renderPhaseData(
                results.step0,
                'step0-table-container',
                'step0-badge'
            );

            // Render Phase 1
            renderPhaseData(
                results.step1, 
                'step1-table-container', 
                'step1-badge'
            );

            // Render Phase 2
            renderPhaseData(
                results.step2,
                'step2-table-container',
                'step2-badge'
            );

            // Render Phase 3
            renderPhaseData(
                results.step3,
                'step3-table-container',
                'step3-badge'
            );

            // Scroll down slightly so results are clearly visible
            resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            // Restore Button State
            reconcileBtn.disabled = false;
            btnText.textContent = 'Run Reconciliation';
            spinner.style.display = 'none';
        }
    });

    function renderPhaseData(dataArray, containerId, badgeId) {
        const container = document.getElementById(containerId);
        const badge = document.getElementById(badgeId);

        if (!dataArray || dataArray.length === 0) {
            badge.textContent = '0 Issues';
            badge.className = 'badge success';
            container.innerHTML = '<p class="success-msg">Perfect match! No discrepancies found for this phase.</p>';
        } else {
            badge.textContent = `${dataArray.length} Mismatches`;
            badge.className = 'badge error';
            container.innerHTML = createTable(dataArray);
        }
    }

    function createTable(data) {
        const headers = Object.keys(data[0]).filter(h => h !== 'Phase');
        
        const headerHtml = headers.map(h => `<th>${h}</th>`).join('');
        const bodyHtml = data.map(row => {
            const cells = headers.map(h => `<td>${row[h]}</td>`).join('');
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