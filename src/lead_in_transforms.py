"""Transforms / KPIs — Lead In & Reuniões (v1 diagnóstica).

Fonte: `zoho_activities` · `activity_type = 'Consulta'`.
Classificação de pré: campo `activity.prevendas` + cadastro
`fdw_reconecta.executivas_pre_vendas`.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from .prevendas_transforms import _canonical_official_name
from .transforms import (
    _executivas_churn_nomes_casam,
    _safe_div,
    executivas_churn_agregar_por_executiva,
    executivas_churn_contagem_para_executiva,
    executivas_churn_total,
)

LEAD_IN_AGENDA_TZ = "America/Sao_Paulo"
LEAD_IN_DURACAO_PADRAO_MIN = 60

ST_TEMP_CANCELADA = "Cancelada"
ST_TEMP_REAGENDADA = "Reagendada"
ST_TEMP_CONCLUIDA = "Concluída"
ST_TEMP_PROXIMA = "Próxima"
ST_TEMP_EM_ANDAMENTO = "Em andamento"
ST_TEMP_AGUARDANDO = "Aguardando atualização"

_AGENDA_SORT_ORDER = {
    ST_TEMP_EM_ANDAMENTO: 0,
    ST_TEMP_PROXIMA: 1,
    ST_TEMP_AGUARDANDO: 2,
    ST_TEMP_CONCLUIDA: 3,
    ST_TEMP_CANCELADA: 4,
    ST_TEMP_REAGENDADA: 5,
}

# Ordem da legenda do gráfico (e prioridade operacional de leitura).
AGENDA_CHART_STATUS_ORDER: tuple[str, ...] = (
    ST_TEMP_EM_ANDAMENTO,
    ST_TEMP_PROXIMA,
    ST_TEMP_CONCLUIDA,
    ST_TEMP_AGUARDANDO,
    ST_TEMP_CANCELADA,
    ST_TEMP_REAGENDADA,
)

_AGENDA_FINAL_SUBORDER = {
    ST_TEMP_CONCLUIDA: 0,
    ST_TEMP_CANCELADA: 1,
    ST_TEMP_REAGENDADA: 2,
}

# Paleta unificada — gráfico (hex) e destaque da tabela (rgba suave).
AGENDA_STATUS_COLORS: dict[str, str] = {
    ST_TEMP_EM_ANDAMENTO: "#5DA9FF",
    ST_TEMP_PROXIMA: "#D4B04C",
    ST_TEMP_AGUARDANDO: "#F0A020",
    ST_TEMP_CONCLUIDA: "#57D57E",
    ST_TEMP_CANCELADA: "#FF6B6B",
    ST_TEMP_REAGENDADA: "#E05A9B",
}

AGENDA_STATUS_ROW_BG: dict[str, str] = {
    ST_TEMP_EM_ANDAMENTO: "background-color: rgba(93, 169, 255, 0.18);",
    ST_TEMP_PROXIMA: "background-color: rgba(212, 176, 76, 0.26);",
    ST_TEMP_AGUARDANDO: "background-color: rgba(240, 160, 32, 0.28);",
    ST_TEMP_CONCLUIDA: "background-color: rgba(87, 213, 126, 0.20);",
    ST_TEMP_CANCELADA: "background-color: rgba(255, 107, 107, 0.20);",
    ST_TEMP_REAGENDADA: "background-color: rgba(224, 90, 155, 0.20);",
}

AGENDA_CHART_STATUS_LABELS: dict[str, str] = {
    ST_TEMP_PROXIMA: "Próxima",
    ST_TEMP_EM_ANDAMENTO: "Em andamento",
    ST_TEMP_CONCLUIDA: "Concluída",
    ST_TEMP_AGUARDANDO: "Aguard. atual.",
    ST_TEMP_CANCELADA: "Cancelada",
    ST_TEMP_REAGENDADA: "Reagendada",
}

SEM_CLOSER_AGENDA = "Sem closer identificada"

SEM_PRE_IDENTIFICADA = "Sem pré identificada"
TIPO_COM_PRE = "Com qualificação da pré"
TIPO_SEM_PRE = "Sem qualificação da pré / autoagendamento"
TIPO_PRE_COM_MATCH = "Com pré identificada (cadastro)"
TIPO_PRE_SEM_MATCH = "Pré informada sem match no cadastro"
SEM_CLOSER = "Sem Closer"

FONTE_PRE_ACTIVITY = "activity.prevendas"
FONTE_PRE_LEAD_SLA = "lead_sla_email"
FONTE_PRE_DEAL_SDR = "deal.sdr_ss"
FONTE_PRE_SEM = "sem_pre"

# Regra operacional ainda em validação — limiar para sinalizar ruído no CRM.
_RUIDO_PRE_LIMIAR_PCT = 15.0

_STATUS_MAP: dict[str, tuple[str, ...]] = {
    "Agendada": ("agendada", "agendado"),
    "Realizada": (
        "concluída", "concluído", "concluida", "concluido",
        "realizada", "realizado", "compareceu", "comparecida", "comparecido",
    ),
    "Cancelada": ("cancelada", "cancelado", "cancelou"),
    "Reagendada": ("reagendada", "reagendado"),
}

# Status que permanecem fora dos 4 buckets até validação com a operação.
_STATUS_OUTROS_CONHECIDOS: dict[str, str] = {
    "vencida": "Vencida (pendente CRM — não mapeada)",
    "vencido": "Vencida (pendente CRM — não mapeada)",
    "nao compareceu": "Não compareceu (não mapeado)",
    "não compareceu": "Não compareceu (não mapeado)",
    "no show": "No-show (não mapeado)",
}


def _norm_status_token(status) -> str:
    if status is None or (isinstance(status, float) and pd.isna(status)):
        return ""
    return str(status).strip().lower()


# Reagendamento — classificação interna preservada; oculto na UI até fonte confiável.
LEAD_IN_EXIBIR_REAGENDAMENTO = False


def lead_in_status_bucket(status) -> str:
    """Mapeia `status_reuniao` CRM → bucket operacional (v1 diagnóstica)."""
    tok = _norm_status_token(status)
    if not tok:
        return "Outros"
    # Substring antes do match exato — ordem importa (reagend antes de agend).
    if "reagend" in tok:
        return "Reagendada"
    if "conclu" in tok or "realiz" in tok or "comparec" in tok:
        return "Realizada"
    if "cancel" in tok:
        return "Cancelada"
    if "agend" in tok:
        return "Agendada"
    for bucket, variants in _STATUS_MAP.items():
        if tok in variants:
            return bucket
    return "Outros"


def lead_in_status_bucket_painel(status) -> str:
    """Bucket exibido no painel — reagendamentos → Outros quando ocultos."""
    bucket = lead_in_status_bucket(status)
    if not LEAD_IN_EXIBIR_REAGENDAMENTO and bucket == "Reagendada":
        return "Outros"
    return bucket


def _lead_in_status_col(df: pd.DataFrame | None) -> str:
    if df is not None and "status_bucket_painel" in df.columns:
        return "status_bucket_painel"
    return "status_bucket"


def _lead_in_agenda_temporal_ui(status: str) -> str:
    if not LEAD_IN_EXIBIR_REAGENDAMENTO and status == ST_TEMP_REAGENDADA:
        return ST_TEMP_AGUARDANDO
    return status


def lead_in_agenda_visualizar_opcoes() -> tuple[str, ...]:
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        return LEAD_IN_AGENDA_VISUALIZAR_OPCOES
    return tuple(o for o in LEAD_IN_AGENDA_VISUALIZAR_OPCOES if o != "Reagendadas")


def lead_in_agenda_chart_status_order() -> tuple[str, ...]:
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        return AGENDA_CHART_STATUS_ORDER
    return tuple(s for s in AGENDA_CHART_STATUS_ORDER if s != ST_TEMP_REAGENDADA)


def lead_in_agenda_bucket_chart_order() -> tuple[str, ...]:
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        return AGENDA_BUCKET_CHART_ORDER
    return tuple(s for s in AGENDA_BUCKET_CHART_ORDER if s != "Reagendada")


def lead_in_status_outros_rotulo(status) -> str:
    """Rótulo legível para status ainda em Outros (expander diagnóstico)."""
    tok = _norm_status_token(status)
    if not tok:
        return "(nulo/vazio)"
    return _STATUS_OUTROS_CONHECIDOS.get(tok, tok)


def _official_pre_names(df_pre: pd.DataFrame | None) -> list[str]:
    if df_pre is None or df_pre.empty or "nome" not in df_pre.columns:
        return []
    return sorted(
        {str(n).strip() for n in df_pre["nome"].dropna() if str(n).strip()}
    )


def _lead_in_canonical_pre(nome, official_names: list[str]) -> str:
    if nome is None or (isinstance(nome, float) and pd.isna(nome)):
        return ""
    raw = str(nome).strip()
    if not raw:
        return ""
    canon = _canonical_official_name(raw, official_names)
    return canon or raw


def _lead_in_pick_email_sdr(
    email_norm,
    ts_reuniao,
    lookup: pd.DataFrame | None,
) -> tuple[str, str, pd.Timestamp]:
    """Melhor SDR por email: mais recente até ts_reuniao; senão mais recente."""
    if lookup is None or lookup.empty or not email_norm:
        return "", "", pd.NaT
    en = str(email_norm).strip().lower()
    if not en:
        return "", "", pd.NaT

    sub = lookup[lookup["email_norm"].astype(str).str.lower() == en].copy()
    if sub.empty:
        return "", "", pd.NaT

    ts_ref = pd.Timestamp(ts_reuniao) if ts_reuniao is not None and not pd.isna(ts_reuniao) else pd.NaT
    if not pd.isna(ts_ref):
        antes = sub[sub["ts_vinculo"] <= ts_ref]
        if not antes.empty:
            sub = antes

    row = sub.sort_values("ts_vinculo", ascending=False, na_position="last").iloc[0]
    sdr = str(row.get("sdr_nome") or "").strip()
    fonte = str(row.get("fonte_pre_venda") or FONTE_PRE_LEAD_SLA).strip()
    ts_v = pd.Timestamp(row["ts_vinculo"]) if "ts_vinculo" in row.index else pd.NaT
    return sdr, fonte, ts_v


def lead_in_aplicar_pre(
    df: pd.DataFrame,
    df_pre_oficiais: pd.DataFrame | None,
    df_email_sdr: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Cascata de identificação da pré-venda/SDR por reunião."""
    if df is None or df.empty:
        return df

    official_names = _official_pre_names(df_pre_oficiais)
    out = df.copy()

    out["status_bucket"] = out["status_reuniao"].apply(lead_in_status_bucket)
    out["status_bucket_painel"] = out["status_reuniao"].apply(lead_in_status_bucket_painel)
    out["foi_reagendada"] = out["status_bucket"] == "Reagendada"

    if "email_norm" not in out.columns and "email" in out.columns:
        out["email_norm"] = (
            out["email"].astype(str).str.strip().str.lower().replace({"nan": "", "none": ""})
        )

    def _resolve_pre(row) -> tuple:
        raw = row.get("prevendas_raw")
        raw_s = str(raw).strip() if raw is not None and not pd.isna(raw) else ""
        tem_campo = bool(raw_s)
        cadastro_act = _canonical_official_name(raw_s, official_names) if tem_campo else ""

        # 1) activity.prevendas com match no cadastro oficial
        if cadastro_act:
            return (
                cadastro_act,
                FONTE_PRE_ACTIVITY,
                pd.NaT,
                tem_campo,
                True,
                cadastro_act,
                TIPO_PRE_COM_MATCH,
                True,
                False,
                False,
            )

        ts_reuniao = row.get("ts_reuniao")
        email_norm = row.get("email_norm")

        # 2) associação por email (base SLA / leads repassados)
        sdr_email, fonte_email, ts_vinc = _lead_in_pick_email_sdr(
            email_norm, ts_reuniao, df_email_sdr,
        )
        if sdr_email:
            canon = _lead_in_canonical_pre(sdr_email, official_names)
            match = bool(_canonical_official_name(sdr_email, official_names))
            tipo_diag = TIPO_PRE_COM_MATCH if match else TIPO_PRE_SEM_MATCH
            return (
                canon,
                fonte_email or FONTE_PRE_LEAD_SLA,
                ts_vinc,
                tem_campo,
                match,
                _canonical_official_name(sdr_email, official_names) or "",
                tipo_diag,
                bool(email_norm),
                True,
                False,
            )

        # 3) deal.sdr_ss do deal da reunião
        deal_sdr = row.get("deal_sdr_nome")
        deal_sdr_s = str(deal_sdr).strip() if deal_sdr is not None and not pd.isna(deal_sdr) else ""
        if deal_sdr_s:
            canon = _lead_in_canonical_pre(deal_sdr_s, official_names)
            match = bool(_canonical_official_name(deal_sdr_s, official_names))
            tipo_diag = TIPO_PRE_COM_MATCH if match else TIPO_PRE_SEM_MATCH
            return (
                canon,
                FONTE_PRE_DEAL_SDR,
                pd.NaT,
                tem_campo,
                match,
                _canonical_official_name(deal_sdr_s, official_names) or "",
                tipo_diag,
                bool(email_norm),
                False,
                True,
            )

        # 4) sem pré identificada
        return (
            SEM_PRE_IDENTIFICADA,
            FONTE_PRE_SEM,
            pd.NaT,
            tem_campo,
            False,
            "",
            SEM_PRE_IDENTIFICADA,
            bool(email_norm),
            False,
            False,
        )

    resolved = out.apply(_resolve_pre, axis=1, result_type="expand")
    out["pre_venda_identificada"] = resolved[0]
    out["fonte_pre_venda"] = resolved[1]
    out["data_vinculo_pre"] = resolved[2]
    out["tem_prevendas_campo"] = resolved[3]
    out["pre_cadastro_match"] = resolved[4]
    out["pre_cadastro_nome"] = resolved[5]
    out["tipo_pre_diagnostico"] = resolved[6]
    out["tem_email_encontrado"] = resolved[7]
    out["tem_sdr_via_email"] = resolved[8]
    out["tem_sdr_via_deal_ss"] = resolved[9]

    # Aliases usados pelo restante da página
    out["pre_venda"] = out["pre_venda_identificada"]
    out["fonte_pre"] = out["fonte_pre_venda"]

    tem_sdr = out["pre_venda_identificada"] != SEM_PRE_IDENTIFICADA
    out["tipo_qualificacao"] = tem_sdr.map(
        {True: TIPO_COM_PRE, False: TIPO_SEM_PRE}
    )

    if "closer" not in out.columns:
        out["closer"] = SEM_CLOSER
    out["closer"] = out["closer"].fillna(SEM_CLOSER).replace("", SEM_CLOSER)

    return out


