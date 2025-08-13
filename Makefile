# Makefile

.PHONY: build clean run rebuild install codesign full-install full-rebuild test test-all test-network

# Variables
APP_NAME=SmallRSSReader
DISPLAY_NAME="Small RSS Reader"
SPEC_FILE=small_rss_reader.spec
DIST_DIR=dist
BUILD_DIR=build
APP_BUNDLE=$(DIST_DIR)/$(APP_NAME).app
INSTALL_PATH=/Applications/

# Replace the following line with your actual code signing identity.
# You can find your code signing identity by running:
# security find-identity -v -p codesigning
SIGN_IDENTITY="Developer ID Application: Rocker (TEAMID)"  # <-- Replace with your actual code signing identity

# venv management (use only venv)
VENV=venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PIP) install -r requirements.txt

# Build the application using PyInstaller and the spec file
build: venv
	# pyinstaller --clean --noconfirm $(SPEC_FILE)
	$(PY) setup.py py2app

# Clean up build artifacts created by PyInstaller
clean:
	rm -rf $(BUILD_DIR)/
	rm -rf $(DIST_DIR)/
	rm -fr .eggs

# Run the application directly using Python (for development/testing)
run: venv
	$(PY) small_rss_reader.py --debug

# Rebuild the application: clean then build
rebuild: clean build

# Install the application to /Applications/
install:
	@echo "Installing $(DISPLAY_NAME) to /Applications/"
	# Remove existing app to avoid stale files (e.g., legacy JSON symlinks)
	rm -rf $(INSTALL_PATH)/$(APP_NAME).app
	cp -a $(APP_BUNDLE) $(INSTALL_PATH)
	codesign --force --deep --sign - $(INSTALL_PATH)/$(APP_NAME).app
	@echo "Installed $(DISPLAY_NAME) to /Applications/"

# Codesign the installed application
codesign:
	@echo "Signing $(DISPLAY_NAME) with identity: $(SIGN_IDENTITY)"
	codesign --deep --force --verify --verbose --sign "$(SIGN_IDENTITY)" "$(INSTALL_PATH)"
	@echo "Successfully signed $(DISPLAY_NAME)."

# Full install process: build, install, and codesign
full-install: build install codesign
	@echo "Built, installed, and signed $(DISPLAY_NAME) successfully."

# Full rebuild process: clean, build, install, and codesign
full-rebuild: clean build install codesign
	@echo "Cleaned, built, installed, and signed $(DISPLAY_NAME) successfully."

# Run tests with venv python, verbose output, and headless Qt
test: venv
	QT_QPA_PLATFORM=offscreen \
	QTWEBENGINE_CHROMIUM_FLAGS="--headless --disable-gpu" \
	PYTHONPATH=. $(PY) -m pytest -vv -s

# Run all tests including network-marked ones
test-all: venv
	QT_QPA_PLATFORM=offscreen \
	QTWEBENGINE_CHROMIUM_FLAGS="--headless --disable-gpu" \
	PYTHONPATH=. $(PY) -m pytest -vv -s -m ""

# Run only network tests
test-network: venv
	QT_QPA_PLATFORM=offscreen \
	QTWEBENGINE_CHROMIUM_FLAGS="--headless --disable-gpu" \
	PYTHONPATH=. $(PY) -m pytest -vv -s -m network
