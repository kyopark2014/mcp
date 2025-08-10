import os
import json
import logging
import sys
import uuid
import chat
import time

from typing import Dict, Optional, Required
from bedrock_agentcore.memory import MemoryClient
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("agentcore_memory")

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']
agentcore_memory_role = config['agentcore_memory_role']

memory_client = MemoryClient(region_name=bedrock_region)    

def load_memory_variables(user_id: str):
    memory_id = actor_id = session_id = namespace = None
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        agentcore_path = os.path.join(script_dir, f"user_{user_id}.json")
        with open(agentcore_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

            if 'memory_id' in json_data:
                memory_id = json_data['memory_id']
                logger.info(f"memory_id: {memory_id}")

            if 'actor_id' in json_data:
                actor_id = json_data['actor_id']
                logger.info(f"actor_id: {actor_id}")
            
            if 'session_id' in json_data:
                session_id = json_data['session_id']
                logger.info(f"session_id: {session_id}")
            
            if 'namespace' in json_data:
                namespace = json_data['namespace']
                logger.info(f"namespace: {namespace}")
                
    except Exception as e:        
        logger.error(f"Error loading agentcore config: {e}")
        pass

    if actor_id is None:
        actor_id = user_id
    if session_id is None:
        session_id = uuid.uuid4().hex
    if namespace is None:
        namespace = f"/users/{actor_id}"
    
    return memory_id, actor_id, session_id, namespace

def update_memory_variables(
    user_id: str,
    memory_id: Optional[str]=None, 
    actor_id: Optional[str]=None, 
    session_id: Optional[str]=None, 
    namespace: Optional[str]=None):
    
    logger.info(f"###### update_memory_variables ######")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, f"user_{user_id}.json")    
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    
    # Update config with new values
    if memory_id is not None:
        config['memory_id'] = memory_id
    if actor_id is not None:
        config['actor_id'] = actor_id
    if session_id is not None:
        config['session_id'] = session_id
    else:
        if 'session_id' in config:
            session_id = config['session_id']        
        if session_id is None:
            session_id = uuid.uuid4().hex
            config['session_id'] = session_id
            
    if namespace is not None:
        config['namespace'] = namespace
    
    # Save to file
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    
    logger.info(f"config was updated to {config}")    

# CUSTOM_PROMPT = (
#     "You are tasked with analyzing conversations to extract the user's general preferences."
#      "You'll be analyzing two sets of data:"
#      "<past_conversation>"
#      "[Past conversations between the user and system will be placed here for context]"
#      "</past_conversation>"
#      "<current_conversation>"
#      "[The current conversation between the user and system will be placed here]"
#      "</current_conversation>"
#      "Your job is to identify and categorize the user's general preferences across various topics and domains."
#      "- Extract user preferences for different types of content, services, or products they show interest in."
#      "- Identify communication style preferences, such as formal vs casual, detailed vs concise."
#      "- Recognize technology preferences, such as specific platforms, tools, or applications they prefer."
#      "- Note any recurring themes or topics the user is particularly interested in or knowledgeable about."
#      "- Capture any specific requirements or constraints they mention in their interactions."
#      "use Korean."
# )

USER_PREFERENCE_PROMPT = (
    "You are tasked with analyzing conversations to extract the user's preferences. You'll be analyzing two sets of data:\n"
    "<past_conversation>\n"
    "[Past conversations between the user and system will be placed here for context]\n"
    "</past_conversation>\n"
    "<current_conversation>\n"
    "[The current conversation between the user and system will be placed here]\n"
    "</current_conversation>\n"
    "Your job is to identify and categorize the user's preferences into two main types:\n"
    "- Explicit preferences: Directly stated preferences by the user.\n"
    "- Implicit preferences: Inferred from patterns, repeated inquiries, or contextual clues. Take a close look at user's request for implicit preferences.\n"
    "For explicit preference, extract only preference that the user has explicitly shared. Do not infer user's preference.\n"
    "For implicit preference, it is allowed to infer user's preference, but only the ones with strong signals, such as requesting something multiple times.\n"
    "Use Korean.\n"
)

SUMMARY_PROMPT = (
    "You will be given a text block and a list of summaries you previously generated when available.\n"
    "<task>\n"
    "- When the previously generated is not available, your goal is to summarize the given text block.\n"
    "- When there is existing summary, your goal is to extend summary by taking into account the given text block.\n"
    "- If there are queries/topics specified in the text block, your generated summary need to cover those queries/topics.\n"
    "- If there are instructions in the text block **guiding you how to generate suummary**, you MUST follow them.\n"
    "</task>\n"
    "Use Korean.\n"
)

