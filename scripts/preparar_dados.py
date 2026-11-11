"""Prepare auditable ANP observations, keeping every available month and product.

Run from the project directory with ``python scripts/preparar_dados.py``.
The input CSVs are not altered. Prices remain nominal and unweighted.
"""
from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE_FILES = ("ca-2017-02.csv", "ca-2018-01.csv", "ca-2019-02.csv",
                "ca-2021-02.csv", "ca-2022-02.csv", "ca-2023-02.csv")
UF_REGIAO = {**dict.fromkeys("AC AM AP PA RO RR TO".split(), "Norte"),
             **dict.fromkeys("AL BA CE MA PB PE PI RN SE".split(), "Nordeste"),
             **dict.fromkeys("DF GO MS MT".split(), "Centro-Oeste"),
             **dict.fromkeys("ES MG RJ SP".split(), "Sudeste"),
             **dict.fromkeys("PR RS SC".split(), "Sul")}
REGION_SIGLAS = {"N": "Norte", "NE": "Nordeste", "CO": "Centro-Oeste", "SE": "Sudeste", "S": "Sul"}
PRODUCTS = {"GASOLINA": "GASOLINA COMUM", "GASOLINA COMUM": "GASOLINA COMUM",
            "GASOLINA ADITIVADA": "GASOLINA ADITIVADA", "ETANOL": "ETANOL",
            "DIESEL": "DIESEL", "DIESEL S10": "DIESEL S10", "GNV": "GNV"}
MANDATORY = ["Estado - Sigla", "Municipio", "Produto", "Data da Coleta", "Valor de Venda", "Unidade de Medida"]
OPTIONAL = ["Regiao - Sigla", "CNPJ da Revenda", "Revenda", "Bandeira", "Nome da Rua", "Numero Rua", "Complemento", "Bairro", "Cep", "Valor de Compra"]
PUBLIC_COLUMNS = ["data_coleta", "ano", "mes", "regiao", "uf", "municipio", "produto", "preco_venda", "unidade", "posto_id", "cnpj", "revenda", "bandeira", "arquivo_origem"]
PRIVATE_COLUMNS = ["_rua", "_numero", "_complemento", "_bairro", "_cep", "_compra"]
SUMMARY_VALUES = ["preco_medio", "preco_mediano", "preco_minimo", "preco_maximo", "registros", "postos", "municipios"]


def read_source(path: Path) -> tuple[pd.DataFrame, dict]:
    """Detect encoding and delimiter from actual contents, never guess from year."""
    with path.open("rb") as source:
        sample = source.read(128 * 1024)
    try:
        codecs.getincrementaldecoder("utf-8-sig")().decode(sample, final=False)
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "cp1252"
    first_line = sample.splitlines()[0].decode(encoding)
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    header = next(csv.reader([first_line], delimiter=delimiter))
    if len(header) < len(MANDATORY):
        raise ValueError(f"Cabeçalho ou separador não reconhecido em {path.name}.")
    try:
        frame = pd.read_csv(path, sep=delimiter, encoding=encoding, dtype="string", keep_default_na=False, on_bad_lines="error")
    except UnicodeDecodeError:
        if encoding != "utf-8-sig":
            raise
        encoding = "cp1252"
        frame = pd.read_csv(path, sep=delimiter, encoding=encoding, dtype="string", keep_default_na=False, on_bad_lines="error")
    frame.columns = frame.columns.str.strip()
    missing = sorted(set(MANDATORY) - set(frame.columns))
    if missing:
        raise ValueError(f"{path.name}: colunas obrigatórias ausentes: {', '.join(missing)}")
    return frame, {"arquivo": path.name, "bytes": path.stat().st_size, "encoding": encoding,
                   "separador": delimiter, "linhas_lidas": len(frame), "sha256": sha256_file(path)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column] if column in frame else pd.Series("", index=frame.index, dtype="string")
    return values.astype("string").fillna("").str.strip().str.replace(r"\s+", " ", regex=True).str.upper()


