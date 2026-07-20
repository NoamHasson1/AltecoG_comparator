document.addEventListener('DOMContentLoaded', () => {
    const altecoZone = document.getElementById('alteco-drop-zone');
    const electraZone = document.getElementById('electra-drop-zone');
    const reconcileBtn = document.getElementById('reconcile-btn');
    const resultsContainer = document.getElementById('results-container');
    const resultsTitle = document.getElementById('results-title');
    const resultsTableContainer = document.getElementById('results-table-container');

    let altecoFile = null;
    let electraFile = null;

    function setupDropZone(zone, fileStore) {
        const input = zone.querySelector('.drop-zone-input');
        const promptText = zone.querySelector('.prompt-text');
        const fileNameDisplay = zone.querySelector('.file-name');

        zone.addEventListener('click', () => input.click());

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
                input.files = e.dataTransfer.files;
                fileStore(file);
                promptText.style.display = 'none';
                fileNameDisplay.textContent = file.name;
            }
        });

        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                const file = input.files[0];
                fileStore(file);
                promptText.style.display = 'none';
                fileNameDisplay.textContent = file.name;
            }
        });
    }

    setupDropZone(altecoZone, (file) => { altecoFile = file; });
    setupDropZone(electraZone, (file) => { electraFile = file; });

    reconcileBtn.addEventListener('click', async () => {
        if (!altecoFile || !electraFile) {
            alert('Please select both Alteco and Electra files.');
            return;
        }

        const formData = new FormData();
        formData.append('alteco_file', altecoFile);
        formData.append('electra_file', electraFile);

        resultsTitle.textContent = 'Processing...';
        resultsTableContainer.innerHTML = '';

        try {
            const response = await fetch('/reconcile', {
                method: 'POST',
                body: formData,
            });

            const results = await response.json();

            if (response.status !== 200) {
                throw new Error(results.error || 'An unknown error occurred.');
            }

            if (results.length === 0) {
                resultsTitle.textContent = '✅ Amazing! No metadata mismatches found.';
            } else {
                resultsTitle.textContent = `Found ${results.length} Mismatches`;
                resultsTableContainer.innerHTML = createTable(results);
            }
        } catch (error) {
            resultsTitle.textContent = 'Error';
            resultsTableContainer.innerHTML = `<p style="color: red;">${error.message}</p>`;
        }
    });

    function createTable(data) {
        const headers = Object.keys(data[0]);
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