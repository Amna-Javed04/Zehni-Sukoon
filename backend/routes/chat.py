from flask import Blueprint, request, jsonify, current_app
import requests
import json
import re

chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')

def local_heuristic_extract_score(assessment_type, question, reply):
    """
    Fallback score extraction using keyword matching in Urdu/Roman Urdu.
    """
    reply_clean = reply.lower().strip()
    
    # Check if this is the PHQ-9 Q9 self-harm item
    is_self_harm_item = "better off dead" in question.lower() or "نقصان" in question or "مر جانا" in question
    
    # Check for self-harm risk signals in user reply
    self_harm_keywords = ["mar", "marna", "die", "suicide", "hurt", "nuksan", "nooksan", "zakhmi", "خودکشی", "نقصان", "موت", "مرنا"]
    if is_self_harm_item or any(kw in reply_clean for kw in self_harm_keywords):
        # Stricter self-harm logic: default to flagging risk
        # Any mention of suicidal thoughts or negative feelings on Q9 should be flagged as score >= 1
        # If they explicitly deny, map to 0, otherwise default to 1.
        denial_keywords = ["nahin", "nahi", "no", "never", "bilkul nahi", "نہیں", "بالکل نہیں"]
        if any(dk in reply_clean for dk in denial_keywords):
            return 0, "User explicitly denied self-harm thoughts.", False
        return 1, "Self-harm/suicide risk keyword detected or ambiguous response.", False

    # Standard options mapping:
    # 0: Not at all (بالکل نہیں)
    # 1: Several days (کئی دن)
    # 2: More than half the days (آدھے سے زیادہ دن)
    # 3: Nearly every day (تقریباً ہر روز)
    
    # Check score 0
    if any(kw in reply_clean for kw in ["bilkul nahi", "nahin", "nahi", "no", "never", "بالکل نہیں", "نہیں", "کبھی نہیں"]):
        return 0, "Negative response matched score 0", False
    
    # Check score 3
    if any(kw in reply_clean for kw in ["har roz", "daily", "always", "every day", "taqreeban", "تقریباً ہر روز", "ہر روز", "روزانہ", "ہمیشہ"]):
        return 3, "High frequency response matched score 3", False

    # Check score 2
    if any(kw in reply_clean for kw in ["aadhe", "more than half", "half", "mostly", "آدھے", "آدھے سے زیادہ", "زیادہ تر"]):
        return 2, "Moderate-high frequency response matched score 2", False

    # Check score 1
    if any(kw in reply_clean for kw in ["kai din", "sometimes", "kabhi kabhi", "few days", "کئی دن", "کبھی کبھی", "چند دن"]):
        return 1, "Low frequency response matched score 1", False

    # Default to needing clarification
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
