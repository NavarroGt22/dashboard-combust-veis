"""Painel ANP. Execute: streamlit run app.py

The app reads filtered Parquet columns; it never opens source CSVs on reruns.
Caches are bounded and invalidated by the catalogue/Parquet modification times.
"""
from pathlib import Path
import html
import json
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from fuel_dashboard.logic import (Filters, MONTHS, UF_IBGE, open_dataset, predicate,
                                  query_table, summarize, monthly_changes,
                                  chart_segments, election_comparison, plotly_geojson, default_years)


ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("FUEL_DATASET_DIR", ROOT / "data/processed/registros"))
CATALOG = Path(os.environ.get("FUEL_CATALOG_PATH", ROOT / "data/processed/catalogo.json"))
COLORS = ["#38d5c8", "#48b9ee", "#727ef8", "#ffad66", "#e576aa", "#84d095", "#bc9af0"]
BASE_URL_PATH = st.get_option("server.baseUrlPath").strip("/")
TOPOJSON_URL = f"/{BASE_URL_PATH + '/' if BASE_URL_PATH else ''}app/static/"
CONFIG = {"displayModeBar": "hover", "responsive": True, "locale": "pt-BR", "modeBarButtonsToRemove": ["select2d", "lasso2d"], "topojsonURL": TOPOJSON_URL}


def number(value, decimals=0):
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def signature():
    files = list(DATA.rglob("*.parquet")) if DATA.exists() else []
    if CATALOG.exists():
        files.append(CATALOG)
    return tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files))


@st.cache_data(max_entries=2, show_spinner=False)
def catalog(version):
    values = json.loads(CATALOG.read_text(encoding="utf-8-sig")) if CATALOG.exists() else {}
    dataset = open_dataset(DATA)
    if not values.get("anos"):
        values["anos"] = sorted(dataset.to_table(columns=["ano"]).column("ano").unique().to_pylist())
    if not values.get("produtos"):
        values["produtos"] = sorted(dataset.to_table(columns=["produto"]).column("produto").unique().to_pylist())
    if not values.get("meses_por_ano"):
        coverage = dataset.to_table(columns=["ano", "mes"]).to_pandas().drop_duplicates()
        values["meses_por_ano"] = {str(int(year)): sorted(int(month) for month in rows["mes"].unique())
                                  for year, rows in coverage.groupby("ano", observed=True)}
    return values


@st.cache_data(max_entries=6, show_spinner=False)
def facets(version, filters):
    table = query_table(DATA, filters, ["regiao", "uf", "municipio"])
    frame = table.to_pandas()
    return frame.drop_duplicates(ignore_index=True)


@st.cache_data(max_entries=5, show_spinner=False)
def load_summary(version, filters):
    table = query_table(DATA, filters, ["ano", "mes", "regiao", "uf", "municipio", "preco_venda", "posto_id"])
    frame = table.to_pandas()
    for column in ("regiao", "uf"):
        frame[column] = frame[column].astype("category")
    return summarize(frame)


DETAIL_COLUMNS = ["data_coleta", "produto", "regiao", "uf", "municipio", "revenda", "cnpj", "bandeira", "preco_venda", "unidade"]


@st.cache_data(max_entries=8, show_spinner=False)
def detail_page(version, filters, search, page, page_size):
    dataset = open_dataset(DATA)
    expression = predicate(filters, search, dataset.schema.names)
    total = dataset.count_rows(filter=expression)
    columns = [c for c in DETAIL_COLUMNS if c in dataset.schema.names]
    table = dataset.scanner(columns=columns, filter=expression).head((page + 1) * page_size).slice(page * page_size, page_size)
    return total, table.to_pandas()


@st.cache_data(max_entries=1, show_spinner=False)
def export_csv(version, filters, search):
    dataset = open_dataset(DATA)
    columns = [c for c in DETAIL_COLUMNS if c in dataset.schema.names]
    frame = query_table(DATA, filters, columns, search).to_pandas()
    return frame.to_csv(index=False, sep=";", decimal=",", date_format="%d/%m/%Y").encode("utf-8-sig")


