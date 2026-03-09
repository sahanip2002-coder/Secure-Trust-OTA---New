import os

# CONFIGURATION
# We use 5 characters to match 'IOTFW' exactly. 
# This prevents corrupting the binary headers.
OLD_NAME = b"IOTFW"
NEW_NAME = b"IOTFW" 

# Extensions to scan
EXTENSIONS = ('.py', '.json', '.bin', '.txt', '.md')

def remove_branding(root_dir):
    print(f"Scanning for '{OLD_NAME.decode()}' in {root_dir}...")
    count = 0
    
    for dirpath, _, filenames in os.walk(root_dir):
        # Skip the .git folder if it exists
        if '.git' in dirpath:
            continue
            
        for filename in filenames:
            if filename.endswith(EXTENSIONS) or filename == 'main.py':
                filepath = os.path.join(dirpath, filename)
                try:
                    # Read as binary to handle both .py text and .bin firmware safely
                    with open(filepath, 'rb') as f:
                        content = f.read()
                    
                    if OLD_NAME in content:
                        print(f"Refactoring: {filepath}")
                        # Replace all occurrences
                        new_content = content.replace(OLD_NAME, NEW_NAME)
                        
                        # Write back
                        with open(filepath, 'wb') as f:
                            f.write(new_content)
                        count += 1
                except Exception as e:
                    print(f"Could not process {filepath}: {e}")

    print(f"Done! Updated {count} files.")
    print(f"Your firmware header is now: {NEW_NAME.decode()}-MODULAR-FIRMWARE")

if __name__ == "__main__":
    # Run in the current directory
    remove_branding(".")