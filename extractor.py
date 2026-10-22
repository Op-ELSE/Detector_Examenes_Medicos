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

def normalize_date_format(val):
    """Convierte cualquier fecha detectada al formato estandar mm/dd/yyyy (mes/día/año)."""
    if not val:
        return val
    s = str(val).strip()
    # Coincidencia con YYYY-MM-DD o YYYY/MM/DD o YYYY.MM.DD
    m1 = re.search(r'\b(19\d\d|20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b', s)
    if m1:
        y, m, d = m1.group(1), int(m1.group(2)), int(m1.group(3))
        return f'{m:02d}/{d:02d}/{y}'
    # Coincidencia con DD-MM-YYYY o DD/MM/YYYY o DD.MM.YYYY
    m2 = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](19\d\d|20\d\d)\b', s)
    if m2:
        d, m, y = int(m2.group(1)), int(m2.group(2)), m2.group(3)
        return f'{m:02d}/{d:02d}/{y}'
    return s

def normalize_aptitud(val):
    """Estandariza los resultados de aptitud a: APTO, NO APTO o APTO CON RESTRICCIONES."""
    if not val:
        return val
    s = str(val).strip().upper()
    if 'NO APTO' in s:
        return 'NO APTO'
    if 'RESTRICCI' in s or 'OBSERV' in s:
        return 'APTO CON RESTRICCIONES'
    if 'APTO' in s:
        return 'APTO'
    return s

def clean_numeric_value(val):
    """
    Si el valor contiene datos numéricos de laboratorio o medidas,
    remueve las unidades de medida dejando únicamente el número.
    Ejemplos: '14.5 g/dl' -> '14.5', '120/80 mmHg' -> '120/80', '85 mg/dL' -> '85'.
    """
    if val is None:
        return val
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    if not s:
        return s

    # No alterar fechas con barras o guiones tipo 01/25/2020
    if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', s) or re.search(r'\b\d{4}-\d{2}-\d{2}\b', s):
        return s

    # Si es puramente texto cualitativo (ej. 'Positivo', 'Negativo', 'Normal', 'No reactivo', 'APTO')
    if not re.search(r'\d', s):
        return s

    # Patrón para número con posible rango/presión (ej: 120/80 o 14.5 o 250,000)
    # Extraer dígitos, comas/puntos decimales o barra de presión
    m = re.match(r'^\s*([><=~±]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*(?:[a-zA-Z%µ/°].*)?$', s)
    if m:
        clean_num = m.group(1).strip()
        return clean_num

    # Si contiene número seguido de unidades comunes (mg/dl, g/dl, %, mmhg, etc.)
    cleaned = re.sub(r'(?i)\s*(g/dl|mg/dl|mmol/l|ui/l|u/l|u/ml|mmhg|cm|kg|m2|m|l|ml|%|porcentaje|x10\^?\d*|cel/campo|p/c|leuc/campo|fl|pg|g/l|seg|segundos|bpm|lpm|rpm)\s*$', '', s).strip()
    return cleaned if cleaned else s

