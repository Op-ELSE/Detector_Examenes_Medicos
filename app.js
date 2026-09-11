// static/app.js
document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const uploadBtn = document.getElementById('upload-btn');
  const tableContainer = document.getElementById('table-container');
  const exportBtn = document.getElementById('export-btn');
  const statusDiv = document.getElementById('status');

  // Helper to show a status message
  const showStatus = (msg, isError = false) => {
    statusDiv.textContent = msg;
    statusDiv.style.color = isError ? 'red' : 'green';
  };

  // Build HTML table from an array of records
  const buildTable = (records) => {
    if (!records || records.length === 0) {
      tableContainer.innerHTML = '<p>No hay datos para mostrar.</p>';
      return;
    }
    const cols = Object.keys(records[0]);
    const table = document.createElement('table');
    table.className = 'result-table';
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    cols.forEach(col => {
      const th = document.createElement('th');
      th.textContent = col.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    records.forEach(rec => {
      const tr = document.createElement('tr');
      cols.forEach(col => {
        const td = document.createElement('td');
        let val = rec[col];
        if (Array.isArray(val)) val = val.join('; ');
        td.textContent = val ?? '';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableContainer.innerHTML = '';
    tableContainer.appendChild(table);
  };

  // Upload and extract handler
  const uploadAndExtract = async () => {
    if (fileInput.files.length === 0) {
      showStatus('Seleccione al menos un archivo PDF.', true);
      return;
    }
    const formData = new FormData();
    for (const file of fileInput.files) {
      formData.append('files', file);
    }
    showStatus('Subiendo y procesando...');
    try {
      const resp = await fetch('/api/upload-and-extract', {
        method: 'POST',
        body: formData
      });
      if (!resp.ok) throw new Error(`Error ${resp.status}`);
      const data = await resp.json();
      const results = data.results || [];
      buildTable(results);
      // Enable export button when we have successful rows
      const hasSuccess = results.some(r => r.status === 'success');
      exportBtn.disabled = !hasSuccess;
      showStatus('Procesamiento completado.');
    } catch (e) {
      console.error(e);
      showStatus('Falló la extracción: ' + e.message, true);
    }
  };

  uploadBtn.addEventListener('click', uploadAndExtract);

  // Export to Excel handler
  exportBtn.addEventListener('click', async () => {
    const rows = Array.from(document.querySelectorAll('.result-table tbody tr'));
    if (rows.length === 0) return;
    const cols = Array.from(document.querySelectorAll('.result-table th')).map(th => th.textContent);
    const records = rows.map(tr => {
      const obj = {};
      tr.querySelectorAll('td').forEach((td, i) => {
        const key = cols[i].replace(/\s+/g, '_').toLowerCase();
        obj[key] = td.textContent;
      });
      return obj;
    });
    try {
      const resp = await fetch('/api/export-excel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ records })
      });
      if (!resp.ok) throw new Error(`Error ${resp.status}`);
      const blob = await resp.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'Examenes_Medicos.xlsx';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      showStatus('Error al descargar Excel: ' + e.message, true);
    }
  });
});
