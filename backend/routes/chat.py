from flask import Blueprint, request, jsonify, current_app
import requests
import json
import re

chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')

def local_heuristic_extract_score(assessment_type, question, reply):
    """
    Fallback score extraction using keyword matching in Urdu/Roman Urdu/English.
    """
    reply_clean = reply.lower().strip()
    
    # 1. Self-harm / Crisis Detection (PHQ-9 Q9)
    is_self_harm_item = "better off dead" in question.lower() or "نقصان" in question or "مر جانا" in question
    self_harm_keywords = ["mar", "marna", "die", "suicide", "hurt", "nuksan", "nooksan", "zakhmi", "خودکشی", "نقصان", "موت", "مرنا"]
    if is_self_harm_item or any(kw in reply_clean for kw in self_harm_keywords):
        denial_keywords = ["bilkul nahi", "bilkul nahin", "kabhi nahi", "kabhi nahin", "no", "never", "نہیں", "بالکل نہیں", "کبھی نہیں"]
        if any(dk in reply_clean for dk in denial_keywords) or reply_clean == "nahi" or reply_clean == "nahin":
            return 0, "User explicitly denied self-harm thoughts.", False
        return 1, "Self-harm/suicide risk keyword detected or ambiguous response.", False

    # 2. Vague responses check (requires clarification)
    vague_phrases = [
        "pata nahi", "pata nahin", "samajh nahi", "samajh nahin", "don't know", "dont know",
        "unclear", "unsure", "kuch keh nahi", "kuch keh nahin", "kuch pata nahi", "kuch pata nahin",
        "ajeeb sa", "bas theek", "bas normal", "mood ajeeb", "samjh nahi", "samjh nahin",
        "kuch keh nahi sakte", "kuch keh nahin sakte"
    ]
    if any(vp in reply_clean for vp in vague_phrases) or reply_clean in ["pata nahi", "pata nahin", "no idea", "not sure"]:
        # Only clarify if there are no explicit frequency keywords
        if not any(kw in reply_clean for kw in ["kabhi kabhi", "daily", "har roz", "always"]):
            return None, "Response is vague and requires clarification.", True

    # 3. Explicit low frequency matches first to avoid shadowing by high frequency (e.g. "mostly normal bas thoda sad" should be 1)
    low_freq_distress = [
        "kabhi kabhi bhook nahi", "kabhi kabhi bhook nahin",
        "bas thoda sad", "bas thoda", "sometimes control",
        "sometimes worried", "sometimes energy"
    ]
    low_freq_keywords = [
        "kabhi kabhi", "kabhikabhi", "sometimes", "kai din", "kaee din", "few days", "some days",
        "occasionally", "thoda", "thoda sa", "thoda boht", "thoda bohat", "halka", "halka sa",
        "کئی دن", "کبھی کبھی", "چند دن", "تھوڑا"
    ]
    if any(kw in reply_clean for kw in low_freq_distress) or any(kw in reply_clean for kw in low_freq_keywords):
        return 1, "Low frequency response matched score 1", False

    # 4. Explicit moderate frequency matches (e.g. "aadhe se zyada") matched before raw "zyada"
    mod_freq_keywords = [
        "aadhe", "aadhey", "half", "more than half", "mostly", "ziada tar", "zyada tar",
        "half the time", "half time", "آدھے", "آدھے سے زیادہ", "زیادہ تر"
    ]
    if any(kw in reply_clean for kw in mod_freq_keywords):
        # But make sure it's not "mostly normal" which is score 0/1
        if "mostly normal" in reply_clean or "mostly fine" in reply_clean:
            return 1, "Mostly normal mapped to mild score 1", False
        return 2, "Moderate-high frequency response matched score 2", False

    # 5. Severe Symptom Distress without explicit frequency (e.g. "neend nahi aati", "control nahi hota")
    # This must be run before wellness to prevent false score-0 classifications
    if "control" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean or "control" in reply_clean):
        # Wait, if they say "no control", it's severe worry
        return 3, "High distress response (unable to control worry)", False
    if "neend" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean or "sleep" in reply_clean):
        return 3, "High distress response (insomnia/sleep issues)", False
    if "dil" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean):
        return 3, "High distress response (loss of interest)", False

    # 6. High Frequency (Score 3)
    high_freq_distress = [
        "neend nahi aati bilkul bhi", "neend nahin aati bilkul bhi",
        "zero interest", "relax nahi kar pata", "relax nahin kar pata"
    ]
    high_freq_keywords = [
        "har waqt", "harwaqt", "daily", "always", "every day", "everyday", "har roz", "harroz",
        "bohat zyaada", "bohat zyada", "boht zyada", "boht zyaada", "buhat ziada", "buhat zyaada",
        "ziada", "zyada", "rozana", "constant", "constantly", "hamesha", "nearly every day",
        "تقریباً ہر روز", "ہر روز", "روزانہ", "ہمیشہ", "بہت زیادہ", "زیادہ"
    ]
    if any(kw in reply_clean for kw in high_freq_distress) or any(kw in reply_clean for kw in high_freq_keywords):
        return 3, "High frequency response matched score 3", False

    # 7. Explicit wellness / negation of symptom (Score 0)
    wellness_keywords = [
        "bilkul nahi", "bilkul nahin", "kabhi nahi", "kabhi nahin", "no", "never", "not at all",
        "zero", "no issue", "no problem", "fine", "absolutely fine", "all good", "perfect",
        "bilkul theek", "bilkul thik", "sab theek", "sab thik", "normal", "fit", "healthy",
        "no fear", "absolutely fine", "بالکل نہیں", "نہیں", "کبھی نہیں"
    ]
    if any(wk in reply_clean for wk in wellness_keywords) or reply_clean == "nahi" or reply_clean == "nahin":
        distress_keywords = ["neend", "sleep", "bhook", "appetite", "dil", "interest", "focus", "concentrate", "tension", "pareshan", "ghabrahat"]
        if not any(dk in reply_clean for dk in distress_keywords):
            return 0, "Negative response matched score 0", False

    # 8. Fallback distress indicator
    distress_keywords = ["neend", "sleep", "bhook", "appetite", "dil", "interest", "focus", "concentrate", "tension", "pareshan", "ghabrahat", "anxious", "nervous", "sad", "udasi", "udas"]
    if any(dk in reply_clean for dk in distress_keywords):
        return 1, "Symptom mentioned, defaulted to score 1", False

    return None, "Unable to map response to 0-3 scale via local heuristics.", True


