import google.generativeai as genai
import os
from dotenv import load_dotenv

# 載入 API Key
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("可用模型列表：")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)