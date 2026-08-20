# ❖ DEIS Cognos Scraper - Chile

Automatizador interactivo de descargas de reportes oficiales de **Atenciones de Urgencia** desde el portal IBM Cognos de DEIS (Ministerio de Salud de Chile). 


---

## ► Requisitos e Instalación

Tener instalado **Python 3.10+** . 

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Instalar el motor de navegación:**
   ```bash
   playwright install chromium
   ```

---

## ◆ Cómo usarlo

Ejecutar el script principal en terminal.

```bash
python scraper.py
```

### El asistente preguntará:
1. **Servicio de Salud:** (Ej: Metropolitano Suroriente, u opción de descargar todo Chile).
2. **Año Estadístico:** (Ej: 2016, un rango como 2020-2023, o Todos los años).
3. **Tipo de Establecimiento:** (Todos los tipos, o filtrar por Hospital, SAPU, SAR, etc.).
4. **Establecimientos:** Elegir de la lista dinámica detectada en tiempo real o descargarlos todos automáticamente, uno por uno.

---

## ■ Estructura del Proyecto

```text
cognos/
├── descargas/           # Carpeta donde se organizan automáticamente los archivos .xlsx
│   ├── 2015/
│   ├── 2016/
│   └── log.txt          # Registro histórico de descargas exitosas y errores
├── requirements.txt     # Dependencias del proyecto (Playwright, Rich)
├── scraper.py           # Script principal interactivo
└── README.md            # Documentación
```

---

## ◈ Características Destacadas

- **Interfaz Interactiva (UI):** Uso de la librería `rich` para menús amigables, tablas de resumen y barras de progreso en tiempo real.
- **Listas Dinámicas (Live Fetch):** El script se conecta al servidor para leer la lista *real* de establecimientos dependiendo del Servicio de Salud que elijas, en vez de usar listas desactualizadas.
- **Auto-recuperación (Resume):** Si cancelas la descarga a la mitad y vuelves a ejecutarlo, el script reconoce los archivos ya descargados y se los salta, retomando donde quedó.
- **Caché Inteligente (Fast Mode):** Reutiliza la misma sesión de Cognos limpiando el estado dinámicamente mediante el botón Volver para evitar corrupción de datos. Descarga cada archivo de forma segura en ~45s.