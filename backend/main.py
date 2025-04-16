import argparse
import os
from agents.orchestrator import OrchestratorAgent, KNOWN_META_CATEGORIES
# Optional: Load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Loaded environment variables from .env file.")
except ImportError:
    print(".env file not loaded. Ensure python-dotenv is installed or vars are exported.")

def main():
    parser = argparse.ArgumentParser(description="Run automated controls on documents.")
    parser.add_argument(
        "target",
        help="Path to a document file or a directory containing documents."
    )
    parser.add_argument(
        "-c", "--category",
        help="Specify the control meta-category (e.g., KYC, RGPD). If not provided, the script will try to infer it or prompt the user.",
        choices=KNOWN_META_CATEGORIES + [cat.lower() for cat in KNOWN_META_CATEGORIES], # Allow upper and lower case
        default=None
    )
    # Add other arguments as needed (e.g., specific control IDs, output options)

    args = parser.parse_args()

    # Instantiate the orchestrator
    orchestrator = OrchestratorAgent()

    target_path = args.target
    specified_category = args.category.upper() if args.category else None

    if not os.path.exists(target_path):
        print(f"Error: Target path not found: {target_path}")
        return

    if os.path.isfile(target_path):
        # Process a single file
        orchestrator.run_control_chain(target_path, specified_category)
    elif os.path.isdir(target_path):
        # Process all supported files in a directory
        print(f"Processing directory: {target_path}")
        supported_extensions = ('.docx', '.xlsx', '.pdf', '.txt')
        processed_files = 0
        for root, _, files in os.walk(target_path):
            for file in files:
                if file.lower().endswith(supported_extensions):
                    file_path = os.path.join(root, file)
                    # If category is specified, use it. Otherwise, let orchestrator infer.
                    category_to_use = specified_category
                    # If no category specified AND we are processing a directory,
                    # let the orchestrator try to infer based on the file path.
                    if not specified_category:
                        # The orchestrator's inference logic will run inside run_control_chain
                        pass

                    orchestrator.run_control_chain(file_path, category_to_use)
                    processed_files += 1
                # Add handling for nested directories if needed

        if processed_files == 0:
            print(f"No supported documents ({', '.join(supported_extensions)}) found in directory: {target_path}")
    else:
        print(f"Error: Target path is neither a file nor a directory: {target_path}")

if __name__ == "__main__":
    main()
