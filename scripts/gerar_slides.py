#!/usr/bin/env python
"""Gera dez slides PowerPoint editáveis a partir dos resumos do ETL.

Uso, na raiz do projeto:
    python scripts/gerar_slides.py
    python scripts/gerar_slides.py --produto "ETANOL"

Os gráficos são objetos nativos do PowerPoint, com planilhas incorporadas.
Não usa valores salvos no notebook nem substitui ausência por zero.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
NAVY = "0B1527"
CYAN = "31D1F4"
TEAL = "28CCAD"
ORANGE = "FFAD5B"
WHITE = "F4F7FC"
MUTED = "B3C2D9"
GRID = "33445D"
PANEL = "12243B"
FONT = "Aptos"
MONTHS = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
          7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"}
COLORS = [CYAN, TEAL, ORANGE, "B2A3FF", "7FA6D8", "EF80AB"]
NUMERIC = {"ano", "mes", "ano_eleitoral", "preco_medio", "preco_mediano",
           "preco_minimo", "preco_maximo", "registros", "postos", "municipios",
           "municipios_painel", "variacao_desde_julho_pct", "preco_julho",
           "preco_outubro", "variacao_absoluta", "variacao_percentual"}


def load_csv(path: Path, required: bool = True) -> list[dict]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Execute primeiro o ETL. Arquivo ausente: {path}")
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in NUMERIC.intersection(row):
            raw = row[key]
            if raw is None or not str(raw).strip():
                row[key] = None
            else:
                val = float(raw)
                row[key] = val if math.isfinite(val) else None
    return rows


def br(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "sem dados"
    return f"{value:,.{digits}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "sem comparação"
    prefix = "+" if signed and value > 0 else ""
    return prefix + br(value, 1) + "%"


def change(start: float | None, end: float | None) -> float | None:
    return None if start in (None, 0) or end is None else (end / start - 1) * 100


def weighted(rows: list[dict], col: str = "preco_medio") -> float | None:
    valid = [r for r in rows if r.get(col) is not None and r.get("registros", 0)]
    n = sum(r["registros"] for r in valid)
    return sum(r[col] * r["registros"] for r in valid) / n if n else None


def coverage_gaps(rows: list[dict], years: list[int], months: list[int]) -> dict[int, list[int]]:
    """Ausência depende das linhas disponíveis, nunca de uma regra fixa por ano."""
    present = defaultdict(set)
    for row in rows:
        present[int(row["ano"])].add(int(row["mes"]))
    return {year: missing for year in years
            if (missing := [month for month in months if month not in present[year]])}


def coverage_description(gaps: dict[int, list[int]], total_years: int) -> str:
    if gaps:
        missing = "; ".join(f"{year} ({', '.join(MONTHS[m] for m in months)})"
                            for year, months in gaps.items())
        return f"Meses sem dados no recorte: {missing}.\nAusências permanecem vazias e não entram nas médias."
    return (f"Os {total_years} anos apresentados cobrem os quatro meses do recorte.\n"
            "A tabela registra observações, com composição de postos e municípios variável.")


def election_summary(monthly: list[dict], panel_rows: list[dict], product: str, year: int) -> dict:
    """Exige os dois meses de referência, sem substituir ou preencher endpoints."""
    observations = {int(r["mes"]): r for r in monthly
                    if r["produto"] == product and int(r["ano"]) == year and 7 <= int(r["mes"]) <= 10}
    panel = {int(r["mes"]): r for r in panel_rows
             if r["produto"] == product and int(r["ano"]) == year}
    july, october = observations.get(7), observations.get(10)
    complete = july is not None and october is not None
    return {
        "year": year, "observations": observations, "july": july, "october": october,
        "mean_change": change(july["preco_medio"], october["preco_medio"]) if complete else None,
        "median_change": change(july.get("preco_mediano"), october.get("preco_mediano")) if complete else None,
        "records_change": change(july["registros"], october["registros"]) if complete else None,
        "panel_change": change(panel[7]["preco_medio"], panel[10]["preco_medio"]) if 7 in panel and 10 in panel else None,
    }


def grouped(rows: list[dict], field: str) -> list[tuple[str, float, int]]:
    buckets = defaultdict(list)
    for row in rows:
        buckets[str(row[field])].append(row)
    return sorted([(key, weighted(items), int(sum(r["registros"] for r in items)))
                   for key, items in buckets.items()], key=lambda x: x[1], reverse=True)


def rgb(color: str) -> RGBColor:
    return RGBColor.from_string(color)


def text(slide, value: str, x: float, y: float, w: float, h: float,
         size: float = 20, color: str = WHITE, bold: bool = False,
         align=PP_ALIGN.LEFT, name: str | None = None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        box.name = name
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0)
    tf.margin_top = tf.margin_bottom = Inches(0)
    for i, line in enumerate(value.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.name = FONT
        p.font.size = Pt(size)
        p.font.color.rgb = rgb(color)
        p.font.bold = bold
        p.alignment = align
        p.space_after = Pt(5)
    return box


def add_slide(prs, title: str, subtitle: str | None = None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(NAVY)
    text(slide, title, .6, .35, 12.1, .85, 32, bold=True, name="Titulo")
    if subtitle:
        text(slide, subtitle, .62, 1.18, 12, .55, 18, MUTED, name="Subtitulo")
    return slide


def footer(slide, page: int, note: str = "Fonte: dados tratados a partir dos arquivos do projeto."):
    text(slide, note, .62, 7.00, 11.4, .38, 11, MUTED, name="Fonte")
    text(slide, f"{page:02}", 12.08, 6.99, .6, .32, 12, MUTED, align=PP_ALIGN.RIGHT,
         name="Numero do slide")


def notes(slide, message: str):
    slide.notes_slide.notes_text_frame.text = message


def fill_xml(parent, color: str):
    sp = parent.find("{http://schemas.openxmlformats.org/drawingml/2006/chart}spPr")
    if sp is None:
        sp = OxmlElement("c:spPr")
        parent.append(sp)
    solid = OxmlElement("a:solidFill")
    col = OxmlElement("a:srgbClr")
    col.set("val", color)
    solid.append(col)
    sp.append(solid)
    line = OxmlElement("a:ln")
    line.append(OxmlElement("a:noFill"))
    sp.append(line)


def chart(slide, kind, categories, series, x, y, w, h, *, money=True,
          legend=True, labels=False, palette=None, min_scale=None, max_scale=None):
    data = CategoryChartData()
    data.categories = categories
    for label, values in series:
        data.add_series(label, [None if v is None else float(v) for v in values])
    obj = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data)
    ch = obj.chart
    obj.name = "Grafico editavel " + str(len(slide.shapes))
    ch.has_title = False
    ch.has_legend = legend
    fill_xml(ch._chartSpace, NAVY)
    fill_xml(ch._chartSpace.chart.plotArea, NAVY)
    blanks = ch._chartSpace.chart.find("{http://schemas.openxmlformats.org/drawingml/2006/chart}dispBlanksAs")
    if blanks is None:
        blanks = OxmlElement("c:dispBlanksAs")
        ch._chartSpace.chart.append(blanks)
    blanks.set("val", "gap")
    if legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.name = FONT
        ch.legend.font.size = Pt(16)
        ch.legend.font.color.rgb = rgb(WHITE)
    for axis in (ch.category_axis, ch.value_axis):
        axis.tick_labels.font.name = FONT
        axis.tick_labels.font.size = Pt(16)
        axis.tick_labels.font.color.rgb = rgb(MUTED)
        axis.format.line.color.rgb = rgb(GRID)
        axis.has_major_gridlines = False
    ch.value_axis.has_major_gridlines = True
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb(GRID)
    ch.value_axis.tick_labels.number_format = '0.00' if money else '#,##0'
    if min_scale is not None:
        ch.value_axis.minimum_scale = min_scale
    if max_scale is not None:
        ch.value_axis.maximum_scale = max_scale
    palette = palette or COLORS
    for i, ser in enumerate(ch.series):
        color = palette[i % len(palette)]
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = rgb(color)
        ser.format.line.color.rgb = rgb(color)
        ser.format.line.width = Pt(2.5)
        if kind == XL_CHART_TYPE.LINE_MARKERS:
            ser.marker.size = 7
            ser.marker.format.fill.solid()
            ser.marker.format.fill.fore_color.rgb = rgb(color)
            ser.marker.format.line.color.rgb = rgb(color)
            ser.smooth = False
    if labels:
        plot = ch.plots[0]
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        dl.font.name = FONT
        dl.font.size = Pt(16)
        dl.font.color.rgb = rgb(WHITE)
        dl.number_format = '0.00' if money else '#,##0'
    return ch


def table(slide, headers, rows, x, y, w, h, widths=None, font=18):
    shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(x), Inches(y),
                                   Inches(w), Inches(h))
    shape.name = "Tabela editavel"
    tab = shape.table
    if widths:
        for col, width in zip(tab.columns, widths):
            col.width = Inches(width)
    for r, values in enumerate([headers] + rows):
        for c, value in enumerate(values):
            cell = tab.cell(r, c)
            cell.text = str(value)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(PANEL if r == 0 else NAVY)
            cell.margin_left = Inches(.13)
            cell.margin_right = Inches(.1)
            cell.margin_top = Inches(.07)
            cell.margin_bottom = Inches(.06)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for p in cell.text_frame.paragraphs:
                p.font.name = FONT
                p.font.size = Pt(font)
                p.font.bold = r == 0
                p.font.color.rgb = rgb(CYAN if r == 0 else WHITE)
    return shape


def metric(slide, label, value, x, y, w=5.7, color=CYAN, detail=None):
    text(slide, label, x, y, w, .45, 19, MUTED)
    text(slide, value, x, y + .48, w, .85, 40, color, True)
    if detail:
        text(slide, detail, x, y + 1.37, w, .65, 18, MUTED)


def build(args):
    dataset = args.dados.resolve()
    quality = {}
    if args.qualidade.exists():
        quality = json.loads(args.qualidade.read_text(encoding="utf-8-sig"))
        if quality.get("reconciliacao_ok") is False:
            raise ValueError("O relatório de qualidade indica falha de reconciliação. Revise o ETL antes dos slides.")
    monthly_all = load_csv(dataset / "resumo_mensal_brasil.csv")
    monthly = [r for r in monthly_all if r["produto"] == args.produto and int(r["mes"]) in args.meses]
    if not monthly:
        available = sorted({r["produto"] for r in monthly_all})
        raise ValueError(f"Recorte sem dados para {args.produto}. Produtos: {available}")
    unit_values = {r.get("unidade", "R$/L") for r in monthly}
    if len(unit_values) != 1:
        raise ValueError("O recorte mistura unidades. Gere uma apresentação por produto/unidade.")
    unit = next(iter(unit_values))
    years = sorted({int(r["ano"]) for r in monthly})
    all_years = sorted({int(r["ano"]) for r in monthly_all})
    year_groups = defaultdict(list)
    for row in monthly:
        year_groups[int(row["ano"])].append(row)
    annual = {year: weighted(items) for year, items in year_groups.items()}
    regions = [r for r in load_csv(dataset / "resumo_mensal_regiao.csv")
               if r["produto"] == args.produto and int(r["mes"]) in args.meses]
    states = [r for r in load_csv(dataset / "resumo_mensal_estado.csv")
              if r["produto"] == args.produto and int(r["mes"]) in args.meses]
    region_rank = grouped(regions, "regiao")
    state_rank = grouped(states, "uf")
    annual_records = int(sum(r["registros"] for r in monthly))
    average = weighted(monthly)
    low = min(r["preco_minimo"] for r in monthly)
    high = max(r["preco_maximo"] for r in monthly)
    short_product = args.produto.capitalize()
    if args.produto == "GASOLINA COMUM":
        short_product = "Gasolina comum"
    month_label = ", ".join(MONTHS[m].lower() for m in args.meses)
    scope = f"{short_product}, julho a outubro. Preços nominais em {unit}"
    product_rows = [r for r in monthly_all if r["produto"] == args.produto]
    gaps = coverage_gaps(product_rows, all_years, args.meses)
    panel_rows = load_csv(dataset / "painel_balanceado_municipios.csv", False)
    elections = [election_summary(monthly_all, panel_rows, args.produto, year) for year in (2018, 2022)]
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Preços de combustíveis no Brasil"
    prs.core_properties.subject = "Análise descritiva dos arquivos fornecidos, com cobertura e limites explícitos"
    prs.core_properties.author = "Projeto de análise de combustíveis"

    # 1. Minimal cover.
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(NAVY)
    text(s, "Preços de combustíveis\nno Brasil", .8, 1.25, 11.7, 2.1, 48, WHITE, True)
    text(s, f"{short_product}\nComparação de julho a outubro", .84, 3.65, 11.1, 1.2, 26, CYAN)
    text(s, "Análise das bases processadas pelo projeto\nPreços nominais e amostra observada", .84, 5.3, 11.1, .9, 20, MUTED)
    footer(s, 1)
    notes(s, "Fonte: outputs/datasets/resumo_mensal_brasil.csv. O recorte inicial é julho a outubro. A apresentação usa preços de venda observados, sem atribuição causal política. Os anos sem meses no recorte não entram nas médias.")

    # 2. Context and interpretation.
    s = add_slide(prs, "O que esta análise compara", scope)
    text(s, "Como o preço observado muda\nentre meses, anos e localidades", .7, 2.03, 6.5, 1.5, 32, WHITE, True)
    text(s, "Cada linha válida é uma observação de preço.\nA média dá o mesmo peso a cada observação.", .72, 4.0, 6.4, 1.3, 23, MUTED)
    table(s, ["Recorte", "Leitura"], [
        ["Produto", short_product],
        ["Meses", month_label.capitalize()],
        ["Anos com dados", ", ".join(map(str, years))],
        ["Valor", f"Nominal, em {unit}"],
    ], 7.5, 2.0, 5.1, 3.9, widths=[1.9, 3.2], font=18)
    text(s, "Os arquivos descrevem a amostra pesquisada. A média não usa as quantidades vendidas como peso.", .72, 6.12, 11.8, .7, 19, ORANGE)
    footer(s, 2)
    notes(s, "Fonte: resumos mensais. Método: média aritmética de preco_venda dos registros válidos. Agregações dos resumos mensais usam o número de registros como peso, reproduzindo a média das observações. Não há ponderação por volume vendido, população ou desenho amostral.")

    # 3. Method and source audit.
    source_count = len(quality.get("fontes", []))
    source_subtitle = f"{source_count} arquivos de origem e processamento reproduzível" if source_count else "Arquivos de origem e processamento reproduzível"
    s = add_slide(prs, "Fontes e método", source_subtitle)
    max_months = defaultdict(set)
    for r in monthly_all:
        if r["produto"] == args.produto:
            max_months[int(r["ano"])].add(int(r["mes"]))
    audit_rows = [[str(yr), ", ".join(MONTHS[m] for m in sorted(max_months[yr])),
                   str(len(max_months[yr].intersection(args.meses)))] for yr in all_years]
    table(s, ["Ano", "Meses disponíveis", "Meses no recorte"], audit_rows,
          .7, 1.95, 11.9, 3.0, widths=[1.25, 7.5, 3.15], font=18)
    text(s, "Leitura e padronização dos arquivos. Validação de datas, preços e UF.\nDeduplicação e resumos por produto, mês e localidade.", .75, 5.35, 11.8, 1.0, 21, WHITE)
    if "total_rejeitadas" in quality and "total_duplicatas_removidas" in quality:
        audit_note = f"Todos os produtos: {br(quality['total_rejeitadas'], 0)} linhas rejeitadas e {br(quality['total_duplicatas_removidas'], 0)} duplicatas removidas."
    else:
        audit_note = "O processamento mantém um relatório de qualidade e a identificação do arquivo de origem."
    text(s, audit_note, .75, 6.43, 11.8, .45, 18, MUTED)
    footer(s, 3)
    source_urls = [str(source[key]) for source in quality.get("fontes", [])
                   for key in ("url", "fonte_url", "origem_url", "url_origem") if source.get(key)]
    source_urls.extend(str(source["proveniencia_externa"]["url_oficial"])
                       for source in quality.get("fontes", [])
                       if source.get("proveniencia_externa", {}).get("url_oficial"))
    provenance = " URLs de origem: " + "; ".join(dict.fromkeys(source_urls)) if source_urls else ""
    notes(s, "Fontes: data/raw, data/processed/relatorio_qualidade.json e outputs/datasets/resumo_mensal_brasil.csv. Este quadro considera a disponibilidade do produto selecionado. O notebook serve como referência metodológica. Não foram reutilizados resultados históricos salvos no notebook." + provenance)

    # 4. KPIs. All extrema are individual valid observations.
    s = add_slide(prs, "Indicadores do recorte", scope)
    metric(s, "Preço médio observado", f"R$ {br(average)}", .8, 2.0,
           detail=f"Média das observações, em {unit}")
    metric(s, "Observações válidas", br(annual_records, 0), 7.0, 2.0, color=TEAL,
           detail=f"{len(years)} anos com dados nos meses selecionados")
    metric(s, "Menor preço observado", f"R$ {br(low)}", .8, 4.7,
           detail=f"Extremo de registro individual, em {unit}")
    metric(s, "Maior preço observado", f"R$ {br(high)}", 7.0, 4.7, color=ORANGE,
           detail=f"Extremo de registro individual, em {unit}")
    footer(s, 4, "Fonte: resumos do ETL. Médias ponderadas pelo número de registros de cada mês.")
    notes(s, f"Fonte: outputs/datasets/resumo_mensal_brasil.csv. Produto: {args.produto}. Meses: {args.meses}. Média nacional do recorte = soma(preco_medio_mensal × registros)/soma(registros). Menor e maior preço = extremos dos registros válidos, não extremos das médias. Total de registros: {annual_records}.")

    # 5. Historical year-over-year within the same month window.
    s = add_slide(prs, "Preços mensais por ano", "Cada linha compara os mesmos meses. Lacunas preservam a ausência de dados.")
    data_series = []
    for yr in years:
        lookup = {int(r["mes"]): r["preco_medio"] for r in year_groups[yr]}
        data_series.append((str(yr), [lookup.get(m) for m in args.meses]))
    vals = [v for _, values in data_series for v in values if v is not None]
    lower = max(0, math.floor((min(vals) - .35) * 2) / 2)
    upper = math.ceil((max(vals) + .35) * 2) / 2
    chart(s, XL_CHART_TYPE.LINE_MARKERS, [MONTHS[m] for m in args.meses], data_series,
          .72, 1.95, 11.9, 4.65, min_scale=lower, max_scale=upper)
    text(s, f"Preço médio em {unit}. O eixo começa em {br(lower, 1)} para facilitar a comparação mensal.", .8, 6.57, 11.7, .35, 16, MUTED)
    footer(s, 5)
    notes(s, "Fonte: outputs/datasets/resumo_mensal_brasil.csv. Gráfico nativo editável. Cada série representa um ano e cada ponto é a média das observações do mês. Ausências permanecem vazias. Preços nominais. O eixo vertical tem início explicitamente indicado no slide.")

    # 6. Regional and state comparison.
    s = add_slide(prs, "Comparação entre regiões e estados", scope)
    text(s, "Regiões", .78, 1.9, 5.6, .5, 24, CYAN, True)
    text(s, "Cinco UFs com maior média", 7.05, 1.9, 5.5, .5, 24, TEAL, True)
    chart(s, XL_CHART_TYPE.BAR_CLUSTERED, [r[0] for r in region_rank][::-1],
          [("Preço médio", [r[1] for r in region_rank][::-1])], .7, 2.5, 5.75, 3.8,
          legend=False, labels=True, palette=[CYAN], min_scale=0,
          max_scale=max(r[1] for r in region_rank) * 1.18)
    chart(s, XL_CHART_TYPE.BAR_CLUSTERED, [r[0] for r in state_rank[:5]][::-1],
          [("Preço médio", [r[1] for r in state_rank[:5]][::-1])], 7.0, 2.5, 5.6, 3.8,
          legend=False, labels=True, palette=[TEAL], min_scale=0,
          max_scale=max(r[1] for r in state_rank[:5]) * 1.18)
    text(s, f"Médias em {unit}, ponderadas pelas observações de cada mês e localidade.", .78, 6.5, 11.9, .4, 18, MUTED)
    footer(s, 6)
    notes(s, "Fontes: outputs/datasets/resumo_mensal_regiao.csv e resumo_mensal_estado.csv. As médias do recorte usam os números de registros como pesos. Regiões e UFs têm composição de municípios e postos distinta. O ranking é descritivo da amostra, sem ajuste de composição ou comparação por volume vendido.")

    # 7. Both election windows. Coverage is displayed beside each comparison.
    s = add_slide(prs, "Julho a outubro nos anos eleitorais")
    coverage_2022 = elections[1]["records_change"]
    election_prices = [row[key] for summary in elections for row in summary["observations"].values()
                       for key in ("preco_medio", "preco_mediano") if row.get(key) is not None]
    election_upper = max(1, math.ceil(max(election_prices, default=0) / 2) * 2)
    warning = (f"Em 2022, os registros variam {pct(coverage_2022, True)}. A composição da amostra muda entre meses."
               if coverage_2022 is not None else "A comparação exige os mesmos meses e o acompanhamento da cobertura.")
    text(s, warning, .62, 1.18, 12, .55, 18, ORANGE)
    for i, summary in enumerate(elections):
        left = .7 + i * 6.3
        year = summary["year"]
        obs = summary["observations"]
        july, october = summary["july"], summary["october"]
        text(s, f"{year}     {pct(summary['mean_change'], True)}", left + .05, 1.85,
             5.7, .65, 32, CYAN if i == 0 else TEAL, True)
        if july and october:
            text(s, f"Variação da média. Preço em {unit}", left + .05, 2.48, 5.7, .4, 18, MUTED)
            series = [("Média", [obs.get(m, {}).get("preco_medio") for m in range(7, 11)])]
            if all(obs.get(m, {}).get("preco_mediano") is not None for m in range(7, 11)):
                series.append(("Mediana", [obs[m]["preco_mediano"] for m in range(7, 11)]))
            chart(s, XL_CHART_TYPE.LINE_MARKERS, [MONTHS[m] for m in range(7, 11)], series,
                  left, 2.98, 5.65, 1.9, min_scale=0, max_scale=election_upper, palette=[CYAN, TEAL])
            cov = [["Registros", br(july["registros"], 0), br(october["registros"], 0)],
                   ["Postos", br(july.get("postos"), 0), br(october.get("postos"), 0)],
                   ["Municípios", br(july.get("municipios"), 0), br(october.get("municipios"), 0)]]
            table(s, ["Cobertura", "Julho", "Outubro"], cov, left, 5.0, 5.65, 1.7,
                  widths=[2.05, 1.8, 1.8], font=18)
        else:
            text(s, "Meses de referência ausentes.\nA comparação não recebe estimativa.",
                 left + .05, 3.1, 5.6, 1.6, 23, ORANGE)
    text(s, "O recorte não identifica efeito causal da eleição. Mediana e painel municipal no slide seguinte.",
         .75, 6.79, 11.9, .4, 18, WHITE)
    footer(s, 7, "")
    notes(s, "Fontes: outputs/datasets/resumo_mensal_brasil.csv e painel_balanceado_municipios.csv. Os dois anos eleitorais usam julho a outubro. Variação = (média de outubro / média de julho − 1) × 100. Ausências não recebem estimativa. A mediana é a mediana das observações de cada mês. O painel mantém municípios presentes em todos os quatro meses do mesmo ano e produto. Ele não mantém os mesmos postos ou os mesmos pesos municipais. Mesmo sinal em análises de sensibilidade não identifica causalidade eleitoral. As contagens de cobertura constam da mesma tabela mensal. Preços nominais. Não houve reaproveitamento das saídas do notebook." + provenance)

    # 8. Coverage matrix with explicit gaps.
    s = add_slide(prs, "Cobertura e limites", "Número de observações por ano e mês no recorte selecionado")
    matrix = []
    for yr in all_years:
        lookup = {int(r["mes"]): r for r in monthly if int(r["ano"]) == yr}
        matrix.append([str(yr)] + [br(lookup[m]["registros"], 0) if m in lookup else "ausente" for m in args.meses])
    widths = [1.3] + [10.6 / len(args.meses)] * len(args.meses)
    table(s, ["Ano"] + [MONTHS[m] for m in args.meses], matrix,
          .7, 1.95, 11.9, 3.05, widths=widths, font=18)
    text(s, coverage_description(gaps, len(all_years)), .78, 5.28, 11.8, .95, 20, ORANGE)
    text(s, "Preços nominais. Amostra variável. Sem ponderação por volume vendido.\nO painel de municípios reduz uma diferença de cobertura, mas preserva diferenças de postos e pesos.",
         .78, 6.24, 11.8, .65, 18, MUTED)
    footer(s, 8)
    notes(s, "Fonte: outputs/datasets/resumo_mensal_brasil.csv e relatório de qualidade. Cobertura calculada dinamicamente a partir dos meses disponíveis para o produto selecionado. Não há imputação de meses nem reaproveitamento das saídas históricas gravadas no notebook. Dados observacionais, preços nominais, cobertura não constante e ausência de ponderação de vendas limitam inferências." + provenance)

    # 9. Findings directly computed from the data.
    s = add_slide(prs, "Principais achados", scope)
    peak_year = max(annual, key=annual.get)
    region_spread = region_rank[0][1] - region_rank[-1][1]
    items = [
        (str(peak_year), f"Maior média entre os anos disponíveis: R$ {br(annual[peak_year])} por unidade no recorte.", CYAN),
        (f"R$ {br(region_spread)}", f"Diferença entre as médias de {region_rank[0][0]} e {region_rank[-1][0]}. A composição das amostras varia.", TEAL),
    ]
    for summary in elections:
        if summary["mean_change"] is not None:
            finding = f"Julho–outubro: média {pct(summary['mean_change'], True)}. Mediana {pct(summary['median_change'], True)}."
            if summary["panel_change"] is not None:
                finding += f" Painel municipal {pct(summary['panel_change'], True)}."
        else:
            finding = "Meses de referência ausentes. A comparação não recebe estimativa."
        items.append((str(summary["year"]), finding, ORANGE if summary["year"] == 2022 else "B2A3FF"))
    for i, (headline, body, color) in enumerate(items):
        y = 1.95 + i * 1.15
        text(s, headline, .8, y, 3.0, .65, 32, color, True)
        text(s, body, 4.0, y + .02, 8.5, .95, 22, WHITE)
    footer(s, 9)
    notes(s, "Fontes: resumos mensais Brasil e região, e painel_balanceado_municipios.csv. Maior média anual refere-se exclusivamente aos meses selecionados nos arquivos disponíveis, e não ao ano completo. Diferença regional = maior média regional ponderada por registros menos a menor. As variações eleitorais comparam médias observadas com composição variável, sem inferência causal. O painel restringe o conjunto de municípios aos presentes nos quatro meses do ano e produto, preservando a ponderação das observações e a variação de postos e pesos entre municípios.")

    # 10. Recommendations, useful within the evidence limits.
    s = add_slide(prs, "Uso recomendado da análise", "Comparações de preço acompanhadas de cobertura")
    recs = [
        ("Comparabilidade", "Publicar registros, postos e municípios junto de cada variação de preço."),
        ("Sensibilidade", "Comparar média, mediana e um painel com as mesmas localidades. Investigar também um painel de postos."),
        ("Completude", "Completar os meses ausentes da cobertura e validar a continuidade dos arquivos antes de ampliar a série."
         if gaps else "Preservar a cobertura dos mesmos meses e validar a continuidade dos arquivos ao ampliar a série."),
        ("Atualização", "Reprocessar novas bases com o mesmo método e preservar os relatórios de qualidade."),
    ]
    for i, (label, body) in enumerate(recs):
        y = 1.95 + i * 1.13
        text(s, label, .8, y, 3.05, .6, 24, COLORS[i], True)
        text(s, body, 4.05, y + .02, 8.4, .9, 22, WHITE)
    text(s, "A janela eleitoral descreve os preços. Explicações causais exigem outro desenho de estudo.",
         .8, 6.57, 11.8, .38, 18, ORANGE)
    footer(s, 10)
    notes(s, "Recomendações metodológicas baseadas nos limites dos arquivos fornecidos. O painel municipal disponível não controla a composição de postos nem ponderações municipais constantes. A identificação causal de efeitos políticos demandaria hipótese e desenho empírico próprios, além de fatores econômicos e de políticas de preço.")

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    prs.save(args.saida)
    validate(args.saida)
    print(f"Apresentação gerada: {args.saida.resolve()}")
    print(f"10 slides, {sum(sh.has_chart for sl in prs.slides for sh in sl.shapes)} gráficos nativos editáveis.")


def validate(path: Path):
    """Confere contagem, limites dos objetos, dados e planilhas dos gráficos."""
    prs = Presentation(path)
    if len(prs.slides) != 10:
        raise AssertionError("A apresentação deve conter exatamente dez slides.")
    for index, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            tolerance = Inches(.03)
            if min(shape.left, shape.top) < -tolerance:
                raise AssertionError(f"Objeto fora dos limites no slide {index}: {shape.name}")
            if shape.left + shape.width > prs.slide_width + tolerance or shape.top + shape.height > prs.slide_height + tolerance:
                raise AssertionError(f"Objeto excede o slide {index}: {shape.name}")
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    with zipfile.ZipFile(path) as archive:
        charts = [n for n in archive.namelist() if n.startswith("ppt/charts/chart") and n.endswith(".xml")]
        books = [n for n in archive.namelist() if n.startswith("ppt/embeddings/") and n.endswith(".xlsx")]
        if len(charts) < 3 or len(books) != len(charts):
            raise AssertionError("Gráficos ou planilhas incorporadas ausentes.")
        for name in charts:
            root = ET.fromstring(archive.read(name))
            if not root.findall(".//c:ser", ns) or root.find(".//c:externalData", ns) is None:
                raise AssertionError(f"Gráfico sem séries ou sem dados editáveis: {name}")
            for point in root.findall(".//c:numCache/c:pt/c:v", ns):
                if not math.isfinite(float(point.text)):
                    raise AssertionError(f"Gráfico contém valor numérico inválido: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", type=Path, default=ROOT / "outputs" / "datasets")
    parser.add_argument("--qualidade", type=Path, default=ROOT / "data" / "processed" / "relatorio_qualidade.json")
    parser.add_argument("--saida", type=Path, default=ROOT / "outputs" / "apresentacao" / "analise_combustiveis.pptx")
    parser.add_argument("--produto", default="GASOLINA COMUM")
    parser.add_argument("--meses", default="7,8,9,10", help="Meses separados por vírgula. Padrão: 7,8,9,10")
    args = parser.parse_args()
    args.meses = sorted({int(m) for m in args.meses.split(",")})
    if args.meses != [7, 8, 9, 10]:
        parser.error("Esta narrativa foi preparada para julho–outubro. Use o dashboard para outros meses.")
    build(args)


if __name__ == "__main__":
    main()
