# VS Code Extension for AI SLOP Detector

Real-time code quality analysis directly in VS Code.

## Features

- **Real-time Linting**: Analyze code on save or while typing
- **Inline Warnings**: See slop scores and issues directly in editor
- **Status Bar**: Quick overview of current file's quality
- **History Tracking**: View analysis trends over time
- **Git Integration**: One-click pre-commit hook installation
- **Workspace Analysis**: Analyze entire project at once

## Installation

### From VSIX (Local)
```bash
cd vscode-extension
npm install
npm run compile
npm run package

# Install in VS Code
code --install-extension vscode-slop-detector-2.5.1.vsix
```

### From Marketplace
Search for "AI SLOP Detector" in VS Code Extensions or install directly:
```
ext install Flamehaven.vscode-slop-detector
```

## Usage

### Commands (Ctrl+Shift+P)

- `SLOP Detector: Analyze Current File` - Analyze active file
- `SLOP Detector: Analyze Workspace` - Analyze entire workspace
- `SLOP Detector: Show File History` - View historical trends
- `SLOP Detector: Install Git Pre-Commit Hook` - Setup Git integration

### Configuration

Open Settings (Ctrl+,) and search for "SLOP Detector":

```json
{
  "slopDetector.enable": true,
  "slopDetector.lintOnSave": true,
  "slopDetector.lintOnType": false,
  "slopDetector.showInlineWarnings": true,
  "slopDetector.failThreshold": 50.0,
  "slopDetector.warnThreshold": 30.0,
  "slopDetector.pythonPath": "python",
  "slopDetector.configPath": "",
  "slopDetector.recordHistory": true
}
```

## Requirements

- Python 3.8+
- `ai-slop-detector` package installed (`pip install ai-slop-detector`)

## Screenshots

Coming soon after marketplace release.

## Development

```bash
npm install
npm run compile
npm run watch  # Auto-recompile on changes
```

Press F5 in VS Code to launch Extension Development Host.

## License

MIT License - See LICENSE file