def lead_in_kpis(df: pd.DataFrame) -> dict:
    """Cards principais + taxas (denominador = consultas com bucket conhecido)."""
    zeros = {
        "total": 0,
        "agendadas": 0,
        "realizadas": 0,
        "canceladas": 0,
        "reagendadas": 0,
        "outros": 0,
        "com_pre": 0,
        "sem_pre": 0,
        "taxa_realizacao": 0.0,
        "taxa_cancelamento": 0.0,
        "taxa_reagendamento": 0.0,
    }
    if df is None or df.empty:
        return zeros

    out = dict(zeros)
    out["total"] = len(df)
    bc = _lead_in_status_col(df)
    out["agendadas"] = int((df[bc] == "Agendada").sum())
    out["realizadas"] = int((df[bc] == "Realizada").sum())
    out["canceladas"] = int((df[bc] == "Cancelada").sum())
    out["reagendadas"] = (
        int((df["status_bucket"] == "Reagendada").sum())
        if LEAD_IN_EXIBIR_REAGENDAMENTO
        else 0
    )
    out["outros"] = int((df[bc] == "Outros").sum())
    out["com_pre"] = int((df["tipo_qualificacao"] == TIPO_COM_PRE).sum())
    out["sem_pre"] = int((df["tipo_qualificacao"] == TIPO_SEM_PRE).sum())

    base_taxas = out["agendadas"] + out["realizadas"] + out["canceladas"] + out["outros"]
    if base_taxas == 0:
        base_taxas = out["total"]

    out["taxa_realizacao"] = _safe_div(out["realizadas"], base_taxas) * 100
    out["taxa_cancelamento"] = _safe_div(out["canceladas"], base_taxas) * 100
    out["taxa_reagendamento"] = _safe_div(out["reagendadas"], base_taxas) * 100
    return out


