import sys
from unittest.mock import MagicMock
import google.genai

mock_client = MagicMock()
mock_response = MagicMock()
mock_response.text = '{"purpose": "Monitor Ollama", "key_technologies": ["Python", "Ollama"], "top_level_structure": "src/ contains the source code", "key_concepts": ["Monitoring"]}'
mock_client.models.generate_content.return_value = mock_response

google.genai.Client = MagicMock(return_value=mock_client)

sys.path.append('/home/ubuntu/atobar-flow/src')
from flow_engine.knowledge.onboard_repo import generate_wiki

generate_wiki('/home/ubuntu/workspace', 'workspace')
