"""Paleta de marca Reconecta + formatadores BR.

A paleta é exposta como dict (`PALETTE`) para uso em componentes Python e
injetada como CSS variables (`--color-…`) via `apply_global_style`."""
from __future__ import annotations

PALETTE = {
    # superfícies
    "bg":            "#0a0806",
    "bg_soft":       "#110d09",
    "card":          "#161311",
    "card_hover":    "#1e1915",
    "card_strong":   "#1a1612",
    "border":        "#2a2118",
    "border_strong": "#3a2e20",

    # marca
    "gold":          "#c9a84c",
    "gold_bright":   "#e8c96e",
    "gold_soft":     "#8a7230",
    "wine":          "#7c1f2e",
    "wine_light":    "#c03048",
    "wine_soft":     "#4a1219",

    # texto
    "text":          "#f1e9df",
    "text_subtle":   "#a89a8a",
    "muted":         "#6a5a4a",

    # semânticas
    "green":         "#4ade80",
    "green_soft":    "#1f4a2e",
    "red":           "#f87171",
    "red_soft":      "#4a1e1e",
    "yellow":        "#fbbf24",
    "blue":          "#60a5fa",
}


# ---------------------------------------------------------------------------
# Formatadores
# ---------------------------------------------------------------------------

def brl(v: float | int | None) -> str:
    if v is None or v != v:  # NaN
        return "—"
    s = f"R$ {v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def brl_short(v: float | int | None) -> str:
    if v is None or v != v:
        return "—"
    if abs(v) >= 1_000_000:
        return f"R$ {v / 1_000_000:.1f}M".replace(".", ",")
    if abs(v) >= 1_000:
        return f"R$ {v / 1_000:.0f}K"
    return brl(v)


def pct(v: float | int | None, casas: int = 1) -> str:
    if v is None or v != v:
        return "—"
    return f"{v:.{casas}f}%".replace(".", ",")


def int_br(v: float | int | None) -> str:
    if v is None or v != v:
        return "—"
    return f"{int(v):,}".replace(",", ".")


# ---------------------------------------------------------------------------
# CSS global
# ---------------------------------------------------------------------------

def _css_vars() -> str:
    return "\n".join(f"  --color-{k.replace('_', '-')}: {v};"
                     for k, v in PALETTE.items())


GLOBAL_CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">

<style>
:root {{
{_css_vars()}
}}

/* ----- base ----- */
html, body, .stApp, [class*="css"] {{
  font-family: "Inter", system-ui, -apple-system, sans-serif !important;
}}
.stApp {{
  background: var(--color-bg);
  color: var(--color-text);
}}
.block-container {{
  padding-top: 1rem !important;
  padding-bottom: 2rem !important;
  max-width: 1500px;
}}

/* ----- tipografia ----- */
h1, h2, h3, h4 {{
  color: var(--color-text) !important;
  letter-spacing: -0.01em;
}}
h1 {{ font-weight: 700; font-size: 1.9rem; }}
h2 {{ font-weight: 600; font-size: 1.25rem; }}
h3 {{ font-weight: 600; font-size: 1.05rem; color: var(--color-text-subtle) !important; }}
p, .stMarkdown {{ color: var(--color-text); }}

/* ----- sidebar ----- */
section[data-testid="stSidebar"] {{
  background: var(--color-bg-soft);
  border-right: 1px solid var(--color-border);
}}
section[data-testid="stSidebar"] .stMarkdown h3 {{
  color: var(--color-gold) !important;
  text-transform: uppercase;
  letter-spacing: 2px;
  font-size: 0.7rem;
  margin-top: 1.2rem;
}}
section[data-testid="stSidebar"] label {{
  color: var(--color-text-subtle) !important;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  font-weight: 500;
}}

/* ----- inputs ----- */
[data-baseweb="select"] > div, [data-baseweb="input"] > div,
.stDateInput input, .stTextInput input, .stNumberInput input {{
  background-color: var(--color-card) !important;
  border-color: var(--color-border) !important;
  color: var(--color-text) !important;
  min-height: 34px !important;
  font-size: 0.85rem !important;
}}
[data-baseweb="select"]:hover > div {{
  border-color: var(--color-border-strong) !important;
}}
/* slider mais compacto */
.stSlider > div > div {{ padding-top: 0.25rem !important; }}

