import streamlit as st
import boto3
import json
from typing import Iterator

# Bedrock 클라이언트 설정
bedrock = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-west-2'
)

def get_response(prompt: str) -> Iterator[str]:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "top_p": 0.9,
    })

    response = bedrock.invoke_model_with_response_stream(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        contentType='application/json',
        accept='application/json',
        body=body
    )

    for event in response.get('body'):
        chunk = json.loads(event['chunk']['bytes'].decode())
        if chunk['type'] == 'content_block_delta':
            yield chunk['delta']['text']

def main():
    st.title("Claude 3 Sonnet Chat")
    
    # 세션 상태 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 채팅 히스토리 표시
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 사용자 입력
    if prompt := st.chat_input("메시지를 입력하세요"):
        # 사용자 메시지 표시
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 어시스턴트 응답 표시
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            # 스트리밍 응답 처리
            for response_chunk in get_response(prompt):
                full_response += response_chunk
                message_placeholder.markdown(full_response + "▌")
            message_placeholder.markdown(full_response)
            
        st.session_state.messages.append({"role": "assistant", "content": full_response})

if __name__ == "__main__":
    main()