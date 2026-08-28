import sys
import os

# Add workspace root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.routes.chat import local_heuristic_extract_score

# 20 Realistic PHQ-9 Sample Replies with clinically correct expected scores
phq9_samples = [
    # Roman Urdu
    {"question": "Little interest or pleasure in doing things", "reply": "bilkul nahi dil karta", "expected_score": 3, "clarify": False},
    {"question": "Feeling down, depressed, or hopeless", "reply": "bohat zyaada udas hoon", "expected_score": 3, "clarify": False},
    {"question": "Trouble falling or staying asleep, or sleeping too much", "reply": "neend nahi aati bilkul bhi", "expected_score": 3, "clarify": False},
    {"question": "Feeling tired or having little energy", "reply": "har waqt thaka rehta hoon", "expected_score": 3, "clarify": False},
    {"question": "Poor appetite or overeating", "reply": "kabhi kabhi bhook nahi lagti", "expected_score": 1, "clarify": False},
    
    # Urdu Nastaliq
    {"question": "اپنے بارے میں برا محسوس کرنا", "reply": "بالکل نہیں", "expected_score": 0, "clarify": False},
    {"question": "کسی چیز پر توجہ مرکوز کرنے میں مشکل", "reply": "تقریباً ہر روز یہ مسئلہ ہوتا ہے", "expected_score": 3, "clarify": False},
    {"question": "ہاتھ پاؤں کا ہلنا یا سست ہونا", "reply": "کبھی کبھی", "expected_score": 1, "clarify": False},
    {"question": "مر جانے یا خود کو نقصان پہنچانے کے خیالات", "reply": "بالکل نہیں ایسے کوئی خیالات نہیں ہیں", "expected_score": 0, "clarify": False},
    {"question": "مر جانے یا خود کو نقصان پہنچانے کے خیالات", "reply": "ہاں دل کرتا ہے نقصان پہنچاؤں", "expected_score": 1, "clarify": False}, # Suicide check triggers risk >= 1

    # Vague Answers
    {"question": "Feeling down, depressed, or hopeless", "reply": "pata nahi ajeeb sa lagta hai", "expected_score": None, "clarify": True},
    {"question": "Feeling tired or having little energy", "reply": "bas theek hi hoon", "expected_score": None, "clarify": True},
    {"question": "Little interest or pleasure in doing things", "reply": "samajh nahi aa rahi", "expected_score": None, "clarify": True},
    {"question": "Poor appetite or overeating", "reply": "pata nahi", "expected_score": None, "clarify": True},
    {"question": "Trouble falling or staying asleep", "reply": "kabhi kabhi to ho jata hai", "expected_score": 1, "clarify": False},

    # Code-switched English/Urdu
    {"question": "Feeling down, depressed, or hopeless", "reply": "Mostly normal bas thoda sad lagta hai", "expected_score": 1, "clarify": False},
    {"question": "Little interest or pleasure in doing things", "reply": "I feel zero interest in activities", "expected_score": 3, "clarify": False},
    {"question": "Trouble concentrating on things", "reply": "Daily focus issues hotay hain", "expected_score": 3, "clarify": False},
    {"question": "Feeling tired or having little energy", "reply": "Sometimes energy low ho jati hai", "expected_score": 1, "clarify": False},
    {"question": "Poor appetite or overeating", "reply": "Appetite issues daily basic pay", "expected_score": 3, "clarify": False}
]