/* ----- Streamlit metric (fallback) ----- */
[data-testid="stMetric"] {{
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px 16px;
}}
[data-testid="stMetricLabel"] p {{
  color: var(--color-muted) !important;
  letter-spacing: 2px;
  text-transform: uppercase;
  font-size: 0.66rem !important;
  font-weight: 600 !important;
}}
[data-testid="stMetricValue"] {{
  color: var(--color-gold) !important;
  font-weight: 700 !important;
  font-size: 1.4rem !important;
}}

/* ----- KPI cards customizados ----- */
.kpi-card {{
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 14px;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 108px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.2s;
}}
.kpi-card:hover {{
  border-color: var(--color-border-strong);
  transform: translateY(-1px);
}}
.kpi-card.hero {{
  background: linear-gradient(135deg, var(--color-card) 0%, var(--color-card-strong) 100%);
  min-height: 148px;
  border: 1px solid var(--color-border-strong);
}}
.kpi-card.hero::before {{
  content: "";
  position: absolute;
  top: 0; left: 0;
  width: 3px; height: 100%;
  background: linear-gradient(180deg, var(--color-gold) 0%, var(--color-wine-light) 100%);
}}
.kpi-label {{
  color: var(--color-muted);
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
}}
.kpi-value {{
  color: var(--color-gold);
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}}
.kpi-card.hero .kpi-value {{
  font-size: 2.2rem;
  color: var(--color-gold-bright);
}}
.kpi-hint {{
  color: var(--color-text-subtle);
  font-size: 0.78rem;
  margin-top: 2px;
}}

/* ----- page header ----- */
.page-header {{
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  padding-bottom: 14px;
  margin-bottom: 22px;
  border-bottom: 1px solid var(--color-border);
}}
.page-header-left h1 {{
  margin: 0 !important;
  font-size: 2.1rem;
  font-weight: 700;
}}
.page-header-left .subtitle {{
  color: var(--color-text-subtle);
  font-size: 0.92rem;
  margin-top: 4px;
}}
.page-header-right {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}}
.period-badge {{
  background: var(--color-card);
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  padding: 6px 14px;
  color: var(--color-gold);
  font-size: 0.8rem;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}}
.period-label {{
  color: var(--color-muted);
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 2px;
}}

/* ----- section header ----- */
.section-header {{
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 28px 0 14px 0;
}}
.section-header::before {{
  content: "";
  width: 3px;
  height: 18px;
  background: var(--color-gold);
  border-radius: 2px;
}}
.section-title {{
  color: var(--color-text);
  font-size: 1.15rem;
  font-weight: 600;
}}
.section-sub {{
  color: var(--color-muted);
  font-size: 0.82rem;
}}

/* ----- sidebar brand ----- */
.brand {{
  padding: 8px 4px 16px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 12px;
}}
.brand-title {{
  color: var(--color-gold);
  font-weight: 700;
  font-size: 1.1rem;
  letter-spacing: 0.5px;
}}
.brand-sub {{
  color: var(--color-text-subtle);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 2px;
}}

/* ----- tabs ----- */
.stTabs [data-baseweb="tab-list"] {{
  gap: 4px;
  border-bottom: 1px solid var(--color-border);
}}
.stTabs [data-baseweb="tab"] {{
  background: transparent;
  color: var(--color-text-subtle);
  padding: 8px 18px !important;
  font-weight: 500;
  border-radius: 6px 6px 0 0;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
  color: var(--color-gold) !important;
  background: var(--color-card);
  border-bottom: 2px solid var(--color-gold) !important;
}}

/* ----- dataframes ----- */
[data-testid="stDataFrame"] {{
  border: 1px solid var(--color-border);
  border-radius: 10px;
  overflow: hidden;
}}