def _numeric(values: pd.Series) -> pd.Series:
    # Brazilian decimal commas; a dot is a thousands separator only when a comma exists.
    values = values.astype("string").str.strip()
    comma = values.str.contains(",", regex=False, na=False)
    values = values.where(~comma, values.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(values, errors="coerce").astype("float64")


@lru_cache(maxsize=100000)
def valid_cnpj(digits: str) -> bool:
    """Require 14 digits and both Brazilian CNPJ check digits."""
    if len(digits) != 14 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    for length, weights in [(12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
                            (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])]:
        remainder = sum(int(value) * weight for value, weight in zip(digits[:length], weights)) % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != int(digits[length]):
            return False
    return True


def normalize_frame(raw: pd.DataFrame, source_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Normalize source semantics and return accepted rows, rejects and quality counts."""
    missing = sorted(set(MANDATORY) - set(raw.columns))
    if missing:
        raise ValueError(f"{source_name}: colunas obrigatórias ausentes: {', '.join(missing)}")
    raw = raw.reset_index(drop=True)
    out = pd.DataFrame(index=raw.index)
    date_text = _text(raw, "Data da Coleta")
    out["data_coleta"] = pd.to_datetime(date_text, format="%d/%m/%Y", errors="coerce")
    iso = date_text.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)
    out.loc[iso, "data_coleta"] = pd.to_datetime(date_text.loc[iso], format="%Y-%m-%d", errors="coerce")
    out["uf"] = _text(raw, "Estado - Sigla")
    out["regiao"] = out.uf.map(UF_REGIAO)
    out["municipio"] = _text(raw, "Municipio")
    original_product = _text(raw, "Produto")
    out["produto"] = original_product.map(PRODUCTS).fillna(original_product)
    out["preco_venda"] = _numeric(raw["Valor de Venda"])
    source_unit = _text(raw, "Unidade de Medida").str.replace(" ", "", regex=False)
    unit_map = {"R$/LITRO": "R$/L", "R$/L": "R$/L", "R$/M³": "R$/m³", "R$/M3": "R$/m³"}
    out["unidade"] = source_unit.map(unit_map)
    out["revenda"] = _text(raw, "Revenda").replace("", pd.NA)
    out["bandeira"] = _text(raw, "Bandeira").replace("", pd.NA)
    address_sources = {"_rua": "Nome da Rua", "_numero": "Numero Rua", "_complemento": "Complemento", "_bairro": "Bairro", "_cep": "Cep"}
    for destination, source in address_sources.items():
        out[destination] = _text(raw, source)
    out["_cep"] = out["_cep"].str.replace(r"\D", "", regex=True)
    out["_compra"] = _numeric(_text(raw, "Valor de Compra"))
    digits = _text(raw, "CNPJ da Revenda").str.replace(r"\D", "", regex=True)
    known = digits.map(valid_cnpj)
    out["cnpj"] = digits.where(known, pd.NA)
    out["posto_id"] = ("cnpj:" + out.cnpj).astype("string")
    meaningful_number = ~out["_numero"].isin(["", "S/N", "SN", "S.N.", "0", "SEM NUMERO", "SEM NÚMERO", "N/A", "NÃO INFORMADO"])
    enough_address = (~known & out["revenda"].notna() & out["_rua"].ne("") &
                      (meaningful_number | out["_cep"].str.len().eq(8)) &
                      out["regiao"].notna() & out["municipio"].ne(""))
    if enough_address.any():
        identity = out.loc[enough_address, ["uf", "municipio", "revenda", "_rua", "_numero", "_complemento", "_cep"]].fillna("").agg("|".join, axis=1)
        out.loc[enough_address, "posto_id"] = identity.map(lambda value: "endereco:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24])
    reasons = pd.Series("", index=raw.index, dtype="string")
    invalid_checks = {
        "data_invalida": out.data_coleta.isna(),
        "uf_invalida": out.regiao.isna(),
        "municipio_ausente": out.municipio.eq(""),
        "produto_ausente": out.produto.eq(""),
        "preco_invalido_nao_positivo_ou_nao_finito": out.preco_venda.isna() | ~np.isfinite(out.preco_venda) | out.preco_venda.le(0),
        "unidade_invalida_ou_incompativel": out.unidade.isna() | (out.produto.eq("GNV") & out.unidade.ne("R$/m³")) | (out.produto.ne("GNV") & out.unidade.ne("R$/L")),
    }
    for reason, invalid in invalid_checks.items():
        reasons = reasons.where(~invalid, reasons + reason + ";")
    accepted = reasons.eq("")
    rejects = raw.loc[~accepted].copy()
    rejects.insert(0, "numero_linha", rejects.index + 2)
    rejects.insert(0, "arquivo_origem", source_name)
    rejects["motivos_rejeicao"] = reasons.loc[~accepted].str.rstrip(";")
    out["arquivo_origem"] = source_name
    out["ano"] = out.data_coleta.dt.year.astype("Int16")
    out["mes"] = out.data_coleta.dt.month.astype("Int8")
    reported_region = _text(raw, "Regiao - Sigla").map(REGION_SIGLAS)
    quality = {
        "linhas_lidas": len(raw), "linhas_validas_antes_deduplicacao": int(accepted.sum()),
        "linhas_rejeitadas": int((~accepted).sum()),
        "rejeicoes_por_motivo": {reason: int(mask.sum()) for reason, mask in invalid_checks.items()},
        "colunas_opcionais_ausentes": [name for name in OPTIONAL if name not in raw],
        "campos_opcionais_vazios": {name: int(_text(raw, name).eq("").sum()) for name in OPTIONAL},
        "cnpj_ausente": int(digits.eq("").sum()),
        "cnpj_invalido_nao_vazio": int((~known & digits.ne("")).sum()),
        "regiao_divergente_da_uf": int((reported_region.notna() & reported_region.ne(out.regiao)).sum()),
        "identidades_por_endereco": int((enough_address & accepted).sum()),
        "registros_sem_identidade_de_posto": int((out.posto_id.isna() & accepted).sum()),
        "produtos_nao_previstos": sorted(set(original_product) - set(PRODUCTS) - {""}),
    }
    return out.loc[accepted, PUBLIC_COLUMNS + PRIVATE_COLUMNS].copy(), rejects, quality


def deduplicate_records(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Only remove identical normalized observations, ignoring file provenance."""
    subset = [name for name in frame if name != "arquivo_origem"]
    duplicates = frame.duplicated(subset=subset, keep="first")
    return frame.loc[~duplicates].reset_index(drop=True), int(duplicates.sum())


def aggregate_summary(frame: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    dimensions = dimensions + (["unidade"] if "unidade" not in dimensions else [])
    source = frame.assign(_municipio_id=frame["uf"].astype("string") + "|" + frame["municipio"].astype("string"))
    return source.groupby(dimensions, observed=True, dropna=False).agg(
        preco_medio=("preco_venda", "mean"), preco_mediano=("preco_venda", "median"),
        preco_minimo=("preco_venda", "min"), preco_maximo=("preco_venda", "max"),
        registros=("preco_venda", "size"), postos=("posto_id", "nunique"),
        municipios=("_municipio_id", "nunique")).reset_index().sort_values(dimensions).reset_index(drop=True)


def build_election_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in [2018, 2022]:
        for product in sorted(monthly.produto.unique()):
            sample = monthly.loc[(monthly.ano == year) & (monthly.produto == product)]
            july = sample.loc[sample.mes == 7, "preco_medio"]
            october = sample.loc[sample.mes == 10, "preco_medio"]
            before = float(july.iloc[0]) if len(july) else np.nan
            after = float(october.iloc[0]) if len(october) else np.nan
            status = "disponível" if len(july) and len(october) else "sem julho e outubro" if not len(july) and not len(october) else "sem julho" if not len(july) else "sem outubro"
            unit_sample = monthly.loc[monthly.produto == product, "unidade"]
            rows.append({"ano_eleitoral": year, "produto": product,
                         "unidade": unit_sample.iloc[0] if len(unit_sample) else None,
                         "preco_julho": before, "preco_outubro": after,
                         "variacao_absoluta": after - before,
                         "variacao_percentual": (after / before - 1) * 100,
                         "status": status})
    return pd.DataFrame(rows)


def build_balanced_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Within-year and product panel of UF+municipio present in July to October.

    Its mean and median remain observation weighted (as in the notebook's groupby),
    with a stable municipality roster inside each year, not a stable station roster.
    """
    selected = frame.loc[frame.mes.between(7, 10)].copy()
    keys = ["ano", "produto", "uf", "municipio"]
    eligible = selected.groupby(keys, observed=True)["mes"].nunique()
    eligible = eligible.loc[eligible.eq(4)].reset_index()[keys]
    balanced = selected.merge(eligible, on=keys, how="inner")
    summary = aggregate_summary(balanced, ["ano", "mes", "produto"])
    summary = summary.rename(columns={"municipios": "municipios_painel"})
    baseline = summary.loc[summary.mes == 7, ["ano", "produto", "preco_medio"]].rename(columns={"preco_medio": "preco_julho"})
    summary = summary.merge(baseline, on=["ano", "produto"], how="left")
    summary["variacao_desde_julho_pct"] = (summary.preco_medio / summary.preco_julho - 1) * 100
    return summary


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.10g")


def _json_write(value: dict, path: Path) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _replace_records(staging: Path, target: Path) -> None:
    """Publish a complete partition tree, preventing stale years on reruns."""
    parent = target.parent.resolve()
    if staging.resolve().parent != parent or target.resolve().parent != parent:
        raise ValueError("Diretório de registros fora da pasta processed esperada.")
    backup = Path(tempfile.mkdtemp(prefix=".registros-anterior-", dir=parent))
    backup.rmdir()
    had_target = target.exists()
    if had_target:
        target.rename(backup)
    try:
        staging.rename(target)
    except BaseException:
        if had_target:
            backup.rename(target)
        raise
    if had_target:
        if backup.resolve().parent != parent or not backup.name.startswith(".registros-anterior-"):
            raise ValueError("Recusada remoção de pasta fora do destino gerado.")
        shutil.rmtree(backup)


def run_pipeline(input_dir: Path, project_dir: Path, expected_files=None) -> dict:
    input_dir, project_dir = Path(input_dir).resolve(), Path(project_dir).resolve()
    required_files = SOURCE_FILES if expected_files is None else tuple(expected_files)
    missing = [name for name in required_files if not (input_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Arquivos necessários não encontrados em {input_dir}: {', '.join(missing)}. Copie os CSVs necessários para data/raw ou informe --input-dir.")
    source_files = sorted(set(required_files) | {path.name for path in input_dir.glob("ca-*.csv")}) if expected_files is None else list(required_files)
    manifest_path = input_dir / "fontes_externas.json"
    external_sources = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        entries = manifest.get("fontes", []) if isinstance(manifest, dict) else manifest
        if not isinstance(entries, list):
            raise ValueError("fontes_externas.json deve conter uma lista de fontes.")
        external_sources = {entry["arquivo"]: entry for entry in entries}
    processed = project_dir / "data" / "processed"
    records_dir = processed / "registros"
    exports = project_dir / "outputs" / "datasets"
    for folder in [processed, exports]:
        folder.mkdir(parents=True, exist_ok=True)
    frames, rejected_frames, source_quality = [], [], []
    for name in source_files:
        print(f"Lendo e validando {name}...", flush=True)
        raw, metadata = read_source(input_dir / name)
        if name in external_sources:
            provenance = external_sources[name]
            if provenance.get("sha256") and provenance["sha256"].lower() != metadata["sha256"].lower():
                raise ValueError(f"SHA-256 divergente para fonte externa {name}; confira o arquivo e fontes_externas.json.")
            metadata["proveniencia_externa"] = provenance
        normalized, rejected, quality = normalize_frame(raw, name)
        metadata.update(quality)
        metadata["meses_por_ano"] = {str(int(year)): sorted(int(month) for month in sample.mes.unique()) for year, sample in normalized.groupby("ano", observed=True)}
        source_quality.append(metadata)
        frames.append(normalized)
        if len(rejected):
            rejected_frames.append(rejected)
        print(f"  {len(raw):,} lidas; {len(normalized):,} válidas; {len(rejected):,} rejeitadas", flush=True)
        del raw
    print("Removendo duplicatas semânticas...", flush=True)
    combined = pd.concat(frames, ignore_index=True)
    frames.clear()
    before = combined.groupby("arquivo_origem", observed=True).size().to_dict()
    data, duplicates = deduplicate_records(combined)
    del combined
    after = data.groupby("arquivo_origem", observed=True).size().to_dict()
    for source in source_quality:
        source["duplicatas_removidas"] = int(before.get(source["arquivo"], 0) - after.get(source["arquivo"], 0))
        source["linhas_tratadas"] = int(after.get(source["arquivo"], 0))
    data = data[PUBLIC_COLUMNS].copy()
    data["ano"] = data.ano.astype("int16")
    data["mes"] = data.mes.astype("int8")
    for name in ["regiao", "uf", "municipio", "produto", "unidade", "revenda", "bandeira", "arquivo_origem", "posto_id", "cnpj"]:
        data[name] = data[name].astype("category")
    parquet_paths = []
    staged_records = Path(tempfile.mkdtemp(prefix=".registros-novos-", dir=processed))
    for year, group in data.groupby("ano", observed=True):
        year_dir = staged_records / f"ano={int(year)}"
        year_dir.mkdir(parents=True, exist_ok=True)
        path = year_dir / "dados.parquet"
        # Hive partition supplies ano, avoiding Arrow int16/int32 schema conflicts.
        group.drop(columns="ano").sort_values(["data_coleta", "uf", "municipio", "produto"]).to_parquet(path, index=False, engine="pyarrow", compression="zstd")
        final_path = records_dir / f"ano={int(year)}" / "dados.parquet"
        parquet_paths.append(str(final_path.relative_to(project_dir)).replace("\\", "/"))
    _replace_records(staged_records, records_dir)
    print("Calculando resumos e painel de municípios...", flush=True)
    summaries = {}
    for level, geography in {"brasil": [], "regiao": ["regiao"], "estado": ["regiao", "uf"], "municipio": ["regiao", "uf", "municipio"]}.items():
        summary = aggregate_summary(data, ["ano", "mes", "produto"] + geography)
        _write_csv(summary, exports / f"resumo_mensal_{level}.csv")
        summaries[level] = summary
    selected = data.loc[data.mes.between(7, 10)]
    annual = aggregate_summary(selected, ["ano", "produto"])
    months = selected.groupby(["ano", "produto"], observed=True)["mes"].nunique().rename("meses_observados").reset_index()
    annual = annual.merge(months, on=["ano", "produto"], how="left")
    annual["recorte"] = "julho a outubro (somente meses observados)"
    _write_csv(annual, exports / "resumo_anual_recorte.csv")
    elections = build_election_summary(summaries["brasil"])
    _write_csv(elections, exports / "variacao_eleitoral.csv")
    panel = build_balanced_panel(data)
    _write_csv(panel, exports / "painel_balanceado_municipios.csv")
    coverage = data.groupby(["ano", "mes", "produto", "unidade"], observed=True).size().rename("registros").reset_index()
    _write_csv(coverage, exports / "cobertura.csv")
    if rejected_frames:
        rejected = pd.concat(rejected_frames, ignore_index=True)
    else:
        rejected = pd.DataFrame(columns=["arquivo_origem", "numero_linha", "motivos_rejeicao"] + MANDATORY)
    _write_csv(rejected, exports / "registros_rejeitados.csv")
    now = datetime.now(timezone.utc).isoformat()
    methodology = [
        "Médias, medianas, mínimos e máximos de preços nominais por observação; não ponderados por volume ou população.",
        "GASOLINA foi normalizada para GASOLINA COMUM; produtos e unidades são separados; GNV usa R$/m³, demais produtos R$/L.",
        "UF válida determina a região. Datas DD/MM/AAAA e ISO AAAA-MM-DD são aceitas explicitamente, sem inferência MM/DD. Datas inválidas, preços não positivos/não finitos e unidades incompatíveis são rejeitados.",
        "CNPJ é limpo e validado com dois dígitos verificadores. Sem CNPJ válido, identidade por endereço exige UF, município, revenda, rua e número ou CEP; sem informação suficiente, posto_id permanece nulo e não entra em postos.",
        "Postos conta identidades distintas conhecidas, incluindo identidades de endereço; não representa necessariamente a população de postos nem soma de contagens mensais.",
        "Duplicatas são observações idênticas em todos os campos normalizados, incluindo preço de compra e endereço quando existentes; arquivo de origem não integra a chave.",
        "Meses e anos ausentes não são preenchidos, interpolados ou inferidos. A cobertura efetiva é calculada a partir das datas observadas de todos os CSVs presentes.",
        "Resumos anuais usam julho–outubro dos anos disponíveis; meses ou anos sem observações nesse recorte não recebem preços inferidos.",
        "CSV complementar de origem externa possui URL oficial, data de download e SHA-256 no manifesto e na auditoria por arquivo; o hash declarado é verificado durante o processamento.",
        "Comparação eleitoral é descritiva de julho e outubro; os dados fornecidos não identificam causalidade política.",
        "Painel balanceado usa UF+município presente nos quatro meses julho–outubro, separadamente por ano e produto; a composição pode mudar entre anos e os postos podem mudar dentro do painel.",
        "No painel, médias e medianas são por observação; variação percentual é normalizada pela média observada de julho, mantendo o procedimento de agrupamento do notebook.",
        "O notebook original é referência metodológica, sem executar código nem reutilizar suas saídas salvas, que referenciam arquivos diferentes.",
        "Preço de compra, endereço e região informada são usados na auditoria/deduplicação quando presentes; ausência desses campos opcionais não causa imputação de preços.",
    ]
    quality_report = {
        "gerado_em_utc": now, "fontes": source_quality,
        "fontes_externas": [source["proveniencia_externa"] for source in source_quality if "proveniencia_externa" in source],
        "total_linhas_lidas": sum(source["linhas_lidas"] for source in source_quality),
        "total_rejeitadas": len(rejected), "total_duplicatas_removidas": duplicates,
        "total_registros_tratados": len(data),
        "total_postos_identificados": int(data.posto_id.nunique()),
        "total_municipios": int(data[["uf", "municipio"]].drop_duplicates().shape[0]),
        "registros_sem_identidade_de_posto": int(data.posto_id.isna().sum()),
        "reconciliacao_ok": sum(source["linhas_lidas"] for source in source_quality) == len(data) + len(rejected) + duplicates,
        "precos_positivos_finitos": bool((data.preco_venda.gt(0) & np.isfinite(data.preco_venda)).all()),
        "datas_validas": bool(data.data_coleta.notna().all()),
        "ufs_validas": bool(data.uf.isin(UF_REGIAO).all()),
        "cobertura": json.loads(coverage.to_json(orient="records", force_ascii=False)),
        "metodologia": methodology,
    }
    _json_write(quality_report, processed / "relatorio_qualidade.json")
    months_by_year = {str(int(year)): sorted(int(month) for month in group.mes.unique()) for year, group in data.groupby("ano", observed=True)}
    catalogue = {
        "versao_schema": 1, "gerado_em_utc": now,
        "arquivos_fonte": source_files, "fontes_externas": quality_report["fontes_externas"],
        "anos": sorted(int(year) for year in data.ano.unique()),
        "produtos": sorted(str(product) for product in data.produto.unique()),
        "regioes": sorted(str(region) for region in data.regiao.unique()),
        "ufs": sorted(str(uf) for uf in data.uf.unique()), "meses_por_ano": months_by_year,
        "unidades_por_produto": {str(product): sorted(str(value) for value in group.unidade.unique()) for product, group in data.groupby("produto", observed=True)},
        "total_registros": len(data), "total_postos_identificados": int(data.posto_id.nunique()),
        "data_minima": str(data.data_coleta.min().date()), "data_maxima": str(data.data_coleta.max().date()),
        "arquivos_parquet": parquet_paths, "diretorio_registros": "data/processed/registros",
        "cobertura": quality_report["cobertura"], "recorte_padrao": {"mes_inicial": 7, "mes_final": 10},
        "anos_sem_recorte_padrao": [int(year) for year, months in months_by_year.items() if not set(months).intersection({7, 8, 9, 10})],
        "colunas": PUBLIC_COLUMNS, "relatorio_qualidade": "data/processed/relatorio_qualidade.json",
        "exportacoes": sorted(str(path.relative_to(project_dir)).replace("\\", "/") for path in exports.glob("*.csv")),
    }
    _json_write(catalogue, processed / "catalogo.json")
    lines = ["# Relatório de qualidade — combustíveis", "", f"Gerado em UTC: {now}", "",
             f"- Linhas lidas: {quality_report['total_linhas_lidas']:,}",
             f"- Linhas rejeitadas: {len(rejected):,}", f"- Duplicatas semânticas removidas: {duplicates:,}",
             f"- Registros tratados: {len(data):,}", f"- Postos com identidade conhecida: {data.posto_id.nunique():,}",
             f"- Registros sem identidade de posto: {data.posto_id.isna().sum():,}",
             f"- Reconciliação de contagens: {quality_report['reconciliacao_ok']}", "", "## Cobertura por ano", ""]
    for year, months in months_by_year.items():
        count = int(data.loc[data.ano.eq(int(year))].shape[0])
        lines.append(f"- {year}: meses {', '.join(map(str, months))}; {count:,} registros.")
    lines += ["", "## Auditoria por arquivo", ""]
    for source in source_quality:
        lines += [f"### {source['arquivo']}", "", f"Encoding: {source['encoding']}; separador: `{source['separador']}`; SHA-256: `{source['sha256']}`.",
                  f"Lidas: {source['linhas_lidas']:,}; rejeitadas: {source['linhas_rejeitadas']:,}; duplicatas: {source['duplicatas_removidas']:,}; tratadas: {source['linhas_tratadas']:,}.",
                  f"CNPJ ausente: {source['cnpj_ausente']:,}; CNPJ inválido não vazio: {source['cnpj_invalido_nao_vazio']:,}; identidades por endereço: {source['identidades_por_endereco']:,}.",
                  f"Colunas opcionais ausentes: {', '.join(source['colunas_opcionais_ausentes']) or 'nenhuma'}.",
                  f"Rejeições por motivo: {json.dumps(source['rejeicoes_por_motivo'], ensure_ascii=False)}.",
                  f"Campos opcionais vazios: {json.dumps(source['campos_opcionais_vazios'], ensure_ascii=False)}.", ""]
        if "proveniencia_externa" in source:
            provenance = source["proveniencia_externa"]
            lines += [f"Proveniência externa: {json.dumps(provenance, ensure_ascii=False)}.", ""]
    lines += ["## Metodologia e limites", ""] + [f"- {item}" for item in methodology]
    (processed / "relatorio_qualidade.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not all([quality_report["reconciliacao_ok"], quality_report["precos_positivos_finitos"], quality_report["datas_validas"], quality_report["ufs_validas"]]):
        raise AssertionError("Falha de integridade; consulte relatorio_qualidade.json.")
    print(f"Concluído: {len(data):,} registros tratados; {duplicates:,} duplicatas; {len(rejected):,} rejeitadas.", flush=True)
    return catalogue


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=root / "data" / "raw", help="Pasta com os seis CSVs originais e eventuais ca-*.csv complementares")
    parser.add_argument("--output", type=Path, default=root, help="Raiz do projeto onde data/processed e outputs/datasets serão gravados")
    arguments = parser.parse_args()
    try:
        run_pipeline(arguments.input_dir, arguments.output)
    except (FileNotFoundError, ValueError) as error:
        parser.exit(2, f"Erro: {error}\n")


if __name__ == "__main__":
    main()
