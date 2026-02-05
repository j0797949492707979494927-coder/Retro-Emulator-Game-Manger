import os

# Output file
output_file = "combined_output.txt"
# Get this script's filename to skip it
this_script = os.path.basename(__file__)

# Lists to hold content and unreadable files
file_contents = []
unreadable_files = []

for root, dirs, files in os.walk("."):
    for filename in files:
        if filename == this_script:
            continue  # Skip this script
        filepath = os.path.join(root, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Add a header for the file
            relative_path = os.path.relpath(filepath, ".")
            file_contents.append(f"--- FILE: {relative_path} ---\n{content}\n\n")
        except Exception as e:
            # Couldn't read the file, store path
            relative_path = os.path.relpath(filepath, ".")
            unreadable_files.append(relative_path)

# Write all readable content to output file
with open(output_file, "w", encoding="utf-8") as f:
    f.writelines(file_contents)
    if unreadable_files:
        f.write("--- UNREADABLE FILES ---\n")
        for file in unreadable_files:
            f.write(file + "\n")

print(f"Finished! Combined output saved to '{output_file}'.")
if unreadable_files:
    print("Some files could not be read. See 'combined_output.txt' for the list.")
