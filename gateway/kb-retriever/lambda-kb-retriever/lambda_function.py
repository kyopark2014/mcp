import json

def lambda_handler(event, context):
    print(f"event: {event}")
    print(f"context: {context}")

    toolName = context.client_context.custom['bedrockAgentCoreToolName']
    print(f"context.client_context: {context.client_context}")
    print(f"Original toolName: , {toolName}")
    
    delimiter = "___"
    if delimiter in toolName:
        toolName = toolName[toolName.index(delimiter) + len(delimiter):]
    print(f"Converted toolName: , {toolName}")

    if toolName == 'get_order_tool':
        return {
            'statusCode': 200, 
            'body': "Order Id 123 is in shipped status"
        }
    else:
        return {
            'statusCode': 200, 
            'body': "Updated the order details successfully"
        }