def polish(fig, height=340, money=True):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Segoe UI, Arial, sans-serif", size=11, color="#9fb8cc"),
                      colorway=COLORS, height=height, margin=dict(l=12, r=15, t=15, b=15),
                      legend=dict(orientation="h", y=1.12, x=0, title_text="", font_size=10),
                      hoverlabel=dict(bgcolor="#173247", font_color="#eaf3fc"), separators=",.",
                      modebar_remove=["select2d", "lasso2d"], hovermode="closest")
    fig.update_xaxes(showgrid=False, zeroline=False, title_text=None)
    fig.update_yaxes(gridcolor="#193346", zeroline=False, title_text=None, tickprefix="R$ " if money else "", tickformat=".2f" if money else ",d")
    return fig


def chart(fig, key, height=340, money=True):
    st.plotly_chart(polish(fig, height, money), width="stretch", config=CONFIG, key=key)


def card(label, value, note):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{html.escape(label)}</div><div class="metric-value">{html.escape(value)}</div><div class="metric-note">{html.escape(note)}</div></div>', unsafe_allow_html=True)


def show_overview(summary, filters, unit):
    kpi = summary["kpis"]
    columns = st.columns(6)
    definitions = [("Preço médio", f"R$ {number(kpi['media'], 2)}", f"Média por observação · {unit}"),
                   ("Menor preço", f"R$ {number(kpi['minimo'], 2)}", "Mínimo observado no recorte"),
                   ("Maior preço", f"R$ {number(kpi['maximo'], 2)}", "Máximo observado no recorte"),
                   ("Registros", number(kpi["registros"]), "Observações válidas de preço"),
                   ("Postos identificáveis", number(kpi["postos"]), "IDs distintos no recorte"),
                   ("Variação entre extremos", f"{number(kpi['variacao_pct'], 2)}%" if kpi["variacao_pct"] is not None else "—", f"{kpi['inicio']} → {kpi['fim']} · médias mensais")]
    for column, definition in zip(columns, definitions):
        with column:
            card(*definition)
    states = summary["estados"].sort_values("preco_medio")
    low, high = states.iloc[0], states.iloc[-1]
    st.markdown(f'<div class="insight-row"><div class="insight">MENOR MÉDIA UF &nbsp; <strong>{html.escape(str(low["uf"]))} · R$ {number(low["preco_medio"],2)}</strong></div><div class="insight">MAIOR MÉDIA UF &nbsp; <strong>{html.escape(str(high["uf"]))} · R$ {number(high["preco_medio"],2)}</strong></div><div class="insight">UNIDADE &nbsp; <strong>{unit}</strong> · preços nominais</div></div>', unsafe_allow_html=True)
    monthly = summary["mensal"]
    left, right = st.columns([1.8, 1])
    with left, st.container(border=True):
        st.subheader("Evolução mensal")
        st.caption("Média das observações · lacunas não são conectadas")
        lines = chart_segments(monthly)
        fig = px.line(lines, x="periodo", y="preco_medio", color="ano_rotulo", line_group="segmento", markers=True,
                      color_discrete_sequence=COLORS, labels={"ano_rotulo": "Ano", "preco_medio": f"Preço médio ({unit})", "periodo": "Mês"},
                      hover_data={"registros": ":,", "segmento": False})
        fig.update_traces(line_width=2.5, marker_size=6, connectgaps=False)
        fig.update_xaxes(tickformat="%b\n%Y")
        chart(fig, "trend", 350)
    with right, st.container(border=True):
        st.subheader("Média por ano")
        st.caption("Somente os meses selecionados · média ponderada pelos registros")
        annual = summary["anual"].assign(ano_rotulo=lambda d: d["ano"].astype(str))
        fig = px.bar(annual, x="ano_rotulo", y="preco_medio", text="preco_medio", color="ano_rotulo",
                     color_discrete_sequence=COLORS, labels={"ano_rotulo": "Ano", "preco_medio": f"Preço médio ({unit})"}, hover_data=["registros"])
        fig.update_traces(texttemplate="R$ %{y:.2f}", textposition="outside", cliponaxis=False, marker_line_width=0)
        fig.update_layout(showlegend=False, bargap=.45)
        fig.update_yaxes(range=[0, annual["preco_medio"].max() * 1.22])
        chart(fig, "annual", 350)
    left, right = st.columns([1.45, 1])
    with left, st.container(border=True):
        st.subheader("Variação mês a mês")
        st.caption("Apenas pares de meses consecutivos, dentro de cada ano")
        changes = monthly_changes(monthly)
        if changes.empty:
            st.info("Selecione ao menos dois meses consecutivos com dados no mesmo ano.")
        else:
            changes["periodo"] = pd.to_datetime(dict(year=changes["ano"], month=changes["mes"], day=1))
            fig = go.Figure(go.Bar(x=changes["periodo"], y=changes["variacao_pct"], marker_color=np.where(changes["variacao_pct"] < 0, COLORS[0], COLORS[3]),
                                  hovertemplate="%{x|%m/%Y}<br>Variação: %{y:.2f}%<extra></extra>"))
            fig.update_xaxes(tickformat="%m/%Y")
            polish(fig, 300, False)
            fig.update_yaxes(ticksuffix="%", tickformat=".1f", zeroline=True, zerolinecolor="#4d687d")
            st.plotly_chart(fig, width="stretch", config=CONFIG, key="month_changes")
    with right, st.container(border=True):
        st.subheader("Distribuição dos preços")
        st.caption("Histograma de todas as observações filtradas · 40 intervalos")
        histogram = summary["histograma"]
        fig = go.Figure(go.Bar(x=(histogram["de"] + histogram["ate"]) / 2, y=histogram["registros"],
                              width=(histogram["ate"] - histogram["de"]) * .96, marker_color=COLORS[1],
                              customdata=histogram[["de", "ate"]], hovertemplate="R$ %{customdata[0]:.2f} a %{customdata[1]:.2f}<br>%{y:,} registros<extra></extra>"))
        fig.update_layout(bargap=.02)
        fig.update_xaxes(tickprefix="R$ ", tickformat=".2f")
        chart(fig, "distribution", 300, False)


