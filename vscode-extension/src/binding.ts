import * as vscode from 'vscode';
import * as crypto from 'crypto';
import * as fs from 'fs';
import { fileResults } from './state';

/** Whether a file still holds the bytes its last analysis read (backend 3.14+
 *  `source_sha256`), the editor's form of the work order's VOID HOLD:
 *  MATCH       the file is what was analyzed; lines point where they should
 *  CHANGED     edited (unsaved) or changed on disk since: lines may have moved
 *  UNBOUND     no analysis, or a backend that does not report the hash */
export type Binding = 'MATCH' | 'CHANGED' | 'UNBOUND';

const diskHash = new Map<string, { mtimeMs: number; size: number; sha: string }>();

function hashOnDisk(filePath: string): string | undefined {
    try {
        const stat = fs.statSync(filePath);
        const cached = diskHash.get(filePath);
        if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) { return cached.sha; }
        const sha = crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
        diskHash.set(filePath, { mtimeMs: stat.mtimeMs, size: stat.size, sha });
        return sha;
    } catch {
        return undefined;
    }
}

export function bindingOf(filePath: string): Binding {
    const bound = fileResults.get(filePath)?.source_sha256;
    if (typeof bound !== 'string' || !/^[0-9a-f]{64}$/.test(bound)) { return 'UNBOUND'; }
    const open = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === filePath);
    if (open?.isDirty) { return 'CHANGED'; }
    return hashOnDisk(filePath) === bound ? 'MATCH' : 'CHANGED';
}