def _append_comment_if_extra(std_choice, original_text):
    """
    Si el texto original contiene detalles adicionales significativos más allá de la simple
    etiqueta normalizada (ej: 'NORMAL: campos limpios', 'ALTERADO: soplo sistolico',
    'SI: con firma digital'), concatena: OPCION - Comentario Adicional.
    """
    if not original_text:
        return std_choice
    orig_clean = str(original_text).strip()
    
    # Si ya viene en formato 'OPCION - Comentario' (generado directamente por Gemini)
    if ' - ' in orig_clean:
        partes = orig_clean.split(' - ', 1)
        base = partes[0].strip().upper()
        det = partes[1].strip()
        if det:
            return f"{std_choice} - {det}"
        return std_choice

    orig_upper = orig_clean.upper()
    
    # Frases que simplemente significan NORMAL sin constituir un hallazgo adicional
    trivial_normals = [
        'NORMAL', 'SIN ALTERACIONES', 'S/A', 'SIN ALTERACION', 'CONSERVADO', 'CONSERVADA',
        'APARENTEMENTE NORMAL', 'ADECUADO', 'ADECUADA', 'BUENO', 'BUENA', 'VENTILAN BIEN',
        'CAMPOS PULMONARES LIMPIOS Y NORMALES', 'CAMPOS LIMPIOS', 'SIN LESIONES',
        'NO SE OBSERVAN ALTERACIONES', 'NEGATIVO', '0', '0 MG/DL', 'NO CONTIENE'
    ]
    if any(orig_upper == tn or orig_upper == f"NORMAL {tn}" for tn in trivial_normals):
        return std_choice

    # Quitar palabras de prefijo redundantes con límites de palabra (\b)
    cleaned_detail = re.sub(
        r'^\s*\b(normal|alterado|anormal|patologico|si|sí|se realizo|se realizó|no|positivo|negativo|conservado|conservada|limpido|límpido|turbio|sinusal|ritmo sinusal)\b\s*[-:,;.]*\s*',
        '',
        orig_clean,
        flags=re.IGNORECASE
    ).strip()

    # Si queda texto adicional con significado clínico
    if cleaned_detail and len(cleaned_detail) > 2 and cleaned_detail.upper() != std_choice.upper():
        cleaned_detail = cleaned_detail.strip(" '\"-:,;()[]+")
        if cleaned_detail:
            cleaned_detail = cleaned_detail[0].upper() + cleaned_detail[1:] if len(cleaned_detail) > 1 else cleaned_detail
            return f"{std_choice} - {cleaned_detail}"

    return std_choice