def show_geography(summary, unit):
    states = summary["estados"].sort_values("preco_medio", ascending=True).copy()
    left, right = st.columns([1.4, 1])
    with left, st.container(border=True):
        st.subheader("Ranking dos estados")
        st.caption("Preço médio no recorte · todas as UFs disponíveis na seleção")
        fig = px.bar(states, y="uf", x="preco_medio", orientation="h", text="preco_medio", color="preco_medio",
                     color_continuous_scale=["#1a7495", "#38d5c8"], hover_data=["registros", "postos"],
                     labels={"uf": "UF", "preco_medio": f"Preço médio ({unit})"})
        fig.update_traces(texttemplate="R$ %{x:.2f}", textposition="outside", cliponaxis=False)
        fig.update_layout(coloraxis_showscale=False, showlegend=False)
        fig.update_xaxes(range=[0, states["preco_medio"].max() * 1.25], tickprefix="R$ ")
        polish(fig, max(360, len(states) * 23), False)
        fig.update_yaxes(type="category", categoryorder="array", categoryarray=states["uf"].tolist())
        st.plotly_chart(fig, width="stretch", config=CONFIG, key="ranking")
    with right:
        with st.container(border=True):
            st.subheader("Médias por região")
            st.caption("Observações agrupadas por região")
            regions = summary["regioes"].sort_values("preco_medio", ascending=False)
            fig = px.bar(regions, x="regiao", y="preco_medio", text="preco_medio", color="regiao", color_discrete_sequence=COLORS,
                         hover_data=["registros"], labels={"regiao": "Região", "preco_medio": f"Preço médio ({unit})"})
            fig.update_layout(showlegend=False)
            fig.update_traces(texttemplate="R$ %{y:.2f}", textposition="outside", cliponaxis=False)
            fig.update_yaxes(range=[0, regions["preco_medio"].max() * 1.25])
            chart(fig, "regions", 320)
        map_path = ROOT / "assets/brasil_uf.geojson"
        if map_path.exists():
            with st.container(border=True):
                st.subheader("Panorama territorial")
                st.caption("UFs sem dados no recorte permanecem sem cor")
                geometry = plotly_geojson(json.loads(map_path.read_text(encoding="utf-8")))
                states["codigo"] = states["uf"].map(UF_IBGE)
                fig = px.choropleth(states, geojson=geometry, locations="codigo", featureidkey="properties.codarea", color="preco_medio",
                                    hover_name="uf", hover_data={"codigo": False, "registros": ":,", "preco_medio": ":.2f"},
                                    color_continuous_scale=["#165a80", "#32b7bd", "#86e9ce"], labels={"preco_medio": f"{unit}"})
                fig.update_geos(fitbounds="geojson", visible=False, bgcolor="rgba(0,0,0,0)", projection_type="mercator")
                fig.update_traces(marker_line_color="#071321", marker_line_width=.7)
                fig.update_layout(coloraxis_colorbar=dict(thickness=10, len=.7, title=unit))
                chart(fig, "map", 330)


