import streamlit as st 
import streamlit_paste_button as spb
import chat
import utils
import json
import io
import cost_analysis as cost
import traceback
import mcp_config 
import logging
import sys
import os
import pwd 
import asyncio
import uuid
import claude_agent
from notification_queue import NotificationQueue

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("streamlit")

try:
    user_info = pwd.getpwuid(os.getuid())
    username = user_info.pw_name
    home_dir = user_info.pw_dir
    logger.info(f"Username: {username}")
    logger.info(f"Home directory: {home_dir}")
except (ImportError, KeyError):
    username = "root"
    logger.info(f"Username: {username}")
    pass  

os.environ["DEV"] = "true"  # Skip user confirmation of get_user_input

def run_async(coro):
    """Run async function safely in Streamlit environment."""
    try:
        # Check if there's a running event loop
        loop = asyncio.get_running_loop()
        # If we're in a running event loop, use nest_asyncio to allow nested loops
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.run(coro)
    except RuntimeError:
        # No running event loop, use asyncio.run()
        return asyncio.run(coro)

# title
st.set_page_config(page_title='MCP', page_icon=None, layout="centered", initial_sidebar_state="auto", menu_items=None)

# CSS for adjusting sidebar width
st.markdown("""
    <style>
    [data-testid="stSidebar"][aria-expanded="true"] {
        width: 400px !important;
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
        "MCP를 활용한 Agent를 이용합니다. 왼쪽 메뉴에서 필요한 MCP를 선택하세요."
    ],
    "Agent (Chat)": [
        "MCP를 활용한 Agent를 이용합니다. 채팅 히스토리를 이용해 interative한 대화를 즐길 수 있습니다."
    ],
    "번역하기": [
        "한국어와 영어에 대한 번역을 제공합니다. 한국어로 입력하면 영어로, 영어로 입력하면 한국어로 번역합니다."        
    ],
    "문법 검토하기": [
        "영어와 한국어 문법의 문제점을 설명하고, 수정된 결과를 함께 제공합니다."
    ],
    "이미지 분석": [
        "이미지를 업로드하면 이미지의 내용을 요약할 수 있습니다."
    ]
}

def load_image_generator_config():
    config = None
    try:
        with open("image_generator_config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            # logger.info(f"loaded image_generator_config: {config}")
    except FileNotFoundError:
        config = {"seed_image": ""}
        with open("image_generator_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info("Create new image_generator_config.json")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")    
    return config

def update_seed_image_url(url):
    with open("image_generator_config.json", "w", encoding="utf-8") as f:
        config = {"seed_image": url}
        json.dump(config, f, ensure_ascii=False, indent=4)

def cost_analysis():
    st.subheader("📈 Cost Analysis")

    if not cost.visualizations:
        cost.get_visualiation()

    if 'service_pie' in cost.visualizations:
        st.plotly_chart(cost.visualizations['service_pie'])
    if 'daily_trend' in cost.visualizations:
        st.plotly_chart(cost.visualizations['daily_trend'])
    if 'region_bar' in cost.visualizations:
        st.plotly_chart(cost.visualizations['region_bar'])

    with st.status("thinking...", expanded=True, state="running") as status:
        if not cost.cost_data:
            st.info("비용 데이터를 가져옵니다.")
            cost_data = cost.get_cost_analysis()
            logger.info(f"cost_data: {cost_data}")
            cost.cost_data = cost_data
        else:
            if not cost.insights:        
                st.info("잠시만 기다리세요. 지난 한달간의 사용량을 분석하고 있습니다...")
                insights = cost.generate_cost_insights()
                logger.info(f"insights: {insights}")
                cost.insights = insights
            
            st.markdown(cost.insights)
            st.session_state.messages.append({"role": "assistant", "content": cost.insights})

seed_config = load_image_generator_config()
# logger.info(f"seed_config: {seed_config}")
seed_image_url = seed_config.get("seed_image", "") if seed_config else ""
#logger.info(f"seed_image_url from config: {seed_image_url}")

agentType = None
uploaded_seed_image = None
with st.sidebar:
    st.title("🔮 Menu")
    
    st.markdown(
        "Amazon Bedrock을 이용해 다양한 형태의 대화를 구현합니다." 
        "여기에서는 MCP를 이용해 RAG를 구현하고, Multi agent를 이용해 다양한 기능을 구현할 수 있습니다." 
        "또한 번역이나 문법 확인과 같은 용도로 사용할 수 있습니다."
        "상세한 코드는 [Github](https://github.com/kyopark2014/mcp)을 참조하세요."
    )

    st.subheader("🐱 대화 형태")
    
    # radio selection
    mode = st.radio(
        label="원하는 대화 형태를 선택하세요. ",options=[
            "일상적인 대화", 
            "RAG", 
            "Agent", 
            "Agent (Chat)", 
            "번역하기", 
            "문법 검토하기", 
            "이미지 분석"
        ], index=3
    )   
    st.info(mode_descriptions[mode][0])
    
    if mode=='Agent' or mode=='Agent (Chat)':
        agentType = st.radio(
            label="Agent 타입을 선택하세요. ",options=["langgraph", "strands", "claude"], index=0
            # label="Agent 타입을 선택하세요. ",options=["langgraph", "strands"], index=0
        )

    # mcp selection    
    if mode=='Agent' or mode=='Agent (Chat)' or mode=='비용 분석' or mode=='Swarm Agent' or mode=='Agent with Plan':
        # MCP Config JSON input
        st.subheader("⚙️ MCP Config")

        # Change radio to checkbox
        mcp_options = [
            "knowledge base",
            "notion", "slack", "text_extraction", "pdf-generator", "web_fetch", "outlook", "trade_info", "gog",
            "weather", "korea_weather", "books", "obsidian", "browser-use",        
            "use-aws", 
            "aws-knowledge", "aws-api", "aws document", "aws cost", "aws cli", "aws ccapi",
            "aws cloudwatch", "aws storage", 
            "image generation", "aws diagram", 
            "repl coder",
            "tavily", "perplexity", "ArXiv", "wikipedia", 
            "text editor", "github", "drawio", "aws-drawio"
            "context7", "puppeteer", "playwright", "firecrawl", "airbnb", 
            "pubmed", "chembl", "clinicaltrial", "arxiv-manual", 
            "AWS Sentral (Employee)", "AWS Outlook (Employee)",
            "AWS Slack (Employee)", "AWS Loop (Employee)",
            "사용자 설정"
        ]
        mcp_selections = {}
        default_selections = ["korea_weather", "web_fetch"]
                
        with st.expander("MCP 옵션 선택", expanded=True):            
            # Create two columns
            col1, col2 = st.columns(2)
            
            # Split options into two groups
            mid_point = len(mcp_options) // 2
            first_half = mcp_options[:mid_point]
            second_half = mcp_options[mid_point:]
            
            # Display first group in the first column
            with col1:
                for option in first_half:
                    default_value = option in default_selections
                    mcp_selections[option] = st.checkbox(option, key=f"mcp_{option}", value=default_value)
            
            # Display second group in the second column
            with col2:
                for option in second_half:
                    default_value = option in default_selections
                    mcp_selections[option] = st.checkbox(option, key=f"mcp_{option}", value=default_value)
        
        if mcp_selections["사용자 설정"]:
            mcp = {}
            try:
                with open("user_defined_mcp.json", "r", encoding="utf-8") as f:
                    mcp = json.load(f)
                    logger.info(f"loaded user defined mcp: {mcp}")
            except FileNotFoundError:
                logger.info("user_defined_mcp.json not found")
                pass
            
            mcp_json_str = json.dumps(mcp, ensure_ascii=False, indent=2) if mcp else ""
            
            mcp_info = st.text_area(
                "MCP 설정을 JSON 형식으로 입력하세요",
                value=mcp_json_str,
                height=150
            )
            logger.info(f"mcp_info: {mcp_info}")

            if mcp_info:
                try:
                    mcp_config.mcp_user_config = json.loads(mcp_info)
                    logger.info(f"mcp_user_config: {mcp_config.mcp_user_config}")                    
                    st.success("JSON 설정이 성공적으로 로드되었습니다.")                    
                except json.JSONDecodeError as e:
                    st.error(f"JSON 파싱 오류: {str(e)}")
                    st.error("올바른 JSON 형식으로 입력해주세요.")
                    logger.error(f"JSON 파싱 오류: {str(e)}")
                    mcp_config.mcp_user_config = {}
            else:
                mcp_config.mcp_user_config = {}
                
            with open("user_defined_mcp.json", "w", encoding="utf-8") as f:
                json.dump(mcp_config.mcp_user_config, f, ensure_ascii=False, indent=4)
            logger.info("save to user_defined_mcp.json")
        
        if mcp_selections["image generation"]:
            enable_seed = st.checkbox("Seed Image", value=False)

            if enable_seed:
                st.subheader("🌇 이미지 업로드")
                uploaded_seed_image = st.file_uploader("이미지 생성을 위한 파일을 선택합니다.", type=["png", "jpg", "jpeg"])

                if uploaded_seed_image:
                    url = chat.upload_to_s3(uploaded_seed_image.getvalue(), uploaded_seed_image.name)
                    logger.info(f"uploaded url: {url}")
                    seed_image_url = url
                    update_seed_image_url(seed_image_url)
                
                given_image_url = st.text_input("또는 이미지 URL을 입력하세요", value=seed_image_url, key="seed_image_input")       
                if given_image_url and given_image_url != seed_image_url:       
                    logger.info(f"given_image_url: {given_image_url}")
                    seed_image_url = given_image_url
                    update_seed_image_url(seed_image_url)                    
            else:
                if seed_image_url:
                    logger.info(f"remove seed_image_url")
                    update_seed_image_url("") 
        else:
            enable_seed = False
            if seed_image_url:
                logger.info(f"remove seed_image_url")
                update_seed_image_url("") 

        mcp_servers = [server for server, is_selected in mcp_selections.items() if is_selected]
    else:
        mcp_servers = []

    # model selection box
    modelName = st.selectbox(
        '🖊️ 사용 모델을 선택하세요',
        (
            "Claude 4.6 Sonnet",
            "Claude 4.7 Opus",                        
            "Claude 4.6 Opus",
            "Claude 4.5 Haiku",
            "Claude 4.5 Sonnet",
            "Claude 4.5 Opus",  
            "OpenAI OSS 120B",
            "OpenAI OSS 20B",
            "Nova 2 Lite",
            "Nova Premier", 
            "Nova Pro", 
            "Nova Lite", 
            "Nova Micro",            
        ), index=0
    )

    # debug checkbox
    select_debugMode = st.checkbox('Debug Mode', value=True)
    debugMode = 'Enable' if select_debugMode else 'Disable'

    # multi region check box
    select_multiRegion = st.checkbox('Multi Region', value=False)
    multiRegion = 'Enable' if select_multiRegion else 'Disable'

    # extended thinking of claude 3.7 sonnet
    reasoningMode = "Disable"
    if mode == "일상적인 대화" or mode == "RAG":
        select_reasoning = st.checkbox('Reasoning', value=False)
        reasoningMode = 'Enable' if select_reasoning else 'Disable'
        # logger.info(f"reasoningMode: {reasoningMode}")

    uploaded_file = None
    pasted_image = None

    def safe_paste_button(label, key):
        """streamlit-paste-button 래퍼: 내부 이미지 디코딩 실패 시 안전하게 처리"""
        try:
            result = spb.paste_image_button(label, key=key, errors="ignore")
            if result.image_data is not None:
                return result.image_data
        except Exception as e:
            logger.warning(f"clipboard paste error: {e}")
        return None

    if mode=='이미지 분석':
        st.subheader("🌇 이미지 업로드")
        uploaded_file = st.file_uploader("이미지 요약을 위한 파일을 선택합니다.", type=["png", "jpg", "jpeg"])

        st.markdown("**또는** 화면 캡처를 붙여넣으세요:")
        pasted_image = safe_paste_button("📋 클립보드에서 붙여넣기", key="paste_image")

    elif mode=='RAG' or mode=="Agent" or mode=="Agent (Chat)":
        st.subheader("📋 문서/이미지 업로드")
        uploaded_file = st.file_uploader("RAG를 위한 파일을 선택합니다.", type=["pdf", "txt", "py", "md", "csv", "json", "png", "jpg", "jpeg"], key=chat.fileId)

    chat.update(modelName, debugMode, multiRegion, reasoningMode, agentType)    

    st.success(f"Connected to {modelName}", icon="💚")
    clear_button = st.button("대화 초기화", key="clear")
    # logger.info(f"clear_button: {clear_button}")

st.title('🔮 '+ mode)

if clear_button==True:    
    cost.cost_data = {}
    cost.visualizations = {}

    chat.map_chain = dict() 
    chat.checkpointers = dict() 
    chat.memorystores = dict() 
    chat.initiate()

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greetings = False

# Display chat messages from history on app rerun
def display_chat_messages() -> None:
    """logger.info message history
    @returns None
    """
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if "images" in message:                
                for url in message["images"]:
                    if url and url.strip():  # 빈 문자열이나 공백만 있는 경우 건너뛰기
                        logger.info(f"url: {url}")

                        file_name = url[url.rfind('/')+1:]
                        st.image(url, caption=file_name, use_container_width=True)
            st.markdown(message["content"])

display_chat_messages()

def show_references(reference_docs):
    if debugMode == "Enable" and reference_docs:
        with st.expander(f"답변에서 참조한 {len(reference_docs)}개의 문서입니다."):
            for i, doc in enumerate(reference_docs):
                st.markdown(f"**{doc.metadata['name']}**: {doc.page_content}")
                st.markdown("---")

# Greet user
if not st.session_state.greetings:
    with st.chat_message("assistant"):
        intro = "아마존 베드락을 이용하여 주셔서 감사합니다. 편안한 대화를 즐기실수 있으며, 파일을 업로드하면 요약을 할 수 있습니다."
        st.markdown(intro)
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": intro})
        st.session_state.greetings = True

if clear_button or "messages" not in st.session_state:
    st.session_state.messages = []        
    uploaded_file = None
    
    st.session_state.greetings = False
    chat.clear_chat_history()
    st.rerun()    

# Preview the uploaded image in the sidebar
file_name = ""
file_bytes = None
state_of_code_interpreter = False

# Handle pasted image from clipboard
if pasted_image is not None and clear_button==False:
    buf = io.BytesIO()
    pasted_image.save(buf, format="PNG")
    file_bytes = buf.getvalue()
    file_name = "pasted_screenshot.png"
    logger.info(f"pasted image: {file_name}, size={len(file_bytes)} bytes")

    if mode == '이미지 분석':
        st.image(pasted_image, caption="붙여넣은 이미지 미리보기", use_container_width=True)

if uploaded_file is not None and clear_button==False:
    logger.info(f"uploaded_file.name: {uploaded_file.name}")
    if uploaded_file.name:
        logger.info(f"csv type? {uploaded_file.name.lower().endswith(('.csv'))}")

    if uploaded_file.name and not mode == '이미지 분석':
        chat.initiate()

        if debugMode=='Enable':
            status = '선택한 파일을 업로드합니다.'
            logger.info(f"status: {status}")
            st.info(status)

        file_name = uploaded_file.name
        logger.info(f"uploading... file_name: {file_name}")
        file_url = chat.upload_to_s3(uploaded_file.getvalue(), file_name)
        logger.info(f"file_url: {file_url}")

        utils.sync_data_source()  # sync uploaded files
            
        status = f'선택한 "{file_name}"의 내용을 요약합니다.'
        if debugMode=='Enable':
            logger.info(f"status: {status}")
            st.info(status)
    
        msg = chat.get_summary_of_uploaded_file(file_name, st)
        st.session_state.messages.append({"role": "assistant", "content": f"선택한 문서({file_name})를 요약하면 아래와 같습니다.\n\n{msg}"})    
        logger.info(f"msg: {msg}")

        st.write(msg)

    if uploaded_file and clear_button==False and mode == '이미지 분석':
        st.image(uploaded_file, caption="이미지 미리보기", use_container_width=True)

        file_name = uploaded_file.name
        url = chat.upload_to_s3(uploaded_file.getvalue(), file_name)
        logger.info(f"url: {url}")

if seed_image_url and clear_button==False and enable_seed==True:
    st.image(seed_image_url, caption="이미지 미리보기", use_container_width=True)
    logger.info(f"preview: {seed_image_url}")
    
# Always show the chat input
if prompt := st.chat_input("메시지를 입력하세요."):
    with st.chat_message("user"):  # display user message in chat message container
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})  # add user message to chat history
    prompt = prompt.replace('"', "").replace("'", "")
    logger.info(f"prompt: {prompt}")

    with st.chat_message("assistant"):
        if mode == '일상적인 대화':
            stream = chat.general_conversation(prompt, st)            
            response = st.write_stream(stream)
            logger.info(f"response: {response}")
            st.session_state.messages.append({"role": "assistant", "content": response})

            chat.save_chat_history(prompt, response)

        elif mode == 'RAG':
            with st.status("running...", expanded=True, state="running") as status:
                response, reference_docs = chat.run_rag_with_knowledge_base(prompt, st)                           
                st.write(response)
                logger.info(f"response: {response}")

                st.session_state.messages.append({"role": "assistant", "content": response})

                chat.save_chat_history(prompt, response)
            
            show_references(reference_docs) 
        
        elif mode == 'Agent' or mode == 'Agent (Chat)':            
            sessionState = ""
            if mode == 'Agent':
                history_mode = "Disable"
            else:
                history_mode = "Enable"

            with st.status("thinking...", expanded=True, state="running") as status:
                notification_queue = NotificationQueue(container=status)

                if agentType == "langgraph":
                    response, artifacts = asyncio.run(chat.run_langgraph_agent(
                        query=prompt, 
                        mcp_servers=mcp_servers, 
                        history_mode=history_mode, 
                        notification_queue=notification_queue))

                elif agentType == "strands":
                    response, artifacts = asyncio.run(chat.run_strands_agent(
                        query=prompt, 
                        strands_tools=[], 
                        mcp_servers=mcp_servers, 
                        history_mode=history_mode, 
                        notification_queue=notification_queue))
                
                elif agentType == "claude":
                    response, artifacts = asyncio.run(claude_agent.run_claude_agent(
                        prompt=prompt, 
                        mcp_servers=mcp_servers, 
                        history_mode=history_mode, 
                        notification_queue=notification_queue))

                if debugMode == "Disable":
                    st.markdown(response)
        
            st.session_state.messages.append({
                "role": "assistant", 
                "content": response,
                "artifacts": artifacts if artifacts else []
            })

            if artifacts:
                for url in artifacts:
                    if url and url.strip():  # 빈 문자열이나 공백만 있는 경우 건너뛰기
                        logger.info(f"url: {url}")
                        file_name = url[url.rfind('/')+1:]
                        st.image(url, caption=file_name, use_container_width=True)

        elif mode == '번역하기':
            response = chat.translate_text(prompt)
            st.write(response)

            st.session_state.messages.append({"role": "assistant", "content": response})

        elif mode == '문법 검토하기':
            response = chat.check_grammer(prompt)
            st.write(response)

            st.session_state.messages.append({"role": "assistant", "content": response})
        
        elif mode == '이미지 분석':
            if (uploaded_file is None or uploaded_file == "") and file_bytes is None:
                st.error("이미지를 먼저 업로드하거나 클립보드에서 붙여넣으세요.")
                st.stop()

            else:
                with st.status("thinking...", expanded=True, state="running") as status:
                    if file_bytes is not None:
                        summary = chat.summarize_image(file_bytes, prompt, st)
                    else:
                        summary = chat.get_image_summarization(file_name, prompt, st)
                    st.write(summary)

                    chat.save_chat_history("문서 분석 결과", summary)
                    st.session_state.messages.append({"role": "assistant", "content": summary})                

        elif mode == '비용 분석':
            with st.status("thinking...", expanded=True, state="running") as status:
                response = cost.ask_cost_insights(prompt)
                st.write(response)

                st.session_state.messages.append({"role": "assistant", "content": response})

        else:
            stream = chat.general_conversation(prompt)

            response = st.write_stream(stream)
            logger.info(f"response: {response}")

            st.session_state.messages.append({"role": "assistant", "content": response})
        

def main():
    """Entry point for the application."""
    # This function is used as an entry point when running as a package
    # The code above is already running the Streamlit app
    pass


if __name__ == "__main__":
    # This is already handled by Streamlit
    pass
