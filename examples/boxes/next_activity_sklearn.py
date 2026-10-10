"""A prediction model as a box: a scikit-learn random forest between
*Prefixes* / *Split by time* and *Predict* / *Evaluate predictions*.

Needs scikit-learn (``pip install scikit-learn``); without it the box is
listed greyed out with "needs sklearn".  Any object with ``fit`` and
``predict`` is a Predictor, so every scikit-learn estimator works the same
way: change the two class names below and the box is a different model.
"""

from openprocess import flow
from openprocess.flow import Dataset, Predictor, box


@box(name="Random forest", group="Predict", needs="sklearn")
def random_forest(train: Dataset, trees: int = 100, depth: int = 8, seed: int = 0) -> Predictor:
    """A random forest on the prefix features: a classifier for the next
    activity or the outcome, a regressor for the remaining time.

    trees: how many trees in the forest
    depth: the largest depth of a tree
    seed: the random seed, recorded in the workflow file
    """
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    cls = RandomForestClassifier if train.kind == "classification" else RandomForestRegressor
    model = cls(n_estimators=trees, max_depth=depth, random_state=seed)
    model.fit(train.X, [str(y) if train.kind == "classification" else y for y in train.y])
    model.name = f"Random forest ({trees} trees)"
    flow.note(f"Fitted on {len(train)} prefixes with {len(train.feature_names)} features")
    return model
