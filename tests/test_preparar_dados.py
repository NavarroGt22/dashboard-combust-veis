"""Checks for mistakes that change price statistics or sample identity."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preparar_dados.py"


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("preparar_dados", SCRIPT)
            cls.etl = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.etl)
        else:
            cls.etl = None

    def module(self):
        self.assertIsNotNone(self.etl, "The ETL implementation must exist")
        return self.etl

    def frame(self, **overrides):
        row = {"Estado - Sigla": " BA ", "Municipio": "Salvador", "Produto": "GASOLINA",
               "Data da Coleta": "02/07/2022", "Valor de Venda": "5,99",
               "Unidade de Medida": "R$ / litro", "CNPJ da Revenda": " 34.274.233/0015-08",
               "Revenda": "Posto Um", "Bandeira": "BRANCA", "Nome da Rua": "Rua A",
               "Numero Rua": "12", "Cep": "40000-000"}
        row.update(overrides)
        return pd.DataFrame([row])

    def test_normalization_preserves_decimal_date_unit_and_valid_identity(self):
        etl = self.module()
        valid, rejected, quality = etl.normalize_frame(self.frame(), "source.csv")
        self.assertEqual(len(rejected), 0)
        self.assertEqual(valid.iloc[0]["preco_venda"], 5.99)
        self.assertEqual(valid.iloc[0]["data_coleta"], pd.Timestamp("2022-07-02"))
        self.assertEqual(valid.iloc[0]["produto"], "GASOLINA COMUM")
        self.assertEqual(valid.iloc[0]["regiao"], "Nordeste")
        self.assertEqual(valid.iloc[0]["unidade"], "R$/L")
        self.assertEqual(valid.iloc[0]["cnpj"], "34274233001508")
        self.assertEqual(valid.iloc[0]["posto_id"], "cnpj:34274233001508")

    def test_invalid_price_date_uf_and_product_unit_are_rejected_with_reason(self):
        etl = self.module()
        fixtures = [("Valor de Venda", "0", "preco"), ("Valor de Venda", "inf", "preco"),
                    ("Data da Coleta", "31/02/2022", "data"), ("Estado - Sigla", "XX", "uf"),
                    ("Produto", "GNV", "unidade")]
        for field, value, reason in fixtures:
            with self.subTest(field=field, value=value):
                valid, rejected, _ = etl.normalize_frame(self.frame(**{field: value}), "sample.csv")
                self.assertEqual(len(valid), 0)
                self.assertEqual(len(rejected), 1)
                self.assertIn(reason, rejected.iloc[0]["motivos_rejeicao"])

    def test_missing_station_identity_is_not_counted_as_one_shared_station(self):
        etl = self.module()
        frame = self.frame(**{"CNPJ da Revenda": "", "Nome da Rua": "", "Numero Rua": "", "Cep": ""})
        valid, _, quality = etl.normalize_frame(frame, "source.csv")
        self.assertTrue(pd.isna(valid.iloc[0]["posto_id"]))
        summary = etl.aggregate_summary(valid, ["ano", "mes", "produto"])
        self.assertEqual(summary.iloc[0]["postos"], 0)
        self.assertEqual(summary.iloc[0]["registros"], 1)

    def test_complete_address_can_identify_station_without_inventing_cnpj(self):
        etl = self.module()
        valid, _, quality = etl.normalize_frame(self.frame(**{"CNPJ da Revenda": "11111111111111"}), "source.csv")
        self.assertTrue(pd.isna(valid.iloc[0]["cnpj"]))
        self.assertTrue(valid.iloc[0]["posto_id"].startswith("endereco:"))

    def test_unnumbered_street_without_cep_does_not_supply_station_identity(self):
        etl = self.module()
        valid, _, _ = etl.normalize_frame(self.frame(**{"CNPJ da Revenda": "", "Numero Rua": "S/N", "Cep": ""}), "source.csv")
        self.assertTrue(pd.isna(valid.iloc[0]["posto_id"]))

    def test_duplicate_file_rows_are_removed_but_distinct_prices_remain(self):
        etl = self.module()
        one, _, _ = etl.normalize_frame(self.frame(), "first.csv")
        duplicate, _, _ = etl.normalize_frame(self.frame(), "second.csv")
        changed, _, _ = etl.normalize_frame(self.frame(**{"Valor de Venda": "6,09"}), "second.csv")
        result, removed = etl.deduplicate_records(pd.concat([one, duplicate, changed], ignore_index=True))
        self.assertEqual(len(result), 2)
        self.assertEqual(removed, 1)
        self.assertAlmostEqual(etl.aggregate_summary(result, ["ano", "mes", "produto"]).iloc[0]["preco_medio"], 6.04)

    def test_both_delimiters_and_quoted_decimal_commas_are_detected(self):
        etl = self.module()
        with tempfile.TemporaryDirectory() as name:
            for separator in [";", ","]:
                path = Path(name) / ("semicolon.csv" if separator == ";" else "comma.csv")
                self.frame().to_csv(path, sep=separator, index=False, encoding="cp1252")
                frame, metadata = etl.read_source(path)
                self.assertEqual(metadata["separador"], separator)
                self.assertEqual(frame.iloc[0]["Valor de Venda"], "5,99")

    def test_election_deltas_do_not_fill_missing_2018_or_missing_endpoint(self):
        etl = self.module()
        monthly = pd.DataFrame([
            {"ano": 2018, "mes": 1, "produto": "GASOLINA COMUM", "unidade": "R$/L", "preco_medio": 4.0},
            {"ano": 2022, "mes": 7, "produto": "GASOLINA COMUM", "unidade": "R$/L", "preco_medio": 6.0},
            {"ano": 2022, "mes": 10, "produto": "GASOLINA COMUM", "unidade": "R$/L", "preco_medio": 4.8},
        ])
        result = etl.build_election_summary(monthly)
        row18 = result[result.ano_eleitoral == 2018].iloc[0]
        row22 = result[result.ano_eleitoral == 2022].iloc[0]
        self.assertTrue(pd.isna(row18.variacao_percentual))
        self.assertEqual(row18.status, "sem julho e outubro")
        self.assertAlmostEqual(row22.variacao_percentual, -20.0)

    def test_balanced_panel_uses_uf_and_city_and_requires_all_four_months(self):
        etl = self.module()
        frames = []
        for month, price in [(7, 6), (8, 5), (9, 4), (10, 3)]:
            frames.append(self.frame(**{"Municipio": "BOM JESUS", "Data da Coleta": f"01/{month:02}/2022", "Valor de Venda": str(price)}))
        frames.append(self.frame(**{"Estado - Sigla": "PI", "Municipio": "BOM JESUS", "Data da Coleta": "01/07/2022", "Valor de Venda": "100"}))
        valid, _, _ = etl.normalize_frame(pd.concat(frames, ignore_index=True), "source.csv")
        panel = etl.build_balanced_panel(valid)
        self.assertEqual(len(panel), 4)
        self.assertEqual(set(panel.municipios_painel), {1})
        self.assertEqual(panel.loc[panel.mes == 7, "preco_medio"].iloc[0], 6)
        self.assertEqual(panel.loc[panel.mes == 10, "variacao_desde_julho_pct"].iloc[0], -50)

    def test_iso_dates_are_accepted_without_guessing_ambiguous_us_dates(self):
        etl = self.module()
        valid, rejected, _ = etl.normalize_frame(self.frame(**{"Data da Coleta": "2022-07-02"}), "source.csv")
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid.iloc[0]["data_coleta"], pd.Timestamp("2022-07-02"))

    def test_encoding_falls_back_if_first_non_utf8_character_is_after_sample(self):
        etl = self.module()
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "late_accent.csv"
            self.frame(**{"Revenda": "A" * 140000 + "Á"}).to_csv(source, index=False, encoding="cp1252")
            frame, metadata = etl.read_source(source)
            self.assertEqual(metadata["encoding"], "cp1252")
            self.assertTrue(frame.iloc[0]["Revenda"].endswith("Á"))

    def test_rerun_replaces_old_year_partitions_and_reconciles_csv_with_parquet(self):
        import pyarrow.dataset as ds
        etl = self.module()
        with tempfile.TemporaryDirectory() as name:
            project = Path(name)
            raw = project / "raw"
            raw.mkdir()
            sample = pd.concat([self.frame(**{"Data da Coleta": f"01/{month:02}/2022", "Valor de Venda": str(10-month)}) for month in [7, 8, 9, 10]], ignore_index=True)
            sample.loc[3, "Valor de Venda"] = "1"
            sample.to_csv(raw / "fixture.csv", index=False)
            etl.run_pipeline(raw, project, expected_files=["fixture.csv"])
            sample["Data da Coleta"] = sample["Data da Coleta"].str.replace("2022", "2023", regex=False)
            sample.to_csv(raw / "fixture.csv", index=False)
            catalogue = etl.run_pipeline(raw, project, expected_files=["fixture.csv"])
            dataset = ds.dataset(project / "data" / "processed" / "registros", format="parquet", partitioning="hive")
            table = dataset.to_table()
            self.assertEqual(table.num_rows, 4)
            self.assertEqual(set(table.column("ano").to_pylist()), {2023})
            self.assertEqual(catalogue["total_registros"], 4)
            summary = pd.read_csv(project / "outputs" / "datasets" / "resumo_mensal_brasil.csv")
            self.assertEqual(summary.registros.sum(), 4)
            self.assertEqual(list(summary.preco_medio), [3, 2, 1, 1])

    def test_default_run_discovers_additional_anp_semester_after_required_originals(self):
        etl = self.module()
        with tempfile.TemporaryDirectory() as name:
            project = Path(name)
            raw = project / "raw"
            raw.mkdir()
            for filename in etl.SOURCE_FILES:
                year = int(filename[3:7])
                self.frame(**{"Data da Coleta": f"01/01/{year}"}).to_csv(raw / filename, index=False)
            self.frame(**{"Data da Coleta": "01/07/2018"}).to_csv(raw / "ca-2018-02.csv", index=False)
            catalogue = etl.run_pipeline(raw, project)
            self.assertEqual(catalogue["total_registros"], 7)
            self.assertEqual(catalogue["meses_por_ano"]["2018"], [1, 7])

    def test_2018_election_is_absent_without_second_semester_and_observed_with_it(self):
        etl = self.module()
        validator_spec = importlib.util.spec_from_file_location("validar_dados", SCRIPT.with_name("validar_dados.py"))
        validator = importlib.util.module_from_spec(validator_spec)
        validator_spec.loader.exec_module(validator)
        with tempfile.TemporaryDirectory() as name:
            project = Path(name)
            raw = project / "raw"
            raw.mkdir()
            first = pd.concat([self.frame(**{"Data da Coleta": f"01/{month:02}/2018"}) for month in range(1,7)], ignore_index=True)
            second = pd.concat([self.frame(**{"Data da Coleta": f"01/{month:02}/2018", "Valor de Venda": "4,00" if month != 10 else "4,80"}) for month in range(7,13)], ignore_index=True)
            first.to_csv(raw / "ca-2018-01.csv", index=False)
            catalogue = etl.run_pipeline(raw, project, expected_files=["ca-2018-01.csv"])
            self.assertEqual(catalogue["anos_sem_recorte_padrao"], [2018])
            absent = pd.read_csv(project / "outputs/datasets/variacao_eleitoral.csv")
            self.assertTrue(absent.loc[absent.ano_eleitoral.eq(2018), "variacao_percentual"].isna().all())
            second.to_csv(raw / "ca-2018-02.csv", index=False)
            catalogue = etl.run_pipeline(raw, project, expected_files=["ca-2018-01.csv", "ca-2018-02.csv"])
            self.assertEqual(catalogue["meses_por_ano"]["2018"], list(range(1,13)))
            self.assertEqual(catalogue["anos_sem_recorte_padrao"], [])
            available = pd.read_csv(project / "outputs/datasets/variacao_eleitoral.csv")
            row = available.loc[available.ano_eleitoral.eq(2018)].iloc[0]
            self.assertAlmostEqual(row.variacao_percentual, 20)
            self.assertEqual(row.status, "disponível")
            self.assertEqual(validator.validate(project)["integridade"], "OK")
            report = (project / "data/processed/relatorio_qualidade.md").read_text(encoding="utf-8")
            self.assertNotIn("2018 não tem observações", report)

    def test_external_source_provenance_and_checksum_are_audited(self):
        etl = self.module()
        with tempfile.TemporaryDirectory() as name:
            project = Path(name)
            raw = project / "raw"
            raw.mkdir()
            path = raw / "ca-2018-02.csv"
            self.frame(**{"Data da Coleta": "01/07/2018"}).to_csv(path, index=False)
            provenance = {"arquivo": "ca-2018-02.csv", "url_oficial": "https://www.gov.br/anp/fonte-oficial", "sha256": etl.sha256_file(path), "baixado_em_utc": "2026-11-11T00:00:00Z"}
            (raw / "fontes_externas.json").write_text(json.dumps({"fontes": [provenance]}), encoding="utf-8")
            etl.run_pipeline(raw, project, expected_files=["ca-2018-02.csv"])
            report = json.loads((project / "data/processed/relatorio_qualidade.json").read_text(encoding="utf-8"))
            self.assertEqual(report["fontes"][0].get("proveniencia_externa"), provenance)
            self.assertIn("https://www.gov.br/anp/fonte-oficial", (project / "data/processed/relatorio_qualidade.md").read_text(encoding="utf-8"))
            provenance["sha256"] = "0" * 64
            (raw / "fontes_externas.json").write_text(json.dumps({"fontes": [provenance]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                etl.run_pipeline(raw, project, expected_files=["ca-2018-02.csv"])


if __name__ == "__main__":
    unittest.main()
