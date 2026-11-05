"""Metrics and diagnostic plots shared by the customer models."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402
from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    mean_absolute_error,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

ACCENT, ACCENT2, MUTED, GRID = "#2a78d6", "#eb6834", "#52514e", "#e4e3df"


def classification_metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float]:
    """Threshold-free metrics plus top-decile precision/recall/lift."""
    k = max(1, int(round(len(y) * 0.1)))
    top = np.argsort(-score, kind="stable")[:k]
    base = y.mean()
    out = {
        "roc_auc": roc_auc_score(y, score),
        "pr_auc": average_precision_score(y, score),
        "base_rate": base,
        "precision_top_decile": y[top].mean(),
        "recall_top_decile": y[top].sum() / max(y.sum(), 1),
        "lift_top_decile": y[top].mean() / base if base else np.nan,
    }
    if np.all((score >= 0) & (score <= 1)):
        out["brier"] = brier_score_loss(y, score)
        out["log_loss"] = log_loss(y, np.clip(score, 1e-6, 1 - 1e-6))
    return {k: float(v) for k, v in out.items()}


def bootstrap_ci(
    y: np.ndarray, score: np.ndarray, metric, n: int = 500, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile bootstrap CI of metric(y, score), resampling customers with replacement."""
    rng = np.random.default_rng(seed)
    stats = [
        metric(y[idx], score[idx]) for idx in (rng.integers(0, len(y), len(y)) for _ in range(n))
    ]
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def best_f1_threshold(y: np.ndarray, proba: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y, proba)
    f1 = 2 * precision * recall / np.where(precision + recall == 0, 1, precision + recall)
    return float(thresholds[np.argmax(f1[:-1])])


def threshold_metrics(y: np.ndarray, proba: np.ndarray, threshold: float) -> dict:
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
    }  # fmt: skip


def rmse(y: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - pred) ** 2)))


def top_decile_capture(y: np.ndarray, pred: np.ndarray) -> float:
    """Share of actual total spend made by the 10% of customers with the highest predictions."""
    k = max(1, int(round(len(y) * 0.1)))
    top = np.argsort(-pred, kind="stable")[:k]
    return float(y[top].sum() / y.sum()) if y.sum() else np.nan


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    """MAE/RMSE plus scale-free metrics valid with mostly-zero targets (no MAPE)."""
    k = max(1, int(round(len(y) * 0.1)))
    top = np.argsort(-pred, kind="stable")[:k]
    mean = y.mean()
    rho = spearmanr(y, pred).statistic if np.std(pred) > 0 else np.nan
    return {
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(np.sqrt(np.mean((y - pred) ** 2))),
        "normalized_mae": float(mean_absolute_error(y, pred) / mean) if mean else np.nan,
        "normalized_rmse": float(np.sqrt(np.mean((y - pred) ** 2)) / mean) if mean else np.nan,
        "total_actual": float(y.sum()),
        "total_predicted": float(pred.sum()),
        "top_decile_spend_capture": float(y[top].sum() / y.sum()) if y.sum() else np.nan,
        "spearman": float(rho),
    }


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_classification(y, curves: dict[str, np.ndarray], path: Path, title: str) -> Path:
    """PR curve, ROC curve and reliability diagram for one or more scored models."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), dpi=110)
    colors = [ACCENT, ACCENT2, "#1baf7a", "#6250d6", MUTED]
    for (name, score), color in zip(curves.items(), colors, strict=False):
        p, r, _ = precision_recall_curve(y, score)
        axes[0].plot(
            r, p, color=color, lw=1.6, label=f"{name} (AP {average_precision_score(y, score):.3f})"
        )
        fpr, tpr, _ = roc_curve(y, score)
        axes[1].plot(
            fpr, tpr, color=color, lw=1.6, label=f"{name} (AUC {roc_auc_score(y, score):.3f})"
        )
        if np.all((score >= 0) & (score <= 1)):
            frac, mean_pred = calibration_curve(y, score, n_bins=10, strategy="quantile")
            axes[2].plot(mean_pred, frac, marker="o", ms=4, color=color, lw=1.4, label=name)
    axes[0].axhline(y.mean(), color=MUTED, ls="--", lw=1, label=f"base rate {y.mean():.3%}")
    axes[1].plot([0, 1], [0, 1], color=MUTED, ls="--", lw=1)
    lim = max(axes[2].get_xlim()[1], axes[2].get_ylim()[1])
    axes[2].plot([0, lim], [0, lim], color=MUTED, ls="--", lw=1)
    for ax, t, xl, yl in zip(
        axes, ["Precision-recall", "ROC", "Calibration (quantile bins)"],
        ["recall", "false positive rate", "mean predicted probability"],
        ["precision", "true positive rate", "observed repurchase rate"], strict=True,
    ):  # fmt: skip
        _style(ax, t)
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_importance(names: list[str], values: np.ndarray, path: Path, title: str, top=20) -> Path:
    order = np.argsort(values)[::-1][:top][::-1]
    fig, ax = plt.subplots(figsize=(8, 0.32 * len(order) + 1.2), dpi=110)
    ax.barh([names[i] for i in order], values[order], color=ACCENT, height=0.7)
    _style(ax, title)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("mean |SHAP value|")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