/* ----- expander ----- */
details[data-testid="stExpander"] {{
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
}}
details[data-testid="stExpander"] summary {{
  color: var(--color-text-subtle);
  font-weight: 500;
}}
details[data-testid="stExpander"] summary:hover {{
  color: var(--color-gold);
}}

/* ----- dividers ----- */
hr, [data-testid="stDivider"] {{
  border-color: var(--color-border) !important;
  margin: 1rem 0 !important;
}}

/* ----- hide streamlit chrome ----- */
#MainMenu, footer {{ visibility: visible; }}
footer {{ color: var(--color-muted) !important; }}
header[data-testid="stHeader"] {{ background: transparent; }}


/* =========================================================================
   LOOKER-STYLE LAYOUT (home / visão geral)
   ========================================================================= */

/* ============================================================
   HEADER UNIFICADO: título + filtros na mesma faixa vinho
   ============================================================ */

/* Filter label (caps pequeno) acima de cada widget */
.filter-strip-label {{
  color: var(--color-muted);
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 1.8px;
  text-transform: uppercase;
  margin-bottom: 3px;
}}

/* O stHorizontalBlock que CONTÉM o título da página vira a faixa vinho */
[data-testid="stHorizontalBlock"]:has(.page-header-title) {{
  background: linear-gradient(90deg, var(--color-wine) 0%, #5e1522 55%, #3a0d15 100%);
  border: 1px solid var(--color-border-strong);
  border-radius: 10px;
  padding: 8px 16px !important;
  margin: -8px 0 16px 0 !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.4);
  align-items: center !important;
  gap: 10px !important;
  min-height: 58px;
}}
/* Cada coluna do header também centraliza verticalmente seu conteúdo */
[data-testid="stHorizontalBlock"]:has(.page-header-title) > [data-testid="stColumn"] {{
  justify-content: center;
}}

