import os
import json
from agno.agent import Agent

class SelectorAgent:
    """
    Agent 3: Selects relevant control prompts (JSON files) based on meta-category.
    """
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = prompts_dir
        # Optional: Initialize Agno Agent if selection logic needs LLM assistance
        # self.agent = Agent(model=..., instructions=["Help select relevant controls..."])
        pass # Placeholder

    def run(self, meta_category: str) -> list[str]:
        """
        Finds all JSON prompt files within the specified meta-category directory.
        """
        print(f"Selector: Looking for prompts in category '{meta_category}'...")
        category_path = os.path.join(self.prompts_dir, meta_category)
        prompt_files = []

        if not os.path.isdir(category_path):
            print(f"Selector: Warning - Category directory not found: {category_path}")
            return []

        try:
            for filename in os.listdir(category_path):
                if filename.lower().endswith('.json'):
                    full_path = os.path.join(category_path, filename)
                    # Optional: Add validation to ensure the JSON is a valid control prompt
                    prompt_files.append(full_path)

            print(f"Selector: Found {len(prompt_files)} prompts in '{meta_category}'.")
            return prompt_files

        except Exception as e:
            print(f"Selector: Error accessing prompts directory {category_path}: {e}")
            return []
