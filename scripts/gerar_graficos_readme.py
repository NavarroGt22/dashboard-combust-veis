"""Gera os SVGs estáticos usados no README a partir de outputs/datasets.

Uso (na raiz do projeto):
    python scripts/gerar_graficos_readme.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "datasets"
OUT = ROOT / "docs" / "imagens"

BG = "#071321"
MUTED = "#8aa3b8"
TEXT = "#e8f2fa"
GRID = "#193346"
AXIS = "#6f879c"
LABEL = "#b7c9d8"
COLORS = ["#38d5c8", "#48b9ee", "#727ef8", "#ffad66", "#e576aa", "#84d095"]


def br_money(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")


def br_num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def write(name: str, content: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"escreveu {path.relative_to(ROOT)}")


def media_anual(gasolina: pd.DataFrame) -> None:
    rows = gasolina.sort_values("ano")
    ymax = 7.0
    plot_top, plot_bottom = 110.0, 350.0
    height = plot_bottom - plot_top
    xs = [120, 250, 380, 510, 640, 770]
    bars = []
    for x, (_, row) in zip(xs, rows.iterrows()):
        price = float(row["preco_medio"])
        y = plot_bottom - (price / ymax) * height
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="90" height="{plot_bottom - y:.1f}" rx="8" fill="url(#bar)"/>'
            f'<text x="{x + 45}" y="{y - 10:.1f}" text-anchor="middle" fill="{TEXT}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" font-weight="600">'
            f'{br_money(price)}</text>'
            f'<text x="{x + 45}" y="378" text-anchor="middle" fill="{LABEL}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">{int(row["ano"])}</text>'
        )
    write(
        "media_anual_gasolina.svg",
        f"""
<svg xmlns="http://www.w3.org/2000/svg" width="920" height="420" viewBox="0 0 920 420" role="img">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BG}"/><stop offset="100%" stop-color="#0d2133"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#48b9ee"/><stop offset="100%" stop-color="#38d5c8"/>
    </linearGradient>
  </defs>
  <rect width="920" height="420" rx="16" fill="url(#bg)"/>
  <text x="36" y="42" fill="{TEXT}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="22" font-weight="700">Gasolina comum · média julho–outubro</text>
  <text x="36" y="68" fill="{MUTED}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">Preço médio nominal (R$/L) · amostra ANP · sem correção pela inflação</text>
  <g stroke="{GRID}" stroke-width="1">
    <line x1="80" y1="110" x2="880" y2="110"/><line x1="80" y1="170" x2="880" y2="170"/>
    <line x1="80" y1="230" x2="880" y2="230"/><line x1="80" y1="290" x2="880" y2="290"/>
    <line x1="80" y1="350" x2="880" y2="350"/>
  </g>
  <g fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" text-anchor="end">
    <text x="72" y="114">R$ 7,00</text><text x="72" y="174">R$ 5,25</text>
    <text x="72" y="234">R$ 3,50</text><text x="72" y="294">R$ 1,75</text>
    <text x="72" y="354">R$ 0,00</text>
  </g>
  {''.join(bars)}
  <text x="36" y="406" fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11">Fonte: ANP · recorte julho–outubro · média das observações (não ponderada por vendas)</text>
</svg>
""",
    )


def evolucao_mensal(mensal: pd.DataFrame) -> None:
    years = sorted(mensal["ano"].unique())
    month_x = {7: 150, 8: 330, 9: 510, 10: 690}

    def y_of(price: float) -> float:
        return 340 - (price - 3) * 60

    polylines = []
    legend = []
    for idx, year in enumerate(years):
        color = COLORS[idx % len(COLORS)]
        subset = mensal[mensal["ano"] == year].sort_values("mes")
        points = " ".join(f"{month_x[int(r.mes)]},{y_of(float(r.preco_medio)):.1f}" for r in subset.itertuples())
        circles = "".join(
            f'<circle cx="{month_x[int(r.mes)]}" cy="{y_of(float(r.preco_medio)):.1f}" r="4.5"/>'
            for r in subset.itertuples()
        )
        width = 3.2 if year == 2022 else 2.8
        polylines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="{width}" points="{points}"/>'
            f'<g fill="{color}">{circles}</g>'
        )
        legend.append(
            f'<rect x="730" y="{110 + idx * 30}" width="14" height="14" rx="3" fill="{color}"/>'
            f'<text x="754" y="{122 + idx * 30}" fill="#d5e4ef">{int(year)}</text>'
        )
    write(
        "evolucao_mensal_gasolina.svg",
        f"""
