"""Reads and normalizes the three input CSVs and collects what is wrong with them.

`validate` reports the collected checks; `load_and_prepare_data` raises the first error. Both start here, so a file the
validation accepts is read the same way by the run.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from engine.data_preprocessor import (
    drop_bi_export_footer_rows,
    parse_investment_columns,
    read_csv_robust,
    resolve_column,
    robust_date_parsing,
    robust_numeric_parsing,
)
from engine.errors import EngineError
from engine.results_schema import Check

log = logging.getLogger(__name__)

_FILE_LABEL = {
    "investment_file": "de investimento",
    "performance_file": "de performance",
    "generic_trends_file": "de tendências",
}


@dataclass
class RawInputs:
    kpi_df: pd.DataFrame  # Date, kpi
    investment_df: pd.DataFrame  # Date, Product Group, investment
    trends_df: pd.DataFrame  # Date, Generic Searches
    performance_df: pd.DataFrame  # the performance file as sent (date column renamed to Date), kept for covariates
    checks: list[Check] = field(default_factory=list)


def _empty_trends() -> pd.DataFrame:
    return pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]"), "Generic Searches": pd.Series(dtype="float64")})


def _read(paths: dict, key: str) -> pd.DataFrame:
    try:
        return read_csv_robust(paths[key])
    except (KeyError, TypeError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as e:
        raise EngineError(
            f"O arquivo {_FILE_LABEL[key]} não foi encontrado ou não pôde ser lido. Envie o arquivo novamente.",
            "file_unreadable",
        ) from e


def _column(df: pd.DataFrame, configured: str, hint: str, description: str) -> str:
    try:
        return resolve_column(df, configured, hint, description)
    except ValueError as e:
        raise EngineError(str(e), "column_missing") from e


def _dates(series: pd.Series, date_format: str | None) -> pd.Series:
    try:
        return robust_date_parsing(series, date_format=date_format)
    except ValueError as e:
        raise EngineError(str(e), "date_unparseable") from e


def _not_numeric(label: str, column: str, ratio: float, examples: list, hint: str) -> Check:
    return Check(
        id="value_not_numeric",
        level="error",
        message=(
            f"A coluna '{column}' do arquivo {label} não pôde ser convertida para número em mais de 50% das "
            f"linhas ({ratio:.0%} inválido). Isso geralmente indica que a coluna errada foi escolhida. "
            f"Exemplos de valores encontrados: {examples}. {hint}"
        ),
        details={"column": column, "invalid_ratio": round(float(ratio), 4), "examples": [str(x) for x in examples]},
    )


def _iso(dates) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in dates]


def _varying_text_columns(performance_df: pd.DataFrame, kpi_df: pd.DataFrame, repeated, skip: set[str]) -> list[str]:
    """Text columns of the performance file whose value differs between rows sharing a date (a source or channel)."""
    rows = performance_df.loc[kpi_df.index[repeated]].assign(_date=kpi_df.loc[kpi_df.index[repeated], "Date"])
    found = []
    for column in performance_df.columns:
        if column in skip or column == "_date":
            continue
        values = rows[column]
        if pd.api.types.is_numeric_dtype(values):
            continue
        if robust_numeric_parsing(values, column_name=str(column)).notna().mean() >= 0.9:
            continue  # numbers written in a local format, not a label
        if (rows.assign(_v=values).groupby("_date")["_v"].nunique() > 1).any():
            found.append(str(column))
    return found


def _duplicate_checks(
    investment_df: pd.DataFrame, kpi_df: pd.DataFrame, performance_df: pd.DataFrame, kpi_value_col: str
) -> list[Check]:
    checks = []
    twice = investment_df.duplicated(["Date", "Product Group"], keep="first")
    if twice.any():
        sample = investment_df[twice].head(5)
        checks.append(
            Check(
                id="duplicate_date_channel",
                level="error",
                message=(
                    f"Há {int(twice.sum())} linha(s) repetida(s) para a mesma data e o mesmo canal no arquivo de "
                    "investimento. Remova ou consolide as duplicatas e envie o arquivo novamente."
                ),
                details={
                    "count": int(twice.sum()),
                    "examples": [
                        {"date": d.strftime("%Y-%m-%d"), "channel": c}
                        for d, c in zip(sample["Date"], sample["Product Group"])
                    ],
                },
            )
        )
    repeated = kpi_df["Date"].duplicated(keep=False).to_numpy()
    if repeated.any():
        dates = _iso(sorted(kpi_df.loc[kpi_df["Date"].duplicated(keep="first"), "Date"].unique())[:10])
        count = int(kpi_df["Date"].duplicated().sum())
        columns = _varying_text_columns(performance_df, kpi_df, repeated, {"Date", kpi_value_col})
        if columns:
            checks.append(
                Check(
                    id="kpi_not_single_source",
                    level="error",
                    message=(
                        f"O arquivo de performance tem mais de uma linha por data, separadas por "
                        f"{', '.join(repr(c) for c in columns)}. Conversões reportadas por plataforma ou canal não "
                        "formam uma fonte única. Envie o total por data."
                    ),
                    details={"columns": columns, "dates": dates[:5]},
                )
            )
        else:
            checks.append(
                Check(
                    id="kpi_duplicate_dates",
                    level="error",
                    message=(f"O arquivo de performance tem {count} data(s) repetida(s). Envie uma linha por data."),
                    details={"count": count, "dates": dates},
                )
            )
    return checks


def _read_inputs(config: dict, paths: dict[str, Path | None]) -> RawInputs:
    """`config` is the legacy dict (`column_mapping`, `date_formats`, `performance_kpi_column`); it is only read."""
    mapping = config["column_mapping"]
    inv_map = mapping.get("investment_file", {})
    perf_map = mapping.get("performance_file", {})
    trends_map = mapping.get("generic_trends_file", {})
    date_formats = config["date_formats"]
    checks: list[Check] = []

    kpi_df = _read(paths, "performance_file")
    performance_raw = kpi_df.copy()
    investment_df = _read(paths, "investment_file")

    if paths.get("generic_trends_file"):
        trends_df = _read(paths, "generic_trends_file")
        date_col = _column(
            trends_df,
            trends_map.get("date_col", "Start Date"),
            "date",
            "coluna de data do arquivo de tendências",
        )
        value_col = _column(
            trends_df,
            trends_map.get("trends_col", "Ad Opportunities"),
            "trends",
            "coluna de valor do arquivo de tendências",
        )
        trends_df = trends_df.rename(columns={date_col: "Date", value_col: "Generic Searches"})
        trends_df = drop_bi_export_footer_rows(trends_df, "Date")
        trends_df["Generic Searches"] = robust_numeric_parsing(
            trends_df["Generic Searches"], column_name="Generic Searches"
        )
        trends_df["Date"] = _dates(trends_df["Date"], date_formats.get("generic_trends_file"))
        trends_df = trends_df.dropna(subset=["Date"])
        trends_df = trends_df[["Date", "Generic Searches"]].sort_values(by="Date").reset_index(drop=True)
    else:
        log.info("   - INFO: No generic trends file path provided. Continuing without trends data.")
        trends_df = _empty_trends()

    kpi_date_col = _column(kpi_df, perf_map.get("date_col", "date"), "date", "coluna de data do arquivo de performance")
    kpi_value_col = _column(
        kpi_df,
        perf_map.get("kpi_col", config["performance_kpi_column"]),
        "kpi",
        "coluna de KPI do arquivo de performance",
    )
    performance_df = performance_raw.rename(columns={kpi_date_col: "Date"})
    kpi_df = kpi_df.rename(columns={kpi_date_col: "Date", kpi_value_col: "kpi"})
    kpi_df = drop_bi_export_footer_rows(kpi_df, "Date")
    kpi_raw_values = kpi_df["kpi"]
    kpi_df["kpi"] = robust_numeric_parsing(kpi_df["kpi"], column_name="kpi")
    kpi_nan_ratio = kpi_df["kpi"].isna().mean() if len(kpi_df) else 0
    if kpi_nan_ratio > 0.5:
        checks.append(
            _not_numeric(
                "de performance",
                kpi_value_col,
                kpi_nan_ratio,
                kpi_raw_values[kpi_df["kpi"].isna()].unique()[:3].tolist(),
                "Verifique a coluna de KPI escolhida no mapeamento.",
            )
        )

    inv_date_col = _column(
        investment_df, inv_map.get("date_col", "dates"), "date", "coluna de data do arquivo de investimento"
    )
    inv_channel_col = _column(
        investment_df,
        inv_map.get("channel_col", "product_group"),
        "channel",
        "coluna de canal do arquivo de investimento",
    )
    inv_value_col = _column(
        investment_df,
        inv_map.get("investment_col", "total_revenue"),
        "investment",
        "coluna de investimento do arquivo de investimento",
    )
    try:
        investment_df, investment_raw_values = parse_investment_columns(
            investment_df,
            inv_date_col,
            inv_channel_col,
            inv_value_col,
            date_format=date_formats.get("investment_file"),
        )
    except ValueError as e:
        raise EngineError(str(e), "date_unparseable") from e
    investment_nan_ratio = investment_df["investment"].isna().mean() if len(investment_df) else 0
    if investment_nan_ratio > 0.5:
        checks.append(
            _not_numeric(
                "de investimento",
                inv_value_col,
                investment_nan_ratio,
                investment_raw_values[investment_df["investment"].isna()].unique()[:3].tolist(),
                "Verifique a coluna de investimento escolhida no mapeamento.",
            )
        )

    kpi_df["Date"] = _dates(kpi_df["Date"], date_formats.get("performance_file"))
    kpi_df = kpi_df.dropna(subset=["Date", "kpi"])
    investment_df = investment_df.dropna(subset=["Date", "investment", "Product Group"])

    checks.extend(_duplicate_checks(investment_df, kpi_df, performance_df, kpi_value_col))

    if kpi_df.empty:
        checks.append(
            Check(
                id="no_valid_rows",
                level="error",
                message=(
                    "Nenhuma linha válida restou no arquivo de performance após a limpeza. "
                    "Verifique o formato da data e do KPI no arquivo."
                ),
                details={"file": "performance_file"},
            )
        )
    if investment_df.empty:
        checks.append(
            Check(
                id="no_valid_rows",
                level="error",
                message=(
                    "Nenhuma linha válida restou no arquivo de investimento após a limpeza. "
                    "Verifique o formato da data, do canal e do investimento no arquivo."
                ),
                details={"file": "investment_file"},
            )
        )

    return RawInputs(
        kpi_df=kpi_df,
        investment_df=investment_df,
        trends_df=trends_df,
        performance_df=performance_df,
        checks=checks,
    )


def cadence_check(inv_cadence: int, kpi_cadence: int) -> Check | None:
    if abs(inv_cadence - kpi_cadence) <= 2:
        return None
    return Check(
        id="cadence_mismatch",
        level="error",
        message=(
            f"Cadências divergentes entre o arquivo de investimento ({inv_cadence} dia(s)) e o arquivo de "
            f"performance ({kpi_cadence} dia(s)). Não é possível conciliar séries com cadências diferentes: "
            "verifique se os dois arquivos reportam na mesma frequência (diária, semanal ou mensal)."
        ),
        details={"investment_days": inv_cadence, "performance_days": kpi_cadence},
    )


def sufficiency_check(investment_df: pd.DataFrame, kpi_df: pd.DataFrame) -> Check | None:
    """What is left after the partial periods are dropped must not be empty."""
    if not investment_df.empty and not kpi_df.empty:
        return None
    return Check(
        id="insufficient_after_partial",
        level="error",
        message=(
            "Após descartar os períodos parciais, não restaram linhas suficientes para continuar a análise. "
            "Verifique a consistência das datas nos arquivos de entrada."
        ),
    )


def apply_channel_groups(investment_df: pd.DataFrame, groups: list[list[str]]) -> pd.DataFrame:
    """Each group becomes one channel named 'A + B', its members' spend summed per date (A3)."""
    if not groups:
        return investment_df
    names = {member: " + ".join(group) for group in groups for member in group}
    renamed = investment_df.assign(**{"Product Group": investment_df["Product Group"].replace(names)})
    return renamed.groupby(["Date", "Product Group"], as_index=False)["investment"].sum()


def read_inputs(config: dict, paths: dict[str, Path | None]) -> RawInputs:
    """Reads the three files. Whatever the data does to the parsers, the caller gets an EngineError with a check id."""
    try:
        return _read_inputs(config, paths)
    except EngineError:
        raise
    except Exception as e:  # odd shapes (numeric channel codes, headers that collide after trimming)
        raise EngineError(
            "Não foi possível interpretar as colunas escolhidas nos arquivos. Confira o mapeamento: o canal deve ser "
            "um texto, e os nomes de coluna não podem se repetir.",
            "column_unusable",
        ) from e