# 20 Realistic GAD-7 Sample Replies with clinically correct expected scores
gad7_samples = [
    # Roman Urdu
    {"question": "Feeling nervous, anxious, or on edge", "reply": "har waqt ghabrahat rehti hai", "expected_score": 3, "clarify": False},
    {"question": "Not being able to stop or control worrying", "reply": "bilkul nahi control hota", "expected_score": 3, "clarify": False},
    {"question": "Worrying too much about different things", "reply": "bohat zyaada pareshani hoti hai", "expected_score": 3, "clarify": False},
    {"question": "Trouble relaxing", "reply": "kabhi kabhi relax nahi kar pata", "expected_score": 1, "clarify": False},
    {"question": "Being so restless that it is hard to sit still", "reply": "kabhi kabhi aisa hota hai", "expected_score": 1, "clarify": False},

    # Urdu Nastaliq
    {"question": "بے چینی یا گھبراہٹ محسوس کرنا", "reply": "بالکل نہیں", "expected_score": 0, "clarify": False},
    {"question": "فکر کو کنٹرول نہ کر پانا", "reply": "تقریباً ہر روز", "expected_score": 3, "clarify": False},
    {"question": "مختلف چیزوں کے بارے میں بہت زیادہ فکر کرنا", "reply": "کبھی کبھی پریشانی ہوتی ہے", "expected_score": 1, "clarify": False},
    {"question": "پرسکون ہونے میں مشکل", "reply": "آدھے سے زیادہ دن", "expected_score": 2, "clarify": False},
    {"question": "بے چین رہنا کہ ایک جگہ بیٹھنا مشکل ہو", "reply": "بالکل نہیں ہوتا ایسا", "expected_score": 0, "clarify": False},

    # Vague Answers
    {"question": "Feeling nervous, anxious, or on edge", "reply": "kuch keh nahi sakte", "expected_score": None, "clarify": True},
    {"question": "Not being able to stop or control worrying", "reply": "bas normal he", "expected_score": None, "clarify": True},
    {"question": "Worrying too much about different things", "reply": "dekhte hain aagay", "expected_score": None, "clarify": True},
    {"question": "Trouble relaxing", "reply": "pata nahi chal raha", "expected_score": None, "clarify": True},
    {"question": "Becoming easily annoyed or irritable", "reply": "mood ajeeb sa rehta hai", "expected_score": None, "clarify": True},

    # Code-switched English/Urdu
    {"question": "Feeling nervous, anxious, or on edge", "reply": "I feel very nervous and anxious har waqt", "expected_score": 3, "clarify": False},
    {"question": "Not being able to stop or control worrying", "reply": "Sometimes control issues hotay hain", "expected_score": 1, "clarify": False},
    {"question": "Worrying too much about different things", "reply": "Mostly fine but sometimes worried", "expected_score": 1, "clarify": False},
    {"question": "Trouble relaxing", "reply": "Relaxation is impossible har roz issue hai", "expected_score": 3, "clarify": False},
    {"question": "Feeling afraid as if something awful might happen", "reply": "No fear at all absolutely fine", "expected_score": 0, "clarify": False}
]

def run_tests(assessment_name, samples):
    print(f"\n--- Running Conversational Tests for {assessment_name} ---")
    passed = 0
    failed = 0
    clarified_count = 0
    first_pass_count = 0

    for idx, test in enumerate(samples):
        score, reasoning, needs_clarify = local_heuristic_extract_score(
            assessment_type=assessment_name.lower(),
            question=test["question"],
            reply=test["reply"]
        )

        success = (needs_clarify == test["clarify"])
        if not needs_clarify:
            if test["expected_score"] is not None and score != test["expected_score"]:
                success = False

        if success:
            passed += 1
            status = "PASSED"
        else:
            failed += 1
            status = "FAILED"

        if needs_clarify:
            clarified_count += 1
            action = "Clarification Requested"
        else:
            first_pass_count += 1
            action = f"Mapped to Score: {score}"

        print(f"[{status}] Reply #{idx+1}: '{test['reply']}' -> {action} | Reasoning: {reasoning}")

    total = len(samples)
    print(f"\nResults for {assessment_name}:")
    print(f"Total Tested          : {total}")
    print(f"Success Rate (Match)  : {passed}/{total} ({round(passed/total*100, 1)}%)")
    print(f"First-Pass Scored     : {first_pass_count}/{total}")
    print(f"Required Clarification: {clarified_count}/{total}")
    return passed, failed, clarified_count, first_pass_count

if __name__ == "__main__":
    phq_passed, phq_failed, phq_clarified, phq_first = run_tests("PHQ-9", phq9_samples)
    gad_passed, gad_failed, gad_clarified, gad_first = run_tests("GAD-7", gad7_samples)
    
    total_passed = phq_passed + gad_passed
    total_failed = phq_failed + gad_failed
    
    print("\n==================================================")
    print(f"Combined Testing Results:")
    print(f"Total Passed tests    : {total_passed} / 40")
    print(f"Total Failed tests    : {total_failed} / 40")
    print(f"Total First-Pass      : {phq_first + gad_first} / 40")
    print(f"Total Clarification   : {phq_clarified + gad_clarified} / 40")
    print("==================================================")
