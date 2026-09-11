import os
import io
import json
import re
from pathlib import Path
import fitz  # PyMuPDF
from google import genai
from google.genai import types

def get_gemini_client():
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8-sig').splitlines():
                line = line.strip()
                if line.startswith('GEMINI_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip('\'"')
                    break
    if not key:
        return None
    return genai.Client(api_key=key)

def select_camo_pages(pdf_path, max_pages=3):
    """
    Encuentra las paginas clave del Certificado de Aptitud Medica (CAMO) o resumen.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages <= max_pages:
        selected = list(range(total_pages))
    else:
        camo_pages = []
        keywords = ['aptitud', 'certificado', 'camo', 'anexo 16', 'anexo 7', 'apto', 'restriccion', 'conclusi']
        for i in range(min(total_pages, 8)):
            text = doc[i].get_text().lower()
            if any(k in text for k in keywords):
                camo_pages.append(i)
        
        if not camo_pages:
            selected = list(range(min(total_pages, max_pages)))
        else:
            selected = camo_pages[:max_pages]

    new_doc = fitz.open()
    for p in selected:
        new_doc.insert_pdf(doc, from_page=p, to_page=p)
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    doc.close()
    return pdf_bytes, len(selected)

# Dynamic prompt loading all fields from fields.json
from pathlib import Path
import json

# Load the full list of fields from fields.json
FIELDS_PATH = Path(__file__).parent / 'fields.json'
if FIELDS_PATH.exists():
    with FIELDS_PATH.open(encoding='utf-8') as f:
        ALL_FIELDS = json.load(f)
else:
    ALL_FIELDS = []

def build_dynamic_prompt():
    """Construye el prompt que incluye la lista de campos para Gemini."""
    fields_list = ", ".join(ALL_FIELDS)
    return (
        "Eres un auditor médico experto en Salud Ocupacional.\n"
        "Analiza el documento PDF y extrae la información correspondiente a los siguientes campos:\n"
        f"{fields_list}\n"
        "Devuelve un objeto JSON donde cada clave sea el nombre exacto del campo. Si un campo no está presente, omítelo.\n"
        "No añadas información adicional fuera de los campos solicitados."
    )

EXTRACTION_PROMPT = build_dynamic_prompt()

def extract_with_gemini(pdf_path, filename):
    client = get_gemini_client()
    if not client:
        raise ValueError('No se encontro la clave de API de Gemini.')

    pdf_bytes, pages_count = select_camo_pages(pdf_path, max_pages=3)
    
    response = client.models.generate_content(
        model='gemini-flash-latest',
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf'),
            EXTRACTION_PROMPT
        ],
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            temperature=0.1
        )
    )

    raw_text = response.text.strip()
    if raw_text.startswith('```json'):
        raw_text = raw_text[7:]
    if raw_text.endswith('```'):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    data = json.loads(raw_text)
    data['archivo'] = filename
    return data

def extract_locally_fallback(pdf_path, filename):
    doc = fitz.open(pdf_path)
    text = ''
    for p in doc[:3]:
        text += p.get_text() + '\n'
    doc.close()

    dni_match = re.search(r'\b(\d{8})\b', text)
    dni = dni_match.group(1) if dni_match else ''
    
    aptitud = 'APTO'
    if 'NO APTO' in text.upper():
        aptitud = 'NO APTO'
    elif 'RESTRICCION' in text.upper() or 'OBSERVACI' in text.upper():
        aptitud = 'APTO CON RESTRICCIONES'

    return {
        'archivo': filename,
        'dni': dni,
        'apellidos_nombres': 'Revisar manualmente en visor',
        'edad': '',
        'sexo': '',
        'puesto': '',
        'empresa_empleadora': '',
        'empresa_cliente': '',
        'tipo_examen': 'Periodico' if 'PERIODICO' in text.upper() else 'Ingreso',
        'fecha_examen': '',
        'fecha_vencimiento': '',
        'aptitud': aptitud,
        'restricciones': 'Revisar PDF',
        'diagnosticos': 'Revisar PDF',
        'recomendaciones': '',
        'clinica': '',
        'medico_evaluador': ''
    }

def extract_medical_pdf(pdf_path, filename=None):
    if filename is None:
        filename = os.path.basename(pdf_path)
    try:
        return extract_with_gemini(pdf_path, filename)
    except Exception as e:
        print(f'Error con Gemini para {filename}: {e}. Usando fallback local.')
        data = extract_locally_fallback(pdf_path, filename)
        data['error_gemini'] = str(e)
        return data
