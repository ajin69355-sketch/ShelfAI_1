# scripts/test_pipeline.py

import os
from dotenv import load_dotenv

# We need to add the project root to Python's path to allow imports
# from the 'shelfai' package.
import sys
# This line finds the parent directory of 'scripts' (i.e., shelfai-project)
# and adds it to the list of places Python looks for modules.
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from shelfai.data_pipeline.loader import load_and_clean_data

def main():
    """
    Main function to execute the test.
    """
    # load_dotenv will read the .env file and set the environment variables.
    load_dotenv()

    # Retrieve the dataset path from the environment variable.
    # This is much better than hardcoding the path in the script.
    file_path = os.getenv("DATASET_PATH")

    if not file_path:
        print("Error: DATASET_PATH not found in .env file.")
        return

    # Call our main data loading function
    stock_data = load_and_clean_data(file_path)

    # If data was loaded successfully, print the first few records to verify.
    if stock_data:
        print("\n--- Verification: First 3 Clean Records ---")
        for record in stock_data[:3]:
            # The .dict() method converts the Pydantic model back to a dictionary
            # for easy printing.
            print(record.dict())
            print("-" * 20)

        print(f"\nSuccessfully loaded and validated {len(stock_data)} stock lots.")
    else:
        print("\nNo data was loaded. Please check the errors above.")


# Standard Python entry point
if __name__ == "__main__":
    main()