def lead_in_matriz(df: pd.DataFrame) -> pd.DataFrame:
    """Status × (com pré / sem pré / total)."""
    rows = []
    bc = _lead_in_status_col(df)
    for status in ("Agendada", "Realizada", "Cancelada"):
        sub = df[df[bc] == status] if df is not None and not df.empty else pd.DataFrame()
        com_n = int((sub["tipo_qualificacao"] == TIPO_COM_PRE).sum()) if not sub.empty else 0
        sem_n = int((sub["tipo_qualificacao"] == TIPO_SEM_PRE).sum()) if not sub.empty else 0
        rows.append({
            "Status / Resultado da reunião": status,
            "Com qualificação da pré": com_n,
            "Sem pré / autoagendamento": sem_n,
            "Total": com_n + sem_n,
        })
    if df is not None and not df.empty and (df[bc] == "Outros").any():
        sub = df[df[bc] == "Outros"]
        com_n = int((sub["tipo_qualificacao"] == TIPO_COM_PRE).sum())
        sem_n = int((sub["tipo_qualificacao"] == TIPO_SEM_PRE).sum())
        rows.append({
            "Status / Resultado da reunião": "Outros (diagnóstico)",
            "Com qualificação da pré": com_n,
            "Sem pré / autoagendamento": sem_n,
            "Total": com_n + sem_n,
        })
    return pd.DataFrame(rows)


LEAD_IN_AGENDA_OPCAO_TODO_PERIODO = "Todo o período selecionado"

AGENDA_BUCKET_CHART_ORDER: tuple[str, ...] = (
    "Agendada",
    "Realizada",
    "Cancelada",
    "Reagendada",
    "Outros",
)

AGENDA_BUCKET_CHART_COLORS: dict[str, str] = {
    "Agendada": AGENDA_STATUS_COLORS[ST_TEMP_PROXIMA],
    "Realizada": AGENDA_STATUS_COLORS[ST_TEMP_CONCLUIDA],
    "Cancelada": AGENDA_STATUS_COLORS[ST_TEMP_CANCELADA],
    "Reagendada": AGENDA_STATUS_COLORS[ST_TEMP_REAGENDADA],
    "Outros": "#9AA0A6",
}

LEAD_IN_AGENDA_VISUALIZAR_OPCOES: tuple[str, ...] = (
    "Todas",
    "Próximas",
    "Em andamento",
    "Aguardando atualização",
    "Concluídas",
    "Canceladas",
    "Reagendadas",
)

_AGENDA_VISUALIZAR_STATUS: dict[str, tuple[str, ...]] = {
    "Próximas": (ST_TEMP_PROXIMA,),
    "Em andamento": (ST_TEMP_EM_ANDAMENTO,),
    "Aguardando atualização": (ST_TEMP_AGUARDANDO,),
    "Concluídas": (ST_TEMP_CONCLUIDA,),
    "Canceladas": (ST_TEMP_CANCELADA,),
    "Reagendadas": (ST_TEMP_REAGENDADA,),
}


def lead_in_agenda_filtrar(
    agenda: pd.DataFrame,
    visualizar: str,
    *,
    modo_historico: bool = False,
) -> pd.DataFrame:
    """Filtro rápido da tabela Agenda do dia (não altera cards nem gráfico)."""
    if agenda is None or agenda.empty or visualizar == "Todas":
        return agenda

    if modo_historico:
        if visualizar == "Próximas" and "status_bucket" in agenda.columns:
            return agenda.loc[agenda["status_bucket"] == "Agendada"].copy()
        if visualizar == "Em andamento":
            return agenda.iloc[0:0].copy()

    statuses = _AGENDA_VISUALIZAR_STATUS.get(visualizar)
    if not statuses or "status_temporal" not in agenda.columns:
        return agenda
    return agenda.loc[agenda["status_temporal"].isin(statuses)].copy()


