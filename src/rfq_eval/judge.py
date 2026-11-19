"""Model-judged rubrics.

The deterministic runner does not construct scores. A live judge would have to
supply a model id and a prompt hash; this module does not call one.
"""

from rfq_eval.schema import ModelBasedSection

RUBRICS = (
    "quote_letter_grounding: every number in the quote letter also appears in the cost sheet",
    "ambiguity_wording: flag prose adds no commercial commitment beyond the cited source",
    "risk_wording: risk text stays inside the cited source and the rule that raised it",
)


def model_based_section() -> ModelBasedSection:
    return ModelBasedSection(
        status="not_run",
        reason=(
            "The deterministic runner does not call a model judge. "
            "Model-based scores are withheld until a live judge records its model id and prompt hash."
        ),
        scores=None,
        rubrics=list(RUBRICS),
    )