SEMENTIC_PROMPT = (
    "You are a long-term memory extraction agent supporting a lifelong learning system.\n"
    "Your task is to identify and extract meaningful information about the users from a given list of messages.\n"
    "Analyze the conversation and extract structured information about the user according to the schema below.\n"
    "Only include details that are explicitly stated or can be logically inferred from the conversation.\n"
    "- Extract information ONLY from the user messages. You should use assistant messages only as supporting context.\n"
    "- If the conversation contains no relevant or noteworthy information, return an empty list.\n"
    "- Do NOT extract anything from prior conversation history, even if provided. Use it solely for context.\n"
    "- Do NOT incorporate external knowledge.\n"
    "- Avoid duplicate extractions.\n"
    "Use Korean.\n"
)

def retrieve_memory_id():
    memory_id = None
    memory_name = projectName.replace("-", "_")  # use projectName as memory name

    memories = memory_client.list_memories()
    logger.info(f"memories: {memories}")
    for memory in memories:            
        logger.info(f"Memory ID: {memory.get('id')}")
        if memory.get('id').split("-")[0] == memory_name:
            logger.info(f"The memory of {memory_name} was found")
            memory_id = memory.get('id')
            logger.info(f"Memory Arn: {memory.get('arn')}")
            break

    return memory_id

def load_memory_strategy(memory_id: str):
    strategies = memory_client.get_memory_strategies(memory_id)
    logger.info(f"strategies: {strategies}")
    return strategies

def add_strategy(memory_id: str, namespace: str):
    strategy = {
            "customMemoryStrategy": {
                "name": chat.user_id,
                "namespaces": [namespace],
                "configuration" : {
                    "userPreferenceOverride" : {
                        "extraction" : {
                            "modelId" : "anthropic.claude-3-5-sonnet-20241022-v2:0",
                            "appendToPrompt": USER_PREFERENCE_PROMPT
                        }
                    }
                }
            }
        }
    memory_client.add_strategy(memory_id, strategy)
    logger.info(f"strategy was added to memory_id: {memory_id}")
    time.sleep(5)

def create_strategy_if_not_exists(memory_id: str, namespace: str, strategy_name: str):
    # create strategy if not exists
    has_strategy = False
    strategies = load_memory_strategy(memory_id)
    for strategy in strategies:
        logger.info(f"strategy: {strategy}")
        if strategy.get("name") == strategy_name:
            logger.info(f"UserPreference strategy found")
            has_strategy = True
            break
    if not has_strategy:
        logger.info(f"UserPreference strategy not found, adding...")
        add_strategy(memory_id, namespace)
        logger.info(f"UserPreference strategy was added...")

def create_memory(namespace: str):
    result = memory_client.create_memory_and_wait(
        name=projectName.replace("-", "_"),
        description=f"Memory for {projectName}",
        event_expiry_days=365, # 7 - 365 days
        # memory_execution_role_arn=memory_execution_role_arn
        strategies=[{
            #"userPreferenceMemoryStrategy": {
            "customMemoryStrategy": {
                "name": chat.user_id,
                "namespaces": [namespace],
                "configuration" : {
                    "userPreferenceOverride" : {
                        "extraction" : {
                            "modelId" : "anthropic.claude-3-5-sonnet-20241022-v2:0",
                            "appendToPrompt": USER_PREFERENCE_PROMPT
                        }
                    }
                }
            }
        }],
        memory_execution_role_arn=agentcore_memory_role
    )
    logger.info(f"result of memory creation: {result}")
    memory_id = result.get('id')
    logger.info(f"created memory_id: {memory_id}")

    return memory_id
    
def save_conversation_to_memory(memory_id, actor_id, session_id, query, result):
    logger.info(f"###### save_conversation_to_memory ######")

    event_timestamp = datetime.now(timezone.utc)
    conversation = [
        (query, "USER"),
        (result, "ASSISTANT")
    ]

    memory_result = memory_client.create_event(
        memory_id=memory_id,
        actor_id=actor_id, 
        session_id=session_id, 
        event_timestamp=event_timestamp,
        messages=conversation
    )
    logger.info(f"result of save conversation to memory: {memory_result}")

def get_memory_record(user_id: str):
    logger.info(f"###### get_memory_record ######")    

    memory_id, actor_id, session_id, namespace = load_memory_variables(user_id)
    logger.info(f"memory_id: {memory_id}, user_id: {user_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")
    
    conversations = memory_client.list_events(
        memory_id=memory_id,
        actor_id=actor_id,
        session_id=session_id,
        max_results=5,
    )
    logger.info(f"conversations: {conversations}")

    return conversations