<svg xmlns="http://www.w3.org/2000/svg" width="920" height="440" viewBox="0 0 920 440" role="img">
  <defs>
    <linearGradient id="bg2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BG}"/><stop offset="100%" stop-color="#0d2133"/>
    </linearGradient>
  </defs>
  <rect width="920" height="440" rx="16" fill="url(#bg2)"/>
  <text x="36" y="42" fill="{TEXT}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="22" font-weight="700">Evolução mensal · gasolina comum</text>
  <text x="36" y="68" fill="{MUTED}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">Julho a outubro por ano · R$/L nominal</text>
  <g stroke="{GRID}" stroke-width="1">
    <line x1="90" y1="100" x2="700" y2="100"/><line x1="90" y1="160" x2="700" y2="160"/>
    <line x1="90" y1="220" x2="700" y2="220"/><line x1="90" y1="280" x2="700" y2="280"/>
    <line x1="90" y1="340" x2="700" y2="340"/>
  </g>
  <g fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" text-anchor="end">
    <text x="82" y="104">R$ 7,00</text><text x="82" y="164">R$ 6,00</text>
    <text x="82" y="224">R$ 5,00</text><text x="82" y="284">R$ 4,00</text>
    <text x="82" y="344">R$ 3,00</text>
  </g>
  <g fill="{LABEL}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" text-anchor="middle">
    <text x="150" y="368">Jul</text><text x="330" y="368">Ago</text>
    <text x="510" y="368">Set</text><text x="690" y="368">Out</text>
  </g>
  {''.join(polylines)}
  <g font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">{''.join(legend)}</g>
  <text x="36" y="408" fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11">Destaque: em 2022 a média cai de julho a outubro. A composição da amostra também muda entre os meses.</text>
</svg>
""",
    )


def variacao_eleitoral(eleitoral: pd.DataFrame) -> None:
    gas = eleitoral[(eleitoral["produto"] == "GASOLINA COMUM") & (eleitoral["status"] == "disponível")]
    blocks = []
    centers = {2018: 295, 2022: 635}
    for _, row in gas.iterrows():
        ano = int(row["ano_eleitoral"])
        jul = float(row["preco_julho"])
        out = float(row["preco_outubro"])
        pct = float(row["variacao_percentual"])
        cx = centers[ano]
        y_jul = 370 - jul / 7 * 260
        y_out = 370 - out / 7 * 260
        color = "#ffad66" if pct >= 0 else "#e576aa"
        sign = f"+{br_num(pct, 1)}%" if pct >= 0 else f"−{br_num(abs(pct), 1)}%"
        blocks.append(
            f'<rect x="{cx - 75}" y="{y_jul:.1f}" width="70" height="{370 - y_jul:.1f}" rx="8" fill="#48b9ee"/>'
            f'<rect x="{cx + 5}" y="{y_out:.1f}" width="70" height="{370 - y_out:.1f}" rx="8" fill="#38d5c8"/>'
            f'<text x="{cx - 40}" y="{y_jul - 10:.1f}" text-anchor="middle" fill="{TEXT}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">{br_num(jul)}</text>'
            f'<text x="{cx + 40}" y="{y_out - 10:.1f}" text-anchor="middle" fill="{TEXT}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" font-weight="600">{br_num(out)}</text>'
            f'<text x="{cx}" y="396" text-anchor="middle" fill="{LABEL}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="15" font-weight="600">{ano}</text>'
            f'<text x="{cx}" y="100" text-anchor="middle" fill="{color}" '
            f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" font-weight="700">{sign}</text>'
        )
    write(
        "variacao_eleitoral.svg",
        f"""
<svg xmlns="http://www.w3.org/2000/svg" width="920" height="420" viewBox="0 0 920 420" role="img">
  <defs>
    <linearGradient id="bg3" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BG}"/><stop offset="100%" stop-color="#0d2133"/>
    </linearGradient>
  </defs>
  <rect width="920" height="420" rx="16" fill="url(#bg3)"/>
  <text x="36" y="42" fill="{TEXT}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="22" font-weight="700">Anos eleitorais · julho vs outubro</text>
  <text x="36" y="68" fill="{MUTED}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">Gasolina comum · R$/L · variação descritiva (não causal)</text>
  <g stroke="{GRID}" stroke-width="1">
    <line x1="80" y1="110" x2="880" y2="110"/><line x1="80" y1="175" x2="880" y2="175"/>
    <line x1="80" y1="240" x2="880" y2="240"/><line x1="80" y1="305" x2="880" y2="305"/>
    <line x1="80" y1="370" x2="880" y2="370"/>
  </g>
  <g fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" text-anchor="end">
    <text x="72" y="114">R$ 7,00</text><text x="72" y="179">R$ 5,25</text>
    <text x="72" y="244">R$ 3,50</text><text x="72" y="309">R$ 1,75</text>
    <text x="72" y="374">R$ 0,00</text>
  </g>
  {''.join(blocks)}
  <g font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">
    <rect x="780" y="140" width="14" height="14" rx="3" fill="#48b9ee"/><text x="804" y="152" fill="#d5e4ef">Julho</text>
    <rect x="780" y="168" width="14" height="14" rx="3" fill="#38d5c8"/><text x="804" y="180" fill="#d5e4ef">Outubro</text>
  </g>
