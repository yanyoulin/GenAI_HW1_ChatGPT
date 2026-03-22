import streamlit as st
import google.generativeai as genai
import os
import uuid
from dotenv import load_dotenv
from PIL import Image

# 1. 初始化與環境設定
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("請在 .env 檔案中設定 GEMINI_API_KEY")
    st.stop()

genai.configure(api_key=api_key)

st.set_page_config(page_title="My Advanced Gemini Chatbot", layout="wide")
st.title("🌟 Advanced Gemini ChatGPT (Pro UI)")

# --- 資料結構初始化 ---
# 我們改用一個主字典來存所有對話，透過 'folder' 屬性來決定它屬於誰
# 結構: { chat_id: {"name": "對話名稱", "folder": "資料夾名稱" 或 None, "messages": []} }
if "chats" not in st.session_state:
    init_id = str(uuid.uuid4())
    st.session_state.chats = {
        init_id: {"name": "新對話", "folder": None, "messages": []}
    }
if "folders" not in st.session_state:
    st.session_state.folders = [] # 存放所有資料夾名稱的列表
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = init_id

# 確保 current_chat_id 是有效的 (防呆：如果刪除了當前對話)
if st.session_state.current_chat_id not in st.session_state.chats:
    if st.session_state.chats:
        st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
    else:
        new_id = str(uuid.uuid4())
        st.session_state.chats[new_id] = {"name": "新對話", "folder": None, "messages": []}
        st.session_state.current_chat_id = new_id

# --- 側邊欄：對話與資料夾管理 (符合主流 UI) ---
with st.sidebar:
    st.header("💬 對話列表")
    
    # 頂部控制列：新增對話 & 新增資料夾
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 新增對話", use_container_width=True):
            new_id = str(uuid.uuid4())
            st.session_state.chats[new_id] = {"name": f"新對話 {len(st.session_state.chats)+1}", "folder": None, "messages": []}
            st.session_state.current_chat_id = new_id
            st.rerun()
    with col2:
        # 使用 popover 實作點擊後彈出輸入框的新增資料夾
        with st.popover("📁 新增資料夾", use_container_width=True):
            new_folder_name = st.text_input("輸入資料夾名稱")
            if st.button("建立", key="create_folder_btn"):
                if new_folder_name and new_folder_name not in st.session_state.folders:
                    st.session_state.folders.append(new_folder_name)
                    st.rerun()

    st.divider()

    # --- 渲染對話列表的共用函數 ---
    def render_chat_item(chat_id, chat_data):
        c1, c2 = st.columns([0.85, 0.15]) # 85% 給按鈕，15% 給三點選單
        with c1:
            # 判斷是否為當前選取的對話，給予不同的 Icon
            icon = "👉" if st.session_state.current_chat_id == chat_id else "💬"
            if st.button(f"{icon} {chat_data['name']}", key=f"btn_{chat_id}", use_container_width=True):
                st.session_state.current_chat_id = chat_id
                st.rerun()
        with c2:
            # 使用 popover 實作三點設定選單
            with st.popover("⋮", use_container_width=True):
                st.markdown("**設定**")
                
                # 1. 更改對話名稱
                new_name = st.text_input("重新命名", value=chat_data['name'], key=f"ren_{chat_id}")
                if new_name != chat_data['name']:
                    st.session_state.chats[chat_id]['name'] = new_name
                    st.rerun()
                
                # 2. 放入資料夾
                folder_options = ["(未分類)"] + st.session_state.folders
                current_folder_val = chat_data['folder'] if chat_data['folder'] else "(未分類)"
                selected_folder = st.selectbox(
                    "移動到資料夾", 
                    folder_options, 
                    index=folder_options.index(current_folder_val),
                    key=f"mov_{chat_id}"
                )
                
                new_folder_val = None if selected_folder == "(未分類)" else selected_folder
                if new_folder_val != chat_data['folder']:
                    st.session_state.chats[chat_id]['folder'] = new_folder_val
                    st.rerun()
                
                # 3. 刪除對話
                if st.button("🗑️ 刪除", key=f"del_{chat_id}", type="primary"):
                    del st.session_state.chats[chat_id]
                    st.rerun()

    # 先渲染「未分類」（沒有被放入資料夾）的對話
    for cid, cdata in list(st.session_state.chats.items()):
        if cdata['folder'] is None:
            render_chat_item(cid, cdata)

    # 再渲染「資料夾」內的對話
    for folder in st.session_state.folders:
        with st.expander(f"📁 {folder}"):
            # 找出屬於這個資料夾的對話
            folder_chats = {cid: cdata for cid, cdata in st.session_state.chats.items() if cdata['folder'] == folder}
            if not folder_chats:
                st.caption("空資料夾")
            else:
                for cid, cdata in folder_chats.items():
                    render_chat_item(cid, cdata)

    st.divider()
    
    # 將 API 設定移至最下方，保持版面乾淨
    with st.expander("⚙️ 模型與 API 設定"):
        selected_model_name = st.selectbox("挑選 LLM 模型", ["gemini-2.5-flash", "gemini-2.5-pro"])
        system_prompt = st.text_area("System Prompt", value="你是一個熱心且專業的助手，請用繁體中文回答。", height=100)
        temp = st.slider("Temperature", 0.0, 2.0, 1.0, 0.1)
        top_p = st.slider("Top P", 0.0, 1.0, 0.95, 0.05)
        max_tokens = st.number_input("Max Output Tokens", 100, 8192, 2048)

# --- 主畫面：當前對話內容 ---

# 取得當前對話的資料
current_chat_data = st.session_state.chats[st.session_state.current_chat_id]
current_messages = current_chat_data["messages"]

# 顯示當前對話名稱標題
st.subheader(f"🗣️ {current_chat_data['name']}")

# 圖片上傳區塊 (可選)
with st.expander("📷 上傳圖片聊天 (可選)", expanded=False):
    uploaded_image = st.file_uploader("選擇一張圖片...", type=["jpg", "jpeg", "png"])
    if uploaded_image:
        st.image(Image.open(uploaded_image), caption="待分析圖片", width=250)

# 顯示歷史訊息
for message in current_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 對話輸入與處理
if prompt := st.chat_input("你想問什麼？"):
    # 儲存與顯示使用者訊息
    st.session_state.chats[st.session_state.current_chat_id]["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        model = genai.GenerativeModel(
            model_name=selected_model_name,
            system_instruction=system_prompt
        )
        
        # 轉換歷史訊息格式
        history = []
        for msg in current_messages[:-1]: 
            role = "model" if msg["role"] == "assistant" else "user"
            history.append({"role": role, "parts": [msg["content"]]})
        
        chat_session = model.start_chat(history=history)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            # 多模態處理
            request_content = [prompt]
            if uploaded_image:
                pil_image = Image.open(uploaded_image)
                request_content.append(pil_image)

            # 發送請求 (Streaming)
            response = chat_session.send_message(
                request_content,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    top_p=top_p,
                    max_output_tokens=max_tokens
                ),
                stream=True
            )
            
            for chunk in response:
                full_response += chunk.text
                message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
        
        # 儲存模型回覆
        st.session_state.chats[st.session_state.current_chat_id]["messages"].append({"role": "assistant", "content": full_response})

    except Exception as e:
        st.error(f"發生錯誤：{str(e)}")