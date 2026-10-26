import extractor

# Test 1: RX_Codigo_de_radiografia debe salir sin clasificar
r1 = extractor.normalize_standard_values('RX_Codigo_de_radiografia', 'RX-2024-001453')
print('Test 1 (codigo):', repr(r1))  # Esperado: 'RX-2024-001453'

# Test 2: RX_Campos_pulmonares sigue clasificando NORMAL/ALTERADO
r2 = extractor.normalize_standard_values('RX_Campos_pulmonares', 'Campos limpios')
print('Test 2 (campos pulmonares NORMAL):', repr(r2))  # Esperado: 'NORMAL'

r3 = extractor.normalize_standard_values('RX_Campos_pulmonares', 'Infiltrado basal derecho')
print('Test 3 (campos pulmonares ALTERADO):', repr(r3))  # Esperado: 'ALTERADO - Infiltrado basal derecho'

# Test 4: firma = texto libre
r4 = extractor.normalize_standard_values('RX_Firma_o_validacion_radiologica', 'Dr. Carlos Mendoza CMP 45210')
print('Test 4 (firma):', repr(r4))  # Esperado: nombre del profesional

# Test 5: aptitud pura
r5 = extractor.normalize_standard_values('Resultado_Aptitud_Final', 'APTO CON RESTRICCIONES - Evitar trabajos en altura')
print('Test 5 (aptitud):', repr(r5))  # Esperado: 'APTO CON RESTRICCIONES'

# Test 6: codigo con texto alrededor
r6 = extractor.normalize_standard_values('RX_Codigo_de_radiografia', 'Codigo de estudio: RAD-2025-00789 NORMAL')
print('Test 6 (codigo con texto):', repr(r6))  # Esperado: texto libre tal cual
