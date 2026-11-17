/** The languages the backend analyzes (src/slop_detector/language_registry.py
 *  and Python), as file extensions and VS Code language ids: the one list the
 *  extension uses. tests/test_language_slot.py fails when it misses a
 *  registered language, when package.json does not activate on one of these
 *  ids, or when another file names a language of its own. */

export const SUPPORTED_EXTENSIONS: readonly string[] = [
    '.py',
    '.js', '.jsx', '.ts', '.tsx',
    '.go',
    '.rs',
];

export const LANGUAGE_IDS: readonly string[] = [
    'python',
    'javascript', 'javascriptreact', 'typescript', 'typescriptreact',
    'go',
    'rust',
];

/** Document selector for every analyzed language. */
export const DOCUMENT_SELECTOR = LANGUAGE_IDS.map((language) => ({ language }));

/** True when the backend analyzes a file with this path's extension. */
export function isSupported(filePath: string): boolean {
    const lower = filePath.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
