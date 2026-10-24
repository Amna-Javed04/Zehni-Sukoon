# ml_research — retired ML artifacts

These files are **research artifacts only. They are NOT used by the application.**

- `RF_model.pkl` — Random Forest PHQ-9 severity classifier
- `xgb_model.pkl` — XGBoost PHQ-9 severity classifier
- `svm_model.pkl` + `svm_scaler.pkl` — scaled SVM PHQ-9 severity classifier
- `label_encoder.pkl` — severity label encoder shared by the three models
- `model.pkl` — an earlier single-model experiment

The app previously ran an ensemble majority vote over these models to pick a
PHQ-9 severity label. That ensemble has been removed: severity now comes
**only** from the standard validated clinical score bands

- **PHQ-9:** 0–4 minimal · 5–9 mild · 10–14 moderate · 15–19 moderately severe · 20–27 severe
- **GAD-7:** 0–4 minimal · 5–9 mild · 10–14 moderate · 15–21 severe

Nothing in `backend/` imports these files, and the `.pkl` files are excluded
from the Docker build context via `.dockerignore`. They are kept here for
historical/research reference only. Loading them would require the removed
dependencies (scikit-learn, xgboost, pandas, numpy, joblib).
