# ai_gemini.py
import os
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)


def gemini_ai_reply(user_input):
    model = genai.GenerativeModel("gemini-2.5-flash-lite-preview-06-17")
    prompt = f"Reply briefly and professionally (under 1000 characters): {user_input}"
    
    try:
        response = model.generate_content(prompt)
        reply = response.text.strip()
        if len(reply) > 1000:
            reply = reply[:997] + "..."
        return reply
    except Exception as e:
        print("AI error:", e)
        return "Sorry, I couldn't process that. Can you please rephrase?"

