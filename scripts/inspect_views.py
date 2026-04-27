"""Uso:
    python scripts/inspect_views.py > inspecao.txt

Roda consultas em information_schema + SELECT * LIMIT 3 para cada view real.
Cole o conteúdo gerado de volta no chat para destravar a reescrita dos SQLs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.db import get_engine

VIEWS: list[tuple[str, str]] = [
    ("bi", "vw_dashboard_comercial_executivas_rw"),
    ("bi", "vw_compatibilidade_sdr_closer"),
    ("bi", "vw_tipos_venda_time"),
    ("bi", "vw_investimento_diario"),
    ("bi", "trat_negocios_rw"),
]

COLS_SQL = """
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = :schema AND table_name = :table
ORDER BY ordinal_position
"""


def main() -> None:
    eng = get_engine()
    with eng.connect() as conn:
        for schema, table in VIEWS:
            full = f"{schema}.{table}"
            print("=" * 80)
            print(f"VIEW: {full}")
            print("=" * 80)

            cols = conn.execute(
                text(COLS_SQL), {"schema": schema, "table": table}
            ).fetchall()
            if not cols:
                print("(nenhuma coluna retornada — verifique nome/schema ou permissão)\n")
                continue

            print("\n-- Colunas --")
            for c in cols:
                nul = "NULL" if c.is_nullable == "YES" else "NOT NULL"
                print(f"  {c.column_name:40s} {c.data_type:24s} {nul}")

            print("\n-- Amostra (3 linhas) --")
            try:
                sample = (
                    conn.execute(text(f"SELECT * FROM {full} LIMIT 3"))
                    .mappings()
                    .all()
                )
                for i, row in enumerate(sample, 1):
                    print(f"  [{i}]")
                    for k, v in row.items():
                        s = str(v)
                        if len(s) > 80:
                            s = s[:77] + "..."
                        print(f"    {k}: {s}")
            except Exception as e:
                print(f"  ERRO ao ler amostra: {e}")
            print()


if __name__ == "__main__":
    main()
