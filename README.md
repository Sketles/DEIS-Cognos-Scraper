# DEIS Cognos Scraper - Chile

Automatizador interactivo y robusto de descargas de reportes oficiales de **Atenciones de Urgencia** desde el portal IBM Cognos de DEIS (Ministerio de Salud de Chile).

---

## Requisitos e Instalación

Requiere **Python 3.10+**.

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Instalar el motor de navegación de Playwright:**
   ```bash
   playwright install chromium
   ```

---

## Uso

Ejecutar el script principal en la terminal:

```bash
python scraper.py
```

### Modos y Opciones Interactivas:
1. **Selección de Servicio de Salud:** Permite seleccionar un servicio específico (ej: *Metropolitano Suroriente*) o la totalidad de servicios del país.
2. **Años Estadísticos:**
   - **Opción 1:** Todos los años consolidados en un único archivo Excel (2015-2025, matriz completa de 276 filas x 586 columnas).
   - **Opción 2:** Todos los años descargados en archivos separados por año.
   - **Opción 3 / 4:** Año específico o rango personalizado (ej: 2020-2023).
3. **Tipo de Establecimiento:** Todos los tipos o filtrado específico (Hospital, SAPU, SAR, etc.).
4. **Establecimientos:** Descarga automática 1 a 1 de todos los centros detectados dinámicamente o selección de uno específico.

---

## Estructura del Proyecto

```text
DEIS-Cognos-Scraper/
├── descargas/           # Directorio donde se organizan automáticamente los archivos .xlsx
│   ├── 2015-2025/       # Archivos consolidados multi-anuales (276 filas x 586 columnas)
│   ├── 2024/            # Archivos anuales individuales
│   └── log.txt          # Registro detallado de ejecución y descargas
├── requirements.txt     # Dependencias (playwright, rich, pandas, openpyxl)
├── scraper.py           # Script principal con arquitectura de evasión de resets Cognos
├── AGENTS.md            # Contexto de arquitectura y flujo para asistentes IA
└── README.md            # Documentación general
```

---

## Características Técnicas

- **Matriz Completa de Datos (276 x 586):** Extracción completa de causas, semanas estadísticas (1 a 53 para 2015-2025) y desgloses por tramo de edad.
- **Evasión de Resets de Estado (Dojo Bypass):** Inyección DOM directa para evitar que el framework Dojo de IBM Cognos resetee las selecciones multi-anuales.
- **Listas Dinámicas en Tiempo Real:** Detección en vivo de los establecimientos reales del servicio de salud seleccionado.
- **Gestión de Descargas y Recuperación:** Salto automático de archivos previamente descargados y reintentos ante saturación del servidor.
- **Sincronización Dinámica:** Monitoreo activo de estados de carga (`progress.gif`) para evitar tiempos muertos innecesarios.