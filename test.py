from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

class Weather(BaseModel):
    temperature: float
    condition: str

def weather_tool(city: str) -> str:
    """Get the weather for a city."""
    return f"it's sunny and 70 degrees in {city}"

agent = create_agent(
    "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0",
    tools=[weather_tool],
    response_format=Weather
)
result = agent.invoke({"messages": [HumanMessage("What's the weather in SF?")]})
print(repr(result["structured_response"]))
#> Weather(temperature=70.0, condition='sunny')