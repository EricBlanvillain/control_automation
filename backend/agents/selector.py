import os
import json
import logging
from typing import Dict, Any
from agno.agent import Agent

# Set up basic logging
logger = logging.getLogger(__name__)
# Basic config - level and format can be configured centrally in the application entry point
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Define required keys for a valid prompt JSON
REQUIRED_PROMPT_KEYS = ["control_id", "prompt_instructions"]

class SelectorAgent:
    """
    Agent 3: Selects relevant control prompts (JSON files) based on meta-category.
    Includes basic validation of prompt files.
    """
    def __init__(self, prompts_dir: str | None = None):
        # Use provided dir, env variable, or default
        self.prompts_dir = prompts_dir or os.getenv("PROMPTS_DIR", "prompts")
        logger.info(f"SelectorAgent initialized. Using prompts directory: {self.prompts_dir}")
        # Optional: Initialize Agno Agent if selection logic needs LLM assistance
        # self.agent = Agent(model=..., instructions=["Help select relevant controls..."])

    def _validate_prompt_file(self, file_path: str) -> bool:
        """Checks if a file is valid JSON and contains required keys."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data: Dict[str, Any] = json.load(f)

            missing_keys = [key for key in REQUIRED_PROMPT_KEYS if key not in data]
            if missing_keys:
                logger.warning(f"Invalid prompt file: {file_path}. Missing required keys: {missing_keys}")
                return False

            # Optionally, add more checks (e.g., prompt_instructions is a non-empty list)
            if not isinstance(data.get("prompt_instructions"), list) or not data["prompt_instructions"]:
                logger.warning(f"Invalid prompt file: {file_path}. 'prompt_instructions' must be a non-empty list.")
                return False

            return True
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON format in prompt file: {file_path}")
            return False
        except Exception as e:
            logger.error(f"Error reading or validating prompt file {file_path}: {e}", exc_info=True)
            return False

    def run(self, meta_category: str) -> list[str]:
        """
        Finds and validates JSON prompt files within the specified meta-category directory.
        Returns a list of paths to valid prompt files.
        """
        logger.info(f"Looking for prompts in category '{meta_category}'...")
        category_path = os.path.join(self.prompts_dir, meta_category)
        valid_prompt_files = []

        if not os.path.isdir(category_path):
            logger.warning(f"Category directory not found: {category_path}")
            return []

        try:
            for filename in os.listdir(category_path):
                if filename.lower().endswith('.json'):
                    full_path = os.path.join(category_path, filename)
                    if self._validate_prompt_file(full_path):
                        valid_prompt_files.append(full_path)
                    # Else: validation failed, warning already logged by _validate_prompt_file

            logger.info(f"Found {len(valid_prompt_files)} valid prompts in '{meta_category}'.")
            return valid_prompt_files

        except Exception as e:
            logger.error(f"Error accessing prompts directory {category_path}: {e}", exc_info=True)
            return []
