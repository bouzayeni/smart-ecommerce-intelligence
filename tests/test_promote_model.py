"""Quality gate of the champion promotion (pure logic, no registry)."""

import pytest

from ml.promote_model import GATES, Gate, decide

HIGHER = Gate("test_pr_auc", True, 0.005)
LOWER = Gate("test_rmse", False, 0.5)


@pytest.mark.parametrize(
    ("gate", "candidate", "champion", "promote"),
    [
        (HIGHER, 0.020, None, True),  # first champion
        (HIGHER, 0.020, 0.018, True),  # better
        (HIGHER, 0.0145, 0.018, True),  # worse, within tolerance (-0.0035)
        (HIGHER, 0.010, 0.018, False),  # worse beyond tolerance
        (LOWER, 17.0, 17.4, True),  # lower rmse is better
        (LOWER, 17.8, 17.4, True),  # +0.4 within 0.5
        (LOWER, 18.5, 17.4, False),
        (HIGHER, None, 0.018, False),  # metric missing on the candidate run
    ],
)
def test_gate(gate, candidate, champion, promote):
    assert decide(gate, candidate, champion).promote is promote


def test_every_registered_model_has_a_gate():
    assert set(GATES) == {"repurchase_propensity", "customer_spend_90d"}