</svg>
""",
    )


def ranking_uf(estado: pd.DataFrame) -> None:
    recorte = estado[(estado["ano"] == 2022) & (estado["mes"].between(7, 10))].copy()
    recorte["peso"] = recorte["preco_medio"] * recorte["registros"]
    agregado = (
        recorte.groupby("uf", as_index=False)
        .agg(peso=("peso", "sum"), registros=("registros", "sum"))
        .assign(media=lambda d: d["peso"] / d["registros"])
        .sort_values("media", ascending=False)
    )
    top = agregado.head(10)
    bottom = agregado.tail(10).sort_values("media")

    def bars(frame: pd.DataFrame, x0: int, fill: str) -> str:
        parts = []
        for i, row in enumerate(frame.itertuples()):
            y = 124 + i * 34
            width = float(row.media) / 6.5 * 320
            label_x = x0 + 44 + width
            parts.append(
                f'<text x="{x0}" y="{y + 14}" fill="#d5e4ef" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">{row.uf}</text>'
                f'<rect x="{x0 + 34}" y="{y}" width="{width:.0f}" height="18" rx="5" fill="{fill}"/>'
                f'<text x="{label_x:.0f}" y="{y + 14}" fill="#d5e4ef" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">{br_num(row.media)}</text>'
            )
        return "".join(parts)

    write(
        "ranking_uf_2022.svg",
        f"""
<svg xmlns="http://www.w3.org/2000/svg" width="920" height="520" viewBox="0 0 920 520" role="img">
  <defs>
    <linearGradient id="bg4" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BG}"/><stop offset="100%" stop-color="#0d2133"/>
    </linearGradient>
    <linearGradient id="hi" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e576aa"/><stop offset="100%" stop-color="#ffad66"/>
    </linearGradient>
    <linearGradient id="lo" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38d5c8"/><stop offset="100%" stop-color="#48b9ee"/>
    </linearGradient>
  </defs>
  <rect width="920" height="520" rx="16" fill="url(#bg4)"/>
  <text x="36" y="42" fill="{TEXT}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="22" font-weight="700">Ranking por UF · 2022 (jul–out)</text>
  <text x="36" y="68" fill="{MUTED}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13">Gasolina comum · média ponderada pelas observações · R$/L</text>
  <text x="36" y="104" fill="#ffad66" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" font-weight="700">Maiores médias</text>
  <text x="480" y="104" fill="#38d5c8" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" font-weight="700">Menores médias</text>
  {bars(top, 36, "url(#hi)")}
  {bars(bottom, 480, "url(#lo)")}
  <text x="36" y="492" fill="{AXIS}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11">Médias da amostra ANP por UF; não representam o preço de todos os postos do estado.</text>
</svg>
""",
    )


def main() -> None:
    anual = pd.read_csv(DATA / "resumo_anual_recorte.csv")
    mensal = pd.read_csv(DATA / "resumo_mensal_brasil.csv")
    eleitoral = pd.read_csv(DATA / "variacao_eleitoral.csv")
    estado = pd.read_csv(DATA / "resumo_mensal_estado.csv")

    gasolina_anual = anual[anual["produto"] == "GASOLINA COMUM"]
    gasolina_mensal = mensal[
        (mensal["produto"] == "GASOLINA COMUM") & (mensal["mes"].between(7, 10))
    ]
    estado_gas = estado[estado["produto"] == "GASOLINA COMUM"]

    media_anual(gasolina_anual)
    evolucao_mensal(gasolina_mensal)
    variacao_eleitoral(eleitoral)
    ranking_uf(estado_gas)
    print("Pronto. Os SVGs já aparecem no README após o push ao GitHub.")


if __name__ == "__main__":
    main()
