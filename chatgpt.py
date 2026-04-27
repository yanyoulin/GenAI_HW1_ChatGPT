import streamlit as st
import google.generativeai as genai
from groq import Groq
import os
import uuid
import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from PIL import Image
from audio_recorder_streamlit import audio_recorder

from duckduckgo_search import DDGS
import yfinance as yf

# ==========================================
# 1. 初始化與環境設定
# ==========================================
load_dotenv()
gemini_key = os.getenv("GEMINI_API_KEY")
groq_key = os.getenv("GROQ_API_KEY")
sender_email = os.getenv("SENDER_EMAIL")
sender_password = os.getenv("SENDER_PASSWORD")

if not gemini_key or not groq_key:
    st.error("請確保 .env 檔案中同時設定了 GEMINI_API_KEY 與 GROQ_API_KEY")
    st.stop()

genai.configure(api_key=gemini_key)
groq_client = Groq(api_key=groq_key)

st.set_page_config(page_title="HW2 Pro Chatbot", layout="wide")
st.title("🌟 HW2 Advanced Agent (Gemini Core + Auto Routing)")

# ==========================================
# MCP / Tool Use：Python 函數直連 Gemini
# ==========================================
def web_search(query: str) -> str:
    """使用 DuckDuckGo 進行網頁搜尋 (具備反-反爬蟲雙重機制)"""
    try:
        # 第一層保險：強制使用 "html" 後端，避開預設 API 嚴格的 Rate Limit
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3, backend="html"))
            
        # 第二層保險：若 HTML 版剛好被擋，自動降級切換為 "lite" 輕量文字版後端
        if not results:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3, backend="lite"))
                
        # 如果兩層都失敗才報錯
        if not results:
            return json.dumps({"error": "搜尋結果為空，可能是搜尋引擎暫時阻擋，請稍候再試。"}, ensure_ascii=False)
            
        clean_results = [{"標題": r.get("title", ""), "摘要": r.get("body", "")} for r in results]
        return json.dumps(clean_results, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": f"網路搜尋失敗: {str(e)}"}, ensure_ascii=False)

def get_stock_price(ticker: str) -> str:
    """獲取台灣或美國股票的即時價格。台灣股票代碼必須加上 '.TW'，例如台積電為 '2330.TW'。"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            price = round(hist['Close'].iloc[-1], 2)
            return f"{ticker} 的即時收盤價為 {price}"
        else:
            return f"找不到 {ticker} 的股價資料。"
    except Exception as e:
        return f"股價查詢失敗: {str(e)}"

def send_email(to_email: str, subject: str, body: str) -> str:
    """透過 Gmail 自動寄送信件給指定的 Email 信箱。信件內容必須是繁體中文。"""
    if not sender_email or not sender_password:
        return "系統尚未在 .env 設定寄件者信箱與密碼。"
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return f"信件已成功發送至 {to_email}"
    except Exception as e:
        return f"寄信失敗，請檢查密碼: {str(e)}"

# 將函數打包供 Gemini 直接解析
gemini_tools = [web_search, get_stock_price, send_email]
available_functions = {func.__name__: func for func in gemini_tools}

# ==========================================
# 長期記憶引擎 (LTM)
# ==========================================
DATA_FILE = "chat_history.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("chats", {}), data.get("folders", [])
        except Exception:
            pass
    init_id = str(uuid.uuid4())
    return {init_id: {"name": "新對話", "folder": None, "messages": []}}, []

def save_data():
    data = {"chats": st.session_state.chats, "folders": st.session_state.folders}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def summarize_memory(chat_id):
    messages = st.session_state.chats[chat_id]["messages"]
    if len(messages) <= 4:
        st.warning("對話還不夠長，暫時不需要壓縮記憶喔！")
        return
    history_to_compress = messages[:-2]
    text_to_compress = "\n".join([f"{m['role']}: {m['content']}" for m in history_to_compress])
    
    prompt = f"請將以下對話紀錄總結為一段精簡的脈絡摘要（約150字），若有圖片請註記。對話紀錄:\n{text_to_compress}"
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=300
        )
        summary = response.choices[0].message.content
        st.session_state.chats[chat_id]["messages"] = [
            {"role": "assistant", "content": f"🧠 **[系統記憶已壓縮]**\n> 歷史脈絡摘要：\n{summary}"}
        ] + messages[-2:]
        save_data()
        st.success("記憶壓縮成功！")
        st.rerun()
    except Exception as e:
        st.error(f"壓縮記憶失敗: {e}")

if "chats" not in st.session_state:
    loaded_chats, loaded_folders = load_data()
    st.session_state.chats = loaded_chats
    st.session_state.folders = loaded_folders
if not st.session_state.chats:
    init_id = str(uuid.uuid4())
    st.session_state.chats = {init_id: {"name": "新對話", "folder": None, "messages": []}}
    save_data()
if "current_chat_id" not in st.session_state or st.session_state.current_chat_id not in st.session_state.chats:
    st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# ==========================================
# 2. 側邊欄：資料夾與設定
# ==========================================
with st.sidebar:
    st.header("💬 對話清單")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 新對話", use_container_width=True):
            new_id = str(uuid.uuid4())
            st.session_state.chats[new_id] = {"name": f"新對話 {len(st.session_state.chats)+1}", "folder": None, "messages": []}
            st.session_state.current_chat_id = new_id
            save_data()
            st.rerun()
    with col2:
        with st.popover("📁 新資料夾", use_container_width=True):
            new_folder_name = st.text_input("輸入資料夾名稱")
            if st.button("建立"):
                if new_folder_name and new_folder_name not in st.session_state.folders:
                    st.session_state.folders.append(new_folder_name)
                    save_data()
                    st.rerun()

    st.divider()
    def render_chat_item(chat_id, chat_data):
        c1, c2 = st.columns([0.85, 0.15])
        with c1:
            icon = "👉" if st.session_state.current_chat_id == chat_id else "💬"
            if st.button(f"{icon} {chat_data['name']}", key=f"btn_{chat_id}", use_container_width=True):
                st.session_state.current_chat_id = chat_id
                st.rerun()
        with c2:
            with st.popover("⋮", use_container_width=True):
                new_name = st.text_input("重新命名", value=chat_data['name'], key=f"ren_{chat_id}")
                if new_name != chat_data['name']:
                    st.session_state.chats[chat_id]['name'] = new_name
                    save_data()
                    st.rerun()
                if st.button("🗑️ 刪除", key=f"del_{chat_id}", type="primary"):
                    del st.session_state.chats[chat_id]
                    save_data()
                    st.rerun()

    for cid, cdata in list(st.session_state.chats.items()):
        if cdata['folder'] is None:
            render_chat_item(cid, cdata)

    for folder in st.session_state.folders:
        with st.expander(f"📁 {folder}"):
            for cid, cdata in {k: v for k, v in st.session_state.chats.items() if v['folder'] == folder}.items():
                render_chat_item(cid, cdata)

    st.divider()
    with st.expander("🧠 長期記憶管理 (LTM)", expanded=True):
        if st.button("⚡ 壓縮當前對話記憶", use_container_width=True):
            summarize_memory(st.session_state.current_chat_id)

    with st.expander("⚙️ 模型與 API 設定", expanded=False):
        system_prompt = st.text_area("System Prompt", value="你是一個全能的 AI Agent。當需要查資訊時請主動使用 web_search，查股價用 get_stock_price，寄信使用 send_email。完全信任工具結果並用繁體中文流暢回答。", height=100)

# ==========================================
# 3. 主畫面設計
# ==========================================
current_chat_data = st.session_state.chats[st.session_state.current_chat_id]
current_messages = current_chat_data["messages"]

st.subheader(f"🗣️ {current_chat_data['name']}")

chat_container = st.container()
tool_container = st.container()

with chat_container:
    for message in current_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

with tool_container:
    st.markdown("---")
    tool_col1, tool_col2, tool_col3 = st.columns([2, 1, 1])
    with tool_col1:
        # 【關鍵架構切換】：明確區分兩者的任務職責
        routing_mode = st.selectbox(
            "🤖 本次發言模型", 
            [
                "Auto Routing (自動分配)", 
                "Gemini-2.5-Flash (全能 Agent：上網/寄信/看圖)", 
                "Llama-3.3-70B (極速引擎：純文字聊天)",
                "models/gemma-3-27b-it"
            ]
        )
    with tool_col2:
        with st.popover("📎 附加圖片"):
            uploaded_image = st.file_uploader("上傳圖片", type=["jpg", "jpeg", "png"], key=f"uploader_{st.session_state.uploader_key}")
            if uploaded_image:
                st.image(Image.open(uploaded_image), width=150)
    with tool_col3:
        st.caption("語音輸入")
        audio_bytes = audio_recorder("🎤", key=f"audio_{st.session_state.uploader_key}")

# ==========================================
# 4. 核心邏輯：真正的 Agentic Auto-Routing
# ==========================================
prompt = st.chat_input("你想問什麼？")
is_audio_input = False

if audio_bytes and not prompt:
    try:
        with st.spinner("🛠️ Whisper 語音轉文字中..."):
            transcription = groq_client.audio.transcriptions.create(
                file=("audio.wav", audio_bytes), model="whisper-large-v3", language="zh", prompt="繁體中文。"
            )
            prompt = transcription.text
            is_audio_input = True
    except Exception as e:
        st.error(f"語音辨識失敗：{e}")

if prompt:
    user_content_to_save = prompt
    if is_audio_input:
        user_content_to_save = f"🎤 [語音輸入]\n{prompt}"
    elif uploaded_image:
        user_content_to_save = f"🖼️ [附圖提問]\n{prompt}"
        
    st.session_state.chats[st.session_state.current_chat_id]["messages"].append({"role": "user", "content": user_content_to_save})
    save_data()
    
    with chat_container.chat_message("user"):
        st.markdown(user_content_to_save)

    with chat_container.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        success_flag = False
        
        # 【修復 1】：大幅擴充中英文關鍵字，確保英文任務也能觸發 Agent
        tool_keywords = [
            "查", "新聞", "天氣", "股價", "寄", "信", "搜尋", "總統", "是誰", "幫我",
            "search", "news", "weather", "stock", "price", "email", "send", "president", "who", "what"
        ]
        
        selected_engine = routing_mode
        if routing_mode == "Auto Routing (自動分配)":
            if uploaded_image or any(k in prompt.lower() for k in tool_keywords):
                selected_engine = "Gemini-2.5-Flash (全能 Agent：上網/寄信/看圖)"
            else:
                selected_engine = "Llama-3.3-70B (極速引擎：純文字聊天)"

        try:
            # ----------------------------------------
            # 路由 A：Gemini (完美支援繁體中文與 Tool Calling)
            # ----------------------------------------
            if "Gemini" in selected_engine:
                if "models/gemma-3-27b-it" in selected_engine:
                    actual_model_name = "models/gemma-3-27b-it"
                    routing_label = "**[🚀 路由：Gemma-3-27B-It (全能 Agent，內建工具)]**\n\n"
                else:
                    actual_model_name = "gemini-2.5-flash"
                    routing_label = "**[🚀 路由：Gemini-2.5-Flash (Agent)]**\n\n"
                full_response += routing_label
                message_placeholder.markdown(full_response + "▌")
                
                safety_settings = [{"category": f"HARM_CATEGORY_{cat}", "threshold": "BLOCK_NONE"} for cat in ["HARASSMENT", "HATE_SPEECH", "SEXUALLY_EXPLICIT", "DANGEROUS_CONTENT"]]
                model = genai.GenerativeModel(model_name=actual_model_name, system_instruction=system_prompt, tools=gemini_tools)
                
                formatted_history = []
                for msg in current_messages[:-1]:
                    if msg["role"] != "tool":
                        role = "model" if msg["role"] == "assistant" else "user"
                        clean_txt = re.sub(r'\*\*\[.*?路由：.*?\]\*\*\n\n', '', msg["content"])
                        clean_txt = re.sub(r'🔍 正在使用.*?\n\n', '', clean_txt)
                        formatted_history.append({"role": role, "parts": [clean_txt]})
                    
                chat_session = model.start_chat(history=formatted_history)
                request_content = [prompt]
                if uploaded_image:
                    request_content.append(Image.open(uploaded_image))
                
                response = chat_session.send_message(request_content, safety_settings=safety_settings, stream=False)
                
                if response.parts and any(p.function_call for p in response.parts):
                    tool_response_parts = []
                    
                    for part in response.parts:
                        if part.function_call:
                            func_name = part.function_call.name
                            func_args = {k: v for k, v in part.function_call.args.items()}
                            
                            tool_action_text = f"🔍 正在使用 `{func_name}` 執行任務...\n\n"
                            full_response += tool_action_text
                            message_placeholder.markdown(full_response + "▌")
                            
                            try:
                                func_to_call = available_functions[func_name]
                                result_str = func_to_call(**func_args)
                            except Exception as e:
                                result_str = json.dumps({"error": str(e)}, ensure_ascii=False)
                                
                            # 【修復 2】：使用最原始且安全的字典格式回傳，避開 SDK 版本報錯
                            tool_response_parts.append({
                                "function_response": {
                                    "name": func_name,
                                    "response": {"result": result_str}
                                }
                            })
                    
                    if tool_response_parts:
                        final_response = chat_session.send_message(tool_response_parts, safety_settings=safety_settings, stream=True)
                        for chunk in final_response:
                            if chunk.text:
                                full_response += chunk.text
                                message_placeholder.markdown(full_response + "▌")
                else:
                    if response.text:
                        # 模擬 Streaming 效果
                        for char in response.text:
                            full_response += char
                            message_placeholder.markdown(full_response + "▌")
                
                message_placeholder.markdown(full_response)
                        
            # ----------------------------------------
            # 路由 B：Groq Llama 3 (純文字極速聊天，徹底拔除工具)
            # ----------------------------------------
            else:
                routing_label = "**[⚡ 路由：Llama-3.3-70B (極速聊天)]**\n\n"
                full_response += routing_label
                message_placeholder.markdown(full_response + "▌")
                
                messages_for_groq = [{"role": "system", "content": "你是一個熱心助人的純文字 AI。請用繁體中文回答。"}]
                for msg in current_messages[:-1]:
                    clean_content = re.sub(r'\*\*\[.*?路由：.*?\]\*\*\n\n', '', msg["content"])
                    clean_content = re.sub(r'🔍 正在使用.*?\n\n', '', clean_content)
                    messages_for_groq.append({"role": msg["role"], "content": clean_content})

                current_clean_prompt = re.sub(r'\*\*\[.*?路由：.*?\]\*\*\n\n', '', prompt)
                messages_for_groq.append({"role": "user", "content": current_clean_prompt})

                second_response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages_for_groq,
                    stream=True
                )
                
                for chunk in second_response:
                    if chunk.choices[0].delta.content:
                        full_response += chunk.choices[0].delta.content
                        message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)

            st.session_state.chats[st.session_state.current_chat_id]["messages"].append({"role": "assistant", "content": full_response})
            save_data()
            success_flag = True

        except Exception as e:
            st.error(f"發生錯誤：{str(e)}\n\n(這可能是 API 不穩定，請稍候再試)")

    if success_flag:
        st.session_state.uploader_key += 1
        st.rerun()