import extractor

# Test firma_o_validacion (should return name + CMP unchanged)
print('Firma test:', extractor.normalize_standard_values('RX_Firma_o_validacion_radiologica', 'Dr. María Pérez - CMP 67890'))

# Test codigo de radiografia (should return exact code, not NORMAL/ALTERADO)
print('Codigo test 1:', extractor.normalize_standard_values('RX_Codigo_de_radiografia', 'RX-2024-001453'))
print('Codigo test 2 (texto extra):', extractor.normalize_standard_values('RX_Codigo_de_radiografia', 'Código de estudio: RAD-2025-00789'))
