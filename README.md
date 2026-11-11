# Preços de combustíveis no Brasil

Dashboard interativo em **Streamlit e Plotly**, processamento em **Pandas/PyArrow** e apresentação editável gerada com **python-pptx**. Todos os indicadores são calculados a partir dos arquivos incluídos no pacote.

Plano de evolução: [ROADMAP.md](ROADMAP.md).

## Início rápido

Requer Python 3.11 ou 3.12. Extraia o ZIP e abra um terminal na pasta `dashboard_combustiveis`.

```bash
python -m venv .venv
```

No Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

No macOS/Linux, ative com `source .venv/bin/activate`. Se a política do PowerShell impedir a ativação, execute diretamente `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` e `.\.venv\Scripts\python.exe -m streamlit run app.py`.

O pacote já inclui os dados processados. A primeira abertura não exige refazer a limpeza ou acessar serviços externos. O navegador usa normalmente `http://localhost:8501`. Interrompa o servidor com `Ctrl+C`.

Para extrair o projeto em outra pasta ou enviar o código ao GitHub, consulte [Como salvar e enviar ao GitHub](COMO_USAR_E_ENVIAR_AO_GITHUB.md). O `.gitignore` deixa os CSVs brutos fora do controle de versão. Os dados tratados e a apresentação acompanham o repositório.

## Reproduzir o processamento e a apresentação

```bash
python scripts/preparar_dados.py --help
python scripts/preparar_dados.py
python scripts/gerar_slides.py --help
python scripts/gerar_slides.py
python scripts/validar_dados.py
python -m pytest -q
```

Os scripts localizam a raiz do projeto a partir do próprio arquivo. Os CSVs originais ficam em `data/raw`. Não altere esses arquivos para corrigir resultados: modifique o tratamento e reprocesse. Consulte as opções `--help` para caminhos alternativos. O processamento pode levar alguns minutos. O ETL mantém os registros normalizados em memória para deduplicar e agregar, enquanto o uso interativo do painel aplica filtros no Parquet.

## Fontes e cobertura

O pacote reúne os seis arquivos inicialmente fornecidos e o segundo semestre de 2018, obtido diretamente na fonte oficial da ANP para completar a análise. A proveniência, a leitura efetiva e os controles de cada arquivo constam do relatório de qualidade. Os seis arquivos locais originais permanecem preservados e não foram autenticados por comparação com downloads remotos. O complemento oficial de 2018 tem URL, data de obtenção e SHA-256 registrados em `data/raw/fontes_externas.json` e na auditoria.

- `ca-2017-02.csv`: segundo semestre de 2017.
- `ca-2018-01.csv`: primeiro semestre de 2018.
- [`ca-2018-02.csv`](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2018-02.csv): segundo semestre de 2018, complemento baixado da ANP.
- `ca-2019-02.csv`: segundo semestre de 2019.
- `ca-2021-02.csv`: segundo semestre de 2021.
- `ca-2022-02.csv`: segundo semestre de 2022.
- `ca-2023-02.csv`: segundo semestre de 2023.

**2018 agora inclui os dois semestres**, permitindo analisar julho a outubro com registros reais. Os anos de 2020 e outros anos sem arquivo não integram a série. Os meses disponíveis aparecem no catálogo e no relatório após a leitura efetiva. Janeiro a junho de 2018 continuam disponíveis para exploração, enquanto o recorte inicial mantém julho a outubro para comparar os anos nos mesmos meses.

O notebook original foi preservado como referência metodológica. Todos os resultados foram recalculados a partir dos CSVs incluídos no projeto, sem reutilizar os valores salvos no notebook.

## Metodologia

### Tratamento

Cada arquivo tem delimitador e codificação detectados individualmente. Datas são convertidas com prioridade ao formato brasileiro e preços respeitam o separador decimal detectado. Os nomes das colunas, UF, município, produto, unidade e identificação dos postos são normalizados. `GASOLINA` é apresentada como `GASOLINA COMUM`, separada da gasolina aditivada.

Registros sem campos essenciais válidos são rejeitados com motivo. Duplicatas semânticas exatas são removidas sem usar o nome do arquivo como parte da identidade. Observações diferentes do mesmo posto e data não são descartadas apenas por essa coincidência. A identificação dos postos usa o CNPJ normalizado quando válido, e eventual alternativa documentada no relatório. Postos sem identificação suficiente não contam como um posto distinto fictício. Ausências em campos opcionais não implicam exclusão automática.

Preços positivos atípicos não são excluídos por uma faixa arbitrária. O relatório expõe os controles aplicados. Confira preços extremos e registros em conflito antes de usá-los como evidência substantiva.

### Cálculos

