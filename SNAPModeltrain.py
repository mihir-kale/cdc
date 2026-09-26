import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
import xgboost as xgb

# 1. Load dataset and create an immediate copy to prevent fragmentation warnings
df = pd.read_csv("wellbeing.csv")
df = df.copy()

# 2. Update target column name
# Replace 'SNAP' with the exact column header in your CSV file if it differs
target_col = "SNAP"

# 3. Filter out 'Refused' (-1) and 'Not sure' (8), keeping only 0 and 1
df = df[df[target_col].isin([0, 1])].copy()

# 4. Derive child count and child ratio features
if all(col in df.columns for col in ["PPT01", "PPT25", "PPT612", "PPT1317"]):
    df["total_children"] = df[
        ["PPT01", "PPT25", "PPT612", "PPT1317"]
    ].sum(axis=1)
elif "total_children" not in df.columns:
    raise KeyError(
        "Child count columns (PPT01, PPT25, etc.) missing from dataset."
    )

df["child_ratio"] = df["total_children"] / df["PPHHSIZE"].clip(lower=1)

# 5. Specify input features and set categorical column types
feature_cols = [
    "agecat",
    "PPEDUC",
    "PPINCIMP",
    "PPMARIT",
    "PPMSACAT",
    "PPHHSIZE",
    "total_children",
    "child_ratio",
    "PCTLT200FPL",
]

cat_cols = ["agecat", "PPEDUC", "PPINCIMP", "PPMARIT", "PPMSACAT"]

for col in cat_cols:
    df[col] = df[col].astype("category")

X = df[feature_cols]
y = df[target_col].astype(int)
weights = df["finalwt"]

print(
    f"Filtered Dataset Shape: {X.shape}\nTarget Distribution:\n{y.value_counts()}\n"
)

# 6. Train / Validation Split
X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
    X, y, weights, test_size=0.20, random_state=42, stratify=y
)

# 7. Train XGBoost Model
model = xgb.XGBClassifier(
    objective="binary:logistic",
    eval_metric="logloss",
    enable_categorical=True,
    tree_method="hist",
    n_estimators=300,
    learning_rate=0.03,
    max_depth=4,
    random_state=42,
)

model.fit(
    X_train,
    y_train,
    sample_weight=w_train,
    eval_set=[(X_val, y_val)],
    sample_weight_eval_set=[w_val],
    verbose=False,
)

# 8. Evaluate Performance
val_probs = model.predict_proba(X_val)[:, 1]
print(
    "Weighted ROC-AUC Score:",
    roc_auc_score(y_val, val_probs, sample_weight=w_val),
)

val_preds = (val_probs >= 0.35).astype(int)
print("\nClassification Report:\n", classification_report(y_val, val_preds))

# 9. Export Trained Artifact
# model.save_model("snap_xgboost.json")
# print("\nModel saved successfully as snap_xgboost.json!")

