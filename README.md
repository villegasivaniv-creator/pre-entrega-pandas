# Pre-entrega: Adquisición y Normalización de Datos con Pandas

Este repositorio implementa un pipeline completo de **adquisición, limpieza, integración (`merge`) y normalización de datos** utilizando `pandas`. Simula un escenario real donde las transacciones comerciales provienen del departamento de ventas en formato **CSV** (`data/transacciones.csv`) y el catálogo maestro de productos proviene del área de inventario en formato **Excel** (`data/productos.xlsx`).

## Estructura del Repositorio

```text
pre-entrega-pandas/
├── data/
│   ├── transacciones.csv             # 200 transacciones (id_transaccion, id_producto, cantidad, fecha, canal_venta)
│   └── productos.xlsx                # Maestro de productos (id_producto, nombre_producto, categoria, precio_unitario)
├── output/
│   └── ventas_consolidadas.parquet   # Dataset final limpio, tipado y validado en formato Parquet
├── src/
│   ├── generar_datos_ejemplo.py      # Script reproducible (semilla 42) que genera los archivos fuente con casos de prueba
│   └── pipeline.py                   # Pipeline principal de adquisición, limpieza, merge, normalización y exportación
├── notebook_analisis.ipynb           # Jupyter Notebook interactivo con el flujo paso a paso
├── requirements.txt                  # Dependencias con versiones mínimas requeridas
├── .gitignore                        # Archivos excluidos del control de versiones
└── README.md                         # Documentación técnica y guía de reproducibilidad
```

## Requisitos y Librerías Necesarias

El proyecto requiere **Python 3.9+** y las siguientes librerías (especificadas en `requirements.txt`):

| Librería | Versión Mínima | Propósito en el Proyecto |
| :--- | :--- | :--- |
| `pandas` | `>=2.0.0` | Carga, limpieza de tipos y nulos, cruce relacional (`merge`) y normalización. |
| `openpyxl` | `>=3.1.0` | Motor de lectura/escritura para archivos Microsoft Excel (`.xlsx`). |
| `pyarrow` | `>=14.0.0` | Motor columnar para exportar y validar el dataset final en formato `.parquet`. |
| `numpy` | `>=1.24.0` | Generación reproducible de los datos fuente de prueba (`generar_datos_ejemplo.py`). |

## Pasos para Reproducir la Carga y el Procesamiento

```bash
# 1. Clonar el repositorio y entrar al directorio
git clone https://github.com/<tu-usuario>/<tu-repositorio>.git
cd <tu-repositorio>

# 2. Crear y activar un entorno virtual (recomendado)
python -m venv .venv
source .venv/bin/activate        # En Linux / macOS
# .venv\Scripts\activate         # En Windows (CMD / PowerShell)

# 3. Instalar las dependencias
pip install -r requirements.txt

# 4. (Opcional) Regenerar los archivos fuente de ejemplo en data/
python src/generar_datos_ejemplo.py

# 5. Ejecutar el pipeline principal de adquisición y normalización
python src/pipeline.py
```

Al finalizar la ejecución, el archivo resultante se guarda automáticamente en `output/ventas_consolidadas.parquet` y se muestra por consola la auditoría de limpieza, el esquema de tipos (`dtypes`) y las primeras filas del dataset.

## Decisiones Técnicas y Etapas del Pipeline (`src/pipeline.py`)

1. **Adquisición Segura desde Múltiples Fuentes (`adquirir_datos`):**
   * Carga `data/transacciones.csv` con `pd.read_csv(..., encoding="utf-8")`.
   * Carga `data/productos.xlsx` empleando un administrador de contexto explícito (`with pd.ExcelFile(ruta_xlsx, engine="openpyxl") as xls:`) para garantizar que el motor `openpyxl` cierre el archivo inmediatamente después de la lectura.
