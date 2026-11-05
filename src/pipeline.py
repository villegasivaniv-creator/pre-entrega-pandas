"""Pre-entrega: Adquisición y Normalización de Datos con Pandas.

Pipeline modular que integra datos de ventas desde múltiples fuentes (CSV de transacciones
y Excel con el catálogo maestro de productos), corrige tipos de datos, gestiona valores
nulos (eliminación en campos críticos e imputación en secundarios), realiza el merge
validado muchos-a-uno, calcula 'total_venta' y exporta el dataset limpio a formato Parquet.
"""

from pathlib import Path
import logging
import pandas as pd

# Configuración de logging estructurado para trazabilidad en consola
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_CSV = BASE_DIR / "data" / "transacciones.csv"
RUTA_XLSX = BASE_DIR / "data" / "productos.xlsx"
RUTA_SALIDA = BASE_DIR / "output" / "ventas_consolidadas.parquet"


def adquirir_datos(
    ruta_csv: Path = RUTA_CSV, ruta_xlsx: Path = RUTA_XLSX
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee el CSV de transacciones y el Excel del maestro de productos cerrando el motor openpyxl."""
    if not ruta_csv.exists():
        raise FileNotFoundError(f"No se encontró el archivo CSV de transacciones: {ruta_csv}")
    if not ruta_xlsx.exists():
        raise FileNotFoundError(f"No se encontró el archivo Excel de productos: {ruta_xlsx}")

    logger.info("Iniciando adquisición de datos desde CSV y Excel...")
    df_transacciones = pd.read_csv(ruta_csv, encoding="utf-8")

    # Uso explícito de context manager pd.ExcelFile para garantizar el cierre del motor openpyxl
    with pd.ExcelFile(ruta_xlsx, engine="openpyxl") as xls:
        df_productos = pd.read_excel(xls, sheet_name="productos")

    logger.info(
        "Datos cargados -> Transacciones: %s filas | Catálogo Excel: %s filas",
        len(df_transacciones),
        len(df_productos),
    )
    return df_transacciones, df_productos


def limpiar_transacciones(df: pd.DataFrame) -> pd.DataFrame:
    """Verifica y corrige tipos de datos y gestiona valores nulos según el contexto."""
    tx = df.copy()
    filas_iniciales = len(tx)

    # 1. Limpieza previa de strings y conversión de tipos con errors="coerce"
    if "id_producto" in tx.columns:
        tx["id_producto"] = (
            tx["id_producto"].astype(str).str.strip().replace({"nan": None, "None": None, "": None})
        )
    tx["id_producto"] = pd.to_numeric(tx["id_producto"], errors="coerce")
    tx["cantidad"] = pd.to_numeric(tx["cantidad"], errors="coerce")
    tx["fecha"] = pd.to_datetime(tx["fecha"], format="%Y-%m-%d", errors="coerce")

    # 2. Reporte de nulos antes de limpiar
    campos_criticos = ["id_producto", "cantidad", "fecha"]
    nulos_criticos = tx[campos_criticos].isna().sum().to_dict()
    logger.info("Valores nulos detectados en campos críticos de transacciones: %s", nulos_criticos)

    # 3. Manejo de valores nulos según el contexto:
    # - Campos críticos (id_producto, cantidad, fecha): no deben inventarse ni imputarse
    #   porque distorsionarían la facturación y la serie temporal -> se eliminan.
    tx = tx.dropna(subset=campos_criticos).copy()

    # - Validación de reglas de negocio: solo cantidades estrictamente positivas (> 0)
    tx = tx[tx["cantidad"] > 0].copy()

    # - Campo descriptivo secundario (canal_venta): si es nulo, se imputa con categoría por defecto
    if "canal_venta" in tx.columns:
        nulos_canal = int(tx["canal_venta"].isna().sum())
        if nulos_canal > 0:
            tx["canal_venta"] = tx["canal_venta"].fillna("No especificado").astype("string")
            logger.info(
                "Imputados %d valores nulos en 'canal_venta' con 'No especificado'.", nulos_canal
            )

    # 4. Estandarización de tipos enteros para la llave de cruce y cantidades
    tx["id_transaccion"] = pd.to_numeric(tx["id_transaccion"], errors="coerce").astype("int64")
    tx["id_producto"] = tx["id_producto"].astype("int64")
    tx["cantidad"] = tx["cantidad"].astype("int64")

    # Eliminación de transacciones duplicadas por id_transaccion si las hubiera
    tx = tx.drop_duplicates(subset=["id_transaccion"], keep="first")

    logger.info(
        "Transacciones tras limpieza: %d válidas (%d descartadas por nulos/invalidez).",
        len(tx),
        filas_iniciales - len(tx),
    )
    return tx


def limpiar_productos(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos de datos del catálogo maestro y elimina duplicados por id_producto."""
    cat = df.copy()
    filas_iniciales = len(cat)

    cat["id_producto"] = pd.to_numeric(cat["id_producto"], errors="coerce")
    cat["precio_unitario"] = pd.to_numeric(cat["precio_unitario"], errors="coerce")

    # Eliminación de filas sin llave o sin precio válido
    cat = cat.dropna(subset=["id_producto", "nombre_producto", "precio_unitario"]).copy()
    cat = cat[cat["precio_unitario"] > 0].copy()

    # Homogeneización del tipo de la llave a int64 (idéntico a transacciones)
    cat["id_producto"] = cat["id_producto"].astype("int64")
    cat["nombre_producto"] = cat["nombre_producto"].astype(str).str.strip().astype("string")
    if "categoria" in cat.columns:
        cat["categoria"] = cat["categoria"].fillna("General").astype(str).str.strip().astype("string")
    cat["precio_unitario"] = cat["precio_unitario"].round(2).astype("float64")

    # Deduplicación del maestro para garantizar relación muchos-a-uno (m:1) en el merge
    cat = cat.drop_duplicates(subset=["id_producto"], keep="first").reset_index(drop=True)
    logger.info(
        "Catálogo de productos normalizado: %d productos únicos (%d duplicados eliminados).",
        len(cat),
        filas_iniciales - len(cat),
    )
    return cat


def integrar_y_normalizar(
    transacciones: pd.DataFrame, productos: pd.DataFrame
) -> pd.DataFrame:
    """Realiza el merge por id_producto y calcula la columna normalizada 'total_venta'."""
    # Verificación explícita de que las llaves tienen exactamente el mismo tipo antes del merge
    assert transacciones["id_producto"].dtype == productos["id_producto"].dtype, (
        f"Tipos incompatibles en llave id_producto: "
        f"{transacciones['id_producto'].dtype} vs {productos['id_producto'].dtype}"
    )

    # Inner merge validado muchos-a-uno (m:1): descarta transacciones con productos inexistentes
    ventas = pd.merge(
        transacciones,
        productos,
        on="id_producto",
        how="inner",
        validate="m:1",
    )

    huerfanas = len(transacciones) - len(ventas)
    logger.info(
        "Merge completado (inner, m:1): %d filas integradas (%d descartadas por producto inexistente en maestro).",
        len(ventas),
        huerfanas,
    )

    # Columna calculada requerida: total_venta = cantidad * precio_unitario
    ventas["total_venta"] = (ventas["cantidad"] * ventas["precio_unitario"]).round(2)

    # Ordenamiento cronológico y por identificador de transacción
    ventas = ventas.sort_values(by=["fecha", "id_transaccion"]).reset_index(drop=True)

    # Orden de columnas limpio y consistente
    columnas_orden = [
        "id_transaccion",
        "fecha",
        "id_producto",
        "nombre_producto",
        "categoria",
        "canal_venta",
        "cantidad",
        "precio_unitario",
        "total_venta",
    ]
    columnas_finales = [c for c in columnas_orden if c in ventas.columns]
    return ventas[columnas_finales]


def validar_dataset_final(df: pd.DataFrame) -> None:
    """Ejecuta aserciones de calidad de datos sobre el dataset consolidado antes de exportar."""
    campos_criticos = [
        "id_transaccion",
        "fecha",
        "id_producto",
        "nombre_producto",
        "cantidad",
        "precio_unitario",
        "total_venta",
    ]
    nulos_restantes = int(df[campos_criticos].isna().sum().sum())
    assert nulos_restantes == 0, f"Error: existen {nulos_restantes} valores nulos en campos críticos."
    assert pd.api.types.is_datetime64_any_dtype(df["fecha"]), "Error: 'fecha' no es de tipo datetime64."
    assert (df["total_venta"] > 0).all(), "Error: existen valores no positivos en 'total_venta'."
    logger.info("Validación de calidad superada: 0 nulos en campos críticos y tipos verificados.")


def exportar_parquet(df: pd.DataFrame, ruta_salida: Path = RUTA_SALIDA) -> None:
    """Exporta el dataset final en formato Parquet usando pyarrow y verifica su lectura."""
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ruta_salida, index=False, engine="pyarrow", compression="snappy")

    # Verificación de lectura del archivo Parquet generado
    df_leido = pd.read_parquet(ruta_salida, engine="pyarrow")
    assert len(df_leido) == len(df), "Error al verificar el archivo Parquet exportado."
    logger.info(
        "Archivo Parquet exportado y verificado en: %s (%d filas, %d columnas).",
        ruta_salida,
        len(df_leido),
        len(df_leido.columns),
    )