def normalize_standard_values(key, val):
    """
    Estandariza los valores categóricos a formato 'OPCION' o 'OPCION - Comentario adicional'
    si el examen médico reporta hallazgos específicos.
    Aptitud médica final se mantiene estrictamente pura ('APTO', 'NO APTO', 'APTO CON RESTRICCIONES').
    Recomendaciones, observaciones y conclusiones extensas se mantienen como texto libre.
    """
    if val is None:
        return val
    s = str(val).strip()
    if not s:
        return s
    
    key_lower = key.lower()
    
    # Excluir campos de texto libre narrativo (Recomendaciones, Observaciones, Conclusiones, Nombres y Firmas de Profesionales)
    if any(k in key_lower for k in ['recomendaci', 'observaci', 'conclusion', 'hallazgo', 'nombre', 'restricci', 'motivo', 'instrumento', 'centro_medico', 'comentario', 'firma', 'validacion']):
        return s

    s_upper = s.upper()

    # 1. Aptitud médica final o sectorial (ESTRICTAMENTE PURA, sin comentarios anexados aquí)
    if 'aptitud' in key_lower or key_lower in ['resultado_aptitud_final', 'alt_resultado_de_suficiencia']:
        if 'NO APTO' in s_upper:
            return 'NO APTO'
        if 'RESTRICCI' in s_upper or 'OBSERV' in s_upper:
            return 'APTO CON RESTRICCIONES'
        if 'APTO' in s_upper:
            return 'APTO'
        return s

    # 2. Campos booleanos / Si-No (Pruebas realizadas, validaciones, firmas)
    if any(k in key_lower for k in ['realizada', 'realizado', 'validada', 'validado', 'declarado', 'cumple']):
        if any(w in s_upper for w in ['SI', 'SÍ', 'REALIZADO', 'REALIZADA', 'APLICADO', 'VALIDADO', 'CORRECTO', 'TRUE', '1']):
            return _append_comment_if_extra('SI', s)
        if any(w in s_upper for w in ['NO', 'NO REALIZADO', 'NO REALIZADA', 'FALSO', 'FALSE', '0']):
            return _append_comment_if_extra('NO', s)
        return s

    # 3. Exámenes toxicológicos / Drogas (Cocaína, Cannabinoides)
    if 'dro_' in key_lower or 'cocaina' in key_lower or 'cannabinoide' in key_lower:
        if any(w in s_upper for w in ['NO REACTIVO', 'NEGATIVO', 'NO DETECTADO']):
            return _append_comment_if_extra('NO REACTIVO', s)
        if any(w in s_upper for w in ['REACTIVO', 'POSITIVO', 'DETECTADO']):
            return _append_comment_if_extra('REACTIVO', s)
        if 'INDETERMINADO' in s_upper or 'DUDOSO' in s_upper:
            return _append_comment_if_extra('INDETERMINADO', s)

    # 4. Grupo sanguíneo ABO y Factor RH
    if 'rh_grupo_sanguineo' in key_lower:
        m_abo = re.search(r'\b(A|B|AB|O)\b', s_upper)
        if m_abo:
            return m_abo.group(1)
    if 'rh_factor' in key_lower or 'factor_rh' in key_lower:
        if 'POS' in s_upper or '+' in s_upper:
            return 'POSITIVO (+)'
        if 'NEG' in s_upper or '-' in s_upper:
            return 'NEGATIVO (-)'

    # 5. EKG: Ritmo cardíaco y ritmo sinusal
    if 'ekg_ritmo' in key_lower:
        if 'SINUSAL' in s_upper:
            return _append_comment_if_extra('SINUSAL', s)
        if 'ARRIT' in s_upper:
            return _append_comment_if_extra('ARRITMIA', s)
        if 'NO SINUSAL' in s_upper:
            return _append_comment_if_extra('NO SINUSAL', s)

    # 6. Agudeza visual / Oftalmología
    if 'oft_resultado_de_ishihara' in key_lower or 'vision_de_colores' in key_lower:
        if any(w in s_upper for w in ['NORMAL', 'NEGATIVO', 'CONSERVAD', 'CONSERVA']):
            return _append_comment_if_extra('NORMAL', s)
        if any(w in s_upper for w in ['ALTERAD', 'DEFICIT', 'POSITIVO', 'DALTONISMO', 'ANORMAL']):
            return _append_comment_if_extra('ALTERADO', s)

    if 'oft_uso_de_lentes' in key_lower:
        if any(w in s_upper for w in ['SI', 'SÍ', 'USA', 'CORRECTOR']):
            return _append_comment_if_extra('SI', s)
        if any(w in s_upper for w in ['NO', 'NO USA']):
            return _append_comment_if_extra('NO', s)

    if 'oft_estereopsis' in key_lower:
        if any(w in s_upper for w in ['NORMAL', 'CONSERVAD', 'PRESENTE', 'POSITIV']):
            return _append_comment_if_extra('CONSERVADA', s)
        if any(w in s_upper for w in ['ALTERAD', 'ANORMAL', 'DISMINUID', 'NEGATIV']):
            return _append_comment_if_extra('ALTERADA', s)

    # 7. Orina: Aspecto, Color, Elementos Químicos
    if 'ori_aspecto' in key_lower:
        if 'LIMPID' in s_upper or 'CLARO' in s_upper or 'TRANSPARENTE' in s_upper:
            return _append_comment_if_extra('LIMPIDO', s)
        if 'LIGERAMENTE TURBIO' in s_upper or 'SEMILIMPIDO' in s_upper:
            return _append_comment_if_extra('LIGERAMENTE TURBIO', s)
        if 'TURBIO' in s_upper:
            return _append_comment_if_extra('TURBIO', s)

    if 'ori_color' in key_lower:
        if 'AMARILLO' in s_upper or 'AMBAR' in s_upper:
            return _append_comment_if_extra('AMARILLO', s)
        if 'ROJIZO' in s_upper or 'HEMAT' in s_upper:
            return _append_comment_if_extra('ROJIZO', s)

    if any(k in key_lower for k in ['ori_glucosa', 'ori_hemoglobina', 'ori_proteinas', 'ori_sangre', 'ori_cetonas', 'ori_bilirrubina', 'ori_nitritos']):
        if any(w in s_upper for w in ['NEGATIVO', 'NO CONTIENE', 'AUSENTE', 'NO OBSERVA', '0', 'NORMAL']):
            return _append_comment_if_extra('NEGATIVO', s)
        if any(w in s_upper for w in ['POSITIVO', 'TRAZAS', 'PRESENTE', '+']):
            return _append_comment_if_extra('POSITIVO', s)

    # 8. Evaluación de Órganos / Sistemas (Clínico, RX, Musculoesquelético, Dermatológico)
    # Ej: Cabeza, Cuello, Tórax, Abdomen, Piel, Columna, etc.
    if any(key_lower.startswith(p) for p in ['cli_', 'rx_', 'mus_', 'der_', 'alt_']):
        if any(w in s_upper for w in ['NORMAL', 'CONSERVAD', 'SIN ALTERACI', 'S/A', 'NEGATIV', 'APARENTEMENTE NORMAL', 'ADECUAD', 'BUENO', 'VENTILAN BIEN']):
            return _append_comment_if_extra('NORMAL', s)
        # Si no dice normal y describe hallazgos o anomalías, es ALTERADO + detalle
        return _append_comment_if_extra('ALTERADO', s)

    # 9. Resultados generales de especialidades (RX_Resultado, EKG_Resultado, PSI_Resultado, etc.)
    if 'resultado' in key_lower or 'indicador' in key_lower:
        if any(w in s_upper for w in ['NORMAL', 'DENTRO DE LIMITES', 'DENTRO DE RANGO', 'NEGATIVO', 'SIN ALTERACION', 'CONSERVADO', 'ADECUADO', 'OPTIMO', 'NO PATOLOGICO']):
            return _append_comment_if_extra('NORMAL', s)
        if any(w in s_upper for w in ['ALTERADO', 'FUERA DE RANGO', 'PATOLOGICO', 'ANORMAL', 'OBSERVADO', 'POSITIVO']):
            return _append_comment_if_extra('ALTERADO', s)
        if any(w in s_upper for w in ['NO APTO']):
            return 'NO APTO'
        if any(w in s_upper for w in ['APTO CON RESTRIC', 'CON RESTRIC']):
            return 'APTO CON RESTRICCIONES'
        if any(w in s_upper for w in ['APTO']):
            return 'APTO'

    return s

