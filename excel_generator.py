import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Dynamically generate columns from fields.json
from pathlib import Path
import json

# Path to fields.json located in the project root
FIELDS_PATH = Path(__file__).parent / 'fields.json'
if FIELDS_PATH.exists():
    with FIELDS_PATH.open(encoding='utf-8') as f:
        FIELD_NAMES = json.load(f)
else:
    FIELD_NAMES = []

import re

def _normalize_date(val):
    if not val:
        return val
    s = str(val).strip()
    m1 = re.search(r'\b(19\d\d|20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b', s)
    if m1:
        return f'{int(m1.group(2)):02d}/{int(m1.group(3)):02d}/{m1.group(1)}'
    m2 = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](19\d\d|20\d\d)\b', s)
    if m2:
        return f'{int(m2.group(2)):02d}/{int(m2.group(1)):02d}/{m2.group(3)}'
    return s

def _normalize_aptitud(val):
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

def _clean_numeric_value(val):
    if val is None:
        return val
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    if not s:
        return s
    # Ignorar fechas
    if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', s) or re.search(r'\b\d{4}-\d{2}-\d{2}\b', s):
        return s
    if not re.search(r'\d', s):
        return s
    m = re.match(r'^\s*([><=~±]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*(?:[a-zA-Z%µ/°].*)?$', s)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(r'(?i)\s*(g/dl|mg/dl|mmol/l|ui/l|u/l|u/ml|mmhg|cm|kg|m2|m|l|ml|%|porcentaje|x10\^?\d*|cel/campo|p/c|leuc/campo|fl|pg|g/l|seg|segundos|bpm|lpm|rpm)\b.*', '', s).strip()
    return cleaned if cleaned else s

def _make_columns():
    cols = []
    # Always include the PDF filename column
    cols.append(('archivo', 'Archivo PDF', 26))
    for field in FIELD_NAMES:
        cols.append((field, field, 22))
    return cols

COLUMNS = _make_columns()

def generate_excel(records):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Exámenes Médicos'
    ws.views.sheetView[0].showGridLines = True

    # Estilos de Encabezado
    header_font = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1F4E78', end_color='1F4E78', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    data_font = Font(name='Segoe UI', size=10)
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    wrap_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # Colores para Aptitud Médica
    fill_apto = PatternFill(start_color='D1E7DD', end_color='D1E7DD', fill_type='solid')
    font_apto = Font(name='Segoe UI', size=10, bold=True, color='0F5132')

    fill_restriccion = PatternFill(start_color='FFF3CD', end_color='FFF3CD', fill_type='solid')
    font_restriccion = Font(name='Segoe UI', size=10, bold=True, color='664D03')

    fill_no_apto = PatternFill(start_color='F8D7DA', end_color='F8D7DA', fill_type='solid')
    font_no_apto = Font(name='Segoe UI', size=10, bold=True, color='842029')

    fill_observado = PatternFill(start_color='E2D9F3', end_color='E2D9F3', fill_type='solid')
    font_observado = Font(name='Segoe UI', size=10, bold=True, color='432874')

    fill_alt_row = PatternFill(start_color='F9FAFB', end_color='F9FAFB', fill_type='solid')

    # Fila de Encabezados
    ws.row_dimensions[1].height = 32
    for col_idx, (field_id, header_text, col_width) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width

    # Filas de Datos
    for row_idx, rec in enumerate(records, 2):
        ws.row_dimensions[row_idx].height = 28
        is_alt = (row_idx % 2 == 1)

        for col_idx, (field_id, _, _) in enumerate(COLUMNS, 1):
            val = rec.get(field_id, '')
            if isinstance(val, list):
                val = '; '.join(str(x) for x in val)
            elif val is None:
                val = ''
            
            if 'fecha' in field_id.lower() and val:
                val = _normalize_date(val)
            elif 'aptitud' in field_id.lower():
                val = _normalize_aptitud(val)
            else:
                val = _clean_numeric_value(val)
            
            cell = ws.cell(row=row_idx, column=col_idx, value=str(val))
            cell.font = data_font
            cell.border = thin_border

            if 'fecha' in field_id.lower() or field_id in ['dni', 'edad', 'sexo', 'tipo_examen', 'fecha_examen', 'fecha_vencimiento', 'Fecha_Examen', 'Fecha_Vencimiento', 'DNI']:
                cell.alignment = center_align
            elif field_id in ['restricciones', 'diagnosticos', 'recomendaciones', 'Recomendacion_General', 'Restricciones_General']:
                cell.alignment = wrap_align
            else:
                cell.alignment = left_align

            if is_alt:
                cell.fill = fill_alt_row

            # Formato condicional para Aptitud
            if field_id in ['aptitud', 'Resultado_Aptitud_Final']:
                apt_upper = str(val).upper()
                cell.alignment = center_align
                if 'RESTRICCION' in apt_upper or 'OBSERVACIONES' in apt_upper:
                    cell.fill = fill_restriccion
                    cell.font = font_restriccion
                elif 'NO APTO' in apt_upper:
                    cell.fill = fill_no_apto
                    cell.font = font_no_apto
                elif 'OBSERVADO' in apt_upper or 'PENDIENTE' in apt_upper:
                    cell.fill = fill_observado
                    cell.font = font_observado
                elif 'APTO' in apt_upper:
                    cell.fill = fill_apto
                    cell.font = font_apto

    # Auto-filtro
    num_rows = max(len(records) + 1, 1)
    ws.auto_filter.ref = f'A1:{get_column_letter(len(COLUMNS))}{num_rows}'

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer