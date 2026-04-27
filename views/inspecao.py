import streamlit as st

from src.db import run_sql
from src.repositories import VIEW_REGISTRY
from src.transforms import describe_df
from src.ui.page import start_page

start_page(
    title="Inspeção de Views",
    subtitle="Consulta raw das views reais de bi.*",
    filters=(),
    include_period=False,
)

choice = st.selectbox("View", list(VIEW_REGISTRY.keys()))
full_name = VIEW_REGISTRY[choice]
st.code(full_name, language="sql")

limit = st.slider("Linhas da amostra", 100, 5000, 500, step=100)

try:
    df = run_sql(f"SELECT * FROM {full_name} LIMIT :lim", {"lim": limit})
except Exception as e:
    st.error(f"Falha ao consultar: {e}")
    st.stop()

info = describe_df(df)
c1, c2, c3 = st.columns(3)
c1.metric("Linhas na amostra", f"{info['rows']:,}".replace(",", "."))
c2.metric("Colunas", info["cols"])
c3.metric("Colunas de data", len(info["date_columns"]))

st.subheader("Tipos de coluna")
dtypes = df.dtypes.astype(str).reset_index()
dtypes.columns = ["coluna", "tipo"]
st.dataframe(dtypes, use_container_width=True, hide_index=True)

st.subheader("Describe (colunas numéricas)")
numeric = df.select_dtypes(include="number")
if numeric.empty:
    st.info("Sem colunas numéricas nesta view.")
else:
    st.dataframe(numeric.describe(), use_container_width=True)

st.subheader("Amostra")
st.dataframe(df, use_container_width=True, hide_index=True)
