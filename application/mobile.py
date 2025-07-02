import streamlit as st 
import chat
import json
import knowledge_base as kb
import cost_analysis as cost
import supervisor
import router
import swarm
import traceback
import mcp_config 
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("streamlit")

# Mobile-optimized page configuration
st.set_page_config(
    page_title='MCP Mobile',
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items=None
)

    # Mobile-optimized CSS
st.markdown("""
    <style>
    /* 모바일 환경에 맞는 폰트 크기 조정 */
    .stMarkdown {
        font-size: 16px;
    }
    
    /* 채팅 입력창 크기 조정 */
    .stTextInput > div > div > input {
        font-size: 16px;
    }
    
    /* 버튼 크기 조정 */
    .stButton > button {
        width: 100%;
        font-size: 16px;
    }
    
    /* 사이드바 숨김 */
    [data-testid="stSidebar"] {
        display: none;
    }
    
    /* 메인 컨텐츠 영역 최대화 */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

mode_descriptions = {
    "일상적인 대화": [
        "대화이력을 바탕으로 챗봇과 일상의 대화를 편안히 즐길수 있습니다."
    ],
    "RAG": [
        "Bedrock Knowledge Base를 이용해 구현한 RAG로 필요한 정보를 검색합니다."
    ],
    "Agent": [
        "MCP를 활용한 Agent를 이용합니다."
    ],
    "번역하기": [
        "한국어와 영어에 대한 번역을 제공합니다."
    ],
    "문법 검토하기": [
        "영어와 한국어 문법의 문제점을 설명하고, 수정된 결과를 함께 제공합니다."
    ],
    "이미지 분석": [
        "이미지를 업로드하면 이미지의 내용을 요약할 수 있습니다."
    ]
}

    # Mobile-optimized mode selection
mode = st.selectbox(
    "대화 모드 선택",
    ["일상적인 대화", "RAG", "Agent", "번역하기", "문법 검토하기", "이미지 분석"]
)

st.info(mode_descriptions[mode][0])

    # Model selection
modelName = st.selectbox(
    '사용 모델',
    ("Nova Premier", 'Nova Pro', 'Nova Lite', 'Nova Micro', 'Claude 3.7 Sonnet', 'Claude 3.5 Sonnet', 'Claude 3.0 Sonnet', 'Claude 3.5 Haiku'),
    index=5
)

    # MCP configuration (only for Agent mode)
mcp = ""
if mode == 'Agent':
    mcp_options = ["default", "code interpreter", "aws document", "aws cost", "aws cli", "tavily"]
    mcp_selections = {}
    default_selections = ["default", "tavily", "aws cli", "code interpreter"]
    
    st.subheader("MCP 설정")
    for option in mcp_options:
        default_value = option in default_selections
        mcp_selections[option] = st.checkbox(option, key=f"mcp_{option}", value=default_value)
    
    if not any(mcp_selections.values()):
        mcp_selections["default"] = True
    
    mcp = mcp_config.load_selected_config(mcp_selections)

    # Debug mode
select_debugMode = st.checkbox('Debug Mode', value=False)
debugMode = 'Enable' if select_debugMode else 'Disable'

    # Multi-region configuration
select_multiRegion = st.checkbox('Multi Region', value=False)
multiRegion = 'Enable' if select_multiRegion else 'Disable'

chat.update(modelName, debugMode, multiRegion, mcp)

    # File upload processing
uploaded_file = None
if mode in ['이미지 분석', 'RAG']:
    uploaded_file = st.file_uploader(
        "파일 업로드",
        type=["png", "jpg", "jpeg", "pdf", "txt", "py", "md", "csv", "json"] if mode == 'RAG' else ["png", "jpg", "jpeg"]
    )

    # Chat history initialization
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greetings = False

    # Display chat messages
def display_chat_messages():
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if "images" in message:
                for url in message["images"]:
                    st.image(url, use_column_width=True)
            st.markdown(message["content"])

display_chat_messages()

    # Initial greeting
if not st.session_state.greetings:
    with st.chat_message("assistant"):
        intro = "모바일 환경에서 MCP를 이용해 주셔서 감사합니다. 편안한 대화를 즐기실 수 있습니다."
        st.markdown(intro)
        st.session_state.messages.append({"role": "assistant", "content": intro})
        st.session_state.greetings = True

    # Chat input processing
if prompt := st.chat_input("메시지를 입력하세요"):
    with st.chat_message("user"):
        st.markdown(prompt)
    
    st.session_state.messages.append({"role": "user", "content": prompt})
    prompt = prompt.replace('"', "").replace("'", "")

    with st.chat_message("assistant"):
        if mode == '일상적인 대화':
            stream = chat.general_conversation(prompt)
            response = st.write_stream(stream)
            st.session_state.messages.append({"role": "assistant", "content": response})
            chat.save_chat_history(prompt, response)

        elif mode == 'RAG':
            with st.status("검색 중...", expanded=True, state="running") as status:
                response, reference_docs = chat.run_rag_with_knowledge_base(prompt, st)
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                chat.save_chat_history(prompt, response)

        elif mode == 'Agent':
            chat.references = []
            chat.image_url = []
            response = chat.run_agent(prompt, "Disable", st)

        elif mode == '번역하기':
            response = chat.translate_text(prompt)
            st.write(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
            chat.save_chat_history(prompt, response)

        elif mode == '문법 검토하기':
            response = chat.check_grammer(prompt)
            st.write(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
            chat.save_chat_history(prompt, response)

        elif mode == '이미지 분석':
            if uploaded_file is None:
                st.error("파일을 먼저 업로드하세요.")
                st.stop()
            else:
                if modelName == "Claude 3.5 Haiku":
                    st.error("Claude 3.5 Haiku은 이미지를 지원하지 않습니다. 다른 모델을 선택해주세요.")
                else:
                    with st.status("분석 중...", expanded=True, state="running") as status:
                        summary = chat.get_image_summarization(uploaded_file.name, prompt, st)
                        st.write(summary)
                        st.session_state.messages.append({"role": "assistant", "content": summary}) 