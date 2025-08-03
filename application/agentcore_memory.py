import os
import json
import logging
import sys

from typing import Dict, Optional
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
accountId = config['accountId']
projectName = config['projectName']
agentcore_memory_role = config['agentcore_memory_role']

def load_memory_variables():
    memory_id = user_id = actor_id = session_id = namespace = None
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        agentcore_path = os.path.join(script_dir, "agentcore.json")
        with open(agentcore_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

            if 'memory_id' in json_data:
                memory_id = json_data['memory_id']
                logger.info(f"memory_id: {memory_id}")

            if 'user_id' in json_data:
                user_id = json_data['user_id']
                logger.info(f"user_id: {user_id}")

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
    
    return memory_id, user_id, actor_id, session_id, namespace

# initialize memory_client
memory_id, user_id, actor_id, session_id, namespace = load_memory_variables()
memory_client = MemoryClient(region_name=bedrock_region)

def update_memory_variables(    
    new_memory_id: Optional[str]=None, 
    new_user_id: Optional[str]=None,
    new_actor_id: Optional[str]=None, 
    new_session_id: Optional[str]=None, 
    new_namespace: Optional[str]=None):
    global memory_id, user_id, actor_id, session_id, namespace
    
    logger.info(f"###### update_memory_variables ######")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "agentcore.json")
    
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    
    # Update config with new values
    if new_memory_id is not None:
        config['memory_id'] = new_memory_id
        memory_id = new_memory_id
    if new_user_id is not None:
        config['user_id'] = new_user_id
        user_id = new_user_id
    if new_actor_id is not None:
        config['actor_id'] = new_actor_id
        actor_id = new_actor_id
    if new_session_id is not None:
        config['session_id'] = new_session_id
        session_id = new_session_id
    if new_namespace is not None:
        config['namespace'] = new_namespace
        namespace = new_namespace
    
    # Save to file
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    
    logger.info(f"config was updated to {config}")    

CUSTOM_PROMPT = (
    "You are tasked with analyzing conversations to extract the user's general preferences."
     "You'll be analyzing two sets of data:"
     "<past_conversation>"
     "[Past conversations between the user and system will be placed here for context]"
     "</past_conversation>"
     "<current_conversation>"
     "[The current conversation between the user and system will be placed here]"
     "</current_conversation>"
     "Your job is to identify and categorize the user's general preferences across various topics and domains."
     "- Extract user preferences for different types of content, services, or products they show interest in."
     "- Identify communication style preferences, such as formal vs casual, detailed vs concise."
     "- Recognize technology preferences, such as specific platforms, tools, or applications they prefer."
     "- Note any recurring themes or topics the user is particularly interested in or knowledgeable about."
     "- Capture any specific requirements or constraints they mention in their interactions."
     "use Korean language."
)

def init_memory(userId, actorId, sessionId):
    global memory_id, user_id, actor_id, session_id, namespace
    
    logger.info(f"###### init_memory ######")

    if userId is not None:
        user_id = userId
    if actorId is not None:
        actor_id = actorId
    if sessionId is not None:
        session_id = sessionId

    memories = memory_client.list_memories()
    logger.info(f"memories: {memories}")
    for memory in memories:            
        logger.info(f"Memory ID: {memory.get('id')}")
        memory_name = memory.get('id').split("-")[0]
        if memory_name == projectName:
            logger.info(f"The memory of {memory_name} was found")
            memory_id = memory.get('id')
            logger.info(f"Memory Arn: {memory.get('arn')}")
            break

    namespace = f"/users/{actor_id}"
    if memory_id is None:  # memory_id still not found, create new memory_id        
        result = memory_client.create_memory_and_wait(
            name=projectName,
            description=f"Memory for {projectName}",
            event_expiry_days=365, # 7 - 365 days
            # memory_execution_role_arn=memory_execution_role_arn
            strategies=[{
                #"userPreferenceMemoryStrategy": {
                "customMemoryStrategy": {
                    "name": "UserPreference",
                    "namespaces": [namespace],
                    "configuration" : {
                        "userPreferenceOverride" : {
                            "extraction" : {
                                "modelId" : "anthropic.claude-3-5-sonnet-20241022-v2:0",
                                "appendToPrompt": CUSTOM_PROMPT
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

    update_memory_variables(new_memory_id=memory_id, new_user_id=user_id, new_actor_id=actor_id, new_session_id=session_id, new_namespace=namespace)
    
def save_conversation_to_memory(query, result):
    logger.info(f"###### save_conversation_to_memory ######")
    logger.info(f"memory_id: {memory_id}, user_id: {user_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")

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

def get_memory_record():
    logger.info(f"###### get_memory_record ######")    
    logger.info(f"memory_id: {memory_id}, user_id: {user_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")
    
    conversations = memory_client.list_events(
        memory_id=memory_id,
        actor_id=actor_id,
        session_id=session_id,
        max_results=5,
    )
    logger.info(f"conversations: {conversations}")

    return conversations

