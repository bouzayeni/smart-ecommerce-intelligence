"""The API's on-demand feature payload must match the features the models were trained on."""

from app.schemas.predictions import CATEGORICAL_FEATURES, NUMERIC_FEATURES, CustomerFeatures
from ml.customer import features as training


def test_feature_lists_match_training():
    assert NUMERIC_FEATURES == training.NUMERIC_FEATURES
    assert CATEGORICAL_FEATURES == training.CATEGORICAL_FEATURES


def test_payload_model_covers_every_feature():
    assert set(CustomerFeatures.model_fields) == set(NUMERIC_FEATURES + CATEGORICAL_FEATURES)