def lead_in_agenda_now() -> datetime:
    """`now` local do app (America/Sao_Paulo) como naive — alinhado ao CRM."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(LEAD_IN_AGENDA_TZ)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def lead_in_agenda_periodo_inclui_hoje(
    data_ini: date,
    data_fim: date,
    today: date | None = None,
) -> bool:
    """True quando o recorte global inclui a data atual."""
    today = today or date.today()
    return data_ini <= today <= data_fim


def lead_in_agenda_ref_date(
    data_ini: date,
    data_fim: date,
    today: date | None = None,
) -> tuple[date, bool]:
    """Data de foco da agenda (tempo real) e se é o dia atual."""
    today = today or date.today()
    if lead_in_agenda_periodo_inclui_hoje(data_ini, data_fim, today):
        return today, True
    return data_fim, False


def lead_in_agenda_datas_disponiveis(
    df: pd.DataFrame,
    data_ini: date,
    data_fim: date,
) -> list[date]:
    """Datas do período com pelo menos uma consulta."""
    if df is None or df.empty or "data_reuniao" not in df.columns:
        return []
    dr = pd.to_datetime(df["data_reuniao"], errors="coerce").dt.date
    mask = dr.notna() & (dr >= data_ini) & (dr <= data_fim)
    if not mask.any():
        return []
    return sorted(dr.loc[mask].unique().tolist())


def _lead_in_meeting_start(row: pd.Series) -> pd.Timestamp:
    for col in ("start_datetime", "ts_reuniao"):
        if col in row.index:
            val = row[col]
            if val is not None and not pd.isna(val):
                return pd.Timestamp(val)
    return pd.NaT


def _lead_in_meeting_end(
    row: pd.Series,
    duracao_min: int = LEAD_IN_DURACAO_PADRAO_MIN,
) -> pd.Timestamp:
    if "end_datetime" in row.index:
        val = row["end_datetime"]
        if val is not None and not pd.isna(val):
            return pd.Timestamp(val)
    start = _lead_in_meeting_start(row)
    if pd.isna(start):
        return pd.NaT
    return start + pd.Timedelta(minutes=duracao_min)


def _lead_in_fmt_minutos(minutos: float, prefixo: str) -> str:
    m = max(int(abs(minutos)), 0)
    if m < 60:
        return f"{prefixo} {m} min"
    h, r = divmod(m, 60)
    return f"{prefixo} {h}h {r}m"


def lead_in_status_temporal_historico(status_reuniao) -> str:
    """Status da agenda para datas passadas — prioriza o CRM, sem relógio."""
    tok = _norm_status_token(status_reuniao)
    if "cancel" in tok:
        return ST_TEMP_CANCELADA
    if "reagend" in tok:
        return (
            ST_TEMP_REAGENDADA
            if LEAD_IN_EXIBIR_REAGENDAMENTO
            else ST_TEMP_AGUARDANDO
        )
    if "conclu" in tok or "realiz" in tok or "comparec" in tok:
        return ST_TEMP_CONCLUIDA
    if "agend" in tok or not tok or "vencid" in tok:
        return ST_TEMP_AGUARDANDO
    return ST_TEMP_AGUARDANDO


def lead_in_status_temporal(
    status_reuniao,
    ts_start: pd.Timestamp,
    ts_end: pd.Timestamp,
    now: datetime,
    *,
    modo_historico: bool = False,
) -> str:
    if modo_historico:
        return lead_in_status_temporal_historico(status_reuniao)

    tok = _norm_status_token(status_reuniao)
    if "cancel" in tok:
        return ST_TEMP_CANCELADA
    if "reagend" in tok:
        return (
            ST_TEMP_REAGENDADA
            if LEAD_IN_EXIBIR_REAGENDAMENTO
            else ST_TEMP_AGUARDANDO
        )
    if "conclu" in tok or "realiz" in tok or "comparec" in tok:
        return ST_TEMP_CONCLUIDA

    now_ts = pd.Timestamp(now)
    if pd.isna(ts_start):
        return ST_TEMP_AGUARDANDO

    if now_ts < ts_start:
        return ST_TEMP_PROXIMA
    if not pd.isna(ts_end) and now_ts <= ts_end:
        return ST_TEMP_EM_ANDAMENTO
    if pd.isna(ts_end) and now_ts <= ts_start + pd.Timedelta(
        minutes=LEAD_IN_DURACAO_PADRAO_MIN
    ):
        return ST_TEMP_EM_ANDAMENTO

    if "agend" in tok or not tok or "vencid" in tok:
        return ST_TEMP_AGUARDANDO
    return ST_TEMP_AGUARDANDO


def lead_in_tempo_restante(
    status_temporal: str,
    ts_start: pd.Timestamp,
    ts_end: pd.Timestamp,
    now: datetime,
) -> str:
    now_ts = pd.Timestamp(now)
    if status_temporal == ST_TEMP_PROXIMA and not pd.isna(ts_start):
        mins = (ts_start - now_ts).total_seconds() / 60
        return _lead_in_fmt_minutos(mins, "Faltam")
    if status_temporal == ST_TEMP_EM_ANDAMENTO:
        return "Em andamento"
    if status_temporal == ST_TEMP_AGUARDANDO:
        ref = ts_end if not pd.isna(ts_end) else ts_start
        if not pd.isna(ref):
            mins = (now_ts - ref).total_seconds() / 60
            return _lead_in_fmt_minutos(mins, "Passou há")
        return "Aguardando atualização"
    return status_temporal


def _lead_in_agenda_prioridade(row: pd.Series, now: datetime) -> tuple:
    """Chave de ordenação operacional (menor = mais urgente)."""
    st = row.get("status_temporal")
    ts = row.get("ts_start")
    now_ts = pd.Timestamp(now)

    if st == ST_TEMP_EM_ANDAMENTO:
        return (0, 0, pd.Timestamp(ts).value if pd.notna(ts) else 0)

    if st == ST_TEMP_PROXIMA:
        if pd.notna(ts):
            mins = (pd.Timestamp(ts) - now_ts).total_seconds() / 60
        else:
            mins = 99999.0
        if mins <= 30:
            bucket = 1
        elif mins <= 60:
            bucket = 2
        else:
            bucket = 3
        return (bucket, mins, pd.Timestamp(ts).value)

    if st == ST_TEMP_AGUARDANDO:
        ts_val = pd.Timestamp(ts).value if pd.notna(ts) else 0
        return (4, 0, -ts_val)

    if st in _AGENDA_FINAL_SUBORDER:
        ts_val = pd.Timestamp(ts).value if pd.notna(ts) else 0
        return (5, _AGENDA_FINAL_SUBORDER[st], -ts_val)

    return (6, 0, pd.Timestamp(ts).value if pd.notna(ts) else 0)


def _lead_in_agenda_destaque(row: pd.Series, now: datetime) -> str:
    """Status temporal da linha → chave da paleta (somente exibição)."""
    st = row.get("status_temporal")
    if st in AGENDA_STATUS_ROW_BG:
        return str(st)
    return ""


def _lead_in_enriquecer_agenda_linhas(
    out: pd.DataFrame,
    now: datetime,
    *,
    modo_historico: bool,
) -> pd.DataFrame:
    out["ts_start"] = out.apply(_lead_in_meeting_start, axis=1)
    out["ts_end"] = out.apply(_lead_in_meeting_end, axis=1)
    out["status_temporal"] = out.apply(
        lambda r: lead_in_status_temporal(
            r.get("status_reuniao"),
            r["ts_start"],
            r["ts_end"],
            now,
            modo_historico=modo_historico,
        ),
        axis=1,
    )
    if modo_historico:
        out["tempo_restante"] = out["status_temporal"]
    else:
        out["tempo_restante"] = out.apply(
            lambda r: lead_in_tempo_restante(
                r["status_temporal"],
                r["ts_start"],
                r["ts_end"],
                now,
            ),
            axis=1,
        )
    out["horario_reuniao"] = out["ts_start"].apply(
        lambda ts: ts.strftime("%H:%M") if pd.notna(ts) else "—"
    )
    out["data_reuniao_fmt"] = out["data_reuniao"].apply(
        lambda d: d.strftime("%d/%m/%Y") if d is not None and not pd.isna(d) else "—"
    )
    return out


def lead_in_ordenar_agenda(
    df: pd.DataFrame,
    now: datetime | None = None,
    *,
    modo_historico: bool = False,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    if modo_historico:
        out = df.copy()
        sort_cols = ["data_reuniao", "ts_start"] if "data_reuniao" in out.columns else ["ts_start"]
        return (
            out.sort_values(sort_cols, na_position="last")
            .reset_index(drop=True)
        )

    now = now or lead_in_agenda_now()
    out = df.copy()
    out["_agenda_sort"] = out.apply(lambda r: _lead_in_agenda_prioridade(r, now), axis=1)
    out = (
        out.sort_values("_agenda_sort", na_position="last")
        .drop(columns=["_agenda_sort"])
        .reset_index(drop=True)
    )
    return out


def lead_in_preparar_agenda(
    df: pd.DataFrame,
    data_ini: date,
    data_fim: date,
    ref_date: date | None = None,
    *,
    periodo_completo: bool = False,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, date | None, bool, datetime, bool, bool]:
    """Filtra o dia/período de foco e calcula status temporal + tempo restante.

    Retorna: agenda, ref_date, is_today, now, modo_historico, periodo_completo.
    """
    now = now or lead_in_agenda_now()
    today = now.date()
    modo_historico = not lead_in_agenda_periodo_inclui_hoje(data_ini, data_fim, today)
    periodo_completo = bool(periodo_completo and modo_historico)

    if modo_historico:
        if periodo_completo:
            ref_date = None
        else:
            datas_disp = lead_in_agenda_datas_disponiveis(df, data_ini, data_fim)
            if ref_date is None:
                ref_date = datas_disp[-1] if datas_disp else data_fim
        is_today = False
    else:
        ref_date = today
        is_today = True
        periodo_completo = False

    if df is None or df.empty:
        return pd.DataFrame(), ref_date, is_today, now, modo_historico, periodo_completo

    out = df.copy()
    if "data_reuniao" not in out.columns:
        return pd.DataFrame(), ref_date, is_today, now, modo_historico, periodo_completo

    out["data_reuniao"] = pd.to_datetime(out["data_reuniao"], errors="coerce").dt.date
    if periodo_completo:
        out = out[
            out["data_reuniao"].notna()
            & (out["data_reuniao"] >= data_ini)
            & (out["data_reuniao"] <= data_fim)
        ].copy()
    else:
        out = out[out["data_reuniao"] == ref_date].copy()
    if out.empty:
        return out, ref_date, is_today, now, modo_historico, periodo_completo

    out = _lead_in_enriquecer_agenda_linhas(out, now, modo_historico=modo_historico)
    out["status_temporal"] = out["status_temporal"].map(_lead_in_agenda_temporal_ui)
    agenda = lead_in_ordenar_agenda(out, now, modo_historico=modo_historico)
    return agenda, ref_date, is_today, now, modo_historico, periodo_completo


def lead_in_agenda_kpis(agenda: pd.DataFrame) -> dict:
    zeros = {
        "proxima_reuniao": "—",
        "proxima_linha1": "—",
        "proxima_closer": SEM_CLOSER_AGENDA,
        "proxima_tempo": "—",
        "restantes_hoje": 0,
        "em_andamento": 0,
        "aguardando": 0,
        "concluidas_hoje": 0,
        "canceladas_hoje": 0,
    }
    if agenda is None or agenda.empty:
        return zeros

    proximas = agenda[agenda["status_temporal"] == ST_TEMP_PROXIMA].sort_values("ts_start")
    if not proximas.empty:
        row = proximas.iloc[0]
        hora = row.get("horario_reuniao", "—")
        nome = row.get("nome_cliente") or "—"
        closer = row.get("closer")
        closer_s = (
            str(closer).strip()
            if closer is not None and not pd.isna(closer) and str(closer).strip()
            else SEM_CLOSER_AGENDA
        )
        if closer_s == SEM_CLOSER:
            closer_s = SEM_CLOSER_AGENDA
        tempo = str(row.get("tempo_restante") or "—").strip()
        zeros["proxima_reuniao"] = f"{hora} · {nome}"
        zeros["proxima_linha1"] = f"{hora} · {nome}"
        zeros["proxima_closer"] = closer_s
        zeros["proxima_tempo"] = tempo

    zeros["restantes_hoje"] = int((agenda["status_temporal"] == ST_TEMP_PROXIMA).sum())
    zeros["em_andamento"] = int((agenda["status_temporal"] == ST_TEMP_EM_ANDAMENTO).sum())
    zeros["aguardando"] = int((agenda["status_temporal"] == ST_TEMP_AGUARDANDO).sum())
    zeros["concluidas_hoje"] = int((agenda["status_temporal"] == ST_TEMP_CONCLUIDA).sum())
    zeros["canceladas_hoje"] = int((agenda["status_temporal"] == ST_TEMP_CANCELADA).sum())
    return zeros


def lead_in_agenda_kpis_historico(agenda: pd.DataFrame) -> dict:
    """Cards da agenda em modo histórico (contagens por bucket do CRM)."""
    zeros = {
        "total_dia": 0,
        "agendadas": 0,
        "realizadas": 0,
        "canceladas": 0,
        "reagendadas": 0,
        "outros": 0,
    }
    if agenda is None or agenda.empty:
        return zeros

    zeros["total_dia"] = len(agenda)
    bc = _lead_in_status_col(agenda)
    if bc not in agenda.columns:
        zeros["agendadas"] = int((agenda["status_temporal"] == ST_TEMP_AGUARDANDO).sum())
        zeros["realizadas"] = int((agenda["status_temporal"] == ST_TEMP_CONCLUIDA).sum())
        zeros["canceladas"] = int((agenda["status_temporal"] == ST_TEMP_CANCELADA).sum())
        zeros["reagendadas"] = 0
        return zeros

    zeros["agendadas"] = int((agenda[bc] == "Agendada").sum())
    zeros["realizadas"] = int((agenda[bc] == "Realizada").sum())
    zeros["canceladas"] = int((agenda[bc] == "Cancelada").sum())
    zeros["reagendadas"] = 0
    zeros["outros"] = int((agenda[bc] == "Outros").sum())
    return zeros


def lead_in_agenda_tabela(
    agenda: pd.DataFrame,
    *,
    modo_historico: bool = False,
    periodo_completo: bool = False,
) -> pd.DataFrame:
    if agenda is None or agenda.empty:
        return pd.DataFrame()

    if "pre_venda" not in agenda.columns and "pre_venda_identificada" in agenda.columns:
        agenda = agenda.copy()
        agenda["pre_venda"] = agenda["pre_venda_identificada"]

    cols = [
        *(
            ["data_reuniao_fmt"]
            if periodo_completo
            else []
        ),
        "horario_reuniao",
        *([] if modo_historico else ["tempo_restante"]),
        "nome_cliente",
        "closer",
        "pre_venda",
        "status_reuniao",
        "email",
        "telefone",
        "motivo_cancelamento",
    ]
    seen: set[str] = set()
    present: list[str] = []
    for c in cols:
        if c in agenda.columns and c not in seen:
            seen.add(c)
            present.append(c)
    return agenda[present].copy()


def lead_in_agenda_styler(
    display_df: pd.DataFrame,
    agenda_meta: pd.DataFrame,
    now: datetime | None = None,
):
    """Destaque visual por urgência operacional (pandas Styler)."""
    now = now or lead_in_agenda_now()
    n = min(len(display_df), len(agenda_meta))
    destaques = [
        _lead_in_agenda_destaque(agenda_meta.iloc[i], now)
        for i in range(n)
    ]

    def _row_style(row: pd.Series) -> list[str]:
        idx = row.name
        key = destaques[idx] if isinstance(idx, int) and idx < len(destaques) else ""
        css = AGENDA_STATUS_ROW_BG.get(key, "")
        return [css] * len(row)

    return display_df.style.apply(_row_style, axis=1)


def lead_in_agenda_por_hora(agenda: pd.DataFrame) -> pd.DataFrame:
    if agenda is None or agenda.empty:
        return pd.DataFrame()

    tmp = agenda.copy()
    tmp["hora"] = pd.to_datetime(tmp["ts_start"], errors="coerce").dt.floor("h")
    tmp = tmp.dropna(subset=["hora"])
    if tmp.empty:
        return pd.DataFrame()

    tmp["hora_label"] = tmp["hora"].dt.strftime("%H:%M")
    return (
        tmp.groupby(["hora_label", "status_temporal"], dropna=False)
        .size()
        .reset_index(name="qtd")
        .sort_values("hora_label")
        .reset_index(drop=True)
    )


def _lead_in_sort_hora_labels(labels: list[str]) -> list[str]:
    def _key(h: str) -> tuple:
        try:
            return (0, pd.Timestamp(f"2000-01-01 {h}").value)
        except Exception:
            return (1, h)

    return sorted(labels, key=_key)


def lead_in_agenda_por_hora_pivot(agenda: pd.DataFrame) -> pd.DataFrame:
    """Pivot hora × status_temporal para gráfico empilhado."""
    long_df = lead_in_agenda_por_hora(agenda)
    if long_df.empty:
        return pd.DataFrame()

    pivot = (
        long_df.pivot_table(
            index="hora_label",
            columns="status_temporal",
            values="qtd",
            aggfunc="sum",
            fill_value=0,
        )
    )
    chart_order = lead_in_agenda_chart_status_order()
    for status in chart_order:
        if status not in pivot.columns:
            pivot[status] = 0
    pivot = pivot[list(chart_order)]
    horas = _lead_in_sort_hora_labels(pivot.index.tolist())
    return pivot.reindex(horas).fillna(0).astype(int)


def lead_in_agenda_por_dia_pivot(agenda: pd.DataFrame) -> pd.DataFrame:
    """Pivot data × status_bucket (CRM) para gráfico do período completo."""
    if agenda is None or agenda.empty or "data_reuniao" not in agenda.columns:
        return pd.DataFrame()

    tmp = agenda.copy()
    bc = _lead_in_status_col(tmp)
    if bc not in tmp.columns:
        return pd.DataFrame()

    tmp["data_label"] = tmp["data_reuniao"].apply(
        lambda d: d.strftime("%d/%m/%Y") if d is not None and not pd.isna(d) else "—"
    )
    long_df = (
        tmp.groupby(["data_label", bc], dropna=False)
        .size()
        .reset_index(name="qtd")
        .rename(columns={bc: "status_bucket"})
    )
    if long_df.empty:
        return pd.DataFrame()

    pivot = (
        long_df.pivot_table(
            index="data_label",
            columns="status_bucket",
            values="qtd",
            aggfunc="sum",
            fill_value=0,
        )
    )
    bucket_order = lead_in_agenda_bucket_chart_order()
    for bucket in bucket_order:
        if bucket not in pivot.columns:
            pivot[bucket] = 0
    pivot = pivot[list(bucket_order)]

    def _sort_data_label(lbl: str) -> tuple:
        try:
            return (0, pd.Timestamp(lbl, dayfirst=True).value)
        except Exception:
            return (1, lbl)

    datas = sorted(pivot.index.tolist(), key=_sort_data_label)
    return pivot.reindex(datas).fillna(0).astype(int)


def lead_in_agenda_diagnostico(
    agenda: pd.DataFrame,
    now: datetime,
    ref_date: date,
    is_today: bool,
    *,
    modo_historico: bool = False,
    periodo_completo: bool = False,
) -> dict:
    base = {
        "now": now,
        "timezone": LEAD_IN_AGENDA_TZ,
        "ref_date": ref_date,
        "is_today": is_today,
        "modo_historico": modo_historico,
        "periodo_completo": periodo_completo,
        "duracao_padrao_min": LEAD_IN_DURACAO_PADRAO_MIN,
        "futuras": 0,
        "em_andamento": 0,
        "aguardando": 0,
        "finalizadas": 0,
        "total_dia": 0,
    }
    if agenda is None or agenda.empty:
        return base

    st = agenda["status_temporal"]
    base["total_dia"] = len(agenda)
    base["futuras"] = int((st == ST_TEMP_PROXIMA).sum())
    base["em_andamento"] = int((st == ST_TEMP_EM_ANDAMENTO).sum())
    base["aguardando"] = int((st == ST_TEMP_AGUARDANDO).sum())
    finalizados = (ST_TEMP_CONCLUIDA, ST_TEMP_CANCELADA)
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        finalizados = (*finalizados, ST_TEMP_REAGENDADA)
    base["finalizadas"] = int(st.isin(finalizados).sum())
    return base


def _bucket_pivot(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    bc = _lead_in_status_col(df)
    piv = (
        df.groupby([group_col, bc], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ("Agendada", "Realizada", "Cancelada", "Reagendada", "Outros"):
        if col not in piv.columns:
            piv[col] = 0
    piv = piv.rename(columns={
        "Agendada": "agendadas",
        "Realizada": "realizadas",
        "Cancelada": "canceladas",
        "Reagendada": "reagendadas",
        "Outros": "outros",
    })
    base = (
        piv["agendadas"] + piv["realizadas"] + piv["canceladas"] + piv["outros"]
    )
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        base = base + piv["reagendadas"]
    piv["pct_realizacao"] = [
        _safe_div(re, b) * 100
        for re, b in zip(piv["realizadas"], base)
    ]
    piv["pct_cancelamento"] = [
        _safe_div(ca, b) * 100
        for ca, b in zip(piv["canceladas"], base)
    ]
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        piv["pct_reagendamento"] = [
            _safe_div(rg, b) * 100
            for rg, b in zip(piv["reagendadas"], base)
        ]
    return piv


def lead_in_ranking_closer(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    rank = _bucket_pivot(df, "closer")
    rank = rank.sort_values(
        ["realizadas", "agendadas"],
        ascending=[False, False],
    ).reset_index(drop=True)
    return rank.rename(columns={"closer": "Closer"})


def lead_in_ranking_pre(df: pd.DataFrame) -> pd.DataFrame:
    """Ranking por pré — apenas consultas com qualificação (campo prevendas)."""
    if df is None or df.empty:
        return pd.DataFrame()

    sub = df[df["tipo_qualificacao"] == TIPO_COM_PRE].copy()
    if sub.empty:
        return pd.DataFrame()

    rank = _bucket_pivot(sub, "pre_venda")
    if "outros" not in rank.columns:
        rank["outros"] = 0
    rank["qualificadas"] = (
        rank["agendadas"] + rank["realizadas"] + rank["canceladas"] + rank["outros"]
        + (rank["reagendadas"] if LEAD_IN_EXIBIR_REAGENDAMENTO else 0)
    )
    rank["pct_realizacao"] = rank.apply(
        lambda r: _safe_div(r["realizadas"], r["qualificadas"]) * 100,
        axis=1,
    )
    rank = rank.drop(
        columns=["pct_cancelamento", "pct_reagendamento", "agendadas"],
        errors="ignore",
    )
    rank = rank.sort_values(
        ["qualificadas", "realizadas"],
        ascending=[False, False],
    ).reset_index(drop=True)
    return rank.rename(columns={"pre_venda": "Pré-venda"})


def lead_in_churn_preparar(
    df_churn: pd.DataFrame,
    df_deal_pre: pd.DataFrame | None,
    df_pre_oficiais: pd.DataFrame | None,
    df_email_sdr: pd.DataFrame | None,
) -> pd.DataFrame:
    """Enriquece churns com cascata de pré (mesma regra das consultas)."""
    if df_churn is None or df_churn.empty:
        return pd.DataFrame()

    tmp = df_churn.copy()
    if df_deal_pre is not None and not df_deal_pre.empty:
        pre_map = df_deal_pre.drop_duplicates("deal_id")
        cols = ["deal_id"] + [
            c for c in ("prevendas_raw", "deal_sdr_nome") if c in pre_map.columns
        ]
        tmp = tmp.merge(pre_map[cols], on="deal_id", how="left")

    if "email" in tmp.columns:
        tmp["email_norm"] = (
            tmp["email"]
            .astype(str)
            .str.strip()
            .str.lower()
            .replace({"nan": "", "none": ""})
        )
    if "ts_churn" in tmp.columns:
        tmp["ts_reuniao"] = tmp["ts_churn"]
    elif "data_churn" in tmp.columns:
        tmp["ts_reuniao"] = tmp["data_churn"]
    tmp["status_reuniao"] = ""
    if "prevendas_raw" not in tmp.columns:
        tmp["prevendas_raw"] = pd.NA

    return lead_in_aplicar_pre(tmp, df_pre_oficiais, df_email_sdr)


def lead_in_churn_agregar_por_pre(df_churn_pre: pd.DataFrame) -> pd.DataFrame:
    if df_churn_pre is None or df_churn_pre.empty:
        return pd.DataFrame(columns=["pre_venda", "churn"])
    return (
        df_churn_pre.groupby("pre_venda_identificada", as_index=False)
        .agg(churn=("deal_id", "nunique"))
        .rename(columns={"pre_venda_identificada": "pre_venda"})
        .sort_values("churn", ascending=False)
        .reset_index(drop=True)
    )


def lead_in_ranking_closer_com_churn(
    df: pd.DataFrame,
    df_churn_period: pd.DataFrame,
    df_oficiais: pd.DataFrame | None,
) -> pd.DataFrame:
    """Ranking por closer + clientes cancelados (stage Churn)."""
    rank = lead_in_ranking_closer(df)
    churn_agg = executivas_churn_agregar_por_executiva(df_churn_period, df_oficiais)

    if rank.empty and (churn_agg is None or churn_agg.empty):
        return pd.DataFrame()

    if rank.empty:
        out = churn_agg.rename(columns={"executiva": "Closer"})
        for col in (
            "agendadas", "realizadas", "canceladas", "reagendadas",
            "pct_realizacao", "pct_cancelamento", "pct_reagendamento",
        ):
            out[col] = 0
    else:
        out = rank.copy()
        out["churn"] = out["Closer"].apply(
            lambda c: executivas_churn_contagem_para_executiva(c, churn_agg)
        )
        if churn_agg is not None and not churn_agg.empty:
            for _, row in churn_agg.iterrows():
                nom = str(row["executiva"])
                if int(row["churn"] or 0) <= 0:
                    continue
                if any(
                    _executivas_churn_nomes_casam(str(ex), nom)
                    for ex in out["Closer"]
                ):
                    continue
                extra = {c: 0 for c in out.columns}
                extra["Closer"] = nom
                extra["churn"] = int(row["churn"])
                out = pd.concat([out, pd.DataFrame([extra])], ignore_index=True)

    cols = ["Closer", "agendadas", "realizadas", "canceladas", "churn", "pct_realizacao", "pct_cancelamento"]
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        cols = [
            "Closer", "agendadas", "realizadas", "canceladas", "reagendadas",
            "churn", "pct_realizacao", "pct_cancelamento", "pct_reagendamento",
        ]
    out = out[[c for c in cols if c in out.columns]]
    if not out.empty and "realizadas" in out.columns:
        out = out.sort_values("realizadas", ascending=False).reset_index(drop=True)
    return out


def lead_in_ranking_pre_com_churn(
    df: pd.DataFrame,
    df_churn_period: pd.DataFrame,
    df_pre_oficiais: pd.DataFrame | None,
    df_email_sdr: pd.DataFrame | None,
    df_deal_pre: pd.DataFrame | None,
) -> pd.DataFrame:
    """Ranking por pré (qualificadas) + clientes cancelados por cascata."""
    rank = lead_in_ranking_pre(df)
    churn_pre = lead_in_churn_preparar(
        df_churn_period, df_deal_pre, df_pre_oficiais, df_email_sdr,
    )
    churn_agg = lead_in_churn_agregar_por_pre(churn_pre)

    if rank.empty and (churn_agg is None or churn_agg.empty):
        return pd.DataFrame()

    pre_col = "Pré-venda" if "Pré-venda" in rank.columns else "pre_venda"

    if rank.empty:
        out = churn_agg.rename(columns={"pre_venda": pre_col})
        for col in ("qualificadas", "realizadas", "canceladas", "reagendadas"):
            out[col] = 0
        out["pct_realizacao"] = 0.0
    else:
        out = rank.copy()
        churn_map = {
            str(row["pre_venda"]): int(row["churn"] or 0)
            for _, row in churn_agg.iterrows()
        }
        out["churn"] = out[pre_col].astype(str).map(churn_map).fillna(0).astype(int)
        if churn_agg is not None and not churn_agg.empty:
            existentes = set(out[pre_col].astype(str))
            for _, row in churn_agg.iterrows():
                nom = str(row["pre_venda"])
                if int(row["churn"] or 0) <= 0 or nom in existentes:
                    continue
                extra = {c: 0 for c in out.columns}
                extra[pre_col] = nom
                extra["churn"] = int(row["churn"])
                if "qualificadas" in out.columns:
                    extra["qualificadas"] = 0
                out = pd.concat([out, pd.DataFrame([extra])], ignore_index=True)

    cols = [pre_col, "qualificadas", "realizadas", "canceladas", "churn", "pct_realizacao"]
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        cols.insert(5, "reagendadas")
    out = out[[c for c in cols if c in out.columns]]
    if not out.empty and "qualificadas" in out.columns:
        out = out.sort_values("qualificadas", ascending=False).reset_index(drop=True)
    return out


LEAD_IN_RESUMO_TOTAL = "Total"

LEAD_IN_RESUMO_TOTAL_ROW_CSS = (
    "background-color: rgba(255, 255, 255, 0.07); "
    "font-weight: bold; "
    "border-top: 1px solid rgba(255, 255, 255, 0.18);"
)

_CLOSER_DISPLAY_RENAME = {
    "agendadas": "Agendadas",
    "realizadas": "Realizadas",
    "canceladas": "Canceladas",
    "reagendadas": "Reagendadas",
    "churn": "Clientes canc.",
    "pct_realizacao": "% realização",
    "pct_cancelamento": "% cancelamento",
    "pct_reagendamento": "% reagendamento",
}

_PRE_DISPLAY_RENAME = {
    "qualificadas": "Qualificadas",
    "realizadas": "Realizadas",
    "canceladas": "Canceladas",
    "reagendadas": "Reagendadas",
    "churn": "Clientes canc.",
    "pct_realizacao": "% realização",
}

LEAD_IN_CHURN_COL_LABEL = "Clientes canc."
LEAD_IN_CHURN_COL_HELP = "Clientes em stage = Churn (distinto de reuniões canceladas)"


def _lead_in_resumo_total_row(
    df: pd.DataFrame,
    label_col: str,
    sum_cols: tuple[str, ...],
) -> dict:
    """Monta dict da linha Total (soma das colunas de contagem)."""
    row: dict = {label_col: LEAD_IN_RESUMO_TOTAL}
    for col in sum_cols:
        if col in df.columns:
            row[col] = int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return row


def lead_in_resumo_closer_exibir(rank: pd.DataFrame) -> pd.DataFrame:
    """Tabela Por closer: ordenação + linha Total + rótulos de exibição."""
    if rank is None or rank.empty:
        return pd.DataFrame()

    body = rank.sort_values("realizadas", ascending=False).reset_index(drop=True)
    bucket_cols = ("agendadas", "realizadas", "canceladas")
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        bucket_cols = (*bucket_cols, "reagendadas")
    total = _lead_in_resumo_total_row(body, "Closer", (*bucket_cols, "churn"))
    den = sum(total.get(c, 0) for c in bucket_cols)
    total["pct_realizacao"] = _safe_div(total.get("realizadas", 0), den) * 100
    total["pct_cancelamento"] = _safe_div(total.get("canceladas", 0), den) * 100
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        total["pct_reagendamento"] = _safe_div(total.get("reagendadas", 0), den) * 100

    out = pd.concat([body, pd.DataFrame([total])], ignore_index=True)
    rename = {
        k: v for k, v in _CLOSER_DISPLAY_RENAME.items()
        if k in out.columns
    }
    return out.rename(columns=rename)


def lead_in_resumo_pre_exibir(rank: pd.DataFrame) -> pd.DataFrame:
    """Tabela Por pré: ordenação + linha Total + rótulos de exibição."""
    if rank is None or rank.empty:
        return pd.DataFrame()

    pre_col = "Pré-venda" if "Pré-venda" in rank.columns else "pre_venda"
    body = rank.sort_values("qualificadas", ascending=False).reset_index(drop=True)
    sum_cols: tuple[str, ...] = ("qualificadas", "realizadas", "canceladas", "churn")
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        sum_cols = ("qualificadas", "realizadas", "canceladas", "reagendadas", "churn")
    total = _lead_in_resumo_total_row(body, pre_col, sum_cols)
    total["pct_realizacao"] = (
        _safe_div(total.get("realizadas", 0), total.get("qualificadas", 0)) * 100
    )
    out = pd.concat([body, pd.DataFrame([total])], ignore_index=True)
    rename = {k: v for k, v in _PRE_DISPLAY_RENAME.items() if k in out.columns}
    return out.rename(columns=rename)


def lead_in_resumo_styler(display_df: pd.DataFrame, label_col: str):
    """Destaque visual da linha Total (negrito + fundo + borda superior)."""
    if display_df is None or display_df.empty or label_col not in display_df.columns:
        return display_df

    def _row_style(row: pd.Series) -> list[str]:
        if str(row.get(label_col, "")).strip() == LEAD_IN_RESUMO_TOTAL:
            return [LEAD_IN_RESUMO_TOTAL_ROW_CSS] * len(row)
        return [""] * len(row)

    return display_df.style.apply(_row_style, axis=1)


def lead_in_churn_diagnostico(
    df_churn_period: pd.DataFrame,
    df_churn_pre: pd.DataFrame,
    churn_por_executiva: pd.DataFrame,
    churn_por_pre: pd.DataFrame,
) -> dict:
    """Totais de clientes cancelados para o expander de diagnóstico."""
    total = executivas_churn_total(df_churn_period)
    por_closer = (
        int(churn_por_executiva["churn"].sum())
        if churn_por_executiva is not None and not churn_por_executiva.empty
        else 0
    )
    por_pre = (
        int(churn_por_pre["churn"].sum())
        if churn_por_pre is not None and not churn_por_pre.empty
        else 0
    )
    sem_pre = 0
    if churn_por_pre is not None and not churn_por_pre.empty:
        mask = churn_por_pre["pre_venda"].astype(str) == SEM_PRE_IDENTIFICADA
        sem_pre = int(churn_por_pre.loc[mask, "churn"].sum())

    fonte_dist = pd.DataFrame()
    if df_churn_pre is not None and not df_churn_pre.empty and "fonte_pre_venda" in df_churn_pre.columns:
        fonte_dist = (
            df_churn_pre["fonte_pre_venda"]
            .value_counts()
            .rename_axis("fonte_pre_venda")
            .reset_index(name="qtd_deals")
        )

    return {
        "total": total,
        "por_closer_soma": por_closer,
        "por_pre_soma": por_pre,
        "sem_pre_identificada": sem_pre,
        "churn_por_executiva": churn_por_executiva,
        "churn_por_pre": churn_por_pre,
        "fonte_pre_dist": fonte_dist,
    }


_SORT_DATE_COLS = (
    "ts_reuniao",
    "data_reuniao",
    "start_datetime",
    "data_criacao_agendamento",
    "created_time",
    "dt_reuniao",
)


def _lead_in_ts_reuniao_series(df: pd.DataFrame) -> pd.Series:
    """Timestamp da reunião com fallback entre colunas da query."""
    for col in _SORT_DATE_COLS:
        if col in df.columns:
            return pd.to_datetime(df[col], errors="coerce")
    return pd.Series(pd.NaT, index=df.index)


def lead_in_tabela_detalhe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    bc = _lead_in_status_col(out)
    ts = _lead_in_ts_reuniao_series(out)
    finais = ("Realizada", "Cancelada")
    if LEAD_IN_EXIBIR_REAGENDAMENTO:
        finais = (*finais, "Reagendada")
    out["data_realizacao_ou_cancelamento"] = ts.where(
        out[bc].isin(finais),
        pd.NaT,
    )
    if "status_bucket_painel" in out.columns:
        out["status_bucket"] = out["status_bucket_painel"]
    cols = [
        "data_reuniao",
        "nome_cliente",
        "email",
        "telefone",
        "deal_id",
        "closer",
        "pre_venda_identificada",
        "fonte_pre_venda",
        "data_vinculo_pre",
        "status_reuniao",
        "status_bucket",
        "tipo_qualificacao",
        "motivo_cancelamento",
        "data_criacao_agendamento",
        "data_realizacao_ou_cancelamento",
        "activity_id",
    ]
    seen: set[str] = set()
    present: list[str] = []
    for c in cols:
        if c in out.columns and c not in seen:
            seen.add(c)
            present.append(c)
    result = out[present].copy()
    result = result.loc[:, ~result.columns.duplicated()].copy()

    sort_col = next((c for c in _SORT_DATE_COLS if c in result.columns), None)
    if sort_col:
        return result.sort_values(
            sort_col,
            ascending=False,
            na_position="last",
        ).reset_index(drop=True)
    return result.reset_index(drop=True)


def _amostra_diag(df: pd.DataFrame, mask: pd.Series, n: int = 25) -> pd.DataFrame:
    cols = [
        "activity_id", "deal_id", "data_reuniao", "status_reuniao", "status_bucket",
        "email", "email_norm", "prevendas_raw",
        "pre_venda_identificada", "fonte_pre_venda", "data_vinculo_pre",
        "tipo_pre_diagnostico", "tipo_qualificacao", "pre_cadastro_match",
        "deal_sdr_nome", "closer",
    ]
    sub = df.loc[mask, [c for c in cols if c in df.columns]]
    return sub.head(n).reset_index(drop=True)


def lead_in_audit_pre_cadastro(
    df: pd.DataFrame,
    df_pre: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Auditoria `activity.prevendas` × cadastro oficial.

    Retorna (todos os valores distintos, sem match, cadastro não visto no CRM).
    """
    official_names = _official_pre_names(df_pre)
    empty = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    if df is None or df.empty:
        return empty

    sub = df[df["tem_prevendas_campo"]].copy()
    if sub.empty:
        nao_usados = pd.DataFrame({"nome_cadastro": official_names})
        return pd.DataFrame(), pd.DataFrame(), nao_usados

    rows: list[dict] = []
    for raw, g in sub.groupby("prevendas_raw", dropna=False):
        raw_s = str(raw).strip() if raw is not None and not pd.isna(raw) else ""
        canonical = _canonical_official_name(raw_s, official_names) if raw_s else ""
        rows.append({
            "prevendas_crm": raw_s or "(vazio)",
            "qtd": len(g),
            "match_cadastro": "Sim" if canonical else "Não",
            "nome_cadastro": canonical or "—",
        })
    audit = (
        pd.DataFrame(rows)
        .sort_values(["match_cadastro", "qtd"], ascending=[True, False])
        .reset_index(drop=True)
    )
    sem_match = audit[audit["match_cadastro"] == "Não"].reset_index(drop=True)

    usados = {
        str(n).strip()
        for n in audit.loc[audit["match_cadastro"] == "Sim", "nome_cadastro"]
        if str(n).strip() and str(n).strip() != "—"
    }
    nao_usados = pd.DataFrame({
        "nome_cadastro": [n for n in official_names if n not in usados],
    })
    return audit, sem_match, nao_usados