2. **Corrección de Tipos de Datos (`limpiar_transacciones` y `limpiar_productos`):**
   * Convierte `fecha` explícitamente a `datetime64[ns]` (`pd.to_datetime(..., format="%Y-%m-%d", errors="coerce")`).
   * Limpia espacios en blanco en `id_producto` (ej. `" 101 "`, `"108.0"`, `"0107"`) y estandariza la llave `id_producto` como `int64` en **ambos** DataFrames antes de unirlos, evitando fallos de cruce por incompatibilidad de tipos (`string` vs `int`).
   * Deduplica el catálogo de productos por `id_producto` (`drop_duplicates(subset=["id_producto"])`) para asegurar integridad referencial en el maestro.
3. **Manejo Contextual de Valores Nulos (Eliminación vs. Imputación):**
   * **Eliminación en campos críticos (`id_producto`, `cantidad`, `fecha`):** Se eliminan las 6 filas que presentan valores nulos en cualquiera de estos tres campos (`dropna(subset=["id_producto", "cantidad", "fecha"])`), dado que una venta sin producto, sin unidades o sin fecha no puede atribuirse ni facturarse sin distorsionar las métricas.
   * **Imputación en campos descriptivos secundarios (`canal_venta`):** Los 3 registros con `canal_venta` nulo pero con producto, cantidad y fecha válidos se conservan e imputan con `"No especificado"` (`fillna("No especificado")`).
4. **Integración Relacional (`integrar_y_normalizar`):**
   * Verifica mediante `assert` que el tipo de `id_producto` coincida en ambos datasets.
   * Ejecuta `pd.merge(transacciones, productos, on="id_producto", how="inner", validate="m:1")`. La validación `m:1` (muchos-a-uno) garantiza que cada `id_producto` sea único en el catálogo, y el `inner join` descarta la transacción huérfana cuyo producto (`999`) no existe en el maestro (pasando de 194 transacciones limpias a 193 integradas).
5. **Normalización y Columna Calculada:**
   * Calcula la columna `total_venta = (cantidad * precio_unitario).round(2)`.
   * Ordena los registros cronológicamente por `fecha` e `id_transaccion`.
6. **Validación de Calidad y Exportación a Parquet (`validar_dataset_final` y `exportar_parquet`):**
   * Comprueba con aserciones (`assert`) que no existan valores nulos en ningún campo crítico, que `fecha` sea `datetime64[ns]` y que `total_venta > 0`.
   * Exporta el resultado a `output/ventas_consolidadas.parquet` con compresión `snappy` usando `pyarrow` y verifica su lectura inmediata.

## Esquema del Dataset Final (`output/ventas_consolidadas.parquet`)

De las **200 transacciones originales**, tras descartar 6 filas con nulos en campos críticos y 1 fila con `id_producto = 999` inexistente en el catálogo maestro, el dataset consolidado cuenta con **193 registros limpios y 0 valores nulos**:

| Columna | Tipo de Dato (`dtype`) | Origen / Regla de Negocio |
| :--- | :--- | :--- |
| `id_transaccion` | `int64` | Identificador único de la transacción (`transacciones.csv`). |
| `fecha` | `datetime64[ns]` | Fecha de la operación convertida a objeto `datetime` (`transacciones.csv`). |
| `id_producto` | `int64` | Llave primaria/foránea homogeneizada para el `merge` (`CSV` + `Excel`). |
| `nombre_producto` | `string` | Descripción del producto obtenida del maestro (`productos.xlsx`). |
| `categoria` | `string` | Categoría del producto obtenida del maestro (`productos.xlsx`). |
| `canal_venta` | `string` | Canal comercial con nulos imputados como `"No especificado"` (`transacciones.csv`). |
| `cantidad` | `int64` | Unidades vendidas validadas (`> 0`, sin nulos) (`transacciones.csv`). |
| `precio_unitario` | `float64` | Precio unitario de lista obtenido del maestro (`productos.xlsx`). |
| `total_venta` | `float64` | **Columna calculada:** `cantidad * precio_unitario`. |
