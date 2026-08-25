import os
import joblib
import numpy as np

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(base_dir, "models")
    if not os.path.exists(models_dir):
        models_dir = base_dir

    print("--- Loading ML Models and Artifacts ---")
    le = joblib.load(os.path.join(models_dir, "label_encoder.pkl"))
    rf_model = joblib.load(os.path.join(models_dir, "RF_model.pkl"))
    svm_model = joblib.load(os.path.join(models_dir, "svm_model.pkl"))
    svm_scaler = joblib.load(os.path.join(models_dir, "svm_scaler.pkl"))
    xgb_model = joblib.load(os.path.join(models_dir, "xgb_model.pkl"))
    print("All models successfully loaded!\n")

    # Sample 11-feature input vector: 9 PHQ-9 scores + age + gender_code
    # Example scores: [2, 2, 3, 2, 1, 2, 1, 0, 1] -> total score = 14
    phq_answers = [2, 2, 3, 2, 1, 2, 1, 0, 1]
    age = 35
    gender_code = 2  # 1: Male, 2: Female
    
    input_vector = phq_answers + [age, gender_code]
    X = np.array(input_vector).reshape(1, -1)
    
    print(f"Sample Input Vector (11 features): {input_vector}")
    print(f"Total PHQ-9 Score: {sum(phq_answers)} / 27\n")

    results = {}

    # 1. Random Forest (unscaled features)
    rf_pred = rf_model.predict(X)[0]
    rf_label = le.inverse_transform([rf_pred])[0]
    rf_proba = float(np.max(rf_model.predict_proba(X)[0])) * 100
    results["Random Forest"] = {"prediction": rf_label, "confidence": round(rf_proba, 1)}

    # 2. XGBoost (unscaled features)
    xgb_pred = xgb_model.predict(X)[0]
    xgb_label = le.inverse_transform([xgb_pred])[0]
    xgb_proba = float(np.max(xgb_model.predict_proba(X)[0])) * 100
    results["XGBoost"] = {"prediction": xgb_label, "confidence": round(xgb_proba, 1)}

    # 3. SVM (scaled features via svm_scaler)
    X_scaled = svm_scaler.transform(X)
    svm_pred = svm_model.predict(X_scaled)[0]
    svm_label = le.inverse_transform([svm_pred])[0]
    svm_proba = float(np.max(svm_model.predict_proba(X_scaled)[0])) * 100
    results["SVM"] = {"prediction": svm_label, "confidence": round(svm_proba, 1)}

    # Predictions summary & majority vote
    predictions = [res["prediction"] for res in results.values()]
    majority_vote = max(set(predictions), key=predictions.count)
    agreement_count = predictions.count(majority_vote)

    print("--- Model Predictions ---")
    for model_name, data in results.items():
        print(f" - {model_name:15s}: Severity = {data['prediction']:18s} | Confidence = {data['confidence']:.1f}%")

    print("\n--- Summary & Majority Vote ---")
    print(f"Majority Vote Severity : {majority_vote}")
    print(f"Model Agreement        : {agreement_count}/3 models agree ({predictions})")

if __name__ == "__main__":
    main()
