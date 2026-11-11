# Roadmap — Dashboard de Combustíveis

Visão do produto: tornar o painel ANP mais completo, reproduzível e fácil de publicar, sem perder o rigor metodológico já documentado no README.

## Status atual (v1)

- [x] ETL com Pandas/PyArrow a partir dos CSVs da ANP
- [x] Dados processados em Parquet particionado por ano
- [x] Dashboard Streamlit + Plotly (filtros, mapa, tabela, exportação)
- [x] Análise de períodos eleitorais (2018 e 2022) com avisos de não-causalidade
- [x] Geração de apresentação PowerPoint editável
- [x] Testes automatizados (`pytest`) e relatório de qualidade
- [x] Uso offline do mapa (topologia local)

## Fase 1 — Publicação e colaboração (próximo)

- [ ] Publicar no [Streamlit Community Cloud](https://streamlit.io/cloud) a partir deste repositório
- [ ] Adicionar `LICENSE` (ex.: MIT) e badges no README
- [ ] CI no GitHub Actions: lint + `pytest` em cada push
- [ ] Issue templates e checklist de contribuição
- [ ] Documentar variáveis de ambiente e caminhos (`FUEL_DATASET_DIR`, etc.)

## Fase 2 — Dados e cobertura

- [ ] Incluir semestres faltantes (ex.: 2020 e primeiros semestres ausentes) quando disponíveis na ANP
- [ ] Script de download/atualização com checksum e registro em `fontes_externas.json`
- [ ] Opção de preços reais (deflacionados, ex.: IPCA) além dos nominais
- [ ] Catálogo com alerta de cobertura incompleta por produto/UF/mês
- [ ] Versionamento explícito do dataset processado (tag semântica + changelog de dados)

## Fase 3 — Análise e produto

- [ ] Comparativos com preço internacional do petróleo e câmbio (camadas externas, sem inferir causalidade)
- [ ] Painel de bandeiras e concentração de mercado por UF
- [ ] Séries suavizadas e intervalos de confiança descritivos
- [ ] Exportação CSV/Excel do recorte filtrado em um clique
- [ ] Modo “apresentação” com gráficos pré-selecionados para slides

## Fase 4 — Experiência e desempenho

- [ ] Tema visual mais claro (tipografia e contraste acessíveis)
- [ ] Melhorar tempo de carga inicial (pré-agregados e cache persistente)
- [ ] Deep links com estado dos filtros na URL
- [ ] Versão mobile otimizada dos gráficos
- [ ] Página de metodologia embutida no app (resumo do README)

## Fase 5 — Escala (opcional)

- [ ] API leve de consulta (FastAPI) sobre o Parquet
- [ ] Banco analítico (DuckDB/Postgres) para séries maiores
- [ ] Agendamento de atualização mensal dos dados ANP
- [ ] Autenticação simples se o deploy deixar de ser público

## Fora de escopo (por enquanto)

- Inferência causal de efeito eleitoral ou político
- Substituição dos CSVs originais por dados “corrigidos” manualmente
- Mix de unidades (R$/L com R$/m³) no mesmo indicador

## Como contribuir com o roadmap

Abra uma issue descrevendo a melhoria, o impacto esperado e se depende de novos dados. Preferência: mudanças pequenas, testáveis e alinhadas à metodologia já publicada.
