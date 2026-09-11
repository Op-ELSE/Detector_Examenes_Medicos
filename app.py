import os
import shutil
from pathlib import Path
from typing import List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
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

app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

class ExportRequest(BaseModel):
    records: List[Dict[str, Any]]

class ConfigRequest(BaseModel):
    api_key: str

@app.get('/')
async def root():
    index_path = STATIC_DIR / 'index.html'
    if not index_path.exists():
        return JSONResponse({'error': 'Frontend no encontrado'}, status_code=404)
    return FileResponse(str(index_path))

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
