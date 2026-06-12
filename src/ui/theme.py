"""Paleta de marca Reconecta + formatadores BR.

A paleta é exposta como dict (`PALETTE`) para uso em componentes Python e
injetada como CSS variables (`--color-…`) via `apply_app_theme`."""
from __future__ import annotations

from collections.abc import Mapping

PALETTE_DARK = {
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

PALETTE_LIGHT = {
    # superfícies (alinhado ao tema Looker / legibilidade em fundo claro)
    "bg":            "#f5f5f5",
    "bg_soft":       "#eeeeee",
    "card":          "#ffffff",
    "card_hover":    "#fafafa",
    "card_strong":   "#f5f5f5",
    "border":        "#dadce0",
    "border_strong": "#bdc1c6",

    # marca
    "gold":          "#9a7b2f",
    "gold_bright":   "#b8860b",
    "gold_soft":     "#c9a84c",
    "wine":          "#8b2828",
    "wine_light":    "#a83838",
    "wine_soft":     "#fce8e8",

    # texto
    "text":          "#202124",
    "text_subtle":   "#5f6368",
    "muted":         "#80868b",

    # semânticas
    "green":         "#0f9d58",
    "green_soft":    "#d4f4dd",
    "red":           "#d93025",
    "red_soft":      "#fce8e6",
    "yellow":        "#f4b400",
    "blue":          "#1a73e8",
}


class _PaletteView(Mapping[str, str]):
    """Proxy — delega para a paleta ativa (`app_theme.get_active_palette`)."""

    def __getitem__(self, key: str) -> str:
        from .app_theme import get_active_palette
        return get_active_palette()[key]

    def __iter__(self):
        from .app_theme import get_active_palette
        return iter(get_active_palette())

    def __len__(self) -> int:
        from .app_theme import get_active_palette
        return len(get_active_palette())

    def get(self, key: str, default: str | None = None) -> str | None:
        from .app_theme import get_active_palette
        return get_active_palette().get(key, default)


PALETTE: Mapping[str, str] = _PaletteView()


# ---------------------------------------------------------------------------
# Formatadores
# ---------------------------------------------------------------------------

def brl(v: float | int | None, casas: int = 0) -> str:
    """Formato BR: R$ 87.699 (default) ou R$ 87.699,00 com `casas=2`.
    Backward-compatible — chamadas antigas sem `casas` continuam com 0 decimais."""
    if v is None or v != v:  # NaN
        return "—"
    s = f"R$ {v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
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


def fmt_currency_br(v: float | int | None) -> str:
    """R$ pt-BR com 2 casas decimais (padrão dashboards executivos)."""
    return brl(v, casas=2)


def fmt_percent_br(v: float | int | None) -> str:
    """Percentual pt-BR com 2 casas decimais."""
    return pct(v, casas=2)


def int_br(v: float | int | None) -> str:
    if v is None or v != v:
        return "—"
    return f"{int(v):,}".replace(",", ".")


# ---------------------------------------------------------------------------
# CSS global (variáveis `--color-*` são injetadas em `app_theme.py`)
# ---------------------------------------------------------------------------

# Regras CSS (sem tag <style> — montada em `apply_theme_css`).
# Prefixo `f` converte `{{` → `{` herdado do template original.
GLOBAL_CSS_STATIC = f"""
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

/* ----- sidebar user card (avatar | content | gear) ----- */
.sidebar-user-card-marker,
.sidebar-user-switch-marker {{
  display: none;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] {{
  border: 1px solid rgba(211, 176, 79, 0.16);
  border-radius: 12px;
  background: rgba(22, 17, 14, 0.72);
  padding: 8px 9px;
  margin-bottom: 10px;
  align-items: center !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div {{
  gap: 0.5rem !important;
  align-items: center !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:first-child {{
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(2) {{
  min-width: 0;
  flex: 1 1 auto;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(2) [data-testid="stVerticalBlock"] {{
  gap: 0.06rem !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(2) [data-testid="stMarkdown"] p {{
  margin: 0 !important;
  line-height: 1 !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(3) {{
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  flex: 0 0 auto;
  align-self: center !important;
}}
.sidebar-user-avatar-col {{
  display: flex;
  align-items: center;
  justify-content: center;
}}
.sidebar-user-avatar {{
  width: 32px;
  height: 32px;
  border-radius: 999px;
  background: var(--color-wine, #5c2e2e);
  color: var(--color-gold);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.72rem;
  letter-spacing: 0.03em;
}}
.sidebar-user-avatar-img {{
  width: 32px;
  height: 32px;
  border-radius: 999px;
  object-fit: cover;
  border: 1px solid var(--color-border);
  display: block;
}}
.sidebar-user-name {{
  color: var(--color-text);
  font-weight: 800;
  font-size: 0.86rem;
  line-height: 1.05;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}}
.sidebar-user-role-wrap {{
  display: block;
  width: fit-content;
  margin: 2px 0 0;
  line-height: 1;
}}
.sidebar-user-role-wrap p {{
  margin: 0 !important;
  line-height: 1 !important;
}}
.sidebar-user-badge {{
  display: inline-flex;
  width: fit-content;
  max-width: max-content;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 0.58rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  line-height: 1;
  text-transform: uppercase;
}}
.sidebar-user-badge--editor {{
  color: #d3b04f;
  background: rgba(211, 176, 79, 0.14);
  border: 1px solid rgba(211, 176, 79, 0.38);
}}
.sidebar-user-badge--viewer {{
  color: var(--color-text-subtle);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--color-border);
}}
[data-testid="stSidebar"] .sidebar-user-switch-marker + div .stButton {{
  margin: -1px 0 0 !important;
  padding: 0 !important;
}}
[data-testid="stSidebar"] .sidebar-user-switch-marker + div .stButton > button {{
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: rgba(244, 230, 194, 0.82) !important;
  font-size: 0.67rem !important;
  font-weight: 600 !important;
  line-height: 1 !important;
  padding: 0 !important;
  margin: 0 !important;
  min-height: 0.8rem !important;
  height: auto !important;
  width: fit-content !important;
  max-width: fit-content !important;
  justify-content: flex-start !important;
  text-decoration: none !important;
}}
[data-testid="stSidebar"] .sidebar-user-switch-marker + div .stButton > button:hover {{
  color: #ffffff !important;
  background: transparent !important;
  text-decoration: underline !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(3) [data-testid="stPopover"] {{
  margin: 0 !important;
  display: flex;
  align-items: center;
  justify-content: center;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(3) [data-testid="stPopover"] > div > button {{
  width: 36px !important;
  min-width: 36px !important;
  max-width: 36px !important;
  height: 36px !important;
  min-height: 36px !important;
  padding: 0 !important;
  margin: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border-radius: 10px !important;
  border: 1px solid rgba(211, 176, 79, 0.28) !important;
  background: rgba(255, 255, 255, 0.045) !important;
  box-shadow: none !important;
  color: #f4e6c2 !important;
  font-size: 0.95rem !important;
  line-height: 1 !important;
  text-align: center !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(3) [data-testid="stPopover"] > div > button:hover {{
  color: #ffffff !important;
  background: rgba(255, 255, 255, 0.07) !important;
  border-color: rgba(211, 176, 79, 0.45) !important;
}}
[data-testid="stSidebar"] .sidebar-user-card-marker + div[data-testid="stHorizontalBlock"] > div > [data-testid="column"]:nth-child(3) [data-testid="stPopover"] > div > button > *:not(:first-child) {{
  display: none !important;
}}
.sidebar-account-section {{
  color: var(--color-text-subtle);
  font-size: 0.66rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 6px 0 2px;
}}
[data-testid="stPopoverBody"]:has(.sidebar-account-section) {{
  min-width: 210px;
  padding: 8px 10px !important;
  border: 1px solid rgba(211, 176, 79, 0.22) !important;
  border-radius: 10px !important;
  background: rgba(18, 14, 11, 0.96) !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45) !important;
}}
[data-testid="stPopoverBody"]:has(.sidebar-account-section) .stButton > button {{
  font-size: 0.8rem !important;
  min-height: 1.75rem !important;
  padding-top: 0.12rem !important;
  padding-bottom: 0.12rem !important;
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
  container-type: inline-size;
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

/* ----- qual split (Qualificados · Não Qualificados nos cards do funil) -
   Inline numa linha quando o card é largo; empilhado em 2 linhas limpas
   quando estreito. Cada chip é nowrap — nunca quebra no meio do rótulo. */
.mcard-qual-split {{
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--color-border);
  font-size: 0.68rem;
  line-height: 1.25;
}}
.mcard-qual-chip {{
  white-space: nowrap;
  color: var(--color-text-subtle);
}}
.mcard-qual-chip .val {{
  color: var(--color-text);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}}
.mcard-qual-sep {{
  white-space: nowrap;
  color: var(--color-text-subtle);
  opacity: 0.55;
  padding: 0 3px;
}}
.mcard-qual-inline {{
  display: flex;
  flex-wrap: nowrap;
  align-items: baseline;
  gap: 0;
}}
.mcard-qual-stack {{
  display: none;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
}}
@container (max-width: 168px) {{
  .mcard-qual-inline {{ display: none; }}
  .mcard-qual-stack {{ display: flex; }}
}}

/* ----- Origens (chips coloridos por funil_origem) ----------------------
   Bloco secundário do card que mostra a quebra por funil de origem
   (VSL/SE/AG/Sem origem). Chips inline pras 3 origens priorizadas;
   linha muted pra "Sem origem" quando existe, evitando que ela domine
   a tipografia do card (no caso atual representa quase 100% dos leads). */
.mcard-origens {{
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 5px;
}}
.mcard-origens-title {{
  color: var(--color-text-subtle);
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  opacity: 0.75;
}}
.mcard-origens-chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  align-items: baseline;
}}
.mcard-origens-chip {{
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--color-border);
  font-size: 0.72rem;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}
.mcard-origens-chip .lbl {{
  font-weight: 700;
  letter-spacing: 0.4px;
  color: var(--color-text-subtle);
}}
.mcard-origens-chip .val {{
  font-weight: 600;
  color: var(--color-text);
}}
/* Tonalidade sutil por origem — só a borda + label colorido, valor neutro */
.mcard-origens-chip.vsl {{ border-color: rgba(124,58,237,0.45); }}
.mcard-origens-chip.vsl .lbl {{ color: #c4b5fd; }}
.mcard-origens-chip.se  {{ border-color: rgba(37,99,235,0.45); }}
.mcard-origens-chip.se  .lbl {{ color: #93c5fd; }}
.mcard-origens-chip.ag  {{ border-color: rgba(245,158,11,0.45); }}
.mcard-origens-chip.ag  .lbl {{ color: #fcd34d; }}
/* Chip "vazio" (val = '—' ou '0'): atenua mais pra não competir */
.mcard-origens-chip.empty {{ opacity: 0.55; }}
.mcard-origens-muted {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 0.66rem;
  color: var(--color-text-subtle);
  opacity: 0.7;
  padding-top: 1px;
}}
.mcard-origens-muted .lbl {{ letter-spacing: 0.4px; font-weight: 600; }}
.mcard-origens-muted .val {{ font-variant-numeric: tabular-nums; font-weight: 500; }}

/* ----- metric-card resumo (linha executiva — alinhada, sem cortar) ----- */
.mcard.mcard-resumo {{
  min-height: 235px;
  height: auto;
  justify-content: flex-start;
  gap: 0;
  margin-bottom: 16px;
  min-width: 0;
  overflow: visible;
  box-sizing: border-box;
}}
.mcard.mcard-resumo .mcard-header-block {{
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-height: 86px;
  min-width: 0;
  width: 100%;
}}
.mcard.mcard-resumo .mcard-value {{
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 1.45rem;
  min-width: 0;
}}
.mcard.mcard-resumo .mcard-hint {{
  min-height: 2.5em;
  line-height: 1.25;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 0 0 auto;
  min-width: 0;
}}
.mcard.mcard-resumo .mcard-hint-placeholder {{
  visibility: hidden;
}}
.mcard.mcard-resumo .mcard-cost {{
  flex: 0 0 auto;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
}}
.mcard.mcard-resumo .mcard-cost span {{
  color: var(--color-text-subtle);
  font-size: 0.78rem;
  white-space: nowrap;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
}}
.mcard.mcard-resumo .mcard-cost strong {{
  color: var(--color-text);
  font-size: 0.78rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  flex: 0 0 auto;
}}
.mcard.mcard-resumo .mcard-cost-placeholder span,
.mcard.mcard-resumo .mcard-cost-placeholder strong {{
  visibility: hidden;
}}
.mcard.mcard-resumo .mcard-resumo-spacer {{
  flex: 1 1 auto;
  min-height: 8px;
  width: 100%;
}}
.mcard.mcard-resumo .mcard-origin-block {{
  flex: 0 0 auto;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-height: 52px;
  min-width: 0;
  width: 100%;
  overflow: visible;
}}
.mcard.mcard-resumo .mcard-origin-placeholder {{
  border-top-color: transparent;
  visibility: hidden;
  pointer-events: none;
}}
.mcard.mcard-resumo .mcard-origens-title {{
  min-width: 0;
}}
.mcard.mcard-resumo .mcard-origens-chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  align-items: baseline;
  min-width: 0;
  width: 100%;
  overflow: visible;
}}
.mcard.mcard-resumo .mcard-origens-chip {{
  max-width: 100%;
  min-width: 0;
  white-space: normal;
  flex-shrink: 1;
}}
.mcard.mcard-resumo .mcard-origens-chip .val {{
  white-space: normal;
  word-break: break-word;
}}
.mcard.mcard-resumo .mcard-footer {{
  flex: 0 0 auto;
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 4px 8px;
  min-height: 20px;
  min-width: 0;
  width: 100%;
  font-size: 0.66rem;
  color: var(--color-text-subtle);
  opacity: 0.7;
  padding-top: 4px;
  overflow: visible;
}}
.mcard.mcard-resumo .mcard-footer .lbl {{
  letter-spacing: 0.4px;
  font-weight: 600;
  flex: 0 0 auto;
}}
.mcard.mcard-resumo .mcard-footer .val {{
  font-size: 0.6rem;
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  min-width: 0;
  flex: 1 1 auto;
  text-align: right;
  word-break: break-word;
}}
.mcard.mcard-resumo .mcard-footer-placeholder {{
  visibility: hidden;
  pointer-events: none;
}}

/* Linha financeira Pré-vendas */
.mcard.prevendas-finance {{
  min-height: 84px;
  height: 100%;
  margin-bottom: 0;
}}
.mcard.prevendas-finance .mcard-value {{
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}

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
  min-width: 0;
}}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"] > [data-testid="column"] > div {{
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] [data-testid="stMarkdownContainer"],
[data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stMarkdownContainer"] {{
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  width: 100%;
}}
/* garante cards preenchendo 100% da altura disponível */
.mcard, .hero-fin {{
  flex: 1 1 auto;
  width: 100%;
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

/* =====  Sidebar — hierarquia grupo (expansor) > subpáginas ===== */
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {{
  padding-top: 0 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] {{
  gap: 0 !important;
  padding-left: 4px !important;
  padding-right: 4px !important;
}}

/* --- Cabeçalho dos grupos (Time de Marketing, etc.) --- */
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {{
  font-size: 0.62rem !important;
  font-weight: 600 !important;
  letter-spacing: 1.5px !important;
  text-transform: uppercase !important;
  color: var(--color-gold-soft) !important;
  background: var(--color-card) !important;
  border: 1px solid var(--color-border) !important;
  border-radius: 8px !important;
  padding: 9px 12px !important;
  margin: 16px 6px 8px 6px !important;
  display: flex !important;
  flex-direction: row !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 8px !important;
  line-height: 1.25 !important;
  cursor: pointer !important;
  user-select: none !important;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
}}
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"]:hover {{
  background: var(--color-card-hover) !important;
  border-color: var(--color-border-strong) !important;
  color: var(--color-gold) !important;
}}
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] > span {{
  overflow: visible !important;
  white-space: normal !important;
  text-overflow: unset !important;
  min-width: 0 !important;
  flex: 1 1 auto !important;
}}
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] > div:last-child {{
  visibility: visible !important;
  flex-shrink: 0 !important;
  margin-left: auto !important;
  color: var(--color-muted) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}}

/* --- Bloco de cada grupo --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) {{
  margin-bottom: 6px !important;
}}

/* --- Subpáginas dentro do expansor (árvore com linha guia) --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) > li {{
  position: relative !important;
  margin: 1px 0 1px 10px !important;
  padding-left: 16px !important;
  list-style: none !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) > li::before {{
  content: "" !important;
  position: absolute !important;
  left: 4px !important;
  top: 0 !important;
  bottom: 0 !important;
  width: 1px !important;
  background: var(--color-border) !important;
  opacity: 0.9 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) > li::after {{
  content: "" !important;
  position: absolute !important;
  left: 4px !important;
  top: 50% !important;
  width: 9px !important;
  height: 1px !important;
  background: var(--color-border) !important;
  opacity: 0.9 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) > li:last-child::before {{
  bottom: 50% !important;
}}

/* --- Links de subpágina --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) [data-testid="stSidebarNavLink"] {{
  font-size: 0.80rem !important;
  font-weight: 450 !important;
  padding: 7px 10px 7px 8px !important;
  margin: 1px 2px !important;
  border-radius: 8px !important;
  color: var(--color-text-subtle) !important;
  line-height: 1.35 !important;
  border-left: 2px solid transparent !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > div:has([data-testid="stNavSectionHeader"]) [data-testid="stSidebarNavLink"]:hover {{
  background: var(--color-card) !important;
  color: var(--color-text) !important;
  border-left-color: var(--color-border-strong) !important;
}}

/* --- Páginas de topo (ex.: One Page, fora de grupo) --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > li [data-testid="stSidebarNavLink"] {{
  font-size: 0.85rem !important;
  font-weight: 500 !important;
  padding: 8px 12px !important;
  margin: 2px 4px !important;
  border-radius: 8px !important;
  color: var(--color-text-subtle) !important;
  border-left: 2px solid transparent !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > li [data-testid="stSidebarNavLink"]:hover {{
  background: var(--color-card) !important;
  color: var(--color-text) !important;
}}

/* --- Labels: permitir quebra em nomes longos (sem truncar feio) --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span {{
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: unset !important;
  display: block !important;
  line-height: 1.35 !important;
}}

/* --- Página ativa (grupo ou topo) --- */
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: var(--color-wine) !important;
  color: #ffffff !important;
  border-left: 3px solid var(--color-gold) !important;
  font-weight: 600 !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"]:hover {{
  background: var(--color-wine-light) !important;
  color: #ffffff !important;
  border-left-color: var(--color-gold-bright) !important;
}}
"""