def show_elections(summary, filters, unit, values):
    st.subheader("Julho a outubro: comparação descritiva")
    st.caption("Anos eleitorais presidenciais de 2018 e 2022 e anos de controle disponíveis. Todos os filtros laterais continuam aplicados.")
    for year in (2018, 2022):
        available_months = set(int(month) for month in values["meses_por_ano"].get(str(year), []))
        unavailable = [month for month in (7, 8, 9, 10) if month not in available_months]
        if unavailable:
            st.warning(f"Cobertura do acervo em {year}: sem observações em " + ", ".join(MONTHS[month].lower() for month in unavailable) + ". Meses ausentes não são estimados ou imputados.")
    st.info("Diferenças de preços não identificam efeito causal de eleições. Tributação, petróleo, câmbio, cobertura da amostra e outras condições podem mudar ao mesmo tempo.")
    years = sorted(set(filters.years) | {2018, 2022})
    comparison = election_comparison(summary["mensal"], years, filters.months)
    outside = ~comparison["ano"].isin(filters.years)
    comparison.loc[outside, "situacao"] = "Ano fora do filtro lateral"
    comparison.loc[outside, ["julho", "outubro", "variacao_abs", "variacao_pct"]] = np.nan
    available = comparison.loc[comparison["situacao"].eq("Disponível")]
    if not available.empty:
        long = available.melt(id_vars=["ano", "tipo"], value_vars=["julho", "outubro"], var_name="mes", value_name="preco_medio")
        long["ano"] = long["ano"].astype(str)
        long["mes"] = long["mes"].map({"julho": "Julho", "outubro": "Outubro"})
        fig = px.bar(long, x="ano", y="preco_medio", color="mes", barmode="group", text="preco_medio",
                     color_discrete_sequence=[COLORS[1], COLORS[0]], labels={"preco_medio": f"Preço médio ({unit})", "mes": "Mês", "ano": "Ano"}, hover_data=["tipo"])
        fig.update_traces(texttemplate="R$ %{y:.2f}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(range=[0, long["preco_medio"].max() * 1.23])
        chart(fig, "elections", 380)
    else:
        st.info("Para visualizar a comparação, selecione julho e outubro e ao menos um ano com observações em ambos os meses.")
    st.markdown("#### Médias mensais dos anos eleitorais")
    electoral_months = summary["mensal"].loc[summary["mensal"]["ano"].isin([2018, 2022]) & summary["mensal"]["mes"].isin([7, 8, 9, 10])]
    if electoral_months.empty:
        electoral_months = pd.DataFrame(index=pd.Index([2018, 2022], name="ano"), columns=[7, 8, 9, 10], dtype=float)
    else:
        electoral_months = electoral_months.pivot(index="ano", columns="mes", values="preco_medio").reindex(index=[2018, 2022], columns=[7, 8, 9, 10])
    electoral_months = electoral_months.reset_index()
    electoral_months.columns = ["ano", "julho", "agosto", "setembro", "outubro"]
    st.dataframe(electoral_months, hide_index=True, width="stretch", column_config={
        "ano": st.column_config.NumberColumn("Ano", format="%d"), **{
            name: st.column_config.NumberColumn(f"{name.capitalize()} ({unit})", format="%.3f")
            for name in ("julho", "agosto", "setembro", "outubro")}})
    st.caption("Médias de cada mês com os mesmos filtros laterais. Células vazias indicam ausência de dados ou mês/ano fora da seleção.")
    st.markdown("#### Variação de julho a outubro")
    price_columns = ["ano", "tipo", "julho", "outubro", "variacao_abs", "variacao_pct", "situacao"]
    st.dataframe(comparison[price_columns], hide_index=True, width="stretch", column_config={
        "ano": st.column_config.NumberColumn("Ano", format="%d"), "tipo": "Classificação", "julho": st.column_config.NumberColumn(f"Julho ({unit})", format="%.3f"),
        "outubro": st.column_config.NumberColumn(f"Outubro ({unit})", format="%.3f"), "variacao_abs": st.column_config.NumberColumn(f"Δ absoluto ({unit})", format="%.3f"),
        "variacao_pct": st.column_config.NumberColumn("Δ relativo (%)", format="%.2f"), "situacao": "Disponibilidade"})
    st.caption("Δ absoluto = média de outubro − média de julho. Δ relativo = (média de outubro ÷ média de julho − 1) × 100. Mesmos filtros geográficos e de produto; composição dos postos pode variar.")
    st.markdown("#### A amostra também muda entre os meses")
    st.caption("Compare registros, postos identificáveis e municípios (UF + nome) antes de interpretar a mudança dos preços. A média não representa um painel fixo dos mesmos postos.")
    sample_columns = ["ano", "registros_julho", "registros_outubro", "postos_julho", "postos_outubro", "municipios_julho", "municipios_outubro"]
    sample = comparison[sample_columns].copy()
    sample["variacao_registros_pct"] = (sample["registros_outubro"] / sample["registros_julho"] - 1) * 100
    st.dataframe(sample, hide_index=True, width="stretch", column_config={
        "ano": st.column_config.NumberColumn("Ano", format="%d"), "registros_julho": "Registros · jul", "registros_outubro": "Registros · out",
        "postos_julho": "Postos · jul", "postos_outubro": "Postos · out", "municipios_julho": "Municípios · jul", "municipios_outubro": "Municípios · out",
        "variacao_registros_pct": st.column_config.NumberColumn("Δ registros (%)", format="%.2f")})


def show_detail(version, filters, unit):
    st.subheader("Observações do recorte")
    st.caption("Busca textual em revenda, município, CNPJ ou bandeira. A tabela mostra uma página; a exportação inclui todas as linhas da seleção e da busca.")
    search = st.text_input("Buscar nas observações", placeholder="Ex.: Salvador, nome do posto ou CNPJ", key="detail_search")
    page_size = st.selectbox("Linhas por página", [25, 50, 100], index=0)
    total, _ = detail_page(version, filters, search, 0, 1)
    pages = max(1, (total + page_size - 1) // page_size)
    query_key = (filters, search, page_size)
    if st.session_state.get("detail_query") != query_key:
        st.session_state["detail_query"] = query_key
        st.session_state["detail_page"] = 1
    page = st.number_input("Página", min_value=1, max_value=pages, step=1, key="detail_page")
    _, frame = detail_page(version, filters, search, int(page) - 1, page_size)
    st.caption(f"{number(total)} registros encontrados · página {page} de {number(pages)} · ordem dos arquivos tratados")
    st.dataframe(frame, hide_index=True, width="stretch", column_config={"data_coleta": st.column_config.DateColumn("Coleta", format="DD/MM/YYYY"),
                  "produto": "Produto", "regiao": "Região", "uf": "UF", "municipio": "Município", "revenda": "Revenda", "cnpj": "CNPJ",
                  "bandeira": "Bandeira", "preco_venda": st.column_config.NumberColumn(f"Preço ({unit})", format="%.3f"), "unidade": "Unidade"})
    st.caption("CSV: UTF-8 com BOM, separador ponto e vírgula e vírgula decimal. Não há limite de linhas na exportação.")
    if st.button("Preparar CSV completo", disabled=total == 0, type="primary"):
        with st.spinner("Preparando todas as observações filtradas…"):
            content = export_csv(version, filters, search)
        st.download_button("Baixar CSV completo", content, file_name=f"combustiveis_{filters.product.lower().replace(' ', '_')}.csv", mime="text/csv", on_click="ignore")


def show_methodology(values, filters, summary):
    st.subheader("Cobertura, qualidade e método")
    st.markdown("Os valores apresentados são **preços de venda nominais**, coletados pela ANP. Cada observação tem o mesmo peso. A média do período é calculada diretamente sobre os registros, sem usar média simples das médias mensais. Não há ponderação por volume vendido, população ou número de postos.")
    st.markdown("**Unidades:** gasolina, etanol e diesel em R$/L; GNV em R$/m³. A seleção de um único produto evita misturar unidades. Postos identificáveis são IDs distintos não vazios; uma coleta repetida do mesmo posto conta como nova observação, mas não como novo posto.")
    st.markdown("**Comparabilidade:** os anos podem ter meses ou municípios ausentes. Uma mudança de média pode refletir alteração da cobertura e da composição da amostra. As médias anuais usam somente os meses selecionados. Variações mês a mês exigem meses consecutivos no mesmo ano. Pontos ausentes não são conectados nem imputados.")
    st.markdown("**Variação entre extremos:** compara a média do primeiro mês disponível à do último mês disponível no recorte. Com vários anos, é uma diferença entre esses dois pontos temporais; não é a variação de uma média anual.")
    st.markdown("**Tratamento:** leitura dos arquivos locais, padronização de datas, UFs, regiões e produtos; preços numéricos positivos; rejeições e duplicatas registradas no relatório. A identidade de um posto depende dos campos identificadores disponíveis, descritos no relatório de qualidade.")
    st.markdown("**Fonte:** arquivos CSV da pesquisa de preços de revenda da ANP presentes no acervo local. A origem e a cobertura constam do catálogo e do relatório de qualidade. O painel usa as cópias tratadas em Parquet e não atualiza a fonte pela internet.")
    st.markdown("#### Cobertura efetiva do recorte atual")
    coverage = summary["mensal"][["ano", "mes", "registros", "postos", "municipios"]].copy()
    coverage["mes"] = coverage["mes"].map(MONTHS)
    st.dataframe(coverage, hide_index=True, width="stretch", column_config={"ano": st.column_config.NumberColumn("Ano", format="%d"), "mes": "Mês", "registros": "Registros", "postos": "Postos identificáveis", "municipios": "Municípios (UF + nome)"})
    st.markdown("#### Arquivos de auditoria")
    candidates = list((ROOT / "data/processed").glob("*qualidade*.json")) + list((ROOT / "outputs").rglob("*qualidade*.json"))
    if candidates:
        path = candidates[0]
        with st.expander("Ver relatório de qualidade completo"):
            try:
                report = json.loads(path.read_text(encoding="utf-8-sig"))
                st.json(report, expanded=False)
                st.download_button("Baixar relatório de qualidade", path.read_bytes(), file_name=path.name, mime="application/json")
            except (ValueError, OSError):
                st.caption("O relatório não pôde ser lido. Consulte os arquivos de auditoria do projeto.")
    else:
        st.caption("O relatório detalhado acompanha os arquivos de dados tratados. A tabela acima verifica a cobertura do recorte diretamente nos registros carregados.")
    with st.expander("Ver catálogo de cobertura dos arquivos"):
        st.json(values, expanded=False)


def main():
    st.set_page_config(page_title="Combustíveis | Observatório ANP", page_icon="⛽", layout="wide", initial_sidebar_state="auto")
    st.markdown(f"<style>{(ROOT / 'assets/style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    st.markdown('<div class="hero"><div><div class="eyebrow">Inteligência de preços · Brasil</div><h1>Observatório de combustíveis</h1><p>Explore preços de revenda, diferenças territoriais e evolução no tempo.</p></div><div class="hero-badge">● &nbsp; Dados locais · ANP</div></div>', unsafe_allow_html=True)
    version = signature()
    if not any(item[0].endswith(".parquet") for item in version):
        st.info("Os dados tratados ainda não estão disponíveis. Execute `python scripts/preparar_dados.py` na pasta do projeto e recarregue o painel.")
        st.code("python scripts/preparar_dados.py\nstreamlit run app.py", language="bash")
        st.stop()
    try:
        values = catalog(version)
    except Exception as exc:
        st.error("Não foi possível ler os dados tratados. Confira o catálogo e execute novamente o processamento.")
        with st.expander("Detalhes técnicos"):
            st.code(str(exc))
        st.stop()
    years = sorted(int(y) for y in values["anos"])
    products = sorted(values["produtos"])
    with st.sidebar:
        st.markdown('<div class="brand">combustíveis<span>.</span></div><div class="brand-sub">Observatório de preços ANP</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-label">Defina o recorte</div>', unsafe_allow_html=True)
        initial_years = default_years(years, values["meses_por_ano"])
        selected_years = st.multiselect("Anos", years, default=initial_years, key="years_coverage_" + "_".join(map(str, initial_years)))
        selected_months = st.multiselect("Meses", list(MONTHS), default=[7, 8, 9, 10], format_func=lambda x: MONTHS[x], key="months")
        product = st.selectbox("Combustível", products, index=products.index("GASOLINA COMUM") if "GASOLINA COMUM" in products else 0)
        unit = "R$/m³" if product == "GNV" else "R$/L"
        st.caption(f"Unidade de preço: {unit}")
        if not selected_years or not selected_months:
            st.info("Selecione ao menos um ano e um mês para consultar os dados.")
            st.stop()
        base = Filters(tuple(sorted(selected_years)), tuple(sorted(selected_months)), product)
        with st.spinner("Atualizando localidades…"):
            geography = facets(version, base)
        regions = st.multiselect("Regiões", sorted(geography["regiao"].dropna().unique()), placeholder="Todas as regiões")
        if regions:
            geography = geography.loc[geography["regiao"].isin(regions)]
        ufs = st.multiselect("Estados (UF)", sorted(geography["uf"].dropna().unique()), placeholder="Todos os estados")
        if ufs:
            geography = geography.loc[geography["uf"].isin(ufs)]
        municipality_options = sorted(geography[["uf", "municipio"]].dropna().drop_duplicates().itertuples(index=False, name=None), key=lambda pair: (pair[1], pair[0]))
        municipalities = st.multiselect("Municípios", municipality_options, format_func=lambda pair: f"{pair[1]} · {pair[0]}", placeholder="Todos os municípios", key="municipalities_by_uf")
        st.caption("Região, UF e município em branco incluem todas as localidades disponíveis. Os filtros se combinam.")
        st.divider()
        st.caption("Recorte inicial: julho a outubro. Todos os meses e produtos dos arquivos permanecem disponíveis.")
        coverage_labels = []
        for year in years:
            months = sorted(int(month) for month in values["meses_por_ano"].get(str(year), []))
            label = "sem meses registrados"
            if months:
                label = f"{MONTHS[months[0]][:3].lower()}–{MONTHS[months[-1]][:3].lower()}" if len(months) > 1 and months == list(range(months[0], months[-1] + 1)) else ", ".join(MONTHS[month][:3].lower() for month in months)
            coverage_labels.append(f"{year}: {label}")
        st.caption("Cobertura do acervo: " + "; ".join(coverage_labels) + ". Ausência de dados nunca equivale a preço zero.")
    filters = Filters(base.years, base.months, product, tuple(regions), tuple(ufs), tuple(municipalities))
    chips = [product, unit, "Anos: " + ", ".join(map(str, filters.years)), "Meses: " + ", ".join(MONTHS[m][:3] for m in filters.months)]
    if regions or ufs or municipalities:
        chips.extend(regions + ufs + [f"{municipality} · {uf}" for uf, municipality in municipalities])
    else:
        chips.append("Brasil · localidades disponíveis")
    st.markdown('<div class="filter-strip">' + "".join(f'<span class="chip">{html.escape(v)}</span>' for v in chips) + "</div>", unsafe_allow_html=True)
    with st.spinner("Calculando o recorte selecionado…"):
        summary = load_summary(version, filters)
    present_years = set(summary["mensal"]["ano"].tolist())
    missing_years = set(filters.years) - present_years
    if missing_years:
        st.warning("Sem observações no recorte para: " + ", ".join(map(str, sorted(missing_years))) + ". Esses anos não entram nas médias ou nos gráficos.")
    if summary["kpis"]["registros"] == 0:
        st.info("Nenhuma observação corresponde aos filtros. Amplie os meses, selecione outro ano ou remova filtros geográficos. Consulte a cobertura do acervo na barra lateral.")
        show_elections(summary, filters, unit, values)
        show_methodology(values, filters, summary)
        st.stop()
    st.caption("Médias nominais por observação · sem ponderação por volume ou população · somente o período selecionado")
    overview, geography_tab, election_tab, table_tab, quality_tab = st.tabs(["Visão geral", "Território", "Eleições e controles", "Dados detalhados", "Qualidade e método"])
    with overview:
        show_overview(summary, filters, unit)
    with geography_tab:
        show_geography(summary, unit)
    with election_tab:
        show_elections(summary, filters, unit, values)
    with table_tab:
        show_detail(version, filters, unit)
    with quality_tab:
        show_methodology(values, filters, summary)
    st.caption("Fonte: pesquisa de preços de revenda da ANP · acervo local · atualização conforme catálogo de cobertura")


if __name__ == "__main__":
    main()
