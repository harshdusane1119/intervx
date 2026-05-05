import os
import json
import base64
import flask
from flask_cors import CORS
import google.generativeai as genai
import uuid
import requests
from urllib.parse import quote

sessions = {}
import random


os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

from dotenv import load_dotenv
load_dotenv()

app = flask.Flask(__name__, template_folder="templates")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}
CORS(app)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
print("API KEY:", GOOGLE_API_KEY)
genai.configure(
    api_key=GOOGLE_API_KEY,
    transport="rest"
)

model = genai.GenerativeModel("gemini-2.5-flash")

@app.route("/")
def index():
    return flask.render_template("index.html")

@app.route('/start-session', methods=['GET'])
def start_session():
    session_id = str(uuid.uuid4())

    sessions[session_id] = {
        "eye": 0.0,
        "expression": 0.0,
        "gesture": 0.0,
        "frames": 0
    }

    return flask.jsonify({"session_id": session_id})


@app.route("/history", methods=["GET"])
def get_history():
    user_id = flask.request.args.get("user_id")

    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/interviews?user_id=eq.{user_id}&order=created_at.desc",
        headers=HEADERS
    )

    return flask.jsonify(res.json())

@app.route('/update-nonverbal', methods=['POST'])
def update_nonverbal():
    data = flask.request.get_json()
    job_description = data.get("job_description", "")
    user_id = data.get("user_id")
    session_id = data.get("session_id")

    if session_id not in sessions:
        return flask.jsonify({"error": "Invalid session"}), 400

    s = sessions[session_id]

    s["eye"] += float(data.get("eye_contact", 0))
    s["gesture"] += float(data.get("gesture", 0))
    s["expression"] += float(data.get("expression", 0))
    s["frames"] += 1

    return flask.jsonify({"status": "updated"})

@app.route("/register", methods=["POST"])
def register():
    try:
        data = flask.request.get_json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        if not username or not password:
            return flask.jsonify({"error": "Missing username or password"}), 400

        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=HEADERS,
            json={
                "username": username,
                "password": password
            }
        )

        print("REGISTER STATUS:", res.status_code)
        print("REGISTER RESPONSE:", res.text)

        if res.status_code == 201:
            return flask.jsonify({"message": "User registered successfully"})
        else:
            return flask.jsonify({"error": res.text}), 400

    except Exception as e:
        return flask.jsonify({"error": str(e)}), 500

@app.route("/login", methods=["POST"])
def login():
    try:
        data = flask.request.get_json()
        username = data.get("username")
        password = data.get("password")

        res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}&password=eq.{password}",
        headers=HEADERS
)
        print("LOGIN INPUT:", username, password)
        print("SUPABASE RESPONSE:", res.text)

        users = res.json()

        if len(users) == 0:
            return flask.jsonify({"error": "Invalid credentials"}), 401

        return flask.jsonify({
        "message": "Login successful",
        "user_id": users[0]["id"],
        "username": users[0]["username"]   # 🔥 ADD THIS
    })

    except Exception as e:
        return flask.jsonify({"error": str(e)}), 500

@app.route("/generate", methods=["POST"])
def generate():
    print("🔥 /generate called")
    try:
        data = flask.request.get_json()
        job_description = data.get("job_description", "")

        prompt = f"""
        You are an expert HR interviewer.
        Generate exactly 4 interview questions:
        4 job-specific questions which each are 1-2 lines based on the following job description.

        Job Description:
        {job_description}

        Return only the questions in a numbered list format:
        1. ...
        2. ...
        3. ...
        4. ...
        """

        print("⏳ Calling Gemini...")
        response = model.generate_content(prompt)
        print("RESPONSE:", response)

        raw_text = ""

        if hasattr(response, "text") and response.text:
            raw_text = response.text
        elif hasattr(response, "candidates") and response.candidates:
            parts = response.candidates[0].content.parts
            if parts and hasattr(parts[0], "text"):
                raw_text = parts[0].text

        questions_text = raw_text.strip()

        questions = []
        for line in questions_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line[0].isdigit() and ('.' in line[:4]):
                parts = line.split('.', 1)
                question = parts[1].strip() if len(parts) > 1 else line
            else:
                question = line
            questions.append(question)

        return flask.jsonify({"questions": questions})

    except Exception as e:
        print("❌ GENERATE ERROR:", e)
        return flask.jsonify({"error": str(e)}), 500