/* Bloco do título dentro da 1ª coluna do header */
.page-header-title {{
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}}
.ph-logo {{
  color: var(--color-gold-bright);
  font-weight: 800;
  font-size: 0.95rem;
  letter-spacing: 2.2px;
  flex-shrink: 0;
}}
.ph-divider {{
  width: 1px;
  height: 28px;
  background: rgba(255,255,255,0.18);
  flex-shrink: 0;
}}
.ph-text {{
  display: flex;
  flex-direction: column;
  min-width: 0;
}}
.ph-title {{
  color: #fff;
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.ph-subtitle {{
  color: rgba(255,255,255,0.6);
  font-size: 0.7rem;
  line-height: 1.25;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}

/* Filter labels DENTRO da faixa vinho (sobrescreve o cinza padrão) */
[data-testid="stHorizontalBlock"]:has(.page-header-title) .filter-strip-label {{
  color: rgba(255,255,255,0.6) !important;
  letter-spacing: 1.6px;
}}

/* Widgets de filtro DENTRO da faixa vinho — fundo escuro pra destacar do wine */
[data-testid="stHorizontalBlock"]:has(.page-header-title) [data-testid="stPopover"] > div > button,
[data-testid="stHorizontalBlock"]:has(.page-header-title) [data-baseweb="select"] > div {{
  background: rgba(0,0,0,0.32) !important;
  border: 1px solid rgba(255,255,255,0.18) !important;
  color: rgba(255,255,255,0.95) !important;
  min-height: 32px !important;
  font-size: 0.82rem !important;
}}
[data-testid="stHorizontalBlock"]:has(.page-header-title) [data-testid="stPopover"] > div > button:hover,
[data-testid="stHorizontalBlock"]:has(.page-header-title) [data-baseweb="select"] > div:hover {{
  border-color: var(--color-gold-soft) !important;
  background: rgba(0,0,0,0.45) !important;
}}

/* ----- metric-card v2 (Looker-style, cinza escuro) ----- */
.mcard {{
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-height: 84px;
  height: 100%;
  transition: border-color 0.2s;
}}
.mcard:hover {{ border-color: var(--color-border-strong); }}
.mcard-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}}
.mcard-label {{
  color: var(--color-muted);
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 1.8px;
  text-transform: uppercase;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.mcard-value {{
  color: var(--color-text);
  font-size: 1.4rem;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  margin-top: 2px;
}}
.mcard-value.accent {{ color: var(--color-gold); }}
/* delta agora vira pill no canto superior direito */
.mcard-delta {{
  font-size: 0.66rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  margin: 0;
  padding: 2px 7px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
  letter-spacing: 0.2px;
}}
.mcard-delta.up   {{ color: var(--color-green); background: var(--color-green-soft); }}
.mcard-delta.down {{ color: var(--color-red);   background: var(--color-red-soft); }}
.mcard-delta.flat {{ color: var(--color-text-subtle); background: rgba(255,255,255,0.04); }}
.mcard-hint {{
  color: var(--color-text-subtle);
  font-size: 0.72rem;
  margin-top: 2px;
}}
.mcard-break {{
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 3px;
}}
.mcard-break-row {{
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
}}
.mcard-break-row .k {{ color: var(--color-text-subtle); }}
.mcard-break-row .v {{ color: var(--color-text); font-variant-numeric: tabular-nums; font-weight: 500; }}

/* ----- hero financial (Receita com barra/meta/status — slim, não dominante) ----- */
.hero-fin {{
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px 16px;
  position: relative;
  overflow: hidden;
  height: 100%;
}}
.hero-fin::before {{
  content: "";
  position: absolute;
  left: 0; top: 0;
  width: 3px; height: 100%;
  background: linear-gradient(180deg, var(--color-gold) 0%, var(--color-wine-light) 100%);
}}
.hero-fin-label {{
  color: var(--color-muted);
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 1.8px;
  text-transform: uppercase;
}}
.hero-fin-value {{
  color: var(--color-gold);
  font-size: 1.55rem;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  margin: 2px 0 8px 0;
}}
.hero-fin-bar {{
  width: 100%;
  height: 6px;
  background: var(--color-wine-soft);
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 6px;
}}
.hero-fin-bar-fill {{
  height: 100%;
  background: linear-gradient(90deg, var(--color-gold) 0%, var(--color-gold-bright) 100%);
  border-radius: 999px;
  transition: width 0.4s ease;
}}
.hero-fin-bar-fill.over {{
  background: linear-gradient(90deg, var(--color-green) 0%, #86efac 100%);
}}
.hero-fin-foot {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.74rem;
}}
.hero-fin-pct {{
  color: var(--color-text-subtle);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}}
.status-pill {{
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.8px;
  text-transform: uppercase;
}}
.status-pill.below {{
  color: var(--color-red);
  background: var(--color-red-soft);
  border: 1px solid rgba(248,113,113,0.3);
}}
.status-pill.close {{
  color: var(--color-yellow);
  background: rgba(251,191,36,0.12);
  border: 1px solid rgba(251,191,36,0.3);
}}
.status-pill.above {{
  color: var(--color-green);
  background: var(--color-green-soft);
  border: 1px solid rgba(74,222,128,0.3);
}}
.status-pill.none {{
  color: var(--color-muted);
  background: var(--color-card);
  border: 1px solid var(--color-border);
}}

/* ----- section title simples ----- */
.sec-title {{
  color: var(--color-text);
  font-size: 0.95rem;
  font-weight: 600;
  margin: 16px 0 8px 0;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--color-border);
}}
.sec-title .sub {{
  color: var(--color-muted);
  font-size: 0.74rem;
  font-weight: 400;
  margin-left: 10px;
}}

/* =========================================================================
   UX finalizations: uniform cards, polished top-bar filters, sidebar nav
   ========================================================================= */

/* uniformiza a altura dos cards dentro de uma mesma linha */
[data-testid="stHorizontalBlock"] {{
  align-items: stretch !important;
}}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
[data-testid="stHorizontalBlock"] > [data-testid="column"] {{
  display: flex;
  flex-direction: column;
}}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"] > [data-testid="column"] > div {{
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}}
/* garante cards preenchendo 100% da altura disponível */
.mcard, .hero-fin {{
  flex: 1 1 auto;
}}
.mcard {{ min-height: 84px; }}
.hero-fin {{ min-height: 96px; }}

