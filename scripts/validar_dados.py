"""Independent integrity checks over saved Parquet and exported monthly summaries."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


def validate(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    processed = project_dir / 'data/processed'
    report = json.loads((processed / 'relatorio_qualidade.json').read_text(encoding='utf-8'))
    catalog = json.loads((processed / 'catalogo.json').read_text(encoding='utf-8'))
    dataset = ds.dataset(processed / 'registros', format='parquet', partitioning='hive')
    rows = dataset.count_rows()
    assert rows == report['total_registros_tratados'] == catalog['total_registros'], 'Contagem Parquet/catalogo diverge'
    assert rows + report['total_rejeitadas'] + report['total_duplicatas_removidas'] == report['total_linhas_lidas'], 'Reconciliação bruta falhou'
    monthly = pd.read_csv(project_dir / 'outputs/datasets/resumo_mensal_brasil.csv')
    assert not monthly.duplicated(['ano', 'mes', 'produto', 'unidade']).any(), 'Chave mensal duplicada'
    assert int(monthly.registros.sum()) == rows, 'Total mensal diverge'
    assert (monthly.preco_minimo > 0).all()
    assert (monthly.preco_minimo <= monthly.preco_medio + 1e-8).all()
    assert (monthly.preco_medio <= monthly.preco_maximo + 1e-8).all()
    checked = 0
    for year in catalog['anos']:
        frame = dataset.to_table(columns=['ano', 'mes', 'produto', 'unidade', 'preco_venda', 'data_coleta'], filter=ds.field('ano') == year).to_pandas()
        assert frame.data_coleta.notna().all()
        assert frame.ano.eq(frame.data_coleta.dt.year).all()
        assert frame.mes.eq(frame.data_coleta.dt.month).all()
        assert (np.isfinite(frame.preco_venda) & frame.preco_venda.gt(0)).all()
        observed_months = sorted(int(month) for month in frame.mes.unique())
        assert observed_months == catalog['meses_por_ano'][str(year)], f'Meses observados/catalogados divergem em {year}'
        calculated = frame.groupby(['ano', 'mes', 'produto', 'unidade'], observed=True).preco_venda.agg(['count', 'mean', 'min', 'max']).reset_index()
        expected = monthly.loc[monthly.ano == year]
        merged = calculated.merge(expected, on=['ano', 'mes', 'produto', 'unidade'], how='outer', indicator=True)
        assert merged['_merge'].eq('both').all(), f'Cobertura divergente {year}'
        assert merged['count'].eq(merged.registros).all(), f'Contagem divergente {year}'
        for computed, exported in [('mean','preco_medio'), ('min','preco_minimo'), ('max','preco_maximo')]:
            np.testing.assert_allclose(merged[computed], merged[exported], rtol=1e-8, atol=1e-8)
        checked += len(merged)
    for level in ['regiao', 'estado', 'municipio']:
        summary = pd.read_csv(project_dir / f'outputs/datasets/resumo_mensal_{level}.csv')
        assert int(summary.registros.sum()) == rows, f'Total {level} diverge'
        folded = summary.assign(total_preco=summary.preco_medio * summary.registros).groupby(['ano','mes','produto','unidade']).agg(registros=('registros','sum'), soma=('total_preco','sum')).reset_index()
        merged = monthly.merge(folded, on=['ano','mes','produto','unidade'], suffixes=('_br','_geo'), validate='one_to_one')
        assert merged.registros_br.eq(merged.registros_geo).all()
        np.testing.assert_allclose(merged.preco_medio, merged.soma/merged.registros_geo, rtol=1e-8, atol=1e-8)
    annual = pd.read_csv(project_dir / 'outputs/datasets/resumo_anual_recorte.csv')
    assert int(annual.registros.sum()) == dataset.count_rows(filter=ds.field('mes').isin([7,8,9,10])), 'Recorte anual diverge das observações'
    elections = pd.read_csv(project_dir / 'outputs/datasets/variacao_eleitoral.csv')
    for row in elections.itertuples(index=False):
        observed = monthly.loc[(monthly.ano == row.ano_eleitoral) & (monthly.produto == row.produto)]
        july = observed.loc[observed.mes == 7, 'preco_medio']
        october = observed.loc[observed.mes == 10, 'preco_medio']
        if len(july) and len(october):
            np.testing.assert_allclose([row.preco_julho, row.preco_outubro], [july.iloc[0], october.iloc[0]], rtol=1e-8, atol=1e-8)
            np.testing.assert_allclose(row.variacao_percentual, (october.iloc[0] / july.iloc[0] - 1) * 100, rtol=1e-8, atol=1e-7)
        else:
            assert pd.isna(row.variacao_percentual), f'Variação eleitoral inferida sem os dois meses: {row.ano_eleitoral}/{row.produto}'
    return {'registros_verificados':rows, 'grupos_mensais_verificados':checked, 'niveis_geograficos':4, 'integridade':'OK'}


if __name__ == '__main__':
    print(json.dumps(validate(Path(__file__).resolve().parents[1]), ensure_ascii=False, indent=2))
