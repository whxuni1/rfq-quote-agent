"""Evaluation framework for the RFQ quote agent.

Deterministic scoring lives in this package. Model-judged rubrics are described
and are not executed unless a live judge with a recorded model id is supplied.
The default runner never supplies one, and it does not invent metric values.
"""

__version__ = "0.1.0"
