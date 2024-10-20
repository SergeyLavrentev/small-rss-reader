#!/bin/bash

# Script: concat_code.sh
# Description: Concatenates all .py files in the project into a single file with headers indicating the source file.
# Usage: ./concat_code.sh [output_file]
# Default output_file: concatenated_code.py

# Set default output file if not provided
OUTPUT_FILE=${1:-concatenated_code.py}

# Remove the output file if it already exists to prevent duplication
if [ -f "$OUTPUT_FILE" ]; then
    rm "$OUTPUT_FILE"
fi

# Find all .py files excluding certain directories (e.g., __pycache__, data, logs)
# Adjust the excluded directories as per your project structure
EXCLUDE_DIRS=("__pycache__" "data" "logs" "venv" ".git")

# Construct the find command with exclusions
FIND_CMD="find . -type f -name '*.py'"
for dir in "${EXCLUDE_DIRS[@]}"; do
    FIND_CMD+=" ! -path './$dir/*'"
done

# Execute the find command and iterate over each found file
eval $FIND_CMD | sort | while read -r file; do
    # Add a header before each file's content
    echo "### FILE: $file ###" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    
    # Optionally, include the file's path relative to the project root
    echo "# Path: $file" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    
    # Append the file's content
    cat "$file" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    echo "### END OF $file ###" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
done

echo "All .py files have been concatenated into $OUTPUT_FILE"

