# Makefile

.PHONY: build clean run rebuild install

# Build the application using PyInstaller and the spec file
build:
	pyinstaller --clean --noconfirm mini_rss_reader.spec

# Clean up build artifacts created by PyInstaller
clean:
	rm -rf build/
	rm -rf dist/

# Run the application directly using Python
run:
	python mini_rss_reader.py

# Rebuild the application: clean then build
rebuild: clean build

install:
	cp -a dist/Small\ RSS\ Reader.app /Applications/