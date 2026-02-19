import os
import sys
import yaml
import argparse
try:
    from anthropic import AnthropicBedrock
    import botocore.exceptions
except ImportError:
    print("Error: anthropic[bedrock] not installed.")
    sys.exit(1)

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'models.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Config file not found at {config_path}.")
        return {}

def test_bedrock_connection():
    config = load_config()
    # Check if bedrock provider is configured
    bedrock_config = config.get('providers', {}).get('bedrock', {})
    region = bedrock_config.get('region_name', 'us-west-2')
    
    print(f"Testing Bedrock connection in region: {region}")
    
    try:
        client = AnthropicBedrock(aws_region=region)
        # Simple list models call or similar lightweight check if possible, 
        # but AnthropicBedrock doesn't have list_models directly exposed easily like generic Bedrock client.
        # So we try a simple message.
        
        print("Sending 'Hello' to Bedrock...")
        message = client.messages.create(
            model="anthropic.claude-3-5-sonnet-20240620-v1:0", 
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Hello"}
            ]
        )
        print(f"Success! Response: {message.content[0].text}")
        
    except botocore.exceptions.NoCredentialsError:
        print("Error: No AWS credentials found.")
    except botocore.exceptions.ClientError as e:
        print(f"AWS ClientError: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_bedrock_connection()
