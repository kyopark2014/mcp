"""
AgentCore Memory Tool 
modified from strands_tools.agent_core_memory: https://github.com/strands-agents/tools/blob/main/src/strands_tools/agent_core_memory.py

Memory Record Operations:
   • retrieve_memory_records: Semantic search for extracted memories
   • list_memory_records: List all memory records
   • get_memory_record: Get specific memory record
   • delete_memory_record: Delete memory records
"""

import json
import logging
import boto3
import os
import sys
import agentcore_memory
import utils

from datetime import datetime, timezone
from typing import Dict, Optional

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("memory")

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

bedrock_agent_core_client = boto3.client(
    "bedrock-agentcore",
    region_name=bedrock_region
)
# memory_client = MemoryClient(region_name="us-west-2")

def create_event(
    memory_id: str,
    actor_id: str,
    session_id: str,
    content: str,
    event_timestamp: Optional[datetime] = None,
) -> Dict:
    """
    Create an event in a memory session.

    Creates a new event record in the specified memory session. Events are immutable
    records that capture interactions or state changes in your application.

    Args:
        memory_id: ID of the memory store
        actor_id: ID of the actor (user, agent, etc.) creating the event
        session_id: ID of the session this event belongs to
        payload: Text content to store as a memory
        event_timestamp: Optional timestamp for the event (defaults to current time)

    Returns:
        Dict: Response containing the created event details

    Raises:
        ValueError: If required parameters are invalid
        RuntimeError: If the API call fails
    """

    # Set default timestamp if not provided
    if event_timestamp is None:
        event_timestamp = datetime.now(timezone.utc)

    # Format the payload for the API
    formatted_payload = [{"conversational": {"content": {"text": content}, "role": "ASSISTANT"}}]

    return bedrock_agent_core_client.create_event( # boto3 api
        memoryId=memory_id,
        actorId=actor_id,
        sessionId=session_id,
        eventTimestamp=event_timestamp,
        payload=formatted_payload,
    )

# memory_result = memory_client.create_event( # memory sdk
#         memory_id=memory_id,
#         actor_id=user_id, 
#         session_id=user_id, 
#         messages=[
#             (query, "USER"),
#             (result, "ASSISTANT")
#         ]
#     )

def retrieve_memory_records(
    memory_id: str,
    namespace: str,
    search_query: str,
    max_results: Optional[int] = 20, 
    next_token: Optional[str] = None,
) -> Dict:
    """
    Retrieve memory records using semantic search.

    Performs a semantic search across memory records in the specified namespace,
    returning records that semantically match the search query. Results are ranked
    by relevance to the query.

    Args:
        memory_id: ID of the memory store to search in
        namespace: Namespace to search within (e.g., "actor/user123/userId")
        search_query: Natural language query to search for
        max_results: Maximum return in a single call (default: 20, max: 100)
        next_token: Pagination token for retrieving additional results

    Returns:
        Dict: Response containing matching memory records and optional next_token
    """
    logger.info(f"###### retrieve_memory_records ######")
    logger.info(f"memory_id: {memory_id}, namespace: {namespace}, search_query: {search_query}, max_results: {max_results}, next_token: {next_token}")

    # Prepare request parameters
    topK = 20 # Maximum number of top-scoring memory records to return
    params = {"memoryId": memory_id, "namespace": namespace, "searchCriteria": {"topK":topK, "searchQuery": search_query}}
    if max_results is not None:
        params["maxResults"] = max_results
    if next_token is not None:
        params["nextToken"] = next_token

    return bedrock_agent_core_client.retrieve_memory_records(**params)

def get_memory_record(
    memory_id: str,
    memory_record_id: str,
) -> Dict:
    """Get a specific memory record."""
    return bedrock_agent_core_client.get_memory_record(
        memoryId=memory_id,
        memoryRecordId=memory_record_id,
    )

def list_memory_records(
    memory_id: str,
    namespace: str,
    max_results: Optional[int] = None,
    next_token: Optional[str] = None,
) -> Dict:
    """List memory records."""

    logger.info(f"###### list_memory_records ######")
    logger.info(f"memory_id: {memory_id}, namespace: {namespace}, max_results: {max_results}, next_token: {next_token}")

    params = {"memoryId": memory_id}
    if namespace is not None:
        params["namespace"] = namespace
    if max_results is not None:
        params["maxResults"] = max_results
    if next_token is not None:
        params["nextToken"] = next_token
    return bedrock_agent_core_client.list_memory_records(**params)

def delete_memory_record(
    memory_id: str,
    memory_record_id: str,
) -> Dict:
    """Delete a specific memory record."""
    return bedrock_agent_core_client.delete_memory_record(
        memoryId=memory_id,
        memoryRecordId=memory_record_id,
    )

