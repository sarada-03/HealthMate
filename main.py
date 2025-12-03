# main.py (New Version: HealthMate AI with Chroma)
import streamlit as st
import sqlite3
import hashlib
import os
from pathlib import Path
from dotenv import load_dotenv
from streamlit_option_menu import option_menu
from PyPDF2 import PdfReader
from docx import Document

# LangChain / Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma

# Google GenAI client
import google.generativeai as genai

# Load environment
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ---- Model (HealthMate AI) ----
model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction="""
    You are HealthMate AI, a trusted assistant for reviewing medical records.
    - Provide clear, concise, and empathetic answers.
    - Always add a disclaimer that the response is not medical advice.
    - Highlight key evidence from the documents when possible.
    """
)

# ---- Globals ----
DB_NAME = "healthmate.db"
UPLOAD_DIR = "user_files"
CHROMA_DIR = "chroma_indexes"

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

# --------------------
# Database helpers
# --------------------
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS files(
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """)
    print("Database ready")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def sign_up(name, email, password):
    with sqlite3.connect(DB_NAME) as conn:
        try:
            conn.execute("""
            INSERT INTO users (name, email, password) VALUES (?, ?, ?)
            """, (name, email, hash_password(password)))
            conn.commit()
            return True, "Account created successfully!"
        except sqlite3.IntegrityError:
            return False, "Email already exists."

def login(email, password):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("""
        SELECT user_id, name FROM users WHERE email=? AND password=?
        """, (email, hash_password(password))).fetchone()

def save_file_record(user_id, file_name, file_path):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO files (user_id, file_name, file_path) VALUES (?, ?, ?)",
                     (user_id, file_name, file_path))
        conn.commit()

def get_user_files(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT file_name, file_path FROM files WHERE user_id=?", (user_id,)).fetchall()

def delete_file(user_id, file_name):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM files WHERE user_id=? AND file_name=?", (user_id, file_name))
        conn.commit()

init_db()

# --------------------
# File Text Extraction
# --------------------
def extract_text(path):
    if path.endswith(".pdf"):
        pdf = PdfReader(path)
        return "\n".join([p.extract_text() or "" for p in pdf.pages])
    elif path.endswith(".docx"):
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    elif path.endswith(".txt"):
        return open(path, "r", encoding="utf-8").read()
    return ""

def chunk_text(text, chunk_size=1000, overlap=200):
    text = text.replace("\n", " ").strip()
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - overlap)]

# --------------------
# Vector Store Helpers (Chroma)
# --------------------
def build_or_load_index(file_id, texts):
    os.makedirs(CHROMA_DIR, exist_ok=True)
    index_path = os.path.join(CHROMA_DIR, str(file_id))

    if os.path.exists(index_path):
        return Chroma(persist_directory=index_path, embedding_function=embeddings)

    db = Chroma.from_texts(texts, embeddings, persist_directory=index_path)
    db.persist()
    return db

def generate_answer(query, docs, history):
    context = "\n\n".join([d.page_content[:200] for d in docs])
    disclaimer = "\n\n**Disclaimer:** This is informational only, not medical advice."
    prompt = f"""
    User question: {query}

    Context from documents:
    {context}

    History: {history}

    Provide a helpful answer based on context. {disclaimer}
    """
    response = model.generate_content(prompt)
    return response.text

# --------------------
# Streamlit App
# --------------------
st.set_page_config(page_title="HealthMate AI", page_icon="🧑‍⚕️", layout="wide")

if 'messages' not in st.session_state:
    st.session_state.messages = {}
if 'indexes' not in st.session_state:
    st.session_state.indexes = {}

with st.sidebar:
    selected = option_menu(
        "Menu", ["Login/Signup", "Upload Reports", "HealthMate Chat"],
        icons=["person", "upload", "chat-dots"],
        default_index=0
    )

# ---- Login / Signup ----
if selected == "Login/Signup":
    st.subheader("Login / Signup")
    if "user_id" in st.session_state:
        st.info(f"Logged in as {st.session_state['user_name']}")
        if st.button("Logout"):
            st.session_state.clear()
    else:
        action = st.radio("Choose:", ["Login", "Sign Up"])
        if action == "Sign Up":
            name = st.text_input("Name")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.button("Sign Up"):
                ok, msg = sign_up(name, email, password)
                st.success(msg) if ok else st.error(msg)
        else:
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.button("Login"):
                user = login(email, password)
                if user:
                    st.session_state['user_id'], st.session_state['user_name'] = user
                    st.session_state.messages[user[0]] = []
                    st.success(f"Welcome {user[1]}!")
                else:
                    st.error("Invalid credentials")

# ---- Upload Reports ----
if selected == "Upload Reports":
    if "user_id" not in st.session_state:
        st.warning("Please login first")
    else:
        file = st.file_uploader("Upload medical report", type=["pdf", "docx", "txt"])
        if file:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            file_path = os.path.join(UPLOAD_DIR, f"{st.session_state['user_id']}_{file.name}")
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
            save_file_record(st.session_state['user_id'], file.name, file_path)
            st.success(f"File {file.name} uploaded!")
            text_preview = extract_text(file_path)[:500]
            st.text_area("Preview", text_preview, height=150)

        st.subheader("Your Files")
        files = get_user_files(st.session_state['user_id'])
        for fn, fp in files:
            st.markdown(f"- {fn}")
            if st.button(f"Delete {fn}"):
                delete_file(st.session_state['user_id'], fn)
                if os.path.exists(fp): os.remove(fp)
                st.success(f"Deleted {fn}")

# ---- HealthMate Chat ----
if selected == "HealthMate Chat":
    if "user_id" not in st.session_state:
        st.warning("Please login first")
    else:
        files = get_user_files(st.session_state['user_id'])
        if not files:
            st.info("No reports uploaded yet.")
        else:
            s_file = st.selectbox("Choose report", [f[0] for f in files])
            file_id = s_file
            file_path = next(fp for fn, fp in files if fn == s_file)

            k = st.slider("Chunks to retrieve", 2, 8, 4)

            if st.button("Build / Load Index"):
                text = extract_text(file_path)
                chunks = chunk_text(text)
                db = build_or_load_index(file_id, chunks)
                st.session_state.indexes[file_id] = db
                st.success("Index ready!")

            db = st.session_state.indexes.get(file_id)
            if db:
                history = st.session_state.messages.setdefault(st.session_state['user_id'], [])
                for msg in history:
                    st.chat_message(msg['role']).markdown(msg['content'])

                user_q = st.chat_input("Ask about your report...")
                if user_q:
                    st.chat_message("user").markdown(user_q)
                    history.append({"role": "user", "content": user_q})

                    docs = db.similarity_search(user_q, k=k)
                    answer = generate_answer(user_q, docs, history)

                    st.chat_message("assistant").markdown(answer)
                    history.append({"role": "assistant", "content": answer})
