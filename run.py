import sys
import subprocess
import importlib

REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "multipart": "python-multipart",
    "google.generativeai": "google-generativeai",
    "pypdf": "pypdf",
    "dotenv": "python-dotenv",
    "numpy": "numpy"
}

def check_and_install_dependencies():
    missing_packages = []
    
    print("Checking Python dependencies...")
    for module_name, package_name in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            print(f" - Missing package: {package_name}")
            missing_packages.append(package_name)
            
    if missing_packages:
        print("\nInstalling missing packages from requirements.txt...")
        try:
            # First try installing from requirements.txt
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("Dependencies installed successfully!\n")
        except Exception as e:
            # Fallback to individual packages if requirements.txt installation fails
            print(f"Error installing requirements.txt: {e}. Trying individual packages...")
            for pkg in missing_packages:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                except Exception as ex:
                    print(f"Failed to install {pkg}: {ex}")
                    sys.exit(1)
    else:
        print("All dependencies are satisfied!\n")

def start_server():
    print("Starting NexusDoc AI RAG server...")
    print("Access the web interface at: http://localhost:8000")
    print("Press Ctrl+C to terminate.")
    
    try:
        import uvicorn
        # Run server using Uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
    except KeyboardInterrupt:
        print("\nNexusDoc AI server stopped.")
    except Exception as e:
        print(f"Failed to run server: {e}")

if __name__ == "__main__":
    check_and_install_dependencies()
    start_server()
