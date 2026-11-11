"""Regression checks for the analytical rules exposed by the dashboard."""
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fuel_dashboard.logic import (Filters, summarize, election_comparison,
                                  monthly_changes, query_table, chart_segments)


class DashboardLogicTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame({
            "ano": [2022, 2022, 2022, 2022, 2023],
            "mes": [7, 7, 8, 10, 7],
            "regiao": ["Nordeste"] * 5,
            "uf": ["BA", "BA", "BA", "PE", "BA"],
            "municipio": ["SALVADOR", "SALVADOR", "SALVADOR", "RECIFE", "SALVADOR"],
            "produto": ["GASOLINA COMUM"] * 4 + ["GNV"],
            "preco_venda": [4.0, 8.0, 9.0, 3.0, 5.0],
            "posto_id": ["A", "A", "B", None, "C"],
        })

    def test_summary_is_pooled_observation_mean_and_station_identity_is_distinct(self):
        result = summarize(self.rows.iloc[:4])
        self.assertEqual(result["kpis"]["media"], 6.0)
        self.assertEqual(result["kpis"]["postos"], 2)
        self.assertEqual(result["kpis"]["registros"], 4)
        self.assertEqual(result["mensal"].loc[result["mensal"]["mes"].eq(7), "municipios"].iloc[0], 1)
        self.assertEqual(result["anual"].iloc[0]["preco_medio"], 6.0)
        self.assertEqual(result["histograma"]["registros"].sum(), 4)

    def test_monthly_variation_does_not_cross_missing_september_or_year(self):
        monthly = summarize(self.rows)["mensal"]
        changes = monthly_changes(monthly)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes.iloc[0]["mes"], 8)
        self.assertAlmostEqual(changes.iloc[0]["variacao_pct"], 50.0)

    def test_lines_split_when_months_are_not_consecutive(self):
        monthly = summarize(self.rows)["mensal"]
        lines = chart_segments(monthly)
        self.assertEqual(lines.loc[lines["mes"] == 7, "segmento"].nunique(), 2)
        self.assertNotEqual(lines.iloc[1]["segmento"], lines.iloc[2]["segmento"])

    def test_elections_require_both_endpoints_and_do_not_impute_2018(self):
        monthly = summarize(self.rows.iloc[:4])["mensal"]
        comparison = election_comparison(monthly, [2018, 2022], [7, 8, 9, 10])
        first = comparison.set_index("ano").loc[2018]
        self.assertTrue(pd.isna(first["variacao_pct"]))
        self.assertIn("Sem dados", first["situacao"])
        last = comparison.set_index("ano").loc[2022]
        self.assertAlmostEqual(last["variacao_abs"], -3.0)
        self.assertAlmostEqual(last["variacao_pct"], -50.0)
        self.assertEqual(last["registros_julho"], 2)
        self.assertEqual(last["registros_outubro"], 1)

    def test_default_years_follow_coverage_instead_of_excluding_a_specific_year(self):
        from fuel_dashboard.logic import default_years
        self.assertEqual(default_years([2018, 2022], {"2018": [1, 2, 3, 4, 5, 6], "2022": [7, 8, 9, 10]}), [2022])
        self.assertEqual(default_years([2018, 2022], {"2018": [7, 8, 9, 10], "2022": [7, 8, 9, 10]}), [2018, 2022])

    def test_available_2018_second_semester_has_real_four_month_comparison(self):
        rows = pd.concat([self.rows.iloc[[0]]] * 4, ignore_index=True)
        rows["ano"] = 2018
        rows["mes"] = [7, 8, 9, 10]
        rows["preco_venda"] = [4.0, 4.2, 4.4, 4.8]
        summary = summarize(rows)
        self.assertEqual(summary["mensal"]["mes"].tolist(), [7, 8, 9, 10])
        result = election_comparison(summary["mensal"], [2018, 2022], [7, 8, 9, 10]).set_index("ano")
        self.assertEqual(result.loc[2018, "situacao"], "Disponível")
        self.assertAlmostEqual(result.loc[2018, "variacao_abs"], .8)
        self.assertAlmostEqual(result.loc[2018, "variacao_pct"], 20.0)
        self.assertTrue(pd.isna(result.loc[2022, "variacao_pct"]))

    def test_parquet_filters_keep_product_unit_and_do_not_leak_other_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            pq.write_table(pa.Table.from_pandas(self.rows), Path(tmp) / "part.parquet")
            filtered = query_table(tmp, Filters(years=(2023,), months=(7,), product="GNV", ufs=("BA",)))
            self.assertEqual(filtered.num_rows, 1)
            self.assertEqual(filtered.column("produto").to_pylist(), ["GNV"])
            empty = query_table(tmp, Filters(years=(2018,), months=(7,), product="GASOLINA COMUM"))
            self.assertEqual(empty.num_rows, 0)

    def test_missing_july_or_october_selection_is_explicit(self):
        monthly = summarize(self.rows.iloc[:4])["mensal"]
        comparison = election_comparison(monthly, [2022], [7, 8])
        self.assertTrue(pd.isna(comparison.iloc[0]["variacao_pct"]))
        self.assertIn("filtro", comparison.iloc[0]["situacao"].lower())

    def test_search_filters_dictionary_encoded_parquet_case_insensitively(self):
        rows = self.rows.copy()
        rows["municipio"] = rows["municipio"].astype("category")
        with tempfile.TemporaryDirectory() as tmp:
            pq.write_table(pa.Table.from_pandas(rows), Path(tmp) / "part.parquet")
            result = query_table(tmp, Filters(years=(2022,), product="GASOLINA COMUM"), search="recife")
            self.assertEqual(result.num_rows, 1)
            self.assertEqual(result.column("uf").to_pylist(), ["PE"])

    def test_municipality_selection_preserves_uf_for_homonyms_and_multiple_pairs(self):
        rows = pd.DataFrame({"ano": [2022] * 4, "mes": [7] * 4,
                             "produto": ["GASOLINA COMUM"] * 4,
                             "uf": ["BA", "BA", "RJ", "RJ"],
                             "municipio": ["VALENCA", "SALVADOR", "VALENCA", "SALVADOR"],
                             "posto_id": ["A", "B", "C", "D"]})
        with tempfile.TemporaryDirectory() as tmp:
            pq.write_table(pa.Table.from_pandas(rows), Path(tmp) / "part.parquet")
            one = query_table(tmp, Filters(years=(2022,), municipalities=(("BA", "VALENCA"),)))
            self.assertEqual(one.column("posto_id").to_pylist(), ["A"])
            pairs = query_table(tmp, Filters(years=(2022,), municipalities=(("BA", "SALVADOR"), ("RJ", "VALENCA"))))
            self.assertEqual(pairs.column("posto_id").to_pylist(), ["B", "C"])

    def test_map_winding_is_clockwise_for_plotly_without_mutating_source(self):
        from copy import deepcopy
        from fuel_dashboard.logic import plotly_geojson
        ccw = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        clockwise_hole = [[.5, .5], [.5, 1], [1, 1], [1, .5], [.5, .5]]
        source = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"codarea": "29"}, "geometry": {"type": "Polygon", "coordinates": [ccw, clockwise_hole]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": [[ccw]]}}]}
        original = deepcopy(source)
        result = plotly_geojson(source)
        self.assertEqual(result["features"][0]["geometry"]["coordinates"][0], list(reversed(ccw)))
        self.assertEqual(result["features"][0]["geometry"]["coordinates"][1], list(reversed(clockwise_hole)))
        self.assertEqual(result["features"][1]["geometry"]["coordinates"][0][0], list(reversed(ccw)))
        self.assertEqual(source, original)
        self.assertEqual(result["features"][0]["properties"]["codarea"], "29")


if __name__ == "__main__":
    unittest.main()