@chat_bp.route('/extract-score', methods=['POST'])
def extract_score():
    """
    POST /api/chat/extract-score
    Body: { assessment_type, question, reply }
    Returns: { score, reasoning, needs_clarification }
    """
    data = request.get_json(silent=True) or {}
    assessment_type = data.get('assessment_type')
    question = data.get('question')
    reply = data.get('reply')

    if not assessment_type or not question or not reply:
        return jsonify({'error': 'assessment_type, question, and reply are required.'}), 400

    api_key = current_app.config.get('DASHSCOPE_API_KEY')
    base_url = current_app.config.get('DASHSCOPE_BASE_URL')
    model = current_app.config.get('QWEN_MODEL', 'qwen-plus')

    # If API key is missing, fall back directly to local heuristics
    if not api_key:
        score, reasoning, needs_clarify = local_heuristic_extract_score(assessment_type, question, reply)
        return jsonify({
            'score': score,
            'reasoning': reasoning + " (local fallback)",
            'needs_clarification': needs_clarify
        }), 200

    # System instruction for score extraction
    system_prompt = (
        "You are an empathetic, clinical AI score extractor for Zehni Sukoon, a mental health platform in Pakistan.\n"
        "Your task is to analyze the user's free-text reply to a single screening question (from PHQ-9 or GAD-7) "
        "and determine a score from 0 to 3 based on the frequency they describe:\n"
        "- 0: Not at all / بالکل نہیں\n"
        "- 1: Several days / kabhi kabhi / some days / کئی دن\n"
        "- 2: More than half the days / half the time / aadhe se zyada din / آدھے سے زیادہ دن\n"
        "- 3: Nearly every day / daily / har roz / تقریباً ہر روز\n\n"
        "Rules:\n"
        "1. If the reply is vague, unrelated, or lacks enough information to pick 0, 1, 2, or 3, set 'score' to null and 'needs_clarification' to true.\n"
        "2. If they answer clearly, set 'score' to the correct integer and 'needs_clarification' to false.\n"
        "3. CRITICAL Rule for PHQ-9 Question 9 (thoughts of self-harm/suicide):\n"
        "   If there is ANY hint of self-harm, passive suicidal ideation, or ambiguity, DO NOT ask for clarification. "
        "   Map it immediately to a score of 1, 2, or 3 (flagging risk). Ambiguity on Question 9 must default to flagging risk (score >= 1, needs_clarification = false).\n\n"
        "Return ONLY a valid JSON object with the following format:\n"
        "{\n"
        "  \"score\": 0|1|2|3|null,\n"
        "  \"reasoning\": \"brief explanation of why this score was chosen\",\n"
        "  \"needs_clarification\": true|false\n"
        "}"
    )

    user_content = f"Question: {question}\nUser Reply: {reply}"

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content}
            ],
            'response_format': {'type': 'json_object'}
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        res_data = response.json()
        content = res_data['choices'][0]['message']['content']
        
        # Parse JSON from response
        parsed = json.loads(content)
        return jsonify({
            'score': parsed.get('score'),
            'reasoning': parsed.get('reasoning', ''),
            'needs_clarification': parsed.get('needs_clarification', False)
        }), 200

    except Exception as e:
        # Fallback to local heuristic on any failure
        score, reasoning, needs_clarify = local_heuristic_extract_score(assessment_type, question, reply)
        return jsonify({
            'score': score,
            'reasoning': f"Local fallback due to API error: {str(e)}",
            'needs_clarification': needs_clarify
        }), 200


