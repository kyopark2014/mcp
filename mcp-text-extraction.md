## 이미지 분석

OCR처럼 이미지의 내용을 읽어서 전달합니다.

[mcp_server_text_extraction.py](./application/mcp_server_text_extraction.py)와 같이 구현됩니다. 아래와 같이 멀티모달을 이용해 text를 추출합니다.

```python
def _extract_text_with_llm(img_base64: str, prompt: Optional[str] = None) -> str:
    """Extract text from image using LLM."""
    query = prompt or "텍스트를 추출해서 markdown 포맷으로 변환하세요. <result> tag를 붙여주세요."

    multimodal = _get_chat()
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                },
                {"type": "text", "text": query},
            ]
        )
    ]

    extracted_text = ""
    for attempt in range(5):
        logger.info(f"LLM attempt: {attempt}")
        try:
            result = multimodal.invoke(messages)
            extracted_text = result.content
            break
        except Exception:
            err_msg = traceback.format_exc()
            logger.warning(f"LLM error: {err_msg}")

    if len(extracted_text) < 10:
        extracted_text = "텍스트를 추출하지 못하였습니다."

    return extracted_text
```

### MCP 설정

```java
{
   "mcpServers":{
      "text_extraction":{
         "command":"python",
         "args":[
            "f""{workingDir}/mcp_server_text_extraction.py"
         ]
      }
   }
}
```
