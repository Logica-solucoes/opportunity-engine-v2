import logging

import pytest

from engine.logmessages import forward_logs, translate_line


def test_translate_line_individual_curve_plot():
    line = (
        "Individual curve plot saved for GOOGLE DISPLAY/VIDEO: "
        "C:\\Users\\x\\outputs/user_1/Proj\\global_saturation_analysis\\individual_response_curve_GOOGLE_DISPLAY_VIDEO.png"
    )
    assert translate_line(line) == "   - Gráfico de saturação gerado para: GOOGLE DISPLAY/VIDEO"


def test_translate_line_suppressed_patterns():
    assert translate_line("=" * 50) is None
    assert translate_line("-" * 50) is None
    assert translate_line("Generating Global Gemini Report...") is None
    assert translate_line("Assembling Gemini HTML report to 'C:\\path\\to\\report.html'...") is None
    assert translate_line("Generating Markdown report to 'C:\\path\\to\\report.md'...") is None
    assert translate_line("Markdown report generated successfully.") is None


def test_translate_line_report_messages():
    assert translate_line("Global narrative generated and parsed successfully.") == (
        "   - Recomendações geradas com sucesso pela IA."
    )
    assert translate_line("Gemini HTML report saved successfully.") == (
        "   - Relatório de recomendações em HTML gerado com sucesso."
    )


def test_translate_line_additional_patterns():
    assert translate_line("   - Running automated feature selection for causal model...") == (
        "   - Analisando variáveis de contexto para o modelo causal..."
    )
    assert translate_line("C:\\path\\site-packages\\some_lib.py:12: SpecificationWarning: Some warning") is None
    assert translate_line('  warn("Some warning message")') is None
    assert translate_line("  self._init_dates(dates, freq)") is None
    assert translate_line("  trend = spsolve(...)") is None
    assert translate_line("  var *= np.divide(...)") is None
    assert translate_line("  return get_prediction_index(...)") is None


def test_unmatched_lines_pass_through():
    assert translate_line("Estimando o impacto causal") == "Estimando o impacto causal"


@pytest.fixture
def received():
    return []


def test_handler_maps_levels(received):
    log = logging.getLogger("engine.sample")
    with forward_logs(lambda level, message: received.append((level, message))):
        log.debug("detail")
        log.info("Uma etapa")
        log.warning("Um aviso")
        log.error("Um erro")
        log.critical("Algo grave")
    assert received == [("info", "Uma etapa"), ("warning", "Um aviso"), ("error", "Um erro"), ("error", "Algo grave")]


def test_llm_logger_is_forwarded_too(received):
    with forward_logs(lambda level, message: received.append((level, message))):
        logging.getLogger("llm.gemini").warning("Indisponível")
    assert received == [("warning", "Indisponível")]


def test_noise_lines_are_dropped(received):
    with forward_logs(lambda level, message: received.append((level, message))):
        logging.getLogger("engine.sample").info("Generating Global Gemini Report...")
    assert received == []


def test_handler_and_levels_are_restored(received):
    engine_logger = logging.getLogger("engine")
    handlers, level = list(engine_logger.handlers), engine_logger.level
    with forward_logs(lambda level, message: received.append((level, message))):
        pass
    assert engine_logger.handlers == handlers and engine_logger.level == level
    logging.getLogger("engine.sample").warning("depois")
    assert received == []


def test_handler_is_removed_when_the_body_raises(received):
    engine_logger = logging.getLogger("engine")
    handlers = list(engine_logger.handlers)
    with pytest.raises(RuntimeError), forward_logs(lambda level, message: received.append((level, message))):
        raise RuntimeError("boom")
    assert engine_logger.handlers == handlers


def test_nothing_is_written_to_stdout(capfd, received):
    with forward_logs(lambda level, message: received.append((level, message))):
        logging.getLogger("engine.sample").info("Uma etapa")
    out, _ = capfd.readouterr()
    assert out == ""


def test_absolute_paths_are_reduced_to_the_file_name(received):
    log = logging.getLogger("engine.sample")
    with forward_logs(lambda level, message: received.append((level, message))):
        log.warning("Image file not found at /srv/data/ws/1/sim/2/inputs/abc.csv. It will be omitted.")
        log.info("Saved to '/tmp/run/out/report.html' and /tmp/x.png")
    assert received == [
        ("warning", "Image file not found at abc.csv. It will be omitted."),
        ("info", "Saved to 'report.html' and x.png"),
    ]


def test_english_elasticity_lines_are_translated_and_windows_paths_hidden(received):
    log = logging.getLogger("engine.sample")
    with forward_logs(lambda level, message: received.append((level, message))):
        log.info("   - Stage 1: Modeling Organic Baseline...")
        log.info("   - Total Marketing Contribution: 15,756,327.43 (149.05% of Total)")
        log.info(r"   - Simulation data exported for UI: C:\Users\x\Temp\tmp1\response_curve_data.csv")
        log.warning(r"Falha ao ler C:\Users\x\Temp\dados.csv agora")
    assert received == [
        ("info", "   - Etapa 1: modelando o baseline orgânico..."),
        ("info", "   - Contribuição total de marketing: 15,756,327.43 (149.05% do total)"),
        ("warning", "Falha ao ler dados.csv agora"),
    ]


def test_translate_line_numpy_scalar_and_dict_reprs():
    line = "   - Calculated channel investment proportions: {'YOUTUBE': np.float64(0.6145), 'META': 0.3855}"
    assert translate_line(line) == "   - Proporção de investimento calculada por canal: YOUTUBE: 0,61, META: 0,39"
    assert translate_line("x np.float64(1.5) y") == "x 1,50 y"
