"""Generador reproducible de los archivos fuente de ejemplo (CSV y Excel).

Simula datos provenientes de dos departamentos distintos:
1. Ventas (data/transacciones.csv): 200 transacciones con casos reales de suciedad
   (fechas en distintos formatos, espacios en blanco, valores nulos en campos críticos,
   nulos en un campo secundario e ID de producto inexistente en el maestro).
2. Inventario (data/productos.xlsx): Catálogo maestro de productos con precios unitarios,
   incluyendo formato tabular en Excel y un registro duplicado para demostrar la
   normalización del maestro.
"""

from pathlib import Path
import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def generar_catalogo_excel(ruta_xlsx: Path) -> pd.DataFrame:
    """Genera el archivo Excel del maestro de productos cerrando correctamente openpyxl."""
    productos = pd.DataFrame(
        {
            "id_producto": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 105],
            "nombre_producto": [
                "Teclado mecánico",
                "Mouse inalámbrico",
                'Monitor 24"',
                "Auriculares",
                "Webcam HD",
                'Notebook 15"',
                "Disco SSD 1TB",
                "Memoria RAM 16GB",
                "Cable HDMI",
                "Parlantes 2.1",
                "Webcam HD",  # Registro duplicado a limpiar en el pipeline
            ],
            "categoria": [
                "Periféricos",
                "Periféricos",
                "Pantallas",
                "Audio",
                "Periféricos",
                "Equipos",
                "Almacenamiento",
                "Componentes",
                "Accesorios",
                "Audio",
                "Periféricos",
            ],
            "precio_unitario": [
                45000.0,
                18000.0,
                220000.0,
                32000.0,
                28000.0,
                780000.0,
                65000.0,
                42000.0,
                6500.0,
                38000.0,
                28000.0,
            ],
        }
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "productos"
    ws.views.sheetView[0].showGridLines = True

    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    alt_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    headers = list(productos.columns)
    for col_idx, h_text in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col_idx, value=h_text)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(
            horizontal="right" if col_idx in (1, 4) else "left", vertical="center"
        )
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    for row_idx, row in enumerate(productos.itertuples(index=False), start=2):
        for col_idx, val in enumerate(row, start=1):
            c = ws.cell(row=row_idx, column=col_idx, value=val)
            c.border = thin_border
            if row_idx % 2 == 0:
                c.fill = alt_fill
            if col_idx == 1:
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "#,##0"
            elif col_idx in (2, 3):
                c.alignment = Alignment(horizontal="left", vertical="center")
            else:
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "$#,##0.00"

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 5, 14), 40)

    wb.save(str(ruta_xlsx))
    wb.close()
    return productos.drop_duplicates(subset="id_producto")


def generar_transacciones_csv(ruta_csv: Path, ids_validos: pd.Series) -> None:
    """Genera 200 transacciones con casos controlados de suciedad para validar el pipeline."""
    rng = np.random.default_rng(42)
    n = 200
    fechas = pd.date_range("2025-01-01", "2025-12-31", freq="D")

    trans = pd.DataFrame(
        {
            "id_transaccion": range(1, n + 1),
            "id_producto": rng.choice(ids_validos, n).astype(str),
            "cantidad": rng.integers(1, 6, n).astype(float),
            "fecha": pd.Series(rng.choice(fechas, n)).dt.strftime("%Y-%m-%d"),
            "canal_venta": rng.choice(["Online", "Tienda Física", "Corporativo"], n),
        }
    )

    # Inyección controlada de anomalías para demostrar limpieza y normalización:
    trans.loc[[5, 17, 42], "cantidad"] = np.nan          # Nulos en campo crítico (cantidad) -> eliminar
    trans.loc[[9, 63], "fecha"] = np.nan                 # Nulos en campo crítico (fecha) -> eliminar
    trans.loc[[30], "id_producto"] = np.nan              # Nulo en campo crítico (id_producto) -> eliminar
    trans.loc[[70], "id_producto"] = "999"               # Producto inexistente en el maestro -> descartado en inner merge
    trans.loc[[12, 25, 88], "canal_venta"] = np.nan      # Nulos en campo secundario no crítico -> imputar "No especificado"
    trans.loc[[0, 1, 2], "id_producto"] = [" 101 ", "108.0", "0107"]  # IDs como string con espacios/formato distinto

    trans.to_csv(ruta_csv, index=False, encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ruta_xlsx = DATA_DIR / "productos.xlsx"
    ruta_csv = DATA_DIR / "transacciones.csv"

    productos_unicos = generar_catalogo_excel(ruta_xlsx)
    generar_transacciones_csv(ruta_csv, productos_unicos["id_producto"])
    print(f"Archivos fuente generados exitosamente en: {DATA_DIR}")


if __name__ == "__main__":
    main()
