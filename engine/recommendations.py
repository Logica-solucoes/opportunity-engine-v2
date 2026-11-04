"""
This module generates recommendation outputs, including budget scenarios
and strategic markdown files.
"""

import logging
import os

from engine.presentation import format_number

log = logging.getLogger(__name__)

# --- Budget Scenario Generation ---


def generate_basic_recommendations_file(results_data, config, output_dir):
    """
    Generates a basic recommendations markdown file when elasticity is not available.
    """
    try:
        avg_ticket = config["average_ticket"]
        conversion_rate = config["conversion_rate_from_kpi_to_bo"]
        optimization_target = config["optimization_target"].upper()

        causal_incremental_kpi = results_data.get("absolute_lift", 0)
        causal_incremental_orders = causal_incremental_kpi * conversion_rate
        causal_incremental_revenue = causal_incremental_orders * avg_ticket

        inv_pre = results_data.get("total_investment_pre_period", 0)
        inv_post = results_data.get("total_investment_post_period", 0)
        investment_change = inv_post - inv_pre

        if optimization_target == "REVENUE":
            gain_metric = "em receita incremental"
            formatted_gain = format_number(causal_incremental_revenue, currency=True)
            roas = causal_incremental_revenue / investment_change if investment_change > 0 else 0
            efficiency_text = f"O ROAS (Retorno sobre Investimento em Publicidade) real foi de **{roas:.2f}x**."
        else:
            gain_metric = "em conversões incrementais"
            formatted_gain = format_number(causal_incremental_orders)
            cpa = investment_change / causal_incremental_orders if causal_incremental_orders > 0 else 0
            efficiency_text = (
                f"O custo por aquisição incremental (iCPA) foi de **{format_number(cpa, currency=True)}**."
            )

        recommendation_text = (
            f"A análise de Impacto Causal indica que a mudança de investimento "
            f"gerou um impacto de **{formatted_gain}** {gain_metric}. "
            f"{efficiency_text}\n\n"
            f"**Estatísticas do Modelo:**\n"
            f"- Aumento de Investimento: **{results_data.get('investment_change_pct', 0):.2f}%**\n"
            f"- Confiança Estatística: **{(1 - results_data.get('p_value', 1)) * 100:.2f}%**\n"
            f"- Precisão do Modelo (R²): **{results_data.get('model_r_squared', 0):.4f}**\n"
        )

        content = f"""# Resumo de Impacto Causal

## Análise da Oportunidade
{recommendation_text}
"""
        output_path = os.path.join(output_dir, "RECOMMENDATIONS.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        log.info(f"   - Successfully generated basic recommendations file at: {output_path}")

    except Exception as e:
        log.error(
            f"   - ERROR: Could not generate basic recommendations file. Details: {e}",
            exc_info=True,
        )
