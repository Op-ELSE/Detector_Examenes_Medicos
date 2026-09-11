import os
import shutil
from pathlib import Path
from typing import List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from extractor import extract_medical_pdf, get_gemini_client
from excel_generator import generate_excel

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / 'uploads'
STATIC_DIR = BASE_DIR / 'static'

UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title='Detector de Campos de Exámenes Médicos')

# Habilitar CORS para despliegue en internet
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

class ExportRequest(BaseModel):
    records: List[Dict[str, Any]]

class ConfigRequest(BaseModel):
    api_key: str

FALLBACK_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Detector de Campos de Exámenes Médicos</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; color: #1e293b; margin: 0; padding: 30px 20px; }
    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    h1 { margin-top: 0; color: #0f172a; font-size: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 14px; }
    .upload-card { background: #f8fafc; border: 2px dashed #94a3b8; border-radius: 8px; padding: 24px; margin: 20px 0; display: flex; flex-wrap: wrap; gap: 15px; align-items: center; }
    input[type="file"] { font-size: 15px; padding: 8px 12px; background: white; border: 1px solid #cbd5e1; border-radius: 6px; cursor: pointer; }
    button { background-color: #2563eb; color: white; border: none; padding: 10px 22px; font-size: 15px; font-weight: 600; border-radius: 6px; cursor: pointer; }
    button:hover:not(:disabled) { background-color: #1d4ed8; }
    button:disabled { background-color: #94a3b8; cursor: not-allowed; opacity: 0.6; }
    #export-btn { background-color: #059669; }
    #export-btn:hover:not(:disabled) { background-color: #047857; }
    .status { margin-top: 15px; font-weight: 500; font-size: 15px; padding: 12px 16px; border-radius: 6px; display: none; }
    .status.active { display: block; }
    .status.info { background-color: #dbeafe; color: #1e40af; border: 1px solid #bfdbfe; }
    .status.error { background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
    .status.success { background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
    .table-wrapper { margin-top: 25px; overflow-x: auto; max-height: 550px; border: 1px solid #e2e8f0; border-radius: 8px; }
    table.result-table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
    table.result-table th { background-color: #0f172a; color: white; padding: 12px 14px; position: sticky; top: 0; z-index: 10; white-space: nowrap; }
    table.result-table td { padding: 10px 14px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; max-width: 250px; overflow: hidden; text-overflow: ellipsis; }
    table.result-table tr:nth-child(even) { background-color: #f8fafc; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔬 Detector de Campos de Exámenes Médicos</h1>
    <p style="color: #64748b; margin-top: -8px;">Selecciona uno o más PDFs de exámenes ocupacionales y presiona <b>Subir y Extraer</b>.</p>
    <div class="upload-card">
      <input type="file" id="file-input" multiple accept=".pdf" />
      <button type="button" id="upload-btn">Subir y Extraer</button>
      <button type="button" id="export-btn" disabled>Exportar a Excel</button>
    </div>
    <div id="status" class="status"></div>
    <div class="table-wrapper">
      <div id="table-container"></div>
    </div>
  </div>
  <script>
    document.addEventListener('DOMContentLoaded', () => {
      const fileInput = document.getElementById('file-input');
      const uploadBtn = document.getElementById('upload-btn');
      const tableContainer = document.getElementById('table-container');
      const exportBtn = document.getElementById('export-btn');
      const statusDiv = document.getElementById('status');
      let currentResults = [];

      const showStatus = (msg, type = 'info') => {
        statusDiv.textContent = msg;
        statusDiv.className = `status active ${type}`;
      };

      const buildTable = (records) => {
        if (!records || records.length === 0) {
          tableContainer.innerHTML = '<p style="padding: 15px; color: #64748b;">No hay datos extraídos.</p>';
          return;
        }
        const cols = Object.keys(records[0]);
        const table = document.createElement('table');
        table.className = 'result-table';
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        cols.forEach(col => {
          const th = document.createElement('th');
          th.textContent = col.replace(/_/g, ' ').toUpperCase();
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
            td.textContent = (val !== null && val !== undefined) ? val : '';
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        tableContainer.innerHTML = '';
        tableContainer.appendChild(table);
      };

      uploadBtn.onclick = async () => {
        if (!fileInput.files || fileInput.files.length === 0) {
          showStatus('Por favor, selecciona al menos un archivo PDF.', 'error');
          return;
        }
        const formData = new FormData();
        for (let i = 0; i < fileInput.files.length; i++) {
          formData.append('files', fileInput.files[i]);
        }
        uploadBtn.disabled = true;
        showStatus('⏳ Subiendo y extrayendo campos con Inteligencia Artificial... por favor espera.', 'info');
        try {
          const resp = await fetch('/api/upload-and-extract', { method: 'POST', body: formData });
          if (!resp.ok) throw new Error(`Error en el servidor: HTTP ${resp.status}`);
          const data = await resp.json();
          currentResults = data.results || [];
          buildTable(currentResults);
          const hasSuccess = currentResults.some(r => r.status === 'success');
          exportBtn.disabled = !hasSuccess;
          uploadBtn.disabled = false;
          showStatus('✅ ¡Procesamiento completado con éxito! Ya puedes exportar a Excel.', 'success');
        } catch (e) {
          console.error(e);
          uploadBtn.disabled = false;
          showStatus('❌ Falló la extracción: ' + e.message, 'error');
        }
      };

      exportBtn.onclick = async () => {
        if (!currentResults || currentResults.length === 0) return;
        showStatus('Generando archivo Excel...', 'info');
        try {
          const resp = await fetch('/api/export-excel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ records: currentResults })
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const blob = await resp.blob();
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = 'Examenes_Medicos_Consolidado.xlsx';
          document.body.appendChild(a);
          a.click();
          a.remove();
          window.URL.revokeObjectURL(url);
          showStatus('✅ Archivo Excel descargado correctamente.', 'success');
        } catch (e) {
          console.error(e);
          showStatus('❌ Error al exportar: ' + e.message, 'error');
        }
      };
    });
  </script>
</body>
</html>
"""

@app.get('/')
async def root():
    index_path = STATIC_DIR / 'index.html'
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(content=FALLBACK_HTML)

@app.get('/api/config')
async def get_config():
    client = get_gemini_client()
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        env_path = BASE_DIR / '.env'
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8-sig').splitlines():
                line = line.strip()
                if line.startswith('GEMINI_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip("'\"")
                    break
    has_key = bool(key and len(key) > 10)
    masked = f"{key[:6]}...{key[-4:]}" if has_key else ''
    return {'has_key': has_key, 'masked_key': masked}

@app.post('/api/config')
async def save_config(req: ConfigRequest):
    new_key = req.api_key.strip().strip("'\"")
    if not new_key:
        raise HTTPException(status_code=400, detail='La clave no puede estar vacia')
    
    os.environ['GEMINI_API_KEY'] = new_key
    env_path = BASE_DIR / '.env'
    env_path.write_text(f'GEMINI_API_KEY={new_key}\n', encoding='utf-8')
    return {'status': 'ok', 'message': 'Clave guardada exitosamente'}

@app.get('/api/sample-files')
async def list_sample_files():
    files = []
    for f in sorted(BASE_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() == '.pdf':
            files.append({
                'name': f.name,
                'size_bytes': f.stat().st_size,
                'size_mb': round(f.stat().st_size / (1024 * 1024), 2)
            })
    return {'files': files}

@app.post('/api/upload-and-extract')
async def upload_and_extract(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        safe_name = Path(file.filename).name
        save_path = UPLOAD_DIR / safe_name
        with open(save_path, 'wb') as f:
            shutil.copyfileobj(file.file, f)
        
        try:
            record = extract_medical_pdf(str(save_path), safe_name)
            record['status'] = 'success'
        except Exception as e:
            record = {
                'archivo': safe_name,
                'status': 'error',
                'error_detail': str(e),
                'dni': '',
                'apellidos_nombres': 'Error al procesar',
                'aptitud': 'OBSERVADO / PENDIENTE'
            }
        results.append(record)
    return  {'results': results}

@app.post('/api/extract-sample')
async def extract_sample(filename: str = Form(...)):
    pdf_path = BASE_DIR / filename
    if not pdf_path.exists():
        pdf_path = UPLOAD_DIR / filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail='Archivo no encontrado')
    
    record = extract_medical_pdf(str(pdf_path), filename)
    record['status'] = 'success'
    return record

@app.post('/api/export-excel')
async def export_excel(req: ExportRequest):
    if not req.records:
        raise HTTPException(status_code=400, detail='No hay registros para exportar')
    
    buffer = generate_excel(req.records)
    filename = 'Examenes_Medicos_Consolidado.xlsx'
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Access-Control-Expose-Headers': 'Content-Disposition'
    }
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=headers
    )

@app.get('/api/pdf/{filename}')
async def view_pdf(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        file_path = BASE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='PDA no encontrado')
    return FileResponse(str(file_path), media_type='application/pdf')