def main() -> pd.DataFrame:
    transacciones_raw, productos_raw = adquirir_datos()
    transacciones_limpias = limpiar_transacciones(transacciones_raw)
    productos_limpios = limpiar_productos(productos_raw)
    ventas_consolidadas = integrar_y_normalizar(transacciones_limpias, productos_limpios)
    validar_dataset_final(ventas_consolidadas)
    exportar_parquet(ventas_consolidadas)

    print("\n" + "=" * 75)
    print("RESUMEN DEL DATASET FINAL CONSOLIDADO (ventas_consolidadas.parquet)")
    print("=" * 75)
    print(f"Dimensiones: {ventas_consolidadas.shape[0]} filas x {ventas_consolidadas.shape[1]} columnas")
    print(f"Facturación Total Acumulada: ${ventas_consolidadas['total_venta'].sum():,.2f}")
    print("\nTipos de datos (dtypes) y conteo de no-nulos:")
    resumen_tipos = pd.DataFrame(
        {
            "Tipo (dtype)": ventas_consolidadas.dtypes.astype(str),
            "No Nulos": ventas_consolidadas.notna().sum(),
            "Nulos": ventas_consolidadas.isna().sum(),
        }
    )
    print(resumen_tipos.to_string())
    print("\nPrimeras 10 filas del dataset consolidado:")
    print(ventas_consolidadas.head(10).to_string(index=False))
    print("=" * 75)
    return ventas_consolidadas


if __name__ == "__main__":
    main()