/* =====  Filtros no topo (dropdowns executivos) ===== */
[data-baseweb="select"] > div {{
  background: var(--color-card) !important;
  border: 1px solid var(--color-border-strong) !important;
  border-radius: 8px !important;
  min-height: 34px !important;
  transition: border-color 0.15s;
}}
[data-baseweb="select"] > div:hover {{
  border-color: var(--color-gold-soft) !important;
}}
[data-baseweb="select"] div[role="listbox"] {{
  background: var(--color-card) !important;
  border: 1px solid var(--color-border-strong) !important;
}}
[data-baseweb="tag"] {{
  background: var(--color-wine-soft) !important;
  color: var(--color-text) !important;
  border-radius: 4px !important;
}}
[data-baseweb="tag"] svg {{
  color: var(--color-gold-bright) !important;
}}
/* input de data no mesmo padrão */
.stDateInput > div > div {{
  background: var(--color-card) !important;
  border: 1px solid var(--color-border-strong) !important;
  border-radius: 8px !important;
  min-height: 34px !important;
}}
.stDateInput input {{
  background: transparent !important;
  border: none !important;
  color: var(--color-text) !important;
  font-variant-numeric: tabular-nums;
}}

/* remove espaço extra entre o label custom e o widget */
.filter-strip-label + div {{ margin-top: 0 !important; }}

/* ==== popover (multiselect compacto) ==== */
[data-testid="stPopover"] > div > button,
div[data-testid="stPopover"] button[kind="secondary"] {{
  background: var(--color-card) !important;
  border: 1px solid var(--color-border-strong) !important;
  border-radius: 8px !important;
  min-height: 34px !important;
  color: var(--color-text) !important;
  font-weight: 500 !important;
  font-size: 0.85rem !important;
  text-align: left !important;
  justify-content: space-between !important;
  width: 100% !important;
  padding: 0 12px !important;
  font-variant-numeric: tabular-nums;
}}
[data-testid="stPopover"] > div > button:hover {{
  border-color: var(--color-gold-soft) !important;
  background: var(--color-card-hover) !important;
}}
/* dentro do popover: botões pequenos auxiliares */
[data-testid="stPopover"] [data-testid="stHorizontalBlock"] button[kind="secondary"] {{
  background: transparent !important;
  border: 1px solid var(--color-border) !important;
  color: var(--color-text-subtle) !important;
  font-size: 0.78rem !important;
  font-weight: 500 !important;
  min-height: 32px !important;
  padding: 4px 10px !important;
}}
[data-testid="stPopover"] [data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {{
  color: var(--color-gold) !important;
  border-color: var(--color-gold-soft) !important;
}}

/* ==== bloco do período: empilha selectbox + date_input com gap mínimo ==== */
.filter-strip-label ~ div + div .stDateInput {{
  margin-top: 4px;
}}

/* ==== texto auxiliar discreto abaixo de um card (ex.: ritmo de vendas) ==== */
.kpi-foot {{
  margin-top: 4px;
  padding: 0 4px;
  color: var(--color-text-subtle);
  font-size: 0.7rem;
  font-style: italic;
  letter-spacing: 0.2px;
  font-variant-numeric: tabular-nums;
}}
.kpi-foot b {{
  color: var(--color-gold);
  font-style: normal;
  font-weight: 600;
}}

/* =====  Sidebar com st.navigation (marca Reconecta no topo) ===== */
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {{
  padding-top: 0 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {{
  gap: 2px;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
  color: var(--color-text-subtle) !important;
  padding: 8px 14px !important;
  border-radius: 8px !important;
  font-weight: 500;
  font-size: 0.88rem;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {{
  background: var(--color-card) !important;
  color: var(--color-text) !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: var(--color-wine-soft) !important;
  color: var(--color-gold-bright) !important;
  border-left: 3px solid var(--color-gold);
}}
</style>
"""