@app.route("/evaluate", methods=["POST"])
def evaluate():
    try:
        data = flask.request.get_json()
        question = data.get("question", "")
        answer = data.get("answer", "")
        session_id = data.get("session_id")
        user_id = data.get("user_id")
        job_description = data.get("job_description", "")

        if not question or not answer:
            return flask.jsonify({"error": "Missing question or answer"}), 400

        # -------- NON-VERBAL FROM SESSION --------
        
        s = sessions.get(session_id)

        if s and s["frames"] > 0:
            eye = s["eye"] / s["frames"]
            gesture = s["gesture"] / s["frames"]

            nonverbal_scores = {
                "Eye Contact": round(eye, 1),
                "Hand Movement": round(gesture, 1),
                "Facial Expression": 7  # temp for now
            }
        else:
            nonverbal_scores = {
                "Eye Contact": 5,
                "Hand Movement": 5,
                "Facial Expression": 5
            }

        eye_score = nonverbal_scores["Eye Contact"]
        gesture_score = nonverbal_scores["Hand Movement"]
        expression_score = nonverbal_scores["Facial Expression"]


        prompt = f"""
        You are an expert interview evaluator.

        Evaluate the candidate primarily based on VERBAL performance.

        Also consider NON-VERBAL behavior using the given scores.

        VERBAL PARAMETERS:
        - Clarity
        - Relevance
        - Structure
        - Confidence
        - Technical Depth
        - Example Quality
        - Conciseness

        NON-VERBAL SCORES:
        - Eye Contact: {eye_score}/10
        - Hand Movement: {gesture_score}/10
        - Facial Expression: {expression_score}/10

        INSTRUCTIONS:
        - Give MOST focus to verbal evaluation.
        - In the summary, include ONLY 3-4 lines about non-verbal behavior.
        - Keep non-verbal feedback concise and natural.
        - In improvement tips, include at most 1 tip related to non-verbal behavior.
        - Avoid overly harsh scoring unless the answer is clearly very weak.
        - Reward partial correctness, communication effort, and reasonable structure.
        -Candidates are using this platform for practice and learning.
        -Scores should motivate improvement while remaining realistic.
 
        IMPORTANT:
        - ALSO extract feature-level scores (0–10) for each parameter.
        - These features will be used for formula-based scoring.
        - Keep feature values realistic and consistent with verbal_scores.

        FEATURE DEFINITIONS:

        Clarity:
        - grammar (0–10)
        - simplicity (0–10)
        - ambiguity (0–10, higher = worse)

        Relevance:
        - keyword_match (0–10)
        - topical_alignment (0–10)

        Structure:
        - logical_flow (0–10)
        - organization (0–10)

        Confidence:
        - assertiveness (0–10)
        - hesitation (0–10, higher = worse)

        Technical Depth:
        - correctness (0–10)
        - depth (0–10)

        Example Quality:
        - relevance (0–10)
        - specificity (0–10)

        Conciseness:
        - length_score (0–10)

        Return ONLY valid JSON in this format:
        {{
        "features": {{
            "clarity": {{"grammar":0,"simplicity":0,"ambiguity":0}},
            "relevance": {{"keyword_match":0,"topical_alignment":0}},
            "structure": {{"logical_flow":0,"organization":0}},
            "confidence": {{"assertiveness":0,"hesitation":0}},
            "technical": {{"correctness":0,"depth":0}},
            "example": {{"relevance":0,"specificity":0}},
            "conciseness": {{"length_score":0}}
        }},

        "verbal_scores": {{
            "Clarity": 0,
            "Relevance": 0,
            "Structure": 0,
            "Confidence": 0,
            "Technical Depth": 0,
            "Example Quality": 0,
            "Conciseness": 0
        }},
        
        "summary": "4-5 sentence summary of verbal behavior including 1 short line on non-verbal behavior",

        "improvement_tips": [
            "tip 1",
            "tip 2",
            "tip 3",
            "tip 4",
            "tip 5"
        ]
        }}

        Question: {question}
        Answer: {answer}
        """

        response = model.generate_content(prompt)
        raw_text = getattr(response, "text", "")
        cleaned = raw_text.strip().replace("```json", "").replace("```", "")
        json_part = cleaned[cleaned.find("{"): cleaned.rfind("}") + 1]

        try:
            evaluation = json.loads(json_part)
        except Exception:
            evaluation = {"verbal_scores": {}, "summary": "", "improvement_tips": []}

        # ✅ Extract verbal scores
        verbal_scores = evaluation.get("verbal_scores", {})
        features = evaluation.get("features", {})

        # ✅ If features exist → compute scores using formulas
        if features:
            try:
                # --- CLARITY ---
                g = features["clarity"]["grammar"]
                s = features["clarity"]["simplicity"]
                a = features["clarity"]["ambiguity"]
                clarity = (g + s + (10 - a)) / 3

                # --- RELEVANCE ---
                k = features["relevance"]["keyword_match"]
                t = features["relevance"]["topical_alignment"]
                relevance = (k + t) / 2

                # --- STRUCTURE ---
                l = features["structure"]["logical_flow"]
                o = features["structure"]["organization"]
                structure = (l + o) / 2

                # --- CONFIDENCE ---
                c = features["confidence"]["assertiveness"]
                h = features["confidence"]["hesitation"]
                confidence = max(0, (c * 0.7) + ((10 - h) * 0.3))

                # --- TECHNICAL ---
                d = features["technical"]["correctness"]
                e = features["technical"]["depth"]
                technical = (d + e) / 2

                # --- EXAMPLE ---
                r = features["example"]["relevance"]
                sp = features["example"]["specificity"]
                example = (r + sp) / 2

                # --- CONCISENESS ---
                conciseness = features["conciseness"]["length_score"]

                verbal_scores = {
                    "Clarity": round(clarity, 1),
                    "Relevance": round(relevance, 1),
                    "Structure": round(structure, 1),
                    "Confidence": round(confidence, 1),
                    "Technical Depth": round(technical, 1),
                    "Example Quality": round(example, 1),
                    "Conciseness": round(conciseness, 1)
                }

            except Exception as e:
                print("⚠️ Feature scoring failed:", e)

        # ✅ Combine scores
        all_scores = {**verbal_scores, **nonverbal_scores}

        # ✅ Final weighted score
        V = sum(verbal_scores.values()) / 7
        NV = (eye_score + gesture_score + expression_score) / 3

        total = round((0.7 * V + 0.3 * NV) * 10, 1)

        # 🔥 SAVE TO SUPABASE
        try:
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/interviews",
                headers=HEADERS,
                json={
                    "user_id": user_id,
                    "question": question,
                    "job_description": job_description,
                    "scores": all_scores,
                    "summary": evaluation.get("summary", ""),
                    "tips": evaluation.get("improvement_tips", [])
                }
            )

            print("DB STATUS:", res.status_code)
            print("DB RESPONSE:", res.text)

        except Exception as e:
            print("DB INSERT ERROR:", e)

        # ✅ FINAL RESPONSE
        return flask.jsonify({
            "evaluation": {
                "scores": all_scores,
                "total": total,
                "summary": evaluation.get("summary", ""),
                "improvement_tips": evaluation.get("improvement_tips", [])
            }
        })
    except Exception as e:
        return flask.jsonify({"error": str(e)}), 500
        

@app.route("/test-db")
def test_db():
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=HEADERS
        )
        return flask.jsonify(res.json())
    except Exception as e:
        return flask.jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run()