@chat_bp.route('/companion', methods=['POST'])
def companion():
    """
    POST /api/chat/companion
    Body: { message, history }
    """
    data = request.get_json(silent=True) or {}
    message = data.get('message')
    history = data.get('history', [])

    if not message:
        return jsonify({'error': 'message is required.'}), 400

    api_key = current_app.config.get('DASHSCOPE_API_KEY')
    base_url = current_app.config.get('DASHSCOPE_BASE_URL')
    model = current_app.config.get('QWEN_MODEL', 'qwen-plus')

    if not api_key:
        return jsonify({
            'response': "I am here with you. Please feel free to tell me more about how you are feeling."
        }), 200

    # Companion system prompt
    system_prompt = (
        "You are Humdum (ہمدم), an empathetic, caring, non-clinical AI companion for Zehni Sukoon in Pakistan.\n"
        "Your tone must stay calm, supportive, non-clinical, and extremely safe.\n"
        "Use simple language. Respond in the same language the user writes in (Urdu or English/Roman Urdu).\n"
        "Always remind them gently if they are in crisis that they can call the helpline. Never make diagnostic claims."
    )

    # Format messages for Qwen
    messages = [{'role': 'system', 'content': system_prompt}]
    for msg in history[-10:]: # Keep last 10 messages for context
        role = 'user' if msg.get('role') == 'user' else 'assistant'
        messages.append({'role': role, 'content': msg.get('content', '')})
    
    # Append current message if not already in history
    if not messages or messages[-1]['content'] != message:
        messages.append({'role': 'user', 'content': message})

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        payload = {
            'model': model,
            'messages': messages
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        res_data = response.json()
        bot_response = res_data['choices'][0]['message']['content']
        return jsonify({'response': bot_response}), 200

    except Exception as e:
        return jsonify({
            'response': "I hear you. I'm here to listen. Tell me more about what has been on your mind."
        }), 200