def agent_core_memory(
    action: str,
    content: Optional[str] = None,
    query: Optional[str] = None,
    memory_record_id: Optional[str] = None,
    max_results: Optional[int] = 10,
    next_token: Optional[str] = None,
) -> Dict:
    """
    Work with agent memories - create, search, retrieve, list, and manage memory records.

    This tool helps agents store and access memories, allowing them to remember important
    information across conversations and interactions.

    Key Capabilities:
    - Store new memories (text conversations or structured data)
    - Search for memories using semantic search
    - Browse and list all stored memories
    - Retrieve specific memories by ID
    - Delete unwanted memories

    Supported Actions:
    -----------------
    Memory Management:
    - record: Store a new memory (conversation or data)
        Use this when you need to save information for later recall.

    - retrieve: Find relevant memories using semantic search
        Use this when searching for specific information in memories.
        This is the best action for queries like "find memories about X" or "search for memories related to Y".

    - list: Browse all stored memories
        Use this to see all available memories without filtering.
        This is useful for getting an overview of what's been stored.

    - get: Fetch a specific memory by ID
        Use this when you already know the exact memory ID.

    - delete: Remove a specific memory
        Use this to delete memories that are no longer needed.

    Args:
        action: The memory operation to perform (one of: "record", "retrieve", "list", "get", "delete")
        content: For record action: Simple text string to store as a memory
                    Example: "User prefers vegetarian pizza with extra cheese"
        query: Search terms for finding relevant memories (required for retrieve action)
        memory_record_id: ID of a specific memory (required for get and delete actions)
        max_results: Maximum number of results to return (optional)
        next_token: Pagination token (optional)

    Returns:
        Dict: Response containing the requested memory information or operation status
    """
    try:
        mcp_env = utils.load_mcp_env()
        user_id = mcp_env.get('user_id')
        # Use default user_id if None or empty
        if not user_id or (isinstance(user_id, str) and not user_id.strip()):
            user_id = "default"
            logger.info(f"user_id was None or empty, using default: {user_id}")
        memory_id, actor_id, session_id, namespace = agentcore_memory.load_memory_variables(user_id)
        logger.info(f"memory_id: {memory_id}, user_id: {user_id}, actor_id: {actor_id}, session_id: {session_id}, namespace: {namespace}")
        
        # Execute the appropriate action
        logger.info(f"###### action: {action} ######")
        try:
            # Handle action names by mapping to API methods            
            if action == "record":
                response = create_event(
                    memory_id=memory_id,
                    actor_id=actor_id,
                    session_id=session_id,
                    content=content,
                    event_timestamp=datetime.now(timezone.utc),
                )
                # Extract only the relevant "event" field from the response
                event_data = response.get("event", {}) if isinstance(response, dict) else {}
                return {
                    "status": "success",
                    "content": [{"text": f"Memory created successfully: {json.dumps(event_data, default=str)}"}],
                }
            elif action == "retrieve":
                contents = []
                response = retrieve_memory_records(
                    memory_id=memory_id,
                    namespace=namespace,
                    search_query=query,
                    max_results=max_results,
                    next_token=next_token,
                )
                # Extract only the relevant fields from the response
                relevant_data = {}
                if isinstance(response, dict):
                    if "memoryRecordSummaries" in response:
                        relevant_data["memoryRecordSummaries"] = response["memoryRecordSummaries"]
                    if "nextToken" in response:
                        relevant_data["nextToken"] = response["nextToken"]
                    logger.info(f"relevant_data: {relevant_data}")
                    
                    # extract content from memoryRecordSummaries
                    for memory_record_summary in relevant_data["memoryRecordSummaries"]:
                        json_content = memory_record_summary["content"]["text"]
                        content = json.loads(json_content)
                        logger.info(f"content: {content}")
                        contents.append(content)

                return {
                    "text": contents
                }
            elif action == "list":
                response = list_memory_records(
                    memory_id=memory_id,
                    namespace=namespace,
                    max_results=max_results,
                    next_token=next_token,
                )
                # Extract only the relevant fields from the response
                relevant_data = {}
                if isinstance(response, dict):
                    if "memoryRecordSummaries" in response:
                        relevant_data["memoryRecordSummaries"] = response["memoryRecordSummaries"]
                    if "nextToken" in response:
                        relevant_data["nextToken"] = response["nextToken"]

                return {
                    "status": "success",
                    "content": [
                        {"text": f"Memories listed successfully: {json.dumps(relevant_data, default=str)}"}
                    ],
                }
            elif action == "get":
                response = get_memory_record(
                    memory_id=memory_id,
                    memory_record_id=memory_record_id,
                )
                # Extract only the relevant "memoryRecord" field from the response
                memory_record = response.get("memoryRecord", {}) if isinstance(response, dict) else {}
                return {
                    "status": "success",
                    "content": [
                        {"text": f"Memory retrieved successfully: {json.dumps(memory_record, default=str)}"}
                    ],
                }
            elif action == "delete":
                response = delete_memory_record(
                    memory_id=memory_id,
                    memory_record_id=memory_record_id,
                )
                # Extract only the relevant "memoryRecordId" field from the response
                memory_record_id = response.get("memoryRecordId", "") if isinstance(response, dict) else ""

                return {
                    "status": "success",
                    "content": [{"text": f"Memory deleted successfully: {memory_record_id}"}],
                }
        except Exception as e:
            error_msg = f"API error: {str(e)}"
            logger.error(error_msg)
            return {"status": "error", "content": [{"text": error_msg}]}

    except Exception as e:
        logger.error(f"Unexpected error in agent_core_memory tool: {str(e)}")
        return {"status": "error", "content": [{"text": str(e)}]}
