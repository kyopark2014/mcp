from strands import Agent

# Create an agent
agent = Agent()

# Send a message and get a response
agent("안녕 내 이름은 경수야.")

agent("나는 서울에 살고 있어.")

agent("경수는 어디에 살아?")

# Access the conversation history
# print(agent.messages)  # Shows all messages exchanged so far