- **Preço médio:** soma dos preços de venda dividida pela quantidade de observações válidas do recorte. Uma observação é uma coleta de preço, não um litro vendido. Não há ponderação por vendas, população ou igual peso entre estados.
- **Mínimo e máximo:** menor e maior valor de venda observados no recorte.
- **Registros:** número de linhas após tratamento e aplicação dos filtros.
- **Postos distintos:** quantidade de identificadores de posto não nulos e distintos. Não some contagens mensais para obter uma contagem anual.
- **Municípios:** pares distintos de UF e município. Municípios homônimos em estados diferentes permanecem separados.
- **Média por ano:** média das observações dos meses selecionados naquele ano. O título não implica cobertura do ano inteiro.
- **Variação percentual:** `100 × (preço final / preço inicial − 1)`. O indicador identifica a base usada. Variações mensais exigem meses consecutivos com dados.
- **Julho a outubro:** diferença absoluta `média de outubro − média de julho`, e diferença relativa em relação à média de julho. Um mês sem dados permanece ausente.
- **Médias agregadas:** são obtidas das observações, ou ponderadas pela contagem quando combinam resumos. Uma média simples das médias estaduais ou mensais não substitui a média das observações.
- **Mediana e painel balanceado:** os arquivos complementares permitem avaliar sensibilidade. O painel retém municípios observados nos quatro meses de cada ano, usando UF e município como chave. O conjunto pode mudar entre anos e não fixa os mesmos postos ou a mesma frequência de coleta.

Todos os preços são **nominais**, na moeda e unidade dos arquivos. Não há correção pela inflação. Gasolina, etanol e diesel usam R$/L. GNV usa R$/m³ e deve ser analisado individualmente. O seletor de produto impede misturar unidades no mesmo indicador.

### Períodos eleitorais

A análise descreve julho a outubro de **2018 e 2022**, além dos anos de comparação com cobertura. A quantidade de observações, postos e municípios varia entre os meses, com especial atenção à cobertura de 2022. Mudanças na composição da amostra podem alterar as médias. Mesmo o painel municipal balanceado não controla todos esses fatores.

As variações calculadas **não demonstram causalidade eleitoral ou política**. O projeto não implementa experimento, grupo de controle causal, ajuste por inflação, preços internacionais, câmbio ou tributos. Essas variáveis seriam necessárias para investigar hipóteses explicativas.

## Navegação e desempenho

Use os filtros para selecionar produto, anos, meses e território. Municípios aparecem com sua UF para distinguir localidades homônimas. O padrão prioriza gasolina comum de julho a outubro. A tabela permite pesquisa e exportação do recorte. Os gráficos Plotly oferecem tooltips, zoom e exportação de imagem.

Os dados tratados ficam em Parquet particionado por ano. As consultas aplicam filtros antes de converter para Pandas, e o cache evita repetir leituras equivalentes. Os CSVs brutos não são carregados a cada interação. O dashboard funciona sem baixar mapas ou dados durante o uso.

## Organização

```text
dashboard_combustiveis/
  app.py
  requirements.txt
  README.md
  .streamlit/config.toml
  fuel_dashboard/           # consultas, cálculos e visualização
  assets/                  # estilo e malha oficial do IBGE
  static/                  # topologia local para o mapa sem conexão
  data/
    raw/                   # seis CSVs originais, complemento 2018 e notebook
    processed/             # Parquet, catálogo e qualidade
  scripts/
    preparar_dados.py
    gerar_slides.py
  tests/
  outputs/
    datasets/              # resumos mensais e análises complementares
    apresentacao/          # PowerPoint editável
```

Os resumos mensais cobrem Brasil, região, UF e município, com produto e unidade. O relatório de qualidade e o catálogo detalham a cobertura, exclusões e formatos. A apresentação usa os resultados gerados, sem indicadores fixados no código.

## Mapa e documentação técnica

A malha simplificada contém as 27 UFs e usa o identificador oficial `codarea`. A procedência e a URL de obtenção estão em `assets/geografia_fonte.json`. O mapa representa médias da amostra por UF, não preços de todos os postos do estado.

O arquivo do IBGE permanece preservado. A visualização ajusta somente a orientação dos anéis em uma cópia em memória, conforme a [convenção esférica do D3](https://d3js.org/d3-geo). A topologia de fundo do Plotly acompanha o pacote em `static`, servida localmente pelo Streamlit, para permitir uso sem conexão.

- [IBGE: API de malhas geográficas](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3).
- [Streamlit: cache de dados](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data).
- [python-pptx: gráficos editáveis](https://python-pptx.readthedocs.io/en/latest/user/charts.html).

## Solução de problemas

- **Dados processados ausentes:** execute `python scripts/preparar_dados.py` com os sete CSVs incluídos em `data/raw`.
- **Arquivo ausente ou ilegível:** confira nome, integridade e relatório do processamento. Não renomeie o arquivo de 2018 como segundo semestre.
- **Filtro sem observações:** amplie o território ou os meses. A disponibilidade varia por produto e localidade. O catálogo informa a cobertura efetiva de cada ano.
- **Porta ocupada:** use `streamlit run app.py --server.port 8502`.
- **Mudança nos arquivos:** reprocesse antes de gerar novamente os slides. Reinicie o servidor se o navegador continuar exibindo uma sessão antiga.
- **Exibição no PowerPoint:** os gráficos e textos são editáveis. Fontes substituídas pelo computador de destino podem exigir pequenos ajustes visuais.
