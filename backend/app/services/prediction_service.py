"""Churn and spend predictions: stored batch scores by customer id, or on-demand inference
from a feature payload with the latest registered model. Every call is logged."""

import json
import time

import pandas as pd
import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.orm import Session

from app.core.errors import ApiError, not_found
from app.models.entities import PredictionLog, User
from app.repositories.base import one
from app.schemas.predictions import CATEGORICAL_FEATURES, NUMERIC_FEATURES, PredictionRequest
from app.services.model_registry import load_latest

CHURN_MODEL, SPEND_MODEL = "repurchase_propensity", "customer_spend_90d"


def _frame(req: PredictionRequest) -> pd.DataFrame:
    data = req.features.model_dump()
    return pd.DataFrame([{c: data[c] for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES}]).astype(
        {c: float for c in NUMERIC_FEATURES}
    )


def _validate(req: PredictionRequest) -> None:
    if (req.customer_unique_id is None) == (req.features is None):
        raise ApiError(
            422, "validation_error", "Provide exactly one of customer_unique_id or features"
        )


def _log(session, request, user, model, version, mode, req, output, started):
    session.add(
        PredictionLog(
            user_id=user.id,
            model_name=model,
            model_version=version,
            mode=mode,
            customer_unique_id=req.customer_unique_id,
            inputs=req.features.model_dump() if req.features else None,
            output=output,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=getattr(request.state, "request_id", None),
        )
    )


def churn(
    conn: sa.Connection, session: Session, request: Request, user: User, req: PredictionRequest
) -> dict:
    _validate(req)
    started = time.perf_counter()
    if req.customer_unique_id:
        row = one(
            conn,
            """select repurchase_probability_90d, churn_risk_90d, propensity_decile,
                                  churn_risk_band, top_reasons, scored_at_cutoff, model_version
                           from ml.customer_repurchase_scores where customer_unique_id = :c""",
            c=req.customer_unique_id,
        )
        if row is None:
            raise not_found("Customer score")
        row["top_reasons"] = json.loads(row["top_reasons"]) if row["top_reasons"] else []
        out = {"mode": "stored", "model": CHURN_MODEL, **row}
        _log(
            session,
            request,
            user,
            CHURN_MODEL,
            row["model_version"],
            "stored",
            req,
            {"churn_risk_90d": row["churn_risk_90d"]},
            started,
        )
        return out
    m = load_latest(CHURN_MODEL)
    p = float(m.model.predict_proba(_frame(req))[0, 1])
    # Position against the stored population so the absolute number has context.
    pct = one(
        conn,
        """select avg((repurchase_probability_90d < :p)::int) as pct
                       from ml.customer_repurchase_scores""",
        p=p,
    )["pct"]
    out = {
        "mode": "on_demand",
        "model": CHURN_MODEL,
        "model_version": m.version,
        "repurchase_probability_90d": p,
        "churn_risk_90d": 1 - p,
        "propensity_percentile": pct,
        "note": "Historical model (2017-2018 Olist data); churn = no repurchase in 90 days.",
    }
    _log(
        session,
        request,
        user,
        CHURN_MODEL,
        m.version,
        "on_demand",
        req,
        {"churn_risk_90d": 1 - p},
        started,
    )
    return out


def spend(
    conn: sa.Connection, session: Session, request: Request, user: User, req: PredictionRequest
) -> dict:
    _validate(req)
    started = time.perf_counter()
    if req.customer_unique_id:
        row = one(
            conn,
            """select predicted_spend_brl, baseline_spend_brl, historical_spend_brl,
                                  horizon_days, scored_at_cutoff, model_version
                           from ml.customer_spend_predictions where customer_unique_id = :c""",
            c=req.customer_unique_id,
        )
        if row is None:
            raise not_found("Customer prediction")
        _log(
            session,
            request,
            user,
            SPEND_MODEL,
            row["model_version"],
            "stored",
            req,
            {"predicted_spend_brl": row["predicted_spend_brl"]},
            started,
        )
        return {"mode": "stored", "model": SPEND_MODEL, **row}
    m = load_latest(SPEND_MODEL)
    value = max(float(m.model.predict(_frame(req))[0]), 0.0)
    _log(
        session,
        request,
        user,
        SPEND_MODEL,
        m.version,
        "on_demand",
        req,
        {"predicted_spend_brl": value},
        started,
    )
    return {
        "mode": "on_demand",
        "model": SPEND_MODEL,
        "model_version": m.version,
        "predicted_spend_brl": round(value, 2),
        "horizon_days": 90,
        "note": "Predicted GMV, not profit; weak signal (see model card).",
    }