def clean_extracted_data(data):
    """Post-procesa fechas, aptitudes, opciones estandarizadas y valores numéricos limpios."""
    for key, val in list(data.items()):
        if not val:
            continue
        key_lower = key.lower()
        if 'fecha' in key_lower and isinstance(val, str):
            data[key] = normalize_date_format(val)
        else:
            val_clean = clean_numeric_value(val)
            val_std = normalize_standard_values(key, val_clean)
            data[key] = val_std
    return data

def build_dynamic_prompt():
    """Construye el prompt que incluye la lista de campos para Gemini."""
    fields_list = ", ".join(ALL_FIELDS)
    return (
        "Eres un auditor médico experto en Salud Ocupacional.\n"
        "Analiza el documento PDF y extrae la información correspondiente a los siguientes campos:\n"
        f"{fields_list}\n"
        "REGLAS OBLIGATORIAS DE ESTANDARIZACIÓN:\n"
        "1. VALORES TIPO OPCIÓN CON COMENTARIO ADICIONAL:\n"
        "   Para los campos de tipo opción (evaluaciones de órganos, sistemas, radiografías, EKG, orina, toxicología, pruebas realizadas, etc.), SI EL EXAMEN MÉDICO REPORTA UN DETALLE O COMENTARIO ADICIONAL ESPECÍFICO, COLOCA: [OPCION] - [COMENTARIO ADICIONAL]. Si no hay detalle adicional o todo es simple, coloca solo la opción.\n"
        "   Ejemplos:\n"
        "   - Si CLI_Torax dice 'Simétrico con dolor a la palpación' -> 'ALTERADO - Dolor a la palpación'\n"
        "   - Si CLI_Torax dice 'Sin alteraciones' -> 'NORMAL'\n"
        "   - Si RX_Campos_pulmonares dice 'Infiltrado basal derecho' -> 'ALTERADO - Infiltrado basal derecho'\n"
        "   - Si EKG_Ritmo_cardiaco dice 'Sinusal con extrasístoles ventriculares aisladas' -> 'SINUSAL - Extrasístoles ventriculares aisladas'\n"
        "   - Si RX_Radiografia_realizada dice 'Sí, validada con firma digital' -> 'SI - Con firma digital'\n"
        "   - Si ORI_Aspecto dice 'Ligeramente turbio por filamentos de moco' -> 'LIGERAMENTE TURBIO - Presencia de filamentos de moco'\n"
        "   - Las opciones base son: 'NORMAL'/'ALTERADO', 'SI'/'NO', 'NO REACTIVO'/'REACTIVO', 'LIMPIDO'/'TURBIO', 'NEGATIVO'/'POSITIVO', 'SINUSAL'/'ARRITMIA'.\n"
        "2. RESULTADOS DE APTITUD MÉDICA (EXCEPCIÓN ESTRICTA: SOLO LA OPCIÓN PURA, SIN COMENTARIOS):\n"
        "   - Para Resultado_Aptitud_Final y campos de aptitud, DEBE ser ESTRICTAMENTE uno de estos tres valores puros (sin agregarle comentarios):\n"
        "     * 'APTO'\n"
        "     * 'NO APTO'\n"
        "     * 'APTO CON RESTRICCIONES'\n"
        "3. NOMBRES DE PROFESIONALES EN CAMPOS DE FIRMA O VALIDACIÓN:\n"
        "   Para los campos que indican 'Firma_o_validacion' (como RX_Firma_o_validacion_radiologica, EKG_Firma_o_validacion_del_EKG, PSI_Firma_o_validacion_psicologica, AUD_Firma_o_validacion_audiometrica, ODO_Firma_o_validacion_odontologica, ESP_Firma_o_validacion_de_espirometria, OFT_Firma_o_validacion_oftalmologica):\n"
        "   EXTRAE EL NOMBRE COMPLETO DEL PROFESIONAL MÉDICO / EVALUADOR QUE FIRMA O SELLA EL EXAMEN (incluyendo su colegiatura o CMP si está visible, ej: 'Dr. Carlos Mendoza Rojas - CMP 45210' o 'Lic. Patricia Vega Soto'). Si no aparece ningún profesional, deja el campo vacío o coloca 'No indica'. NO coloques 'SI' ni 'NO'.\n"
        "4. VALORES NUMÉRICOS: Para valores cuantitativos de laboratorio, signos vitales y mediciones (Hemoglobina, Glucosa, Presión, etc.), extrae ÚNICAMENTE EL NÚMERO, sin unidades de medida (ej. '14.5', '120/80', '85').\n"
        "5. FECHAS: Formato exacto mm/dd/yyyy (ej. 01/25/2020).\n"
        "6. TEXTO LIBRE (NO UNIFORMIZADO): Únicamente los campos de Recomendaciones (Recomendacion_General, RX_Recomendacion_radiologica, etc.), Restricciones, Observaciones, Conclusiones diagnósticas detalladas, Nombres de pacientes y Firmas de profesionales se redactan de forma libre según lo que indique el informe médico.\n"
        "Devuelve un objeto JSON donde cada clave sea el nombre exacto del campo. Si un campo no está presente, omítelo.\n"
        "No añadas información adicional fuera de los campos solicitados."
    )