def lead_in_matriz_pre_tiers(df: pd.DataFrame) -> pd.DataFrame:
    """Matriz status × 3 tiers de pré (proposta p/ validação)."""
    tiers = (TIPO_PRE_COM_MATCH, TIPO_PRE_SEM_MATCH, SEM_PRE_IDENTIFICADA)
    rows = []
    for status in ("Agendada", "Realizada", "Cancelada", "Reagendada", "Outros"):
        sub = df[df["status_bucket"] == status] if df is not None and not df.empty else pd.DataFrame()
        counts = {
            t: int((sub["tipo_pre_diagnostico"] == t).sum()) if not sub.empty else 0
            for t in tiers
        }
        label = status if status != "Outros" else "Outros (diagnóstico)"
        rows.append({
            "Status da reunião": label,
            TIPO_PRE_COM_MATCH: counts[TIPO_PRE_COM_MATCH],
            TIPO_PRE_SEM_MATCH: counts[TIPO_PRE_SEM_MATCH],
            SEM_PRE_IDENTIFICADA: counts[SEM_PRE_IDENTIFICADA],
            "Total": sum(counts.values()),
        })
    return pd.DataFrame(rows)


def lead_in_diagnostico(df: pd.DataFrame, df_pre: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {
            "total_consultas": 0,
            "com_qualificacao_pre": 0,
            "sem_qualificacao_pre": 0,
            "com_pre_campo": 0,
            "sem_pre_campo": 0,
            "com_cadastro_match": 0,
            "pre_com_match": 0,
            "pre_sem_match": 0,
            "sem_pre_identificada": 0,
            "com_email": 0,
            "sdr_via_activity": 0,
            "sdr_via_email": 0,
            "sdr_via_deal_ss": 0,
            "sem_sdr": 0,
            "fonte_pre_venda_dist": pd.DataFrame(),
            "pct_ruido_pre": 0.0,
            "alerta_ruido_pre": False,
            "status_dist": pd.DataFrame(),
            "status_outros": pd.DataFrame(),
            "fonte_pre_dist": pd.DataFrame(),
            "tipo_pre_dist": pd.DataFrame(),
            "audit_pre": pd.DataFrame(),
            "pre_sem_match_vals": pd.DataFrame(),
            "cadastro_nao_usado": pd.DataFrame(),
            "amostra_com_pre": pd.DataFrame(),
            "amostra_sem_pre": pd.DataFrame(),
            "amostra_sem_sdr": pd.DataFrame(),
            "matriz_pre_tiers": pd.DataFrame(),
            "cadastro_ok": False,
            "n_cadastro": 0,
        }

    com_qual = int((df["tipo_qualificacao"] == TIPO_COM_PRE).sum())
    sem_qual = int((df["tipo_qualificacao"] == TIPO_SEM_PRE).sum())
    com_campo = int(df["tem_prevendas_campo"].sum())
    com_match = int(df["pre_cadastro_match"].sum())
    sem_match = int((df["tipo_pre_diagnostico"] == TIPO_PRE_SEM_MATCH).sum())
    sem_pre_id = int((df["pre_venda_identificada"] == SEM_PRE_IDENTIFICADA).sum())
    pct_ruido = _safe_div(sem_match, com_qual) * 100 if com_qual else 0.0

    status_dist = (
        df.assign(status_reuniao_crm=df["status_reuniao"].fillna("(nulo)"))
        .groupby(["status_reuniao_crm", "status_bucket"], dropna=False)
        .size()
        .reset_index(name="qtd")
        .rename(columns={"status_bucket": "bucket_painel"})
        .sort_values("qtd", ascending=False)
        .reset_index(drop=True)
    )

    outros = df[df["status_bucket"] == "Outros"].copy()
    if not outros.empty:
        status_outros = (
            outros.assign(
                rotulo_diag=outros["status_reuniao"].apply(lead_in_status_outros_rotulo),
            )
            .groupby(["status_reuniao", "rotulo_diag"], dropna=False)
            .size()
            .reset_index(name="qtd")
            .sort_values("qtd", ascending=False)
        )
    else:
        status_outros = pd.DataFrame()

    audit, pre_sem_match_vals, cadastro_nao_usado = lead_in_audit_pre_cadastro(df, df_pre)

    fonte_col = "fonte_pre_venda" if "fonte_pre_venda" in df.columns else "fonte_pre"
    sem_sdr_mask = df["pre_venda_identificada"] == SEM_PRE_IDENTIFICADA

    return {
        "total_consultas": len(df),
        "com_qualificacao_pre": com_qual,
        "sem_qualificacao_pre": sem_qual,
        "com_pre_campo": com_campo,
        "sem_pre_campo": int((~df["tem_prevendas_campo"]).sum()),
        "com_cadastro_match": com_match,
        "pre_com_match": int((df["tipo_pre_diagnostico"] == TIPO_PRE_COM_MATCH).sum()),
        "pre_sem_match": sem_match,
        "sem_pre_identificada": sem_pre_id,
        "com_email": int(df["tem_email_encontrado"].sum()) if "tem_email_encontrado" in df.columns else 0,
        "sdr_via_activity": int((df[fonte_col] == FONTE_PRE_ACTIVITY).sum()),
        "sdr_via_email": int((df[fonte_col] == FONTE_PRE_LEAD_SLA).sum()),
        "sdr_via_deal_ss": int((df[fonte_col] == FONTE_PRE_DEAL_SDR).sum()),
        "sem_sdr": int(sem_sdr_mask.sum()),
        "pct_ruido_pre": pct_ruido,
        "alerta_ruido_pre": pct_ruido >= _RUIDO_PRE_LIMIAR_PCT and sem_match > 0,
        "status_dist": status_dist,
        "status_outros": status_outros,
        "fonte_pre_dist": (
            df["fonte_pre"]
            .value_counts()
            .rename_axis("fonte")
            .reset_index(name="qtd")
        ),
        "fonte_pre_venda_dist": (
            df[fonte_col]
            .value_counts()
            .rename_axis("fonte_pre_venda")
            .reset_index(name="qtd")
        ),
        "tipo_pre_dist": (
            df["tipo_pre_diagnostico"]
            .value_counts()
            .rename_axis("categoria_pre")
            .reset_index(name="qtd")
        ),
        "audit_pre": audit,
        "pre_sem_match_vals": pre_sem_match_vals,
        "cadastro_nao_usado": cadastro_nao_usado,
        "amostra_com_pre": _amostra_diag(df, df["tipo_qualificacao"] == TIPO_COM_PRE),
        "amostra_sem_pre": _amostra_diag(df, df["tipo_qualificacao"] == TIPO_SEM_PRE),
        "amostra_sem_sdr": _amostra_diag(df, sem_sdr_mask),
        "matriz_pre_tiers": lead_in_matriz_pre_tiers(df),
        "cadastro_ok": df_pre is not None and not df_pre.empty,
        "n_cadastro": len(df_pre) if df_pre is not None and not df_pre.empty else 0,
    }