EXTRACTION_PROMPT = build_dynamic_prompt()

import time

# Modelos disponibles y operativos en la cuenta de API
CANDIDATE_MODELS = [
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
    'gemini-flash-latest'
]

def extract_with_gemini(pdf_path, filename):
    client = get_gemini_client()
    if not client:
        raise ValueError('No se encontro la clave de API de Gemini.')

    # Procesar hasta 30 páginas para cubrir todos los exámenes (Hemograma, EKG, RX, etc.)
    pdf_bytes, pages_count = select_camo_pages(pdf_path, max_pages=30)

    last_error = None

    for model_name in CANDIDATE_MODELS:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[{filename}] Intentando con modelo '{model_name}' (intento {attempt + 1}/{max_retries})...")
                response = client.models.generate_content(
                    model=model_name,
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
                data = clean_extracted_data(data)
                return data

            except Exception as e:
                err_str = str(e)
                last_error = e
                # Verificar si es error de sobrecarga (503), saturación o rate limit (429)
                is_transient = any(k in err_str.lower() for k in ['503', 'unavailable', 'high demand', 'overloaded', '429', 'resource_exhausted'])
                
                if is_transient and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2 + 1  # 3s, 5s...
                    print(f"[{filename}] Servidor ocupado ({e}). Esperando {wait_time}s antes de reintentar...")
                    time.sleep(wait_time)
                else:
                    print(f"[{filename}] Falló con modelo '{model_name}': {e}")
                    break  # Cambiar al siguiente modelo de la lista

    # Si todos los modelos y reintentos fallaron, propagar el último error
    raise last_error

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